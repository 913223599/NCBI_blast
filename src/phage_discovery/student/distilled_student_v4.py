# -*- coding: utf-8 -*-
"""
V4 升级版高容量多模态知识蒸馏学生模型与跨窗上下文精修器（全神经网络端到端流水线）

核心改进：
1. Masked Pooling 修复短片段 (<=1kb) 信号稀释问题：对 DNA ResNet+BiGRU 严格按有效长度掩码与 pack_padded 处理，
   确保同一短序列在不同填充长度下表征一致，不被结尾 N-padding 稀释；
2. 内置三模态门控融合网络（约 3.1M 参数）：
   - Branch 1: 1D Dilated ResNet + Packed BiGRU（原始碱基特征 + 200bp 亚窗口分割）；
   - Branch 2: 嵌入式 ORF Synteny Transformer（直接内部抽取操纵子语法表征）；
   - Branch 3: 带内置均值方差归一化的 Residual Tabular MLP（185 维局部结构/理化特征）；
   - Semantic Aux Head: 隐式蛋白功能域监督（离线 DIAMOND 赋予的 4 维语义，推理零 BLASTp）；
3. RegionContextRefiner（跨窗 BiGRU+Attention 精修器）：
   - 在 contig 连续滑窗序列上综合 35kb+ 长程语境与语义概率走势，抑制孤立转座酶脉冲并抬升退化隐蔽前噬菌体。
"""
import argparse
import gc
import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, cast

import numpy as np

from ..benchmark.model_eval import evaluate_model_scores_on_split, load_split_info, tune_decoder_on_val
from ..experts.expert_a_xgb import summarize_report
from ..experts.expert_b_cnn import _resolve_part_fasta
from ..experts.expert_c_orf import MAX_ORFS_PER_WIN, ORF_FEAT_DIM, _load_or_extract_part
from ..experts.seq_dataset import load_window_sequences, reverse_complement_codes
from ..features.window_features import SUB_BINS
from .distilled_student import _focal_bce_with_logits, _kd_bce_loss, _sub_bce_dice_loss

logger = logging.getLogger("phage_discovery.student.distilled_student_v4")

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
):
    """构建 V4 高容量三模态隐式语义神经网络学生模型（支持 Masked Pooling 与多任务输出）。"""
    import torch
    from torch import nn

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
                nn.Linear(ORF_FEAT_DIM, orf_d_model),
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

        def forward(self, tokens, counts):
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
            return torch.where(has_any[:, None], emb, empty)

    class DistilledStudentV4Net(nn.Module):
        feat_mean: torch.Tensor
        feat_std: torch.Tensor

        def __init__(self):
            super().__init__()
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
        ):
            bsz, _, max_seq = dna.shape
            if lengths is None:
                lengths = torch.full((bsz,), max_seq, dtype=torch.long, device=dna.device)
            if orf_tokens is None:
                orf_tokens = torch.zeros((bsz, MAX_ORFS_PER_WIN, ORF_FEAT_DIM), dtype=dna.dtype, device=dna.device)
            if orf_counts is None:
                orf_counts = torch.zeros((bsz,), dtype=torch.long, device=dna.device)

            e_dna, h_seq = self._forward_dna_branch(dna, lengths)
            e_orf = self.orf_stream(orf_tokens, orf_counts)

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
            h_seq, h_fused = self._forward_backbone(
                dna,
                tab,
                lengths=lengths,
                orf_tokens=orf_tokens,
                orf_counts=orf_counts,
            )

            sem_logits = self.sem_head(h_fused)
            win_logit = self.win_head(torch.cat([h_fused, torch.sigmoid(sem_logits)], dim=-1)).squeeze(-1)

            sub_feat = self.sub_pool(h_seq) + self.sub_cond(h_fused).unsqueeze(-1)
            sub_logits = self.sub_head(sub_feat).squeeze(1)

            if return_aux:
                return {
                    "win_logit": win_logit,
                    "sub_logits": sub_logits,
                    "sem_logits": sem_logits,
                    "win_emb": h_fused,
                }
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


def extract_refiner_step_features(
    win_logits: np.ndarray,
    sem_logits: np.ndarray,
    sub_probs: np.ndarray,
    lengths: np.ndarray,
    max_len: int = 5000,
) -> np.ndarray:
    """将单窗模型输出汇总为与绝对基因组无关的 15 维时间步特征，供 RegionContextRefiner 使用。"""
    n = len(win_logits)
    out = np.zeros((n, REFINER_STEP_FEAT_DIM), dtype=np.float32)
    if n == 0:
        return out
    win_probs = 1.0 / (1.0 + np.exp(-np.clip(win_logits, -20.0, 20.0)))
    sem_probs = 1.0 / (1.0 + np.exp(-np.clip(sem_logits, -20.0, 20.0)))
    sub_mean = sub_probs.mean(axis=1)
    sub_max = sub_probs.max(axis=1)
    sub_std = sub_probs.std(axis=1)
    sub_hi = (sub_probs >= 0.5).mean(axis=1)
    valid_frac = lengths.astype(np.float32) / max(1.0, float(max_len))
    log_len = np.log1p(lengths.astype(np.float32)) / float(np.log1p(max_len))

    out[:, 0] = win_logits
    out[:, 1] = win_probs
    out[:, 2:6] = np.clip(sem_logits, -12.0, 12.0)
    out[:, 6:10] = sem_probs
    out[:, 10] = sub_mean
    out[:, 11] = sub_max
    out[:, 12] = sub_std
    out[:, 13] = sub_hi
    out[:, 14] = 0.5 * valid_frac + 0.5 * log_len
    return out


def group_windows_by_contig(
    contig_ids: np.ndarray,
    starts: np.ndarray,
    *,
    max_gap_bp: Optional[int] = 5000,
    source_tags: Optional[np.ndarray] = None,
) -> List[np.ndarray]:
    """按 (source_tag, contig_id) 分组并依 start_bp 升序排列，超出物理步长间隙时自动拆段。"""
    groups: Dict[Any, List[int]] = {}
    if source_tags is not None:
        for idx, (tag, cid) in enumerate(zip(source_tags, contig_ids)):
            groups.setdefault((str(tag), str(cid)), []).append(idx)
    else:
        for idx, cid in enumerate(contig_ids):
            groups.setdefault(str(cid), []).append(idx)

    ordered_groups: List[np.ndarray] = []
    for key in groups:
        idxs = np.asarray(groups[key], dtype=np.int64)
        order = np.argsort(starts[idxs], kind="stable")
        sorted_idxs = idxs[order]
        if max_gap_bp is not None and len(sorted_idxs) > 1:
            sorted_starts = starts[sorted_idxs]
            splits = np.where(np.diff(sorted_starts) > max_gap_bp)[0] + 1
            if splits.size > 0:
                for sub_g in np.split(sorted_idxs, splits):
                    if len(sub_g) > 0:
                        ordered_groups.append(sub_g)
                continue
        ordered_groups.append(sorted_idxs)
    return ordered_groups


def _predict_v4_all(
    model,
    codes: np.ndarray,
    lengths: np.ndarray,
    feats: np.ndarray,
    orf_tokens: np.ndarray,
    orf_counts: np.ndarray,
    device,
    batch_size: int = 128,
) -> Dict[str, np.ndarray]:
    import torch

    model.eval()
    n = len(feats)
    out_win_logit = np.zeros(n, dtype=np.float32)
    out_win_prob = np.zeros(n, dtype=np.float32)
    out_sub_prob = np.zeros((n, SUB_BINS), dtype=np.float32)
    out_sem_logit = np.zeros((n, SEMANTIC_DIM), dtype=np.float32)
    if n == 0:
        return {
            "win_logits": out_win_logit,
            "win_probs": out_win_prob,
            "sub_probs": out_sub_prob,
            "sem_logits": out_sem_logit,
        }

    rc = reverse_complement_codes(codes, lengths)
    max_len = codes.shape[1]
    with torch.no_grad(), torch.autocast(device_type=device.type, dtype=torch.float16, enabled=device.type == "cuda"):
        for i in range(0, n, batch_size):
            sl = slice(i, i + batch_size)
            c1 = torch.from_numpy(codes[sl].astype(np.int64)).to(device)
            oh1 = torch.nn.functional.one_hot(c1, num_classes=5)[..., :4].permute(0, 2, 1).float()
            c2 = torch.from_numpy(rc[sl].astype(np.int64)).to(device)
            oh2 = torch.nn.functional.one_hot(c2, num_classes=5)[..., :4].permute(0, 2, 1).float()
            tb = torch.from_numpy(feats[sl]).to(device)
            ln = torch.from_numpy(lengths[sl].astype(np.int64)).to(device)
            tk = torch.from_numpy(orf_tokens[sl]).to(device)
            cn = torch.from_numpy(orf_counts[sl].astype(np.int64)).to(device)

            r1 = model(oh1, tb, lengths=ln, orf_tokens=tk, orf_counts=cn, return_aux=True)
            r2 = model(oh2, tb, lengths=ln, orf_tokens=tk, orf_counts=cn, return_aux=True)

            w1, w2 = r1["win_logit"].float(), r2["win_logit"].float()
            p1, p2 = torch.sigmoid(w1), torch.sigmoid(w2)
            out_win_prob[sl] = ((p1 + p2) * 0.5).cpu().numpy()
            out_win_logit[sl] = ((w1 + w2) * 0.5).cpu().numpy()

            sp1 = torch.sigmoid(r1["sub_logits"].float())
            sp2 = torch.flip(torch.sigmoid(r2["sub_logits"].float()), dims=[1])
            sp = torch.where((ln == max_len).unsqueeze(1), (sp1 + sp2) * 0.5, sp1)
            out_sub_prob[sl] = sp.cpu().numpy()

            out_sem_logit[sl] = ((r1["sem_logits"].float() + r2["sem_logits"].float()) * 0.5).cpu().numpy()

    return {
        "win_logits": out_win_logit,
        "win_probs": out_win_prob,
        "sub_probs": out_sub_prob,
        "sem_logits": out_sem_logit,
    }


