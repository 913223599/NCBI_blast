"""V4.1 蒸馏学生模型网络结构与区域上下文精修网络定义。"""
from typing import Tuple

import numpy as np

from ..experts.expert_c_orf import MAX_ORFS_PER_WIN, ORF_FEAT_DIM
from ..features.window_features import SUB_BINS

SEMANTIC_DIM = 4

def _normalize_feature_stats(feats: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    mean = np.nan_to_num(feats.mean(axis=0), nan=0.0).astype(np.float32)
    std = np.nan_to_num(feats.std(axis=0), nan=1.0).astype(np.float32)
    std = np.where(std < 1e-6, 1.0, std).astype(np.float32)
    return mean, std

def build_distilled_student_v4(
    feat_dim: int,
    feat_mean: np.ndarray,
    feat_std: np.ndarray,
    *,
    dna_channels: int = 160,
    orf_d_model: int = 128,
    orf_nhead: int = 4,
    orf_num_layers: int = 3,
    fusion_dim: int = 256,
    sem_dim: int = SEMANTIC_DIM,
    orf_feat_dim: int = ORF_FEAT_DIM,
    func_dim: int = 0,
):
    """构建 V4 高容量三模态隐式语义神经网络学生模型（支持 Masked Pooling、多任务输出与可选 9 维功能分区蒸馏头）。"""
    import torch
    from torch import nn

    resolved_orf_dim = int(orf_feat_dim)
    resolved_func_dim = max(0, int(func_dim))

    class ResBlock1dMasked(nn.Module):
        def __init__(self, ch: int, dilation: int):
            super().__init__()
            self.conv1 = nn.Conv1d(ch, ch, kernel_size=5, padding=2 * dilation, dilation=dilation)
            self.bn1 = nn.BatchNorm1d(ch)
            self.conv2 = nn.Conv1d(ch, ch, kernel_size=5, padding=2 * dilation, dilation=dilation)
            self.bn2 = nn.BatchNorm1d(ch)
            self.act = nn.GELU()

        def forward(self, x, mask):
            h = self.act(self.bn1(self.conv1(x))) * mask
            h = self.bn2(self.conv2(h)) * mask
            return self.act(x + h) * mask

    class OrfStream(nn.Module):
        def __init__(self):
            super().__init__()
            self.proj = nn.Sequential(
                nn.Linear(resolved_orf_dim, orf_d_model),
                nn.LayerNorm(orf_d_model),
                nn.GELU(),
            )
            self.pos_emb = nn.Parameter(torch.randn(1, MAX_ORFS_PER_WIN, orf_d_model) * 0.02)
            enc_layer = nn.TransformerEncoderLayer(
                d_model=orf_d_model,
                nhead=orf_nhead,
                dim_feedforward=orf_d_model * 3,
                dropout=0.15,
                activation="gelu",
                batch_first=True,
                norm_first=True,
            )
            self.encoder = nn.TransformerEncoder(enc_layer, num_layers=orf_num_layers, enable_nested_tensor=False)
            self.attn_score = nn.Linear(orf_d_model, 1)
            self.out_proj = nn.Sequential(
                nn.Linear(orf_d_model * 3 + 1, fusion_dim),
                nn.LayerNorm(fusion_dim),
                nn.GELU(),
                nn.Dropout(0.15),
            )
            self.empty_emb = nn.Parameter(torch.zeros(1, fusion_dim))

        def forward(self, tokens, counts, return_seq: bool = False):
            bsz, seq_len, _ = tokens.shape
            pos = torch.arange(seq_len, device=tokens.device)[None, :]
            valid_mask = pos < counts[:, None]
            has_any = counts > 0

            h = self.proj(tokens) + self.pos_emb[:, :seq_len, :]
            # 保护 TransformerEncoder：若某样本有效 ORF 为 0，保留第 0 个位置不屏蔽防止全 -inf NaN
            safe_pad = (~valid_mask) & ((pos > 0) | has_any[:, None])
            h = self.encoder(h, src_key_padding_mask=safe_pad)

            vm = valid_mask.unsqueeze(-1).to(h.dtype)
            mean_pool = (h * vm).sum(dim=1) / vm.sum(dim=1).clamp(min=1.0)
            max_pool = h.masked_fill(~valid_mask.unsqueeze(-1), -1e4).max(dim=1).values
            max_pool = torch.where(has_any[:, None], max_pool, torch.zeros_like(max_pool))
            attn_logits = self.attn_score(h).squeeze(-1).masked_fill(~valid_mask, -1e4)
            attn_w = torch.softmax(attn_logits, dim=-1).unsqueeze(-1)
            attn_pool = torch.where(has_any[:, None], (h * attn_w).sum(dim=1), torch.zeros_like(mean_pool))

            count_feat = torch.log1p(counts.float()).unsqueeze(-1)
            emb = self.out_proj(torch.cat([mean_pool, max_pool, attn_pool, count_feat], dim=-1))
            empty = self.empty_emb.expand(bsz, -1).to(emb.dtype)
            out_emb = torch.where(has_any[:, None], emb, empty)
            if return_seq:
                return out_emb, h * vm
            return out_emb

    class DistilledStudentV4Net(nn.Module):
        feat_mean: torch.Tensor
        feat_std: torch.Tensor

        def __init__(self):
            super().__init__()
            self.orf_feat_dim = resolved_orf_dim
            self.func_dim = resolved_func_dim
            self.register_buffer("feat_mean", torch.tensor(feat_mean, dtype=torch.float32))
            self.register_buffer("feat_std", torch.tensor(feat_std, dtype=torch.float32))

            # Branch 1: DNA ResNet + Masked BiGRU
            self.dna_stem = nn.Sequential(
                nn.Conv1d(4, dna_channels, kernel_size=15, padding=7),
                nn.BatchNorm1d(dna_channels),
                nn.GELU(),
                nn.MaxPool1d(4),
            )
            self.dna_stage1 = nn.ModuleList([ResBlock1dMasked(dna_channels, 2 ** (i % 3)) for i in range(3)])
            self.dna_down2 = nn.Sequential(
                nn.Conv1d(dna_channels, dna_channels, kernel_size=9, padding=4),
                nn.BatchNorm1d(dna_channels),
                nn.GELU(),
                nn.MaxPool1d(5),
            )
            self.dna_stage2 = nn.ModuleList([ResBlock1dMasked(dna_channels, 2 ** (i % 3)) for i in range(3)])
            self.dna_gru = nn.GRU(
                dna_channels, dna_channels // 2, num_layers=2, batch_first=True, bidirectional=True, dropout=0.15,
            )
            self.dna_proj = nn.Sequential(
                nn.Linear(dna_channels * 2, fusion_dim),
                nn.LayerNorm(fusion_dim),
                nn.GELU(),
                nn.Dropout(0.15),
            )

            # Branch 2: Embedded ORF Synteny Transformer
            self.orf_stream = OrfStream()

            # Branch 3: Tabular Residual MLP
            self.tab_in = nn.Sequential(
                nn.Linear(feat_dim, fusion_dim),
                nn.LayerNorm(fusion_dim),
                nn.GELU(),
                nn.Dropout(0.15),
            )
            self.tab_res = nn.Sequential(
                nn.Linear(fusion_dim, fusion_dim),
                nn.LayerNorm(fusion_dim),
                nn.GELU(),
                nn.Dropout(0.15),
                nn.Linear(fusion_dim, fusion_dim),
                nn.LayerNorm(fusion_dim),
            )
            self.tab_act = nn.GELU()

            # Tri-Modal Gated Fusion
            self.modal_gate = nn.Sequential(
                nn.Linear(fusion_dim * 3, 128),
                nn.GELU(),
                nn.Linear(128, 3),
            )
            self.fusion_mlp = nn.Sequential(
                nn.Linear(fusion_dim * 3, fusion_dim * 2),
                nn.LayerNorm(fusion_dim * 2),
                nn.GELU(),
                nn.Dropout(0.20),
                nn.Linear(fusion_dim * 2, fusion_dim),
                nn.LayerNorm(fusion_dim),
                nn.GELU(),
            )

            # Multi-Task Outputs: 语义概念辅助头 + 隐式语义瓶径偏置 + 窗口主分类 + 200bp 亚区分割
            self.sem_head = nn.Sequential(
                nn.Linear(fusion_dim, 96),
                nn.GELU(),
                nn.Linear(96, sem_dim),
            )
            if self.func_dim > 0:
                self.func_head = nn.Sequential(
                    nn.Linear(fusion_dim, 128),
                    nn.GELU(),
                    nn.Linear(128, self.func_dim),
                )
                self.orf_phage_head = nn.Linear(orf_d_model, 1)
                self.orf_func_head = nn.Sequential(
                    nn.Linear(orf_d_model, 96),
                    nn.GELU(),
                    nn.Linear(96, self.func_dim),
                )
                self.func_win_residual = nn.Linear(self.func_dim, 1)
                nn.init.zeros_(self.func_win_residual.weight)
                nn.init.zeros_(self.func_win_residual.bias)
            self.win_head = nn.Sequential(
                nn.Linear(fusion_dim + sem_dim, 128),
                nn.GELU(),
                nn.Dropout(0.15),
                nn.Linear(128, 1),
            )
            self.sub_pool = nn.AdaptiveAvgPool1d(SUB_BINS)
            self.sub_cond = nn.Linear(fusion_dim, dna_channels)
            self.sub_head = nn.Sequential(
                nn.Conv1d(dna_channels, 64, kernel_size=3, padding=1),
                nn.GELU(),
                nn.Conv1d(64, 1, kernel_size=1),
            )

        def _forward_dna_branch(self, dna, lengths):
            bsz, _, max_seq = dna.shape
            dna_pos = torch.arange(max_seq, device=dna.device)[None, :]
            dna_in_mask = (dna_pos < lengths[:, None]).unsqueeze(1).to(dna.dtype)
            x = dna * dna_in_mask

            h1 = self.dna_stem(x)
            t1 = h1.shape[-1]
            v1 = torch.clamp((lengths.float() / 4.0).floor().long(), min=1, max=t1)
            mask1 = (torch.arange(t1, device=h1.device)[None, :] < v1[:, None]).unsqueeze(1).to(h1.dtype)
            h1 = h1 * mask1
            for blk in self.dna_stage1:
                h1 = blk(h1, mask1)

            h2 = self.dna_down2(h1)
            t2 = h2.shape[-1]
            v2 = torch.clamp((lengths.float() / 20.0).floor().long(), min=1, max=t2)
            mask2 = (torch.arange(t2, device=h2.device)[None, :] < v2[:, None]).unsqueeze(1).to(h2.dtype)
            h2 = h2 * mask2
            for blk in self.dna_stage2:
                h2 = blk(h2, mask2)

            # 对有效步长执行 pack_padded BiGRU，消除结尾零填充在反向 GRU 产生的状态漂移
            seq_in = h2.permute(0, 2, 1)
            if not torch.onnx.is_in_onnx_export():
                self.dna_gru.flatten_parameters()
                packed = nn.utils.rnn.pack_padded_sequence(
                    seq_in, v2.detach().cpu(), batch_first=True, enforce_sorted=False,
                )
                packed_out, _ = self.dna_gru(packed)
                gru_out, _ = nn.utils.rnn.pad_packed_sequence(packed_out, batch_first=True, total_length=t2)
            else:
                gru_out, _ = self.dna_gru(seq_in)
            h2 = (h2 + gru_out.permute(0, 2, 1).to(h2.dtype)) * mask2

            mean_pool = (h2 * mask2).sum(dim=-1) / mask2.sum(dim=-1).clamp(min=1.0)
            max_pool = h2.masked_fill(mask2 == 0, -1e4).max(dim=-1).values
            e_dna = self.dna_proj(torch.cat([mean_pool, max_pool], dim=-1))
            return e_dna, h2

        def _forward_backbone(
            self,
            dna,
            tab,
            lengths=None,
            orf_tokens=None,
            orf_counts=None,
            return_orf_seq: bool = False,
        ):
            bsz, _, max_seq = dna.shape
            if lengths is None:
                lengths = torch.full((bsz,), max_seq, dtype=torch.long, device=dna.device)
            if orf_tokens is None:
                orf_tokens = torch.zeros((bsz, MAX_ORFS_PER_WIN, self.orf_feat_dim), dtype=dna.dtype, device=dna.device)
            if orf_counts is None:
                orf_counts = torch.zeros((bsz,), dtype=torch.long, device=dna.device)

            e_dna, h_seq = self._forward_dna_branch(dna, lengths)
            if return_orf_seq:
                e_orf, h_orf_seq = self.orf_stream(orf_tokens, orf_counts, return_seq=True)
            else:
                e_orf = self.orf_stream(orf_tokens, orf_counts, return_seq=False)
                h_orf_seq = None

            tab_norm = (tab - self.feat_mean) / self.feat_std
            e_tab0 = self.tab_in(tab_norm)
            e_tab = self.tab_act(e_tab0 + self.tab_res(e_tab0))

            cat_emb = torch.cat([e_dna, e_orf, e_tab], dim=-1)
            weights = torch.softmax(self.modal_gate(cat_emb), dim=-1)
            gated = torch.cat([
                e_dna * (1.0 + weights[:, 0:1]),
                e_orf * (1.0 + weights[:, 1:2]),
                e_tab * (1.0 + weights[:, 2:3]),
            ], dim=-1)
            h_fused = self.fusion_mlp(gated)
            if return_orf_seq:
                return h_seq, h_fused, h_orf_seq
            return h_seq, h_fused

        def forward(
            self,
            dna,
            tab,
            lengths=None,
            orf_tokens=None,
            orf_counts=None,
            return_aux: bool = False,
        ):
            need_orf_seq = self.func_dim > 0 and return_aux
            if need_orf_seq:
                h_seq, h_fused, h_orf_seq = self._forward_backbone(
                    dna,
                    tab,
                    lengths=lengths,
                    orf_tokens=orf_tokens,
                    orf_counts=orf_counts,
                    return_orf_seq=True,
                )
            else:
                h_seq, h_fused = self._forward_backbone(
                    dna,
                    tab,
                    lengths=lengths,
                    orf_tokens=orf_tokens,
                    orf_counts=orf_counts,
                    return_orf_seq=False,
                )
                h_orf_seq = None

            sem_logits = self.sem_head(h_fused)
            win_logit = self.win_head(torch.cat([h_fused, torch.sigmoid(sem_logits)], dim=-1)).squeeze(-1)

            func_logits = None
            orf_phage_logits = None
            orf_func_logits = None
            if self.func_dim > 0:
                func_logits = self.func_head(h_fused)
                win_logit = win_logit + self.func_win_residual(torch.sigmoid(func_logits)).squeeze(-1)
                if h_orf_seq is not None:
                    orf_phage_logits = self.orf_phage_head(h_orf_seq).squeeze(-1)
                    orf_func_logits = self.orf_func_head(h_orf_seq)

            sub_feat = self.sub_pool(h_seq) + self.sub_cond(h_fused).unsqueeze(-1)
            sub_logits = self.sub_head(sub_feat).squeeze(1)

            if return_aux:
                out_dict = {
                    "win_logit": win_logit,
                    "sub_logits": sub_logits,
                    "sem_logits": sem_logits,
                    "win_emb": h_fused,
                }
                if func_logits is not None:
                    out_dict["func_logits"] = func_logits
                if orf_phage_logits is not None:
                    out_dict["orf_phage_logits"] = orf_phage_logits
                if orf_func_logits is not None:
                    out_dict["orf_func_logits"] = orf_func_logits
                return out_dict
            return win_logit, sub_logits

    return DistilledStudentV4Net()

REFINER_STEP_FEAT_DIM = 15

REFINER_CTX_AUG_DIM = 4

def build_region_context_refiner(
    in_dim: int = REFINER_STEP_FEAT_DIM,
    hidden_dim: int = 128,
    max_delta: float = 2.2,
    use_context_features: bool = True,
):
    """构建轻量跨窗上下文精修器：在 contig 滑窗序列上综合长程走势与邻域活性脉冲对比修正单窗 logit。"""
    import torch
    import torch.nn.functional as F
    from torch import nn

    proj_in_dim = in_dim + (REFINER_CTX_AUG_DIM if use_context_features else 0)

    class RegionContextRefiner(nn.Module):
        excl_kernel: torch.Tensor
        full_kernel: torch.Tensor

        def __init__(self):
            super().__init__()
            self.max_delta = float(max_delta)
            self.use_context_features = use_context_features
            if self.use_context_features:
                # 排除中心自身后的 7 窗（约 +/- 7.5 kb）邻居卷积核，显式刻画脉冲孤立性 vs 连续簇支撑
                excl_k = torch.tensor([[[1.0, 1.0, 1.0, 0.0, 1.0, 1.0, 1.0]]], dtype=torch.float32)
                full_k = torch.ones((1, 1, 7), dtype=torch.float32)
                self.register_buffer("excl_kernel", excl_k, persistent=False)
                self.register_buffer("full_kernel", full_k, persistent=False)
            self.in_proj = nn.Sequential(
                nn.Linear(proj_in_dim, hidden_dim),
                nn.LayerNorm(hidden_dim),
                nn.GELU(),
            )
            self.local_conv = nn.Sequential(
                nn.Conv1d(hidden_dim, hidden_dim, kernel_size=3, padding=1),
                nn.GELU(),
                nn.Conv1d(hidden_dim, hidden_dim, kernel_size=5, padding=2),
                nn.GELU(),
            )
            self.gru = nn.GRU(
                hidden_dim, hidden_dim // 2, num_layers=2, batch_first=True, bidirectional=True, dropout=0.15,
            )
            self.attn = nn.MultiheadAttention(embed_dim=hidden_dim, num_heads=4, dropout=0.1, batch_first=True)
            self.norm1 = nn.LayerNorm(hidden_dim)
            self.norm2 = nn.LayerNorm(hidden_dim)
            self.out_head = nn.Sequential(
                nn.Linear(hidden_dim, 64),
                nn.GELU(),
                nn.Dropout(0.15),
                nn.Linear(64, 1),
            )

        def _append_context_channels(self, step_feats, seq_lens):
            bsz, seq_len, _ = step_feats.shape
            if seq_lens is not None:
                valid = (torch.arange(seq_len, device=step_feats.device)[None, :] < seq_lens[:, None]).to(step_feats.dtype)
            else:
                valid = torch.ones((bsz, seq_len), dtype=step_feats.dtype, device=step_feats.device)

            p_win = step_feats[..., 1] * valid
            p_hall = step_feats[..., 6] * valid
            p_trnp = step_feats[..., 8] * valid

            excl_w = self.excl_kernel.to(dtype=step_feats.dtype)
            full_w = self.full_kernel.to(dtype=step_feats.dtype)
            neigh_sum = F.conv1d(p_win.unsqueeze(1), excl_w, padding=3).squeeze(1)
            neigh_cnt = F.conv1d(valid.unsqueeze(1), excl_w, padding=3).squeeze(1).clamp(min=1.0)
            neigh_p_mean = neigh_sum / neigh_cnt

            active_mask = (p_win >= 0.45).to(step_feats.dtype) * valid
            cluster_cnt = F.conv1d(active_mask.unsqueeze(1), full_w, padding=3).squeeze(1)
            total_cnt = F.conv1d(valid.unsqueeze(1), full_w, padding=3).squeeze(1).clamp(min=1.0)
            cluster_density = cluster_cnt / total_cnt

            local_max_hall = F.max_pool1d(p_hall.unsqueeze(1), kernel_size=5, stride=1, padding=2).squeeze(1)
            hall_minus_trnp = p_hall - p_trnp
            ctx = torch.stack([neigh_p_mean, cluster_density, local_max_hall, hall_minus_trnp], dim=-1)
            return torch.cat([step_feats, ctx], dim=-1)

        def forward(self, step_feats, raw_logits, seq_lens=None):
            """step_feats: (B, W, D), raw_logits: (B, W), return refined_logits: (B, W)."""
            bsz, seq_len, _ = step_feats.shape
            x_feats = self._append_context_channels(step_feats, seq_lens) if self.use_context_features else step_feats
            h0 = self.in_proj(x_feats)
            h_conv = h0 + self.local_conv(h0.permute(0, 2, 1)).permute(0, 2, 1)

            if seq_lens is not None and not torch.onnx.is_in_onnx_export():
                self.gru.flatten_parameters()
                packed = nn.utils.rnn.pack_padded_sequence(
                    h_conv, seq_lens.detach().cpu(), batch_first=True, enforce_sorted=False,
                )
                gru_p, _ = self.gru(packed)
                h_gru, _ = nn.utils.rnn.pad_packed_sequence(gru_p, batch_first=True, total_length=seq_len)
            else:
                h_gru, _ = self.gru(h_conv)
            h = self.norm1(h_conv + h_gru.to(h_conv.dtype))

            key_pad = None
            if seq_lens is not None:
                key_pad = torch.arange(seq_len, device=step_feats.device)[None, :] >= seq_lens[:, None]
            attn_out, _ = self.attn(h, h, h, key_padding_mask=key_pad, need_weights=False)
            h = self.norm2(h + attn_out)
            delta = torch.tanh(self.out_head(h).squeeze(-1)) * self.max_delta
            return raw_logits + delta

    return RegionContextRefiner()