def predict_with_context_refiner(
    refiner,
    win_logits: np.ndarray,
    sem_logits: np.ndarray,
    sub_probs: np.ndarray,
    lengths: np.ndarray,
    contig_ids: np.ndarray,
    starts: np.ndarray,
    device,
    *,
    max_len: int = 5000,
    min_seq_len: int = 3,
    max_gap_bp: Optional[int] = 5000,
) -> np.ndarray:
    """使用 RegionContextRefiner 对按 contig 排好序且物理连续的窗口序列进行跨窗精修。"""
    import torch

    n = len(win_logits)
    out_probs = 1.0 / (1.0 + np.exp(-np.clip(win_logits, -20.0, 20.0)))
    if refiner is None or n == 0:
        return out_probs.astype(np.float32)

    refiner.eval()
    step_feats = extract_refiner_step_features(win_logits, sem_logits, sub_probs, lengths, max_len=max_len)
    groups = group_windows_by_contig(contig_ids, starts, max_gap_bp=max_gap_bp)
    with torch.no_grad():
        for idxs in groups:
            if len(idxs) < min_seq_len:
                continue
            sf_t = torch.from_numpy(step_feats[idxs][None, ...]).to(device)
            rl_t = torch.from_numpy(win_logits[idxs][None, ...]).to(device)
            ln_t = torch.tensor([len(idxs)], dtype=torch.long, device=device)
            ref_logits = refiner(sf_t, rl_t, seq_lens=ln_t).squeeze(0).float().cpu().numpy()
            out_probs[idxs] = 1.0 / (1.0 + np.exp(-np.clip(ref_logits, -20.0, 20.0)))
    return out_probs.astype(np.float32)


def _apply_refiner_augmentations(
    step_feats: np.ndarray,
    raw_logits: np.ndarray,
    labels: np.ndarray,
    rng: np.random.Generator,
) -> Tuple[np.ndarray, np.ndarray]:
    """针对隐蔽退化弱前噬菌体（>=3窗高hallmark）与 1~2 窗孤立低 hallmark 假阳脉冲合成训练增强。"""
    sf = step_feats.copy()
    rl = raw_logits.copy()
    w = len(labels)
    if w < 4:
        return sf, rl

    def _sync_logit_and_prob(sl: slice, vals: np.ndarray) -> None:
        clipped = np.clip(vals, -20.0, 20.0).astype(np.float32)
        rl[sl] = clipped
        sf[sl, 0] = clipped
        sf[sl, 1] = 1.0 / (1.0 + np.exp(-clipped))

    # 1) 搜索连续正前噬菌体片段 (>=3 窗)，模拟隐蔽/退化中置信度分布并保持 hallmark 语义
    pos_runs: List[Tuple[int, int]] = []
    cur = 0
    while cur < w:
        if labels[cur] == 1:
            end = cur + 1
            while end < w and labels[end] == 1:
                end += 1
            if end - cur >= 3:
                pos_runs.append((cur, end))
            cur = end
        else:
            cur += 1

    if pos_runs and rng.random() < 0.45:
        seg_s, seg_e = pos_runs[int(rng.integers(0, len(pos_runs)))]
        seg_len = seg_e - seg_s
        span = int(rng.integers(3, min(10, seg_len) + 1))
        anchor = int(rng.integers(seg_s, seg_e - span + 1))
        sl = slice(anchor, anchor + span)
        # 温和缩放至 0.65~2.95 logit（对应 p ~ 0.66~0.95），避免与真实中等置信前噬菌体失调
        ceil_logit = float(rng.uniform(1.25, 2.95))
        degraded = rng.uniform(0.70, ceil_logit, size=span).astype(np.float32)
        if span >= 5 and rng.random() < 0.30:
            dip_idx = int(rng.integers(1, span - 1))
            degraded[dip_idx] = float(rng.uniform(0.40, 1.05))
        _sync_logit_and_prob(sl, np.minimum(rl[sl], degraded))
        # 确保连续弱化区保有典型 phage hallmark（至少若干核心窗）与低 transposase，避免被误当转座酶脉冲
        hall_floor = rng.uniform(0.45, 2.0, size=span).astype(np.float32)
        sf[sl, 2] = np.maximum(sf[sl, 2], hall_floor)
        sf[sl, 6] = 1.0 / (1.0 + np.exp(-np.clip(sf[sl, 2], -20.0, 20.0)))
        sf[sl, 4] = np.minimum(sf[sl, 4], rng.uniform(-2.8, -1.0, size=span).astype(np.float32))
        sf[sl, 8] = 1.0 / (1.0 + np.exp(-np.clip(sf[sl, 4], -20.0, 20.0)))

    # 2) 在远离正前噬菌体（前后各至少 2 窗均为 0）的纯阴性背景注入 1~2 窗孤立低 hallmark 假阳脉冲
    safe_neg_starts: List[int] = []
    for i in range(w):
        if labels[i] != 0:
            continue
        left_ok = all(labels[k] == 0 for k in range(max(0, i - 2), i))
        right_ok = all(labels[k] == 0 for k in range(i + 1, min(w, i + 3)))
        if left_ok and right_ok:
            safe_neg_starts.append(i)

    if safe_neg_starts and rng.random() < 0.45:
        pos0 = int(rng.choice(safe_neg_starts))
        mode = float(rng.random())
        max_width = 2 if (pos0 + 1 in safe_neg_starts and pos0 + 1 < w) else 1
        width = 2 if (mode >= 0.80 and max_width == 2) else int(rng.integers(1, max_width + 1))
        sl = slice(pos0, pos0 + width)
        spike_logit = rng.uniform(1.6, 3.8, size=width).astype(np.float32)
        _sync_logit_and_prob(sl, spike_logit)

        # 所有孤立假阳脉冲共同特征：低 phage_hallmark 与低 tail
        sf[sl, 2] = rng.uniform(-3.4, -1.0, size=width).astype(np.float32)
        sf[sl, 6] = 1.0 / (1.0 + np.exp(-np.clip(sf[sl, 2], -20.0, 20.0)))
        sf[sl, 5] = np.minimum(sf[sl, 5], rng.uniform(-2.6, -0.7, size=width).astype(np.float32))
        sf[sl, 9] = 1.0 / (1.0 + np.exp(-np.clip(sf[sl, 5], -20.0, 20.0)))

        if mode < 0.35:
            # 模式 1：显式高 transposase 脉冲
            sf[sl, 4] = rng.uniform(1.0, 3.5, size=width).astype(np.float32)
            sf[sl, 8] = 1.0 / (1.0 + np.exp(-np.clip(sf[sl, 4], -20.0, 20.0)))
        elif mode < 0.80:
            # 模式 2：类似 S. aureus 转座酶的低 hallmark 且无明显语义孤立脉冲
            sf[sl, 3] = rng.uniform(-4.5, -1.5, size=width).astype(np.float32)
            sf[sl, 7] = 1.0 / (1.0 + np.exp(-np.clip(sf[sl, 3], -20.0, 20.0)))
            sf[sl, 4] = rng.uniform(-5.5, -2.0, size=width).astype(np.float32)
            sf[sl, 8] = 1.0 / (1.0 + np.exp(-np.clip(sf[sl, 4], -20.0, 20.0)))
        else:
            # 模式 3：低 integrase + 低 hallmark 双窗孤立脉冲
            sf[sl, 3] = rng.uniform(-5.2, -2.5, size=width).astype(np.float32)
            sf[sl, 7] = 1.0 / (1.0 + np.exp(-np.clip(sf[sl, 3], -20.0, 20.0)))
            sf[sl, 4] = rng.uniform(-4.0, -1.5, size=width).astype(np.float32)
            sf[sl, 8] = 1.0 / (1.0 + np.exp(-np.clip(sf[sl, 4], -20.0, 20.0)))
    return sf, rl


def train_context_refiner(
    tr_step_feats: np.ndarray,
    tr_raw_logits: np.ndarray,
    tr_labels: np.ndarray,
    tr_contig_ids: np.ndarray,
    tr_starts: np.ndarray,
    va_step_feats: np.ndarray,
    va_raw_logits: np.ndarray,
    va_labels: np.ndarray,
    va_contig_ids: np.ndarray,
    va_starts: np.ndarray,
    *,
    out_path: Path,
    epochs: int = 16,
    lr: float = 1.5e-3,
    patience: int = 5,
    seed: int = 42,
    use_context_features: bool = True,
    max_delta: float = 2.2,
    tr_source_tags: Optional[np.ndarray] = None,
    max_gap_bp: Optional[int] = 5000,
) -> Tuple[Any, Dict[str, Any]]:
    """按物理连续有序片段训练 RegionContextRefiner，采用正向保护锚定与校准综合早停。"""
    import torch
    import torch.nn.functional as F
    from sklearn.metrics import average_precision_score

    rng = np.random.default_rng(seed)
    torch.manual_seed(seed)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    tr_groups = [
        g
        for g in group_windows_by_contig(
            tr_contig_ids, tr_starts, max_gap_bp=max_gap_bp, source_tags=tr_source_tags,
        )
        if len(g) >= 3
    ]
    va_groups = [
        g
        for g in group_windows_by_contig(va_contig_ids, va_starts, max_gap_bp=max_gap_bp)
        if len(g) >= 3
    ]

    refiner = build_region_context_refiner(
        max_delta=max_delta,
        use_context_features=use_context_features,
    ).to(device)
    refiner_arch = "v2" if use_context_features else "v1"
    if not tr_groups:
        torch.save(refiner.state_dict(), out_path)
        return refiner, {
            "refiner_arch": refiner_arch,
            "best_epoch": 0,
            "best_val_auprc": -1.0,
            "best_val_bce": -1.0,
            "best_val_score": -1.0,
            "tr_contigs": 0,
        }

    opt = torch.optim.AdamW(refiner.parameters(), lr=lr, weight_decay=1e-2)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=max(1, epochs))

    va_keep = va_labels >= 0
    best_score = -1e9
    best_ap = -1.0
    best_bce = 1e9
    best_ep = -1
    bad_ep = 0
    history: List[Dict[str, Any]] = []
    batch_sz = 16

    for ep in range(1, epochs + 1):
        refiner.train()
        order = rng.permutation(len(tr_groups))
        ep_loss = 0.0
        n_used = 0
        for bi in range(0, len(tr_groups), batch_sz):
            b_idxs = order[bi:bi + batch_sz]
            max_w = max(len(tr_groups[k]) for k in b_idxs)
            sf_b = np.zeros((len(b_idxs), max_w, REFINER_STEP_FEAT_DIM), dtype=np.float32)
            rl_b = np.zeros((len(b_idxs), max_w), dtype=np.float32)
            y_b = np.zeros((len(b_idxs), max_w), dtype=np.float32)
            vm_b = np.zeros((len(b_idxs), max_w), dtype=np.float32)
            lens_b = np.zeros((len(b_idxs),), dtype=np.int64)
            for row, gi in enumerate(b_idxs):
                g = tr_groups[gi]
                ln = len(g)
                lens_b[row] = ln
                sf_aug, rl_aug = _apply_refiner_augmentations(
                    tr_step_feats[g], tr_raw_logits[g], tr_labels[g], rng,
                )
                sf_b[row, :ln] = sf_aug
                rl_b[row, :ln] = rl_aug
                lbl = tr_labels[g]
                vm_b[row, :ln] = (lbl >= 0).astype(np.float32)
                y_b[row, :ln] = np.maximum(lbl, 0).astype(np.float32)

            sf_t = torch.from_numpy(sf_b).to(device)
            rl_t = torch.from_numpy(rl_b).to(device)
            y_t = torch.from_numpy(y_b).to(device)
            vm_t = torch.from_numpy(vm_b).to(device)
            ln_t = torch.from_numpy(lens_b).to(device)

            opt.zero_grad(set_to_none=True)
            ref_logits = refiner(sf_t, rl_t, seq_lens=ln_t)
            bce_raw = F.binary_cross_entropy_with_logits(ref_logits, y_t, reduction="none")
            w_cls = torch.where(y_t > 0.5, 1.35, 1.0) * vm_t
            loss_cls = (bce_raw * w_cls).sum() / w_cls.sum().clamp(min=1.0)

            # 非对称正向保护：避免将已高分连续前噬菌体整体向下拖低
            pos_mask = y_t * vm_t
            pos_drop = F.relu(rl_t - ref_logits) * pos_mask
            loss_pos_anchor = 0.35 * (pos_drop ** 2).sum() / pos_mask.sum().clamp(min=1.0)

            # 温和 delta 正则，防止无依据时大幅偏离单窗合理判别
            delta = (ref_logits - rl_t) * vm_t
            loss_reg = 0.06 * (delta ** 2).sum() / vm_t.sum().clamp(min=1.0)

            loss = loss_cls + loss_pos_anchor + loss_reg
            loss.backward()
            torch.nn.utils.clip_grad_norm_(refiner.parameters(), 1.0)
            opt.step()
            ep_loss += float(loss.item()) * len(b_idxs)
            n_used += len(b_idxs)
        sched.step()

        # 验证集整段推理评估（AUPRC + BCE 联合早停）
        refiner.eval()
        va_ref_logits = va_raw_logits.copy()
        with torch.no_grad():
            for g in va_groups:
                sf_t = torch.from_numpy(va_step_feats[g][None, ...]).to(device)
                rl_t = torch.from_numpy(va_raw_logits[g][None, ...]).to(device)
                ln_t = torch.tensor([len(g)], dtype=torch.long, device=device)
                ref_l = refiner(sf_t, rl_t, seq_lens=ln_t).squeeze(0).cpu().numpy()
                va_ref_logits[g] = ref_l

        has_two = bool(np.any(va_keep) and np.unique(va_labels[va_keep]).size > 1)
        if np.any(va_keep):
            va_lk = np.clip(va_ref_logits[va_keep], -20.0, 20.0)
            va_pk = 1.0 / (1.0 + np.exp(-va_lk))
            va_yk = np.maximum(va_labels[va_keep], 0).astype(np.float64)
            va_bce = float(np.mean(np.maximum(va_lk, 0.0) - va_lk * va_yk + np.log1p(np.exp(-np.abs(va_lk)))))
        else:
            va_pk = np.zeros(0, dtype=np.float32)
            va_bce = float(ep_loss / max(1, n_used))
        ap = float(average_precision_score(va_labels[va_keep], va_pk)) if has_two else 0.0
        val_score = (ap - 0.12 * va_bce) if has_two else -va_bce

        history.append({
            "epoch": ep,
            "loss": round(ep_loss / max(1, n_used), 5),
            "val_auprc": round(ap, 5),
            "val_bce": round(va_bce, 5),
            "val_score": round(val_score, 5),
        })
        if val_score > best_score or best_ep < 0:
            best_score, best_ap, best_bce, best_ep, bad_ep = val_score, ap, va_bce, ep, 0
            tmp = out_path.with_name(f".{out_path.name}.tmp")
            torch.save(refiner.state_dict(), tmp)
            tmp.replace(out_path)
        else:
            bad_ep += 1
            if bad_ep >= patience:
                break

    refiner.load_state_dict(torch.load(out_path, map_location=device, weights_only=True))
    return refiner, {
        "refiner_arch": refiner_arch,
        "best_epoch": best_ep,
        "best_val_auprc": round(best_ap, 5),
        "best_val_bce": round(best_bce, 5),
        "best_val_score": round(best_score, 5),
        "tr_contigs": len(tr_groups),
        "history": history,
    }


def _compute_boundary_bin_weights(sub_arr: np.ndarray, sw_arr: np.ndarray) -> np.ndarray:
    """为 200bp 亚区跳变沿前后各 2 bins 及过渡窗口赋予更高损失权重。"""
    n, n_bins = sub_arr.shape
    bin_w = np.ones((n, n_bins), dtype=np.float32)
    if n_bins > 1:
        jumps = np.abs(np.diff(sub_arr, axis=1)) > 0.2
        for k in range(n_bins - 1):
            j = jumps[:, k]
            if np.any(j):
                lo = max(0, k - 1)
                hi = min(n_bins, k + 3)
                bin_w[j, lo:hi] = np.maximum(bin_w[j, lo:hi], 2.0)
    sub_mean = sub_arr.mean(axis=1)
    is_trans = (sub_mean > 0.02) & (sub_mean < 0.98)
    row_w = sw_arr.astype(np.float32) * np.where(is_trans, 1.25, 1.0).astype(np.float32)
    return bin_w * row_w[:, None]


def _extract_sub_head_inputs(
    model,
    codes: np.ndarray,
    lengths: np.ndarray,
    feats: np.ndarray,
    tokens: np.ndarray,
    counts: np.ndarray,
    device,
    batch_size: int = 128,
) -> Tuple[np.ndarray, np.ndarray]:
    """在冻结主干 eval 状态下提取 sub_pool(h_seq) 与 h_fused 特征，杜绝主干权重漂移。"""
    import torch

    n = len(codes)
    if n == 0:
        return (
            np.zeros((0, 1, SUB_BINS), dtype=np.float32),
            np.zeros((0, 1), dtype=np.float32),
        )
    model.eval()
    pool_chunks: List[np.ndarray] = []
    fused_chunks: List[np.ndarray] = []
    with torch.no_grad(), torch.autocast(device_type=device.type, dtype=torch.float16, enabled=device.type == "cuda"):
        for i in range(0, n, batch_size):
            sl = slice(i, i + batch_size)
            c_t = torch.from_numpy(codes[sl].astype(np.int64)).to(device)
            oh = torch.nn.functional.one_hot(c_t, num_classes=5)[..., :4].permute(0, 2, 1).float()
            tb_t = torch.from_numpy(feats[sl]).to(device)
            ln_t = torch.from_numpy(lengths[sl].astype(np.int64)).to(device)
            tk_t = torch.from_numpy(tokens[sl]).to(device)
            cn_t = torch.from_numpy(counts[sl].astype(np.int64)).to(device)
            h_seq, h_fused = model._forward_backbone(oh, tb_t, lengths=ln_t, orf_tokens=tk_t, orf_counts=cn_t)
            pool_chunks.append(model.sub_pool(h_seq).float().cpu().numpy())
            fused_chunks.append(h_fused.float().cpu().numpy())
    return np.concatenate(pool_chunks, axis=0), np.concatenate(fused_chunks, axis=0)


def refine_student_v4_sub_head(
    model,
    tr_codes: np.ndarray,
    tr_lengths: np.ndarray,
    tr_feats: np.ndarray,
    tr_tokens: np.ndarray,
    tr_counts: np.ndarray,
    tr_sub: np.ndarray,
    tr_sw: np.ndarray,
    va_codes: np.ndarray,
    va_lengths: np.ndarray,
    va_feats: np.ndarray,
    va_tokens: np.ndarray,
    va_counts: np.ndarray,
    va_sub: np.ndarray,
    *,
    out_ckpt_path: Optional[Path] = None,
    device=None,
    epochs: int = 12,
    batch_size: int = 128,
    lr: float = 1e-3,
    patience: int = 4,
    seed: int = 42,
    tr_labels: Optional[np.ndarray] = None,
) -> Dict[str, Any]:
    """严格冻结 3.64M 主干权重，仅基于纯 BCE 在过渡与平衡窗口上精修 sub_cond + sub_head 消除边界平台扩散。"""
    import copy
    import torch
    import torch.nn.functional as F

    if device is None:
        device = next(model.parameters()).device
    rng = np.random.default_rng(seed)
    torch.manual_seed(seed)

    va_before = _predict_v4_all(
        model, va_codes, va_lengths, va_feats, va_tokens, va_counts, device, batch_size=max(batch_size, 128),
    )

    valid_mask = tr_sw > 0
    if tr_labels is not None:
        valid_mask = valid_mask & (tr_labels >= -1)
    tr_sub_f = tr_sub.astype(np.float32)
    sub_mean = tr_sub_f.mean(axis=1)

    trans_idx = np.where(valid_mask & (sub_mean > 0.02) & (sub_mean < 0.98))[0]
    pos_idx = np.where(valid_mask & (sub_mean >= 0.98))[0]
    neg_idx = np.where(valid_mask & (sub_mean <= 0.02))[0]

    total_valid = int(np.sum(valid_mask))
    if total_valid <= 512:
        sel_idx = np.where(valid_mask)[0]
    else:
        max_anchor = max(len(trans_idx), 1500)
        pos_sel = rng.choice(pos_idx, size=min(len(pos_idx), max_anchor), replace=False) if len(pos_idx) > 0 else np.zeros(0, dtype=np.int64)
        neg_sel = rng.choice(neg_idx, size=min(len(neg_idx), max_anchor), replace=False) if len(neg_idx) > 0 else np.zeros(0, dtype=np.int64)
        sel_idx = np.concatenate([trans_idx, pos_sel, neg_sel]).astype(np.int64)
        rng.shuffle(sel_idx)

    if len(sel_idx) == 0:
        return {
            "best_epoch": 0,
            "best_val_sub_bce": -1.0,
            "tr_used": 0,
            "tr_trans": 0,
            "win_max_drift": 0.0,
            "sem_max_drift": 0.0,
            "sub_max_delta": 0.0,
            "history": [],
        }

    max_len_seq = int(tr_codes.shape[1]) if tr_codes.ndim == 2 else 5000
    tr_pool, tr_fused = _extract_sub_head_inputs(
        model, tr_codes[sel_idx], tr_lengths[sel_idx], tr_feats[sel_idx], tr_tokens[sel_idx], tr_counts[sel_idx],
        device, batch_size=max(batch_size, 128),
    )
    tr_sub_sel = tr_sub_f[sel_idx]
    tr_w_sel = _compute_boundary_bin_weights(tr_sub_sel, tr_sw[sel_idx])

    # 对满长边界过渡窗口补充反向互补对等样本，增强正反链边界切点对称性
    full_trans = trans_idx[tr_lengths[trans_idx] == max_len_seq]
    if len(full_trans) > 0:
        rc_codes = reverse_complement_codes(tr_codes[full_trans], tr_lengths[full_trans])
        rc_pool, rc_fused = _extract_sub_head_inputs(
            model, rc_codes, tr_lengths[full_trans], tr_feats[full_trans], tr_tokens[full_trans], tr_counts[full_trans],
            device, batch_size=max(batch_size, 128),
        )
        rc_sub = tr_sub_f[full_trans][:, ::-1].copy()
        rc_w = _compute_boundary_bin_weights(rc_sub, tr_sw[full_trans])
        tr_pool = np.concatenate([tr_pool, rc_pool], axis=0)
        tr_fused = np.concatenate([tr_fused, rc_fused], axis=0)
        tr_sub_sel = np.concatenate([tr_sub_sel, rc_sub], axis=0)
        tr_w_sel = np.concatenate([tr_w_sel, rc_w], axis=0)

    # 提取验证集原链及满长反向互补特征，确保 val BCE 口径与双链平均推理完全对齐
    va_sub_f = va_sub.astype(np.float32)
    va_pool_f, va_fused_f = _extract_sub_head_inputs(
        model, va_codes, va_lengths, va_feats, va_tokens, va_counts, device, batch_size=max(batch_size, 128),
    )
    va_rc_mask = (va_lengths == max_len_seq)
    va_rc_idxs = np.where(va_rc_mask)[0]
    if len(va_rc_idxs) > 0:
        va_rc_codes = reverse_complement_codes(va_codes[va_rc_idxs], va_lengths[va_rc_idxs])
        va_pool_rc, va_fused_rc = _extract_sub_head_inputs(
            model, va_rc_codes, va_lengths[va_rc_idxs], va_feats[va_rc_idxs], va_tokens[va_rc_idxs], va_counts[va_rc_idxs],
            device, batch_size=max(batch_size, 128),
        )
    else:
        va_pool_rc = np.zeros((0, tr_pool.shape[1], SUB_BINS), dtype=np.float32)
        va_fused_rc = np.zeros((0, tr_fused.shape[1]), dtype=np.float32)

    va_sub_mean = va_sub_f.mean(axis=1)
    va_trans_mask = (va_sub_mean > 0.02) & (va_sub_mean < 0.98)

    # 严格冻结主干与其它头，仅开放 sub_cond 与 sub_head 参数
    orig_req_grad = {name: p.requires_grad for name, p in model.named_parameters()}
    for p in model.parameters():
        p.requires_grad_(False)
    trainable_params = list(model.sub_cond.parameters()) + list(model.sub_head.parameters())
    for p in trainable_params:
        p.requires_grad_(True)

    opt = torch.optim.AdamW(trainable_params, lr=lr, weight_decay=1e-3)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=max(1, epochs))

    best_bce = 1e9
    best_ep = -1
    bad_ep = 0
    best_sub_cond = copy.deepcopy(model.sub_cond.state_dict())
    best_sub_head = copy.deepcopy(model.sub_head.state_dict())
    history: List[Dict[str, Any]] = []

    for ep in range(1, epochs + 1):
        model.eval()
        model.sub_cond.train()
        model.sub_head.train()
        order = rng.permutation(len(tr_pool))
        ep_loss = 0.0
        n_seen = 0
        for i in range(0, len(order), batch_size):
            b_idx = order[i:i + batch_size]
            p_t = torch.from_numpy(tr_pool[b_idx]).to(device)
            f_t = torch.from_numpy(tr_fused[b_idx]).to(device)
            y_t = torch.from_numpy(tr_sub_sel[b_idx]).to(device)
            w_t = torch.from_numpy(tr_w_sel[b_idx]).to(device)

            opt.zero_grad(set_to_none=True)
            sub_logits = model.sub_head(p_t + model.sub_cond(f_t).unsqueeze(-1)).squeeze(1)
            bce = F.binary_cross_entropy_with_logits(sub_logits, y_t, reduction="none")
            loss = (bce * w_t).sum() / w_t.sum().clamp(min=1e-6)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(trainable_params, 1.0)
            opt.step()
            ep_loss += float(loss.item()) * len(b_idx)
            n_seen += len(b_idx)
        sched.step()

        model.eval()
        with torch.no_grad():
            n_va = len(va_pool_f)
            va_probs = np.zeros((n_va, SUB_BINS), dtype=np.float32)
            for i in range(0, n_va, max(batch_size, 256)):
                sl = slice(i, i + max(batch_size, 256))
                p_t = torch.from_numpy(va_pool_f[sl]).to(device)
                f_t = torch.from_numpy(va_fused_f[sl]).to(device)
                va_probs[sl] = torch.sigmoid(model.sub_head(p_t + model.sub_cond(f_t).unsqueeze(-1)).squeeze(1)).cpu().numpy()
            if len(va_rc_idxs) > 0:
                rc_probs = np.zeros((len(va_rc_idxs), SUB_BINS), dtype=np.float32)
                for i in range(0, len(va_rc_idxs), max(batch_size, 256)):
                    sl = slice(i, i + max(batch_size, 256))
                    p_t = torch.from_numpy(va_pool_rc[sl]).to(device)
                    f_t = torch.from_numpy(va_fused_rc[sl]).to(device)
                    rc_probs[sl] = torch.sigmoid(model.sub_head(p_t + model.sub_cond(f_t).unsqueeze(-1)).squeeze(1)).cpu().numpy()
                va_probs[va_rc_idxs] = 0.5 * (va_probs[va_rc_idxs] + rc_probs[:, ::-1])

        p_clip = np.clip(va_probs, 1e-6, 1.0 - 1e-6)
        bce_mat = -(va_sub_f * np.log(p_clip) + (1.0 - va_sub_f) * np.log(1.0 - p_clip))
        va_all_bce = float(np.mean(bce_mat)) if len(bce_mat) > 0 else float(ep_loss / max(1, n_seen))
        va_trans_bce = float(np.mean(bce_mat[va_trans_mask])) if np.any(va_trans_mask) else va_all_bce
        va_metric = (0.7 * va_trans_bce + 0.3 * va_all_bce) if np.any(va_trans_mask) else va_all_bce

        history.append({
            "epoch": ep,
            "train_bce": round(ep_loss / max(1, n_seen), 6),
            "val_trans_bce": round(va_trans_bce, 6),
            "val_all_bce": round(va_all_bce, 6),
        })
        if va_metric < best_bce or best_ep < 0:
            best_bce, best_ep, bad_ep = va_metric, ep, 0
            best_sub_cond = copy.deepcopy(model.sub_cond.state_dict())
            best_sub_head = copy.deepcopy(model.sub_head.state_dict())
        else:
            bad_ep += 1
            if bad_ep >= patience:
                break

    model.sub_cond.load_state_dict(best_sub_cond)
    model.sub_head.load_state_dict(best_sub_head)
    model.eval()
    for name, p in model.named_parameters():
        p.requires_grad_(orig_req_grad.get(name, True))

    if out_ckpt_path is not None:
        out_p = Path(out_ckpt_path)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        tmp = out_p.with_name(f".{out_p.name}.tmp")
        torch.save(model.state_dict(), tmp)
        tmp.replace(out_p)

    va_after = _predict_v4_all(
        model, va_codes, va_lengths, va_feats, va_tokens, va_counts, device, batch_size=max(batch_size, 128),
    )
    win_max_drift = float(np.max(np.abs(va_after["win_logits"] - va_before["win_logits"]))) if len(va_codes) > 0 else 0.0
    sem_max_drift = float(np.max(np.abs(va_after["sem_logits"] - va_before["sem_logits"]))) if len(va_codes) > 0 else 0.0
    sub_max_delta = float(np.max(np.abs(va_after["sub_probs"] - va_before["sub_probs"]))) if len(va_codes) > 0 else 0.0

    del tr_pool, tr_fused, va_pool_f, va_fused_f, va_pool_rc, va_fused_rc
    if device.type == "cuda":
        torch.cuda.empty_cache()

    return {
        "best_epoch": best_ep,
        "best_val_sub_bce": round(best_bce, 6),
        "tr_used": len(tr_sub_sel),
        "tr_trans": len(trans_idx),
        "win_max_drift": win_max_drift,
        "sem_max_drift": sem_max_drift,
        "sub_max_delta": sub_max_delta,
        "history": history,
    }


def _load_v4_part(
    feature_dir: Path,
    manifest_or_train_dir: Path,
    split: str,
    part: str,
    max_len: int,
    workers: Optional[int],
    *,
    fasta_override: Optional[Path] = None,
    use_semantic: bool = True,
) -> Dict[str, Any]:
    """统一加载某个分片的 tabular 特征、DNA 编码、ORF 张量以及可选 offline 语义目标。"""
    arrs, tokens, counts = _load_or_extract_part(
        feature_dir,
        manifest_or_train_dir,
        split,
        part,
        Path(feature_dir),
        workers,
        fasta_override=fasta_override,
        use_semantic_clean_labels=False,
    )
    orig_labels = arrs["labels"].astype(np.int8, copy=True)
    clean_labels = orig_labels.copy()
    n = len(orig_labels)
    sem_targets = np.zeros((n, SEMANTIC_DIM), dtype=np.float32)
    sem_valid = np.zeros(n, dtype=np.float32)

    if use_semantic:
        sem_path = Path(feature_dir) / f"{split}_{part}_semantic.npz"
        if sem_path.exists():
            with np.load(sem_path, allow_pickle=False) as sem_npz:
                if "clean_labels" in sem_npz and len(sem_npz["clean_labels"]) == n:
                    clean_labels = sem_npz["clean_labels"].astype(np.int8)
                if "sem_targets" in sem_npz and len(sem_npz["sem_targets"]) == n:
                    raw_sem = sem_npz["sem_targets"].astype(np.float32)
                    if raw_sem.ndim == 2 and raw_sem.shape[1] == SEMANTIC_DIM:
                        sem_targets = raw_sem
                    elif raw_sem.ndim == 2 and raw_sem.shape[1] == 2:
                        sem_targets[:, 0] = raw_sem[:, 0]
                        sem_targets[:, 2] = raw_sem[:, 1]
                if "sem_valid_mask" in sem_npz and len(sem_npz["sem_valid_mask"]) == n:
                    sem_valid = sem_npz["sem_valid_mask"].astype(np.float32)
                elif np.any(sem_targets > 0):
                    sem_valid = np.ones(n, dtype=np.float32)

    fasta = _resolve_part_fasta(feature_dir, manifest_or_train_dir, split, part, fasta_override=fasta_override)
    codes, lengths = load_window_sequences(fasta, arrs["contig_ids"], arrs["starts"], arrs["ends"], max_len=max_len)
    return {
        "arrs": arrs,
        "codes": codes,
        "lengths": lengths,
        "tokens": tokens,
        "counts": counts,
        "orig_labels": orig_labels,
        "clean_labels": clean_labels,
        "sem_targets": sem_targets,
        "sem_valid": sem_valid,
    }


CONTIG_REF_PARTS: Tuple[str, ...] = ("chimeras", "mined", "ext_mined", "hard_neg", "hard_v4")


def train_distilled_student_v4(
    train_feature_dir: Path,
    train_dir: Path,
    eval_feature_dir: Path,
    bench_dir: Path,
    out_dir: Path,
    *,
    train_parts: Tuple[str, ...] = ("windows", "chimeras"),
    extra_mined_fasta: Optional[Path] = None,
    extra_fasta_map: Optional[Dict[str, Path]] = None,
    part_weights: Optional[Dict[str, float]] = None,
    teacher_oof_npz: Optional[Path] = None,
    teacher_probs_override: Optional[np.ndarray] = None,
    teacher_weights: Tuple[float, float, float] = (0.4, 0.35, 0.25),
    epochs: int = 24,
    batch_size: int = 64,
    lr: float = 8e-4,
    patience: int = 6,
    max_len: int = 5000,
    dna_channels: int = 160,
    orf_d_model: int = 128,
    orf_nhead: int = 4,
    orf_num_layers: int = 3,
    fusion_dim: int = 256,
    distill_alpha: float = 0.55,
    sub_weight: float = 0.25,
    sem_weight: float = 0.25,
    temperature: float = 2.0,
    focal_gamma: float = 2.0,
    modality_dropout_prob: float = 0.10,
    tune_sub_head: bool = True,
    train_refiner: bool = True,
    refiner_epochs: int = 16,
    train_subbin_refiner: bool = True,
    subbin_epochs: int = 16,
    enable_plateau_decoder: bool = True,
    use_semantic: bool = True,
    workers: Optional[int] = None,
    seed: int = 42,
) -> Dict[str, Any]:
    """训练 V4 高容量三模态蒸馏学生模型、边界亚窗口精修头与跨窗上下文精修器并生成测试报告。"""
    import torch
    from sklearn.metrics import average_precision_score

    torch.manual_seed(seed)
    rng = np.random.default_rng(seed)
    out_root = Path(out_dir).resolve()
    out_root.mkdir(parents=True, exist_ok=True)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    f_map = {k: Path(v) for k, v in (extra_fasta_map or {}).items()}
    if extra_mined_fasta is not None and "mined" not in f_map:
        f_map["mined"] = Path(extra_mined_fasta)
    ordered_parts = list(train_parts)
    mined_npz = Path(train_feature_dir) / "train_mined.npz"
    if "mined" in f_map and f_map["mined"].exists() and mined_npz.exists() and "mined" not in ordered_parts:
        ordered_parts.append("mined")

    w_map = part_weights or {}
    loaded_parts: List[Dict[str, Any]] = []
    part_names_used: List[str] = []
    sw_list: List[np.ndarray] = []
    part_tag_list: List[np.ndarray] = []

    t_data0 = time.perf_counter()
    for part in ordered_parts:
        if not (Path(train_feature_dir) / f"train_{part}.npz").exists():
            continue
        pdata = _load_v4_part(
            train_feature_dir,
            train_dir,
            "train",
            part,
            max_len,
            workers,
            fasta_override=f_map.get(part),
            use_semantic=use_semantic,
        )
        n_p = len(pdata["clean_labels"])
        if n_p == 0:
            continue
        loaded_parts.append(pdata)
        part_names_used.append(part)
        sw_list.append(np.full(n_p, float(w_map.get(part, 1.0)), dtype=np.float32))
        part_tag_list.append(np.full(n_p, part, dtype=object))

    codes_all = np.concatenate([p["codes"] for p in loaded_parts])
    len_all = np.concatenate([p["lengths"] for p in loaded_parts])
    feats_all = np.concatenate([p["arrs"]["features"] for p in loaded_parts])
    tokens_all = np.concatenate([p["tokens"] for p in loaded_parts])
    counts_all = np.concatenate([p["counts"] for p in loaded_parts])
    sub_all = np.concatenate([p["arrs"]["sub_mask"] for p in loaded_parts]).astype(np.float32)
    orig_y_all = np.concatenate([p["orig_labels"] for p in loaded_parts])
    clean_y_all = np.concatenate([p["clean_labels"] for p in loaded_parts])
    sem_t_all = np.concatenate([p["sem_targets"] for p in loaded_parts])
    sem_v_all = np.concatenate([p["sem_valid"] for p in loaded_parts])
    cids_all = np.concatenate([p["arrs"]["contig_ids"] for p in loaded_parts])
    starts_all = np.concatenate([p["arrs"]["starts"] for p in loaded_parts])
    ends_all = np.concatenate([p["arrs"]["ends"] for p in loaded_parts])
    sw_all = np.concatenate(sw_list)
    part_tags_all = np.concatenate(part_tag_list)
    refiner_mask_all = np.isin(part_tags_all, CONTIG_REF_PARTS)
    del loaded_parts, sw_list, part_tag_list

    # 加载或构造多教师 GroupKFold OOF 软概率
    t_oof0 = time.perf_counter()
    if teacher_probs_override is not None and len(teacher_probs_override) == len(clean_y_all):
        teacher_probs_all = np.asarray(teacher_probs_override, dtype=np.float32)
    elif teacher_oof_npz is not None and Path(teacher_oof_npz).exists():
        with np.load(teacher_oof_npz, allow_pickle=False) as tp_npz:
            if "ensemble_oof" in tp_npz and len(tp_npz["ensemble_oof"]) == len(clean_y_all):
                teacher_probs_all = tp_npz["ensemble_oof"].astype(np.float32)
            else:
                wa, wb, wc = teacher_weights
                acc = np.zeros(len(clean_y_all), dtype=np.float32)
                wsum = 0.0
                for key, w in (("xgb_oof", wa), ("exp_b_oof", wb), ("exp_c_oof", wc)):
                    if key in tp_npz and len(tp_npz[key]) == len(clean_y_all) and w > 0:
                        acc += float(w) * tp_npz[key].astype(np.float32)
                        wsum += float(w)
                teacher_probs_all = (acc / max(1e-6, wsum)).astype(np.float32)
    else:
        from .distilled_student import compute_group_oof_xgb_probs

        keep_xgb = clean_y_all >= 0
        xgb_oof = np.where(clean_y_all == 1, 0.9, 0.1).astype(np.float32)
        if np.any(keep_xgb) and np.unique(clean_y_all[keep_xgb]).size > 1:
            xgb_oof[keep_xgb] = compute_group_oof_xgb_probs(
                feats_all[keep_xgb],
                clean_y_all[keep_xgb].astype(np.int32),
                cids_all[keep_xgb],
                n_splits=min(5, len(np.unique(cids_all[keep_xgb]))),
                sample_weights=sw_all[keep_xgb],
                n_estimators=400,
            )
        teacher_probs_all = xgb_oof
    oof_sec = round(time.perf_counter() - t_oof0, 2)

    # 验证集与测试集准备（严禁使用任何测试数据进行训练/早停）
    va_w = _load_v4_part(eval_feature_dir, bench_dir, "val", "windows", max_len, workers, use_semantic=False)
    va_c = _load_v4_part(eval_feature_dir, bench_dir, "val", "chimeras", max_len, workers, use_semantic=False)
    va_codes = np.concatenate([va_w["codes"], va_c["codes"]])
    va_len = np.concatenate([va_w["lengths"], va_c["lengths"]])
    va_feats = np.concatenate([va_w["arrs"]["features"], va_c["arrs"]["features"]])
    va_tokens = np.concatenate([va_w["tokens"], va_c["tokens"]])
    va_counts = np.concatenate([va_w["counts"], va_c["counts"]])
    va_y = np.concatenate([va_w["orig_labels"], va_c["orig_labels"]])
    va_keep = va_y >= 0
    has_two_va = bool(np.any(va_keep) and np.unique(va_y[va_keep]).size > 1)

    # 筛选训练样本：保留 clean_labels>=0 以及真正原始嵌合体边界 (-1)，剔除语义清洗屏蔽的伪负样本
    use_row = (clean_y_all >= 0) | ((clean_y_all == -1) & (orig_y_all == -1))
    codes_tr = codes_all[use_row]
    len_tr = len_all[use_row]
    feats_tr = feats_all[use_row]
    tokens_tr = tokens_all[use_row]
    counts_tr = counts_all[use_row]
    sub_tr = sub_all[use_row]
    y_tr = clean_y_all[use_row]
    teacher_tr = teacher_probs_all[use_row]
    sem_t_tr = sem_t_all[use_row]
    sem_v_tr = sem_v_all[use_row]
    sw_tr = sw_all[use_row]

    valid_idx = y_tr >= 0
    feat_mean, feat_std = _normalize_feature_stats(feats_tr[valid_idx] if np.any(valid_idx) else feats_tr)
    model = build_distilled_student_v4(
        feats_tr.shape[1],
        feat_mean,
        feat_std,
        dna_channels=dna_channels,
        orf_d_model=orf_d_model,
        orf_nhead=orf_nhead,
        orf_num_layers=orf_num_layers,
        fusion_dim=fusion_dim,
    ).to(device)
    n_params = int(sum(p.numel() for p in model.parameters()))

    opt = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=1e-2)
    steps_per_ep = max(1, int(np.ceil(len(y_tr) / batch_size)))
    sched = torch.optim.lr_scheduler.OneCycleLR(opt, max_lr=lr, total_steps=max(1, epochs * steps_per_ep))
    scaler = torch.amp.GradScaler("cuda", enabled=device.type == "cuda")

    pos_cnt = float(np.sum(y_tr == 1))
    neg_cnt = float(np.sum(y_tr == 0))
    pos_w = float(np.clip(neg_cnt / max(1.0, pos_cnt), 0.5, 4.0))
    sem_pos_weight = torch.tensor([1.5, 1.5, 2.0, 1.5], dtype=torch.float32, device=device)
    sem_loss_fn = torch.nn.BCEWithLogitsLoss(pos_weight=sem_pos_weight, reduction="none")

    ckpt_path = out_root / "student_v4.pt"
    best_ap = -1.0
    best_ep = -1
    bad_ep = 0
    history: List[Dict[str, Any]] = []
    if device.type == "cuda":
        torch.cuda.reset_peak_memory_stats()

    t0 = time.perf_counter()
    for ep in range(1, epochs + 1):
        model.train()
        order = rng.permutation(len(y_tr))
        ep_loss = 0.0
        for bi in range(steps_per_ep):
            idx = order[bi * batch_size:(bi + 1) * batch_size]
            b_codes = codes_tr[idx].copy()
            b_len = len_tr[idx]
            b_sub = sub_tr[idx].copy()
            rc_mask = (b_len == max_len) | (b_sub.min(axis=1) == b_sub.max(axis=1))
            if rng.random() < 0.5 and np.any(rc_mask):
                b_codes[rc_mask] = reverse_complement_codes(b_codes[rc_mask], b_len[rc_mask])
                full_only = rc_mask & (b_len == max_len)
                b_sub[full_only] = b_sub[full_only, ::-1]

            c_t = torch.from_numpy(b_codes.astype(np.int64)).to(device)
            oh = torch.nn.functional.one_hot(c_t, num_classes=5)[..., :4].permute(0, 2, 1).float()
            ln_t = torch.from_numpy(b_len.astype(np.int64)).to(device)
            tb_t = torch.from_numpy(feats_tr[idx]).to(device)
            tk_t = torch.from_numpy(tokens_tr[idx]).to(device)
            cn_t = torch.from_numpy(counts_tr[idx].astype(np.int64)).to(device)

            # 轻量模态随机丢弃（Modality Dropout）：随机将少数样本 Tabular 或 ORF 屏蔽，增强纯 DNA 分支表征
            if modality_dropout_prob > 0.0:
                m_drop = rng.random(len(idx))
                orf_drop = m_drop < modality_dropout_prob
                tab_drop = (m_drop >= modality_dropout_prob) & (m_drop < 2.0 * modality_dropout_prob)
                if np.any(orf_drop):
                    od_t = torch.from_numpy(orf_drop).to(device)
                    cn_t = torch.where(od_t, torch.zeros_like(cn_t), cn_t)
                    tk_t = torch.where(od_t[:, None, None], torch.zeros_like(tk_t), tk_t)
                if np.any(tab_drop):
                    td_t = torch.from_numpy(tab_drop).to(device)
                    tb_t = torch.where(td_t[:, None], model.feat_mean.unsqueeze(0).expand_as(tb_t), tb_t)

            yb_raw = y_tr[idx]
            win_valid = torch.from_numpy((yb_raw >= 0).astype(np.float32)).to(device)
            yb = torch.from_numpy(np.maximum(yb_raw, 0).astype(np.float32)).to(device)
            tp = torch.from_numpy(teacher_tr[idx]).to(device)
            sb = torch.from_numpy(b_sub).to(device)
            st_t = torch.from_numpy(sem_t_tr[idx]).to(device)
            sv_t = torch.from_numpy(sem_v_tr[idx]).to(device)
            wb = torch.from_numpy(sw_tr[idx]).to(device)

            opt.zero_grad(set_to_none=True)
            with torch.autocast(device_type=device.type, dtype=torch.float16, enabled=device.type == "cuda"):
                out_d = model(oh, tb_t, lengths=ln_t, orf_tokens=tk_t, orf_counts=cn_t, return_aux=True)
                w_logit = out_d["win_logit"]
                s_logits = out_d["sub_logits"]
                sem_logits = out_d["sem_logits"]

                l_hard = _focal_bce_with_logits(
                    w_logit, yb, pos_weight=pos_w, gamma=focal_gamma, valid_mask=win_valid, sample_weight=wb,
                )
                l_kd = _kd_bce_loss(
                    w_logit, tp, temperature=temperature, valid_mask=win_valid, sample_weight=wb,
                )
                l_sub = _sub_bce_dice_loss(s_logits, sb, sample_weight=wb)
                sem_elem = sem_loss_fn(sem_logits, st_t).mean(dim=1)
                sem_eff = sv_t * wb
                l_sem = (sem_elem * sem_eff).sum() / sem_eff.sum().clamp(min=1e-4)

                loss = (1.0 - distill_alpha) * l_hard + distill_alpha * l_kd + sub_weight * l_sub + sem_weight * l_sem

            cast(torch.Tensor, scaler.scale(loss)).backward()
            scaler.unscale_(opt)
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            scale_before = scaler.get_scale()
            scaler.step(opt)
            scaler.update()
            if not (device.type == "cuda" and scaler.get_scale() < scale_before):
                sched.step()
            ep_loss += float(loss.item()) * len(idx)

        va_pred = _predict_v4_all(
            model, va_codes[va_keep], va_len[va_keep], va_feats[va_keep], va_tokens[va_keep], va_counts[va_keep], device,
            batch_size=max(64, batch_size),
        )
        ap = float(average_precision_score(va_y[va_keep], va_pred["win_probs"])) if has_two_va else -ep_loss
        history.append({"epoch": ep, "train_loss": round(ep_loss / max(1, len(y_tr)), 5), "val_auprc": round(ap, 5)})
        logger.info(f"StudentV4 epoch {ep}: loss={ep_loss / max(1, len(y_tr)):.4f} val_auprc={ap:.4f}")
        if device.type == "cuda":
            torch.cuda.empty_cache()
        if ap > best_ap or best_ep < 0:
            best_ap, best_ep, bad_ep = ap, ep, 0
            tmp = ckpt_path.with_name(f".{ckpt_path.name}.tmp")
            torch.save(model.state_dict(), tmp)
            tmp.replace(ckpt_path)
        else:
            bad_ep += 1
            if bad_ep >= patience:
                break

    train_sec = round(time.perf_counter() - t0, 2)
    peak_mb = round(torch.cuda.max_memory_allocated() / (1024 * 1024), 1) if device.type == "cuda" else 0.0
    model.load_state_dict(torch.load(ckpt_path, map_location=device, weights_only=True))

    sub_tune_info: Dict[str, Any] = {"enabled": False}
    if tune_sub_head:
        sub_tune_info = {
            "enabled": True,
            **refine_student_v4_sub_head(
                model,
                codes_tr,
                len_tr,
                feats_tr,
                tokens_tr,
                counts_tr,
                sub_tr,
                sw_tr,
                va_c["codes"],
                va_c["lengths"],
                va_c["arrs"]["features"],
                va_c["tokens"],
                va_c["counts"],
                va_c["arrs"]["sub_mask"].astype(np.float32),
                out_ckpt_path=ckpt_path,
                device=device,
                seed=seed,
                tr_labels=y_tr,
            ),
        }

    del codes_tr, len_tr, feats_tr, tokens_tr, counts_tr, sub_tr, sem_t_tr, sem_v_tr, sw_tr
    gc.collect()

    va_w_pred = _predict_v4_all(
        model, va_w["codes"], va_w["lengths"], va_w["arrs"]["features"], va_w["tokens"], va_w["counts"], device,
    )
    va_c_pred = _predict_v4_all(
        model, va_c["codes"], va_c["lengths"], va_c["arrs"]["features"], va_c["tokens"], va_c["counts"], device,
    )
    te_w = _load_v4_part(eval_feature_dir, bench_dir, "test", "windows", max_len, workers, use_semantic=False)
    te_c = _load_v4_part(eval_feature_dir, bench_dir, "test", "chimeras", max_len, workers, use_semantic=False)

    t_inf0 = time.perf_counter()
    te_w_pred = _predict_v4_all(
        model, te_w["codes"], te_w["lengths"], te_w["arrs"]["features"], te_w["tokens"], te_w["counts"], device,
    )
    te_c_pred = _predict_v4_all(
        model, te_c["codes"], te_c["lengths"], te_c["arrs"]["features"], te_c["tokens"], te_c["counts"], device,
    )
    infer_sec = round(time.perf_counter() - t_inf0, 3)

    # 可选训练 RegionContextRefiner 与场景 A 200 bp SubBinContextRefiner（融合物理连续分片并按 source_tag+gap 拆分）
    from .subbin_refiner import (
        build_contig_subbin_sequences,
        extract_per_orf_viral_scores,
        predict_subbin_probs_with_refiner,
        project_orf_to_25bins,
        train_subbin_context_refiner,
    )

    refiner = None
    refiner_info: Dict[str, Any] = {"enabled": False}
    refiner_ckpt = out_root / "context_refiner.pt"
    subbin_refiner = None
    subbin_info: Dict[str, Any] = {"enabled": False}
    subbin_ckpt = out_root / "subbin_refiner.pt"
    tr_c_pred = None
    if (train_refiner or train_subbin_refiner) and np.any(refiner_mask_all):
        tr_c_pred = _predict_v4_all(
            model,
            codes_all[refiner_mask_all],
            len_all[refiner_mask_all],
            feats_all[refiner_mask_all],
            tokens_all[refiner_mask_all],
            counts_all[refiner_mask_all],
            device,
        )

    if train_refiner and tr_c_pred is not None:
        tr_sf = extract_refiner_step_features(
            tr_c_pred["win_logits"], tr_c_pred["sem_logits"], tr_c_pred["sub_probs"], len_all[refiner_mask_all], max_len=max_len,
        )
        va_sf = extract_refiner_step_features(
            va_c_pred["win_logits"], va_c_pred["sem_logits"], va_c_pred["sub_probs"], va_c["lengths"], max_len=max_len,
        )
        refiner, r_rep = train_context_refiner(
            tr_sf,
            tr_c_pred["win_logits"],
            clean_y_all[refiner_mask_all],
            cids_all[refiner_mask_all],
            starts_all[refiner_mask_all],
            va_sf,
            va_c_pred["win_logits"],
            va_c["orig_labels"],
            va_c["arrs"]["contig_ids"],
            va_c["arrs"]["starts"],
            out_path=refiner_ckpt,
            epochs=refiner_epochs,
            seed=seed,
            tr_source_tags=part_tags_all[refiner_mask_all],
        )
        refiner_info = {"enabled": True, "ckpt_path": str(refiner_ckpt), **r_rep}

    va_chim_raw_sc = va_c_pred["win_probs"]
    te_chim_raw_sc = te_c_pred["win_probs"]
    va_chim_ref_sc = predict_with_context_refiner(
        refiner, va_c_pred["win_logits"], va_c_pred["sem_logits"], va_c_pred["sub_probs"],
        va_c["lengths"], va_c["arrs"]["contig_ids"], va_c["arrs"]["starts"], device, max_len=max_len,
    ) if refiner is not None else va_chim_raw_sc
    te_chim_ref_sc = predict_with_context_refiner(
        refiner, te_c_pred["win_logits"], te_c_pred["sem_logits"], te_c_pred["sub_probs"],
        te_c["lengths"], te_c["arrs"]["contig_ids"], te_c["arrs"]["starts"], device, max_len=max_len,
    ) if refiner is not None else te_chim_raw_sc

    va_subbin_profiles = None
    te_subbin_profiles = None
    va_chim_sub_eval = va_c_pred["sub_probs"]
    te_chim_sub_eval = te_c_pred["sub_probs"]

    if train_subbin_refiner and tr_c_pred is not None:
        tr_ref_sc = predict_with_context_refiner(
            refiner, tr_c_pred["win_logits"], tr_c_pred["sem_logits"], tr_c_pred["sub_probs"],
            len_all[refiner_mask_all],
            np.array([f"{t}::{c}" for t, c in zip(part_tags_all[refiner_mask_all], cids_all[refiner_mask_all])], dtype=object),
            starts_all[refiner_mask_all],
            device, max_len=max_len,
        ) if refiner is not None else tr_c_pred["win_probs"]

        tr_orf_bins = project_orf_to_25bins(
            tokens_all[refiner_mask_all], counts_all[refiner_mask_all],
            extract_per_orf_viral_scores(model, tokens_all[refiner_mask_all], counts_all[refiner_mask_all], device),
        )
        va_orf_bins = project_orf_to_25bins(
            va_c["tokens"], va_c["counts"],
            extract_per_orf_viral_scores(model, va_c["tokens"], va_c["counts"], device),
        )
        tr_sb_groups = group_windows_by_contig(
            cids_all[refiner_mask_all], starts_all[refiner_mask_all],
            max_gap_bp=max_len, source_tags=part_tags_all[refiner_mask_all],
        )
        va_sb_groups = group_windows_by_contig(va_c["arrs"]["contig_ids"], va_c["arrs"]["starts"], max_gap_bp=max_len)
        tr_sb_seqs = build_contig_subbin_sequences(
            tr_sb_groups,
            starts_all[refiner_mask_all],
            ends_all[refiner_mask_all],
            tr_ref_sc,
            tr_c_pred["win_probs"],
            tr_c_pred["sem_logits"],
            tr_c_pred["sub_probs"],
            win_orf_25bins=tr_orf_bins,
            sub_targets=sub_all[refiner_mask_all],
            valid_win_mask=(clean_y_all[refiner_mask_all] >= 0),
        )
        va_sb_seqs = build_contig_subbin_sequences(
            va_sb_groups,
            va_c["arrs"]["starts"],
            va_c["arrs"]["ends"],
            va_chim_ref_sc,
            va_chim_raw_sc,
            va_c_pred["sem_logits"],
            va_c_pred["sub_probs"],
            win_orf_25bins=va_orf_bins,
            sub_targets=va_c["arrs"]["sub_mask"].astype(np.float32),
        )
        subbin_refiner, sb_rep = train_subbin_context_refiner(
            tr_sb_seqs, va_sb_seqs, out_path=subbin_ckpt, epochs=subbin_epochs, seed=seed,
        )
        subbin_info = {"enabled": True, "ckpt_path": str(subbin_ckpt), **sb_rep}

        va_subbin_profiles, va_chim_sub_eval = predict_subbin_probs_with_refiner(
            subbin_refiner, va_sb_groups, va_c["arrs"]["contig_ids"], va_c["arrs"]["starts"], va_c["arrs"]["ends"],
            va_chim_ref_sc, va_chim_raw_sc, va_c_pred["sem_logits"], va_c_pred["sub_probs"],
            device, win_orf_25bins=va_orf_bins, min_windows=2,
        )
        te_orf_bins = project_orf_to_25bins(
            te_c["tokens"], te_c["counts"],
            extract_per_orf_viral_scores(model, te_c["tokens"], te_c["counts"], device),
        )
        te_sb_groups = group_windows_by_contig(te_c["arrs"]["contig_ids"], te_c["arrs"]["starts"], max_gap_bp=max_len)
        te_subbin_profiles, te_chim_sub_eval = predict_subbin_probs_with_refiner(
            subbin_refiner, te_sb_groups, te_c["arrs"]["contig_ids"], te_c["arrs"]["starts"], te_c["arrs"]["ends"],
            te_chim_ref_sc, te_chim_raw_sc, te_c_pred["sem_logits"], te_c_pred["sub_probs"],
            device, win_orf_25bins=te_orf_bins, min_windows=2,
        )
        del tr_orf_bins, va_orf_bins, te_orf_bins, tr_sb_seqs, va_sb_seqs

    del codes_all, len_all, feats_all, tokens_all, counts_all, sub_all
    gc.collect()
    if device.type == "cuda":
        torch.cuda.empty_cache()

    va_win_sc = va_w_pred["win_probs"]
    te_win_sc = te_w_pred["win_probs"]

    plateau_cands = ((4, 0.90), (0, None)) if enable_plateau_decoder else ((0, None),)
    use_sb = subbin_refiner is not None
    sb_smooth = not use_sb
    sb_pad = 3000 if use_sb else 2000

    decoder_raw = tune_decoder_on_val(
        load_split_info(bench_dir, "val"), va_c["arrs"], va_chim_raw_sc, chim_sub_probs=va_c_pred["sub_probs"],
    )
    decoder_ref = tune_decoder_on_val(
        load_split_info(bench_dir, "val"), va_c["arrs"], va_chim_ref_sc, chim_sub_probs=va_chim_sub_eval,
        plateau_candidates=plateau_cands,
        precomputed_bin_profiles=va_subbin_profiles,
        smooth_profile=sb_smooth,
        refine_pad_bp=sb_pad,
    ) if (refiner is not None or use_sb) else decoder_raw

    val_raw_rep = evaluate_model_scores_on_split(
        bench_dir, "val", va_w["arrs"], va_win_sc, va_c["arrs"], va_chim_raw_sc,
        decoder_raw["seed_threshold"], decoder_raw["extend_threshold"],
        chim_sub_probs=va_c_pred["sub_probs"], sub_threshold=decoder_raw.get("sub_threshold"),
    )
    test_raw_rep = evaluate_model_scores_on_split(
        bench_dir, "test", te_w["arrs"], te_win_sc, te_c["arrs"], te_chim_raw_sc,
        decoder_raw["seed_threshold"], decoder_raw["extend_threshold"],
        chim_sub_probs=te_c_pred["sub_probs"], sub_threshold=decoder_raw.get("sub_threshold"),
    )
    val_ref_rep = evaluate_model_scores_on_split(
        bench_dir, "val", va_w["arrs"], va_win_sc, va_c["arrs"], va_chim_ref_sc,
        decoder_ref["seed_threshold"], decoder_ref["extend_threshold"],
        chim_sub_probs=va_chim_sub_eval, sub_threshold=decoder_ref.get("sub_threshold"),
        plateau_min_windows=int(decoder_ref.get("plateau_min_windows", 0)),
        plateau_second_threshold=decoder_ref.get("plateau_second_threshold"),
        precomputed_bin_profiles=va_subbin_profiles,
        smooth_profile=bool(decoder_ref.get("smooth_profile", True)),
        refine_pad_bp=int(decoder_ref.get("refine_pad_bp", 2000)),
    )
    test_ref_rep = evaluate_model_scores_on_split(
        bench_dir, "test", te_w["arrs"], te_win_sc, te_c["arrs"], te_chim_ref_sc,
        decoder_ref["seed_threshold"], decoder_ref["extend_threshold"],
        chim_sub_probs=te_chim_sub_eval, sub_threshold=decoder_ref.get("sub_threshold"),
        plateau_min_windows=int(decoder_ref.get("plateau_min_windows", 0)),
        plateau_second_threshold=decoder_ref.get("plateau_second_threshold"),
        precomputed_bin_profiles=te_subbin_profiles,
        smooth_profile=bool(decoder_ref.get("smooth_profile", True)),
        refine_pad_bp=int(decoder_ref.get("refine_pad_bp", 2000)),
    )

    np.savez_compressed(
        out_root / "student_scores.npz",
        val_windows=va_win_sc,
        val_chimeras=va_chim_ref_sc,
        val_chimeras_raw=va_chim_raw_sc,
        val_chimeras_sub=va_c_pred["sub_probs"],
        val_chimeras_sub_refined=va_chim_sub_eval,
        test_windows=te_win_sc,
        test_chimeras=te_chim_ref_sc,
        test_chimeras_raw=te_chim_raw_sc,
        test_chimeras_sub=te_c_pred["sub_probs"],
        test_chimeras_sub_refined=te_chim_sub_eval,
    )

    # 释放模型并保存 V4 元数据与标准/兼容双份报告
    del model, refiner, subbin_refiner
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()

    meta = {
        "model_version": "v4",
        "feat_dim": int(feat_std.shape[0]),
        "max_len": max_len,
        "dna_channels": dna_channels,
        "orf_d_model": orf_d_model,
        "orf_nhead": orf_nhead,
        "orf_num_layers": orf_num_layers,
        "fusion_dim": fusion_dim,
        "sem_dim": SEMANTIC_DIM,
        "use_context_refiner": bool(refiner_info["enabled"]),
        "refiner_arch": refiner_info.get("refiner_arch", "v2" if refiner_info["enabled"] else "none"),
        "refiner_ckpt": str(refiner_ckpt) if refiner_info["enabled"] else None,
        "use_subbin_refiner": bool(subbin_info["enabled"]),
        "subbin_arch": subbin_info.get("arch", "none"),
        "subbin_ckpt": str(subbin_ckpt) if subbin_info["enabled"] else None,
        "student_ckpt": str(ckpt_path),
    }
    meta_path = out_root / "student_v4_meta.json"
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    total_test_mb = float(test_raw_rep["chimera_benchmark"]["overall"].get("total_scanned_mb") or 20.862)
    est_sec_per_5mb = round((infer_sec / max(1e-6, total_test_mb)) * 5.0, 3)

    active_dec = decoder_ref if refiner_info["enabled"] else decoder_raw
    report: Dict[str, Any] = {
        "model_name": "StudentV4_TriModal_MaskedSemantic",
        "model_version": "v4",
        "trained_at": datetime.now().isoformat(timespec="seconds"),
        "device": str(device),
        "architecture": meta,
        "params": n_params,
        "train_parts_used": part_names_used,
        "train_rows": int(np.sum(use_row)),
        "oof_teacher_sec": oof_sec,
        "data_prep_sec": round(time.perf_counter() - t_data0, 2),
        "train_sec": train_sec,
        "peak_gpu_mem_mb": peak_mb,
        "test_inference_sec": infer_sec,
        "est_sec_per_5mb": est_sec_per_5mb,
        "best_epoch": best_ep,
        "best_val_auprc": round(best_ap, 5),
        "history": history,
        "sub_head_refinement": sub_tune_info,
        "context_refiner": refiner_info,
        "subbin_refiner": subbin_info,
        "decoder_tuned_on_val": active_dec,
        "decoder_raw_on_val": decoder_raw,
        "val": val_ref_rep if (refiner_info["enabled"] or subbin_info["enabled"]) else val_raw_rep,
        "test": test_ref_rep if (refiner_info["enabled"] or subbin_info["enabled"]) else test_raw_rep,
        "val_raw": val_raw_rep,
        "test_raw": test_raw_rep,
        "model_path": str(ckpt_path),
        "meta_path": str(meta_path),
    }

    for fname in ("student_v4_report.json", "student_report.json"):
        rp = out_root / fname
        tmp_rp = out_root / f".{fname}.tmp"
        tmp_rp.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp_rp.replace(rp)
    report["report_path"] = str(out_root / "student_v4_report.json")
    return report


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="训练 V4 三模态知识蒸馏学生模型与上下文精修器")
    parser.add_argument("--train-feature-dir", required=True)
    parser.add_argument("--train-dir", required=True)
    parser.add_argument("--eval-feature-dir", required=True)
    parser.add_argument("--bench-dir", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--epochs", type=int, default=24)
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--extra-mined-fasta", default=None)
    parser.add_argument("--no-refiner", action="store_true")
    parser.add_argument("--no-subbin-refiner", action="store_true")
    args = parser.parse_args()
    rep = train_distilled_student_v4(
        Path(args.train_feature_dir),
        Path(args.train_dir),
        Path(args.eval_feature_dir),
        Path(args.bench_dir),
        Path(args.out_dir),
        epochs=args.epochs,
        batch_size=args.batch_size,
        extra_mined_fasta=Path(args.extra_mined_fasta) if args.extra_mined_fasta else None,
        train_refiner=not args.no_refiner,
        train_subbin_refiner=not args.no_subbin_refiner,
    )
    print(json.dumps(summarize_report({**rep, "best_iteration": rep["best_epoch"]}), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
