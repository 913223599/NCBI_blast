# -*- coding: utf-8 -*-
"""
轻量 ORF 蛋白序列 + 邻域上下文功能分区与宿主防御对抗精判模块 (OrfFunctionalJudge)。

设计定位（与全基因组滑窗扫描器解耦的单一职责后置精判模型）：
1. 输入：由候选区段或 Contig 解析出的连续 ORF 列表 [(start, end, strand, aa_seq), ...]；
2. 蛋白级表征（两通道可选对比）：
   - AA 一级序列通道：氨基酸 Token Embedding + 多尺度 1D 空洞残差卷积 + Attention Pooling，直接捕捉溶菌酶/终末酶/整合酶/防御系统结构基序；
   - 肽理化与拓扑统计通道（104 维）：复用 _encode_protein_22(22) + 7x7 二肽(49) + 3x3x3 三肽(27) + 6 维邻域基因拓扑（长度/链向/前后间距与同向共线性）；
3. 基因序上下文通道：3 层 TransformerEncoder 在 32-ORF 连续滑窗上下文（覆盖 25~35 kb 操纵子）内聚合基因簇共线性；
4. 输出：10 维功能分区 logits（P0..P8 沿用 FUNCTIONAL_PARTITION_NAMES，第 10 维 P9=host_defense_virulence）与 1 维噬菌体同源基因 logit。
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Sequence, Tuple

import numpy as np

from ..data.functional_partitions import FUNCTIONAL_PARTITION_NAMES
from ..experts.expert_c_orf import _encode_protein_22
from ..features.peptide_features import (
    DIPEPTIDE_7X7_DIM,
    TRIPEPTIDE_3X3X3_DIM,
    encode_peptide_3x3x3_triad,
    encode_peptide_7x7_dipeptide,
)

logger = logging.getLogger("phage_discovery.student.orf_functional_judge")

JUDGE_CLASS_NAMES: Tuple[str, ...] = tuple(FUNCTIONAL_PARTITION_NAMES) + ("host_defense_virulence",)
NUM_JUDGE_CLASSES: int = len(JUDGE_CLASS_NAMES)

MAX_JUDGE_AA_LEN: int = 512
CTX_WIN_ORFS: int = 32
ORF_JUDGE_STAT_DIM: int = 22 + DIPEPTIDE_7X7_DIM + TRIPEPTIDE_3X3X3_DIM + 6  # 104

_STD_AA = "ACDEFGHIKLMNPQRSTVWY"
_AA_TOKEN_LUT = np.full(256, 21, dtype=np.uint8)  # 未知/非标准残基统一映射为 <unk>=21
for _idx, _ch in enumerate(_STD_AA, start=1):
    _AA_TOKEN_LUT[ord(_ch)] = _idx
_AA_TOKEN_LUT[ord("*")] = 0
_AA_TOKEN_LUT[ord("-")] = 0
AA_VOCAB_SIZE: int = 22


def encode_aa_tokens_batch(
    aa_seqs: Sequence[str],
    *,
    max_len: int = MAX_JUDGE_AA_LEN,
) -> Tuple[np.ndarray, np.ndarray]:
    """
    将一批氨基酸序列编码为定长整数矩阵 (N, max_len) 与有效长度向量 (N,)。
    <pad>=0, 20 种标准氨基酸=1..20, <unk>=21；有效长度至少为 1（空序列 length=1 以防全掩码 NaN）。
    """
    n = len(aa_seqs)
    ids = np.zeros((n, max_len), dtype=np.uint8)
    lens = np.ones(n, dtype=np.int32)
    for i, raw in enumerate(aa_seqs):
        s = (raw or "").strip().upper().rstrip("*")
        if not s:
            continue
        if len(s) > max_len:
            s = s[:max_len]
        arr = np.frombuffer(s.encode("ascii", errors="replace"), dtype=np.uint8)
        toks = _AA_TOKEN_LUT[arr]
        ids[i, : len(toks)] = toks
        lens[i] = max(1, len(toks))
    return ids, lens


def encode_contig_orf_stat_features(
    orfs: Sequence[Tuple[int, int, int, str]],
) -> np.ndarray:
    """
    为一条 Contig 上按坐标排序的连续 ORF [(start, end, strand, aa_seq), ...] 计算纯序列+拓扑同源特征 (M, 104)。
    训练与推理均完全仅依赖 (start, end, strand, aa_seq)，消除对离线 Pyrodigal 内部打分的依赖偏移。
    """
    m = len(orfs)
    out = np.zeros((m, ORF_JUDGE_STAT_DIM), dtype=np.float32)
    if m == 0:
        return out

    off_dp = 22
    off_tri = off_dp + DIPEPTIDE_7X7_DIM
    off_topo = off_tri + TRIPEPTIDE_3X3X3_DIM

    for i, (s_bp, e_bp, strand, aa) in enumerate(orfs):
        aa_clean = (aa or "").strip().upper().rstrip("*")
        out[i, :22] = _encode_protein_22(aa_clean)
        out[i, off_dp:off_tri] = encode_peptide_7x7_dipeptide(aa_clean)
        out[i, off_tri:off_topo] = encode_peptide_3x3x3_triad(aa_clean)

        aa_len = max(1, len(aa_clean))
        st = 1.0 if int(strand) >= 0 else -1.0
        gap_prev = max(0, int(s_bp) - int(orfs[i - 1][1])) if i > 0 else 0
        gap_next = max(0, int(orfs[i + 1][0]) - int(e_bp)) if (i + 1) < m else 0
        same_prev = 1.0 if (i > 0 and (1 if int(orfs[i - 1][2]) >= 0 else -1) == int(st)) else 0.0
        same_next = 1.0 if ((i + 1) < m and (1 if int(orfs[i + 1][2]) >= 0 else -1) == int(st)) else 0.0

        out[i, off_topo] = float(np.log1p(aa_len) / 8.0)
        out[i, off_topo + 1] = st
        out[i, off_topo + 2] = float(np.log1p(gap_prev) / 10.0)
        out[i, off_topo + 3] = float(np.log1p(gap_next) / 10.0)
        out[i, off_topo + 4] = same_prev
        out[i, off_topo + 5] = same_next

    return out


def slice_contig_orf_windows(
    orfs: Sequence[Tuple[int, int, int, str]],
    *,
    ctx_len: int = CTX_WIN_ORFS,
    stride: int = 16,
    max_aa_len: int = MAX_JUDGE_AA_LEN,
) -> List[Dict[str, Any]]:
    """
    将一条 Contig 上排序的 ORF 序列切分为定长 ctx_len 上下文滑窗样本，返回每窗的编码张量与原始全局索引。
    """
    m = len(orfs)
    if m == 0:
        return []

    stat_all = encode_contig_orf_stat_features(orfs)
    aa_ids_all, aa_lens_all = encode_aa_tokens_batch([o[3] for o in orfs], max_len=max_aa_len)

    windows: List[Dict[str, Any]] = []
    if m <= ctx_len:
        starts = [0]
    else:
        starts = list(range(0, m - ctx_len + 1, max(1, int(stride))))
        if starts[-1] + ctx_len < m:
            starts.append(m - ctx_len)

    for st in starts:
        ed = min(m, st + ctx_len)
        vcnt = ed - st
        w_aa = np.zeros((ctx_len, max_aa_len), dtype=np.uint8)
        w_len = np.ones(ctx_len, dtype=np.int32)
        w_stat = np.zeros((ctx_len, ORF_JUDGE_STAT_DIM), dtype=np.float32)

        w_aa[:vcnt] = aa_ids_all[st:ed]
        w_len[:vcnt] = aa_lens_all[st:ed]
        w_stat[:vcnt] = stat_all[st:ed]

        windows.append(
            {
                "start_idx": int(st),
                "end_idx": int(ed),
                "valid_count": int(vcnt),
                "aa_ids": w_aa,
                "aa_lens": w_len,
                "stat_feats": w_stat,
            }
        )
    return windows


def build_orf_functional_judge(
    stat_mean: np.ndarray,
    stat_std: np.ndarray,
    *,
    stat_dim: int = ORF_JUDGE_STAT_DIM,
    d_model: int = 160,
    nhead: int = 4,
    num_ctx_layers: int = 3,
    ctx_len: int = CTX_WIN_ORFS,
    aa_embed_dim: int = 32,
    aa_channels: int = 96,
    use_aa_seq: bool = True,
    num_classes: int = NUM_JUDGE_CLASSES,
    arch: str = "baseline",
    aa_mask_prob: float = 0.0,
    distill_dim: int = 1024,
):
    """
    构建纯正轻量的“ORF 一级序列结构基序 + 邻域基因序上下文”功能与防御精判网络。
    支持：
      - use_aa_seq=False：纯肽统计特征消融对照；
      - arch="baseline"：原始多尺度 1D 卷积 + 标准绝对位置 Transformer + 独立输出头；
      - arch="r1"：序列 Token 掩码防过拟合 + 序列远程自注意力 + 4 头多原型池化 +
        基因间相对操纵子拓扑偏置注意力 + 先功能后鉴伪语义门控耦合头；
      - arch="r2"：在 R1 基础上增加浅层高分辨率 stride=1 短基序支路（保留 3~7aa 防御活性中心细节）
        与训练期 ProstT5 折叠同源语义特征对齐投影头（return_seq_distill=True 时激活）；
      - arch="r3"：在 R2 基础上增加操纵子宏观态势门控（OperonMacroContextGate，感知整段窗口
        编码紧致度与功能模块协同态势并 FiLM 调制回逐 ORF 表征）与窗级完整度预测辅助头；
      - arch="unified"：共享 R2/R3 蛋白与操纵子基础知识底座 `h_base`，内部功能分化为两路专家头
        （分化头 B `intact_func_head` 直连未经宏观平滑的 `h_base` 保持完整度峰值，分化头 C
        经宏观门控专精防御排雷与 10 类精准分区），支持推理期 `active_experts` 按需激活。
    """
    import torch
    from torch import nn

    if arch not in ("baseline", "r1", "r2", "r3", "unified", "unified_v4_3"):
        raise ValueError(f"不支持的 OrfFunctionalJudge 架构: {arch}")
    is_ctx_rel = arch in ("r1", "r2", "r3", "unified", "unified_v4_3")
    is_r2_or_r3 = arch in ("r2", "r3", "unified", "unified_v4_3")
    is_r3 = arch in ("r3", "unified", "unified_v4_3")
    is_unified = arch in ("unified", "unified_v4_3")
    is_v4_3 = arch == "unified_v4_3"

    class MaskedSeqConvBlock1d(nn.Module):
        def __init__(self, ch: int, kernel_size: int, dilation: int):
            super().__init__()
            pad = ((kernel_size - 1) * dilation) // 2
            self.conv1 = nn.Conv1d(ch, ch, kernel_size=kernel_size, padding=pad, dilation=dilation)
            self.norm1 = nn.GroupNorm(8, ch)
            self.conv2 = nn.Conv1d(ch, ch, kernel_size=kernel_size, padding=pad, dilation=dilation)
            self.norm2 = nn.GroupNorm(8, ch)
            self.act = nn.GELU()

        def forward(self, x: torch.Tensor, mask: torch.Tensor) -> torch.Tensor:
            h = self.act(self.norm1(self.conv1(x))) * mask
            h = self.norm2(self.conv2(h)) * mask
            return self.act(x + h) * mask

    class OrfSequenceEncoder(nn.Module):
        def __init__(self):
            super().__init__()
            self.emb = nn.Embedding(AA_VOCAB_SIZE, aa_embed_dim, padding_idx=0)
            if is_ctx_rel:
                # R1/R2：在 stem 阶段即执行 stride=2 基序压紧 (512->256)，兼顾更大等效感受野与低显存高吞吐
                self.stem = nn.Sequential(
                    nn.Conv1d(aa_embed_dim, aa_channels, kernel_size=5, stride=2, padding=2),
                    nn.GroupNorm(8, aa_channels),
                    nn.GELU(),
                )
                self.blocks = nn.ModuleList(
                    [
                        MaskedSeqConvBlock1d(aa_channels, kernel_size=5, dilation=1),
                        MaskedSeqConvBlock1d(aa_channels, kernel_size=7, dilation=2),
                    ]
                )
                # 二次降采样 (256->128) 后再做远程 Self-Attention 与 4 头池化，捕捉跨域交互同时抑制连续模板死记
                self.ds_conv = nn.Sequential(
                    nn.Conv1d(aa_channels, aa_channels, kernel_size=5, stride=2, padding=2),
                    nn.GroupNorm(8, aa_channels),
                    nn.GELU(),
                )
                seq_attn_layer = nn.TransformerEncoderLayer(
                    d_model=aa_channels,
                    nhead=4,
                    dim_feedforward=aa_channels * 2,
                    dropout=0.20,
                    activation="gelu",
                    batch_first=True,
                    norm_first=True,
                )
                self.seq_attn = nn.TransformerEncoder(
                    seq_attn_layer,
                    num_layers=2,
                    enable_nested_tensor=False,
                )
                self.attn_pool = nn.Conv1d(aa_channels, 4, kernel_size=1)
                proj_in = aa_channels * (2 + 4) + 1
                if is_r2_or_r3:
                    # R2/R3：额外保留浅层高分辨率 stride=1 短基序支路（k=5 与 k=3），找回被降采样抹平的 Defense/MGE 短活性中心
                    self.hi_motif = nn.Sequential(
                        nn.Conv1d(aa_embed_dim, 48, kernel_size=5, stride=1, padding=2),
                        nn.GroupNorm(8, 48),
                        nn.GELU(),
                        nn.Conv1d(48, 48, kernel_size=3, stride=1, padding=1),
                        nn.GroupNorm(8, 48),
                        nn.GELU(),
                    )
                    proj_in += 48 * 2
                self.proj = nn.Sequential(
                    nn.Linear(proj_in, 128),
                    nn.LayerNorm(128),
                    nn.GELU(),
                    nn.Dropout(0.25),
                )
                if is_r2_or_r3:
                    self.distill_proj = nn.Sequential(
                        nn.Linear(128, 256),
                        nn.LayerNorm(256),
                        nn.GELU(),
                        nn.Linear(256, int(distill_dim)),
                    )
            else:
                self.stem = nn.Sequential(
                    nn.Conv1d(aa_embed_dim, aa_channels, kernel_size=5, padding=2),
                    nn.GroupNorm(8, aa_channels),
                    nn.GELU(),
                )
                self.blocks = nn.ModuleList(
                    [
                        MaskedSeqConvBlock1d(aa_channels, kernel_size=5, dilation=1),
                        MaskedSeqConvBlock1d(aa_channels, kernel_size=5, dilation=2),
                        MaskedSeqConvBlock1d(aa_channels, kernel_size=7, dilation=4),
                    ]
                )
                self.attn_pool = nn.Conv1d(aa_channels, 1, kernel_size=1)
                self.proj = nn.Sequential(
                    nn.Linear(aa_channels * 3 + 1, 128),
                    nn.LayerNorm(128),
                    nn.GELU(),
                    nn.Dropout(0.15),
                )

        def forward(self, flat_ids: torch.Tensor, flat_lens: torch.Tensor) -> torch.Tensor:
            n_items, max_l = flat_ids.shape
            if n_items == 0:
                return flat_ids.new_zeros((0, 128), dtype=torch.float32)

            pos = torch.arange(max_l, device=flat_ids.device)[None, :]
            raw_valid = pos < flat_lens[:, None]
            if is_ctx_rel and self.training and aa_mask_prob > 0.0:
                # 仅对有效氨基酸残基执行随机掩码 (<unk>=21)，迫使网络依赖结构化保守位点而非局部死记
                drop_mask = (torch.rand_like(flat_ids, dtype=torch.float32) < float(aa_mask_prob)) & raw_valid & (flat_ids > 0)
                in_ids = torch.where(drop_mask, flat_ids.new_full((), 21), flat_ids)
            else:
                in_ids = flat_ids

            mask = raw_valid.unsqueeze(1)
            x = self.emb(in_ids).permute(0, 2, 1)
            mask_f = mask.to(x.dtype)
            if is_ctx_rel:
                h = self.stem(x * mask_f)
                s1_len = h.shape[-1]
                s1_cnt = ((flat_lens - 1) // 2 + 1).clamp(min=1, max=s1_len)
                s1_mask = (torch.arange(s1_len, device=flat_ids.device)[None, :] < s1_cnt[:, None]).unsqueeze(1).to(h.dtype)
                h = h * s1_mask
                for blk in self.blocks:
                    h = blk(h, s1_mask)

                h_ds = self.ds_conv(h)
                ds_len = h_ds.shape[-1]
                # 按实际氨基酸长度计算总 stride=4 下采样后有效块掩码，至少保留首块防全空 NaN
                ds_cnt = ((flat_lens - 1) // 4 + 1).clamp(min=1, max=ds_len)
                ds_pos = torch.arange(ds_len, device=flat_ids.device)[None, :]
                ds_valid = ds_pos < ds_cnt[:, None]
                h_seq = h_ds.transpose(1, 2)  # (N, ds_len, C)
                h_seq = self.seq_attn(h_seq, src_key_padding_mask=~ds_valid)
                h_c = h_seq.transpose(1, 2)
                ds_mask_f = ds_valid.unsqueeze(1).to(h_c.dtype)
                h_c = h_c * ds_mask_f

                mean_p = h_c.sum(dim=-1) / ds_mask_f.sum(dim=-1).clamp(min=1.0)
                max_p = h_c.masked_fill(~ds_valid.unsqueeze(1), -1e4).max(dim=-1).values
                attn_l = self.attn_pool(h_c).masked_fill(~ds_valid.unsqueeze(1), -1e4)  # (N, 4, ds_len)
                attn_w = torch.softmax(attn_l, dim=-1)
                attn_p = torch.einsum("nkl,ncl->nkc", attn_w, h_c).reshape(n_items, -1)
                len_f = torch.log1p(flat_lens.to(h_c.dtype)).unsqueeze(-1) / 7.0
                parts = [mean_p, max_p, attn_p, len_f]
                if is_r2_or_r3:
                    hi = self.hi_motif(x * mask_f) * mask_f
                    hi_mean = hi.sum(dim=-1) / mask_f.sum(dim=-1).clamp(min=1.0)
                    hi_max = hi.masked_fill(~mask, -1e4).max(dim=-1).values
                    parts.extend([hi_mean, hi_max])
                return self.proj(torch.cat(parts, dim=-1))

            h = self.stem(x * mask_f) * mask_f
            for blk in self.blocks:
                h = blk(h, mask_f)

            mean_p = h.sum(dim=-1) / mask_f.sum(dim=-1).clamp(min=1.0)
            max_p = h.masked_fill(~mask, -1e4).max(dim=-1).values
            attn_l = self.attn_pool(h).squeeze(1).masked_fill(~mask.squeeze(1), -1e4)
            attn_w = torch.softmax(attn_l, dim=-1).unsqueeze(1)
            attn_p = (h * attn_w).sum(dim=-1)
            len_f = torch.log1p(flat_lens.to(h.dtype)).unsqueeze(-1) / 7.0
            return self.proj(torch.cat([mean_p, max_p, attn_p, len_f], dim=-1))

    class RelativeOperonAttentionBlock(nn.Module):
        """携带基因间相对位置、同链共线性与紧密操纵子连接偏置的 Pre-Norm Transformer 层。"""

        def __init__(self, dim: int, num_heads: int, dropout: float = 0.15):
            super().__init__()
            self.dim = dim
            self.num_heads = num_heads
            self.head_dim = dim // num_heads
            self.norm1 = nn.LayerNorm(dim)
            self.qkv = nn.Linear(dim, dim * 3)
            self.bias_proj = nn.Linear(4, num_heads, bias=False)
            self.proj = nn.Linear(dim, dim)
            self.drop = nn.Dropout(dropout)
            self.norm2 = nn.LayerNorm(dim)
            self.ffn = nn.Sequential(
                nn.Linear(dim, dim * 2),
                nn.GELU(),
                nn.Dropout(dropout),
                nn.Linear(dim * 2, dim),
                nn.Dropout(dropout),
            )

        def forward(
            self,
            x: torch.Tensor,
            rel_topo: torch.Tensor,
            valid_mask: torch.Tensor,
        ) -> torch.Tensor:
            bsz, seq_len, _ = x.shape
            h = self.norm1(x)
            qkv = self.qkv(h).reshape(bsz, seq_len, 3, self.num_heads, self.head_dim).permute(2, 0, 3, 1, 4)
            q, k, v = qkv[0], qkv[1], qkv[2]
            scores = torch.matmul(q, k.transpose(-2, -1)) / (float(self.head_dim) ** 0.5)
            # 注入相对操纵子拓扑偏置 (B, H, L, L)
            topo_bias = self.bias_proj(rel_topo).permute(0, 3, 1, 2)
            scores = scores + topo_bias.to(scores.dtype)
            # 对无效 Key 槽位与无效 Query 行执行防溢出屏蔽
            key_invalid = (~valid_mask)[:, None, None, :]
            scores = scores.masked_fill(key_invalid, -1e4)
            attn = torch.softmax(scores, dim=-1)
            attn = attn * valid_mask[:, None, :, None].to(attn.dtype)
            attn = self.drop(attn)
            out = torch.matmul(attn, v).transpose(1, 2).reshape(bsz, seq_len, self.dim)
            x = x + self.drop(self.proj(out))
            x = x + self.ffn(self.norm2(x))
            return x * valid_mask.unsqueeze(-1).to(x.dtype)

    def _compute_operon_rel_topo(
        stat_feats: torch.Tensor,
        valid_mask: torch.Tensor,
    ) -> torch.Tensor:
        """
        从纯序列统计张量 stat_feats[..., 98:102] 解析每对 ORF (i, j) 的 4 维操纵子相对拓扑关系：
          [signed_rel_pos, inv_dist, same_strand, same_operon_block]。
        严格屏蔽无效槽位，确保 Padding 不变性。
        """
        bsz, seq_len, _ = stat_feats.shape
        device = stat_feats.device
        vm_f = valid_mask.to(torch.float32)

        strand = torch.where(stat_feats[:, :, 99] >= 0.0, 1.0, -1.0) * vm_f
        gap_next = torch.expm1(torch.clamp(stat_feats[:, :, 101].float() * 10.0, min=0.0, max=14.0))
        same_next_flag = stat_feats[:, :, 103].float() > 0.5

        pos = torch.arange(seq_len, device=device, dtype=torch.float32)
        diff = pos[None, :] - pos[:, None]  # (L, L) j - i
        signed_rel = torch.clamp(diff / 16.0, -1.0, 1.0)[None, :, :].expand(bsz, -1, -1)
        inv_dist = (1.0 / (1.0 + torch.abs(diff)))[None, :, :].expand(bsz, -1, -1)
        same_strand = (0.5 * (strand[:, :, None] * strand[:, None, :] + 1.0))

        # 判断相邻 (k -> k+1) 是否处于紧密同向操纵子（同链且间隙 < 350bp）
        if seq_len > 1:
            adj_valid = valid_mask[:, :-1] & valid_mask[:, 1:]
            adj_operon = adj_valid & same_next_flag[:, :-1] & (gap_next[:, :-1] <= 350.0)
            breaks = (~adj_operon).to(torch.long)
            block_ids = torch.cat(
                [torch.zeros((bsz, 1), device=device, dtype=torch.long), torch.cumsum(breaks, dim=1)],
                dim=1,
            )
            same_operon = (block_ids[:, :, None] == block_ids[:, None, :]).to(torch.float32)
        else:
            same_operon = torch.ones((bsz, 1, 1), device=device, dtype=torch.float32)

        pair_valid = (valid_mask[:, :, None] & valid_mask[:, None, :]).to(torch.float32)
        rel = torch.stack([signed_rel, inv_dist, same_strand, same_operon], dim=-1)
        return rel * pair_valid.unsqueeze(-1)

    class OrfFunctionalJudgeNet(nn.Module):
        stat_mean: torch.Tensor
        stat_std: torch.Tensor

        def __init__(self):
            super().__init__()
            self.arch = arch
            self.use_aa_seq = bool(use_aa_seq)
            self.register_buffer("stat_mean", torch.tensor(stat_mean, dtype=torch.float32))
            self.register_buffer("stat_std", torch.tensor(stat_std, dtype=torch.float32))

            self.stat_enc = nn.Sequential(
                nn.Linear(stat_dim, 128),
                nn.LayerNorm(128),
                nn.GELU(),
                nn.Dropout(0.15),
            )
            if self.use_aa_seq:
                self.seq_enc = OrfSequenceEncoder()
                fuse_in = 256
            else:
                fuse_in = 128

            self.orf_fuse = nn.Sequential(
                nn.Linear(fuse_in, d_model),
                nn.LayerNorm(d_model),
                nn.GELU(),
                nn.Dropout(0.15),
            )

            if is_ctx_rel:
                self.ctx_blocks = nn.ModuleList(
                    [RelativeOperonAttentionBlock(d_model, nhead, dropout=0.15) for _ in range(num_ctx_layers)]
                )
            else:
                self.ctx_pos_emb = nn.Parameter(torch.randn(1, ctx_len, d_model) * 0.02)
                enc_layer = nn.TransformerEncoderLayer(
                    d_model=d_model,
                    nhead=nhead,
                    dim_feedforward=d_model * 2,
                    dropout=0.15,
                    activation="gelu",
                    batch_first=True,
                    norm_first=True,
                )
                self.ctx_encoder = nn.TransformerEncoder(
                    enc_layer,
                    num_layers=num_ctx_layers,
                    enable_nested_tensor=False,
                )

            self.func10_head = nn.Sequential(
                nn.Linear(d_model, 128),
                nn.GELU(),
                nn.Dropout(0.15),
                nn.Linear(128, num_classes),
            )
            if is_ctx_rel:
                # 先功能后鉴伪耦合头：接收 [ctx_h, func10_prob, ctx_func_mean(10), ctx_core_max(1), ctx_p9_mean(1)]
                self.phage_head = nn.Sequential(
                    nn.Linear(d_model + num_classes * 2 + 2, 96),
                    nn.LayerNorm(96),
                    nn.GELU(),
                    nn.Dropout(0.15),
                    nn.Linear(96, 1),
                )
                # 显式先验残差门控权重：P9 宿主对抗负向抑制，结构协同正向增强
                self.gamma_p9_self = nn.Parameter(torch.tensor(0.5))
                self.gamma_p9_ctx = nn.Parameter(torch.tensor(0.3))
                self.gamma_core_ctx = nn.Parameter(torch.tensor(0.3))
                if is_r3:
                    # R3：操纵子宏观态势门控与窗级核心完整度辅助头
                    self.macro_pool_w = nn.Linear(d_model, 1)
                    self.macro_fuse = nn.Sequential(
                        nn.Linear(d_model * 2 + 6, d_model),
                        nn.LayerNorm(d_model),
                        nn.GELU(),
                        nn.Dropout(0.15),
                    )
                    self.macro_film_scale = nn.Linear(d_model, d_model)
                    self.macro_film_shift = nn.Linear(d_model, d_model)
                    self.win_core_head = nn.Sequential(
                        nn.Linear(d_model + 6, 64),
                        nn.GELU(),
                        nn.Dropout(0.10),
                        nn.Linear(64, 1),
                    )
                if is_unified:
                    if is_v4_3:
                        # V4.3 分化头 B（DualSkip）：融合未平滑局部单 ORF 表征 e_orf 与宏观上下文 h_base
                        self.intact_dualskip_proj = nn.Sequential(
                            nn.Linear(d_model * 2, d_model),
                            nn.LayerNorm(d_model),
                            nn.GELU(),
                            nn.Dropout(0.15),
                        )
                        # V4.3 窗口级细菌素/Tailocin 协同抑制支路，学习纯尾簇与质粒复制岛风险信号
                        self.tailocin_guard_head = nn.Sequential(
                            nn.Linear(d_model + 14, 64),
                            nn.GELU(),
                            nn.Dropout(0.10),
                            nn.Linear(64, 1),
                        )
                        self.gamma_tailocin = nn.Parameter(torch.tensor(0.5))
                    # 分化头 B（完整度专家）：直连未经宏观平滑的共享底座或 DualSkip，维持结构模块尖锐激活峰
                    self.intact_func_head = nn.Sequential(
                        nn.Linear(d_model, 128),
                        nn.GELU(),
                        nn.Dropout(0.15),
                        nn.Linear(128, num_classes),
                    )
            else:
                self.phage_head = nn.Sequential(
                    nn.Linear(d_model, 64),
                    nn.GELU(),
                    nn.Dropout(0.10),
                    nn.Linear(64, 1),
                )

        def forward(
            self,
            aa_ids: torch.Tensor,
            aa_lens: torch.Tensor,
            stat_feats: torch.Tensor,
            valid_counts: torch.Tensor,
            return_seq_distill: bool = False,
            return_win_core: bool = False,
            active_experts: Sequence[str] | None = None,
            return_experts: bool = False,
            detach_intact_base: bool = False,
        ):
            bsz, seq_len, _ = stat_feats.shape
            pos = torch.arange(seq_len, device=stat_feats.device)[None, :]
            valid_mask = pos < valid_counts[:, None]
            has_any = valid_counts > 0

            stat_norm = (stat_feats - self.stat_mean) / self.stat_std
            # 仅对有效槽位运算并强制归零被 mask 位置，杜绝任何 padding 污染特征统计
            stat_norm = stat_norm * valid_mask.unsqueeze(-1).to(stat_norm.dtype)
            e_stat = self.stat_enc(stat_norm)

            distill_out = None
            if self.use_aa_seq:
                flat_mask = valid_mask.reshape(-1)
                e_seq = e_stat.new_zeros((bsz * seq_len, 128))
                if torch.any(flat_mask):
                    v_ids = aa_ids.reshape(-1, aa_ids.shape[-1])[flat_mask]
                    v_lens = aa_lens.reshape(-1)[flat_mask]
                    seq_out = self.seq_enc(v_ids, v_lens).to(e_seq.dtype)
                    e_seq[flat_mask] = seq_out
                    if return_seq_distill and is_r2_or_r3:
                        d_flat = e_stat.new_zeros((bsz * seq_len, int(distill_dim)))
                        d_flat[flat_mask] = self.seq_enc.distill_proj(seq_out).to(d_flat.dtype)
                        distill_out = d_flat.reshape(bsz, seq_len, int(distill_dim))
                e_seq = e_seq.reshape(bsz, seq_len, 128)
                e_orf = self.orf_fuse(torch.cat([e_stat, e_seq], dim=-1))
            else:
                e_orf = self.orf_fuse(e_stat)

            vm = valid_mask.unsqueeze(-1).to(e_orf.dtype)
            if is_ctx_rel:
                rel_topo = _compute_operon_rel_topo(stat_feats, valid_mask)
                h_base = e_orf * vm
                for blk in self.ctx_blocks:
                    h_base = blk(h_base, rel_topo, valid_mask)

                exp_set = set(active_experts) if active_experts is not None else ({"defense_func", "intact"} if is_unified else {"defense_func"})
                need_defense_func = (not is_unified) or ("defense_func" in exp_set) or ("func" in exp_set) or ("phage" in exp_set)
                need_intact = is_unified and ("intact" in exp_set)

                intact_logits = None
                if need_intact:
                    if is_v4_3:
                        e_in = e_orf.detach() if detach_intact_base else e_orf
                        h_in = h_base.detach() if detach_intact_base else h_base
                        ds_feat = self.intact_dualskip_proj(torch.cat([e_in, h_in], dim=-1)) * vm
                        intact_logits = self.intact_func_head(ds_feat) * vm
                    else:
                        base_in = h_base.detach() if detach_intact_base else h_base
                        intact_logits = self.intact_func_head(base_in) * vm

                func10_logits = None
                phage_logits = None
                win_core_logit = None
                tailocin_neg_logit = None

                if need_defense_func:
                    h = h_base
                    if is_r3:
                        # 提取窗口内基因间宏观统计 (6D): 有效占比/平均对数长/正反链均衡/基因间平均间隙/共线性连续度/长基因比例
                        denom_f = vm.sum(dim=1).clamp(min=1.0)
                        t_slice = (stat_feats[:, :, 98:104] * vm).to(h.dtype)
                        mean_t = t_slice.sum(dim=1) / denom_f  # (B, 6)
                        # 窗级注意力池化 + 最大池化得到操纵子宏观上下文向量
                        w_l = self.macro_pool_w(h).squeeze(-1).masked_fill(~valid_mask, -1e4)
                        w_a = torch.softmax(w_l, dim=-1).unsqueeze(-1)
                        h_attn = (h * w_a).sum(dim=1)
                        h_max = h.masked_fill(~valid_mask.unsqueeze(-1), -1e4).max(dim=1).values
                        h_max = torch.where(has_any[:, None], h_max, h_max.new_zeros(h_max.shape))
                        h_macro = self.macro_fuse(torch.cat([h_attn, h_max, mean_t], dim=-1))
                        scale = 1.0 + 0.5 * torch.tanh(self.macro_film_scale(h_macro)).unsqueeze(1)
                        shift = 0.5 * self.macro_film_shift(h_macro).unsqueeze(1)
                        h = (h * scale + shift) * vm

                    func10_logits = self.func10_head(h) * vm
                    f_prob = torch.sigmoid(func10_logits) * vm

                    denom = vm.sum(dim=1, keepdim=True).clamp(min=1.0)
                    ctx_f_mean = (f_prob.sum(dim=1, keepdim=True) / denom).expand(-1, seq_len, -1)
                    # P0..P4 为核心结构模块，P9 为宿主防御对抗
                    core_max_per_cls = f_prob[:, :, :5].masked_fill(~valid_mask.unsqueeze(-1), 0.0).max(dim=1).values
                    ctx_core_signal = core_max_per_cls.mean(dim=-1, keepdim=True).unsqueeze(1).expand(-1, seq_len, -1)
                    ctx_p9_mean = ctx_f_mean[:, :, 9:10]

                    if is_r3:
                        win_core_logit = self.win_core_head(
                            torch.cat([h_macro, core_max_per_cls, ctx_p9_mean[:, 0, :]], dim=-1)
                        ).squeeze(-1) * has_any.to(h.dtype)

                    ph_in = torch.cat([h, f_prob, ctx_f_mean, ctx_core_signal, ctx_p9_mean], dim=-1)
                    raw_ph = self.phage_head(ph_in).squeeze(-1)
                    p9_self = f_prob[:, :, 9]
                    tailocin_pen = 0.0
                    if is_v4_3:
                        tailocin_neg_logit = self.tailocin_guard_head(
                            torch.cat([h_macro, core_max_per_cls, ctx_f_mean[:, 0, :9]], dim=-1)
                        ).squeeze(-1) * has_any.to(h.dtype)
                        tailocin_pen = (
                            torch.nn.functional.softplus(self.gamma_tailocin)
                            * torch.sigmoid(tailocin_neg_logit).unsqueeze(1)
                        )
                    phage_logits = (
                        raw_ph
                        - torch.nn.functional.softplus(self.gamma_p9_self) * (p9_self - 0.5)
                        - torch.nn.functional.softplus(self.gamma_p9_ctx) * ctx_p9_mean.squeeze(-1)
                        + torch.nn.functional.softplus(self.gamma_core_ctx) * ctx_core_signal.squeeze(-1)
                        - tailocin_pen
                    ) * valid_mask.to(raw_ph.dtype)

                if return_experts:
                    return {
                        "h_base": h_base,
                        "e_orf": e_orf,
                        "func10_logits": func10_logits,
                        "phage_logits": phage_logits,
                        "intact_func_logits": intact_logits,
                        "distill_out": distill_out,
                        "win_core_logit": win_core_logit,
                        "tailocin_neg_logit": tailocin_neg_logit,
                    }
                if return_win_core and is_r3:
                    if return_seq_distill and distill_out is not None:
                        return func10_logits, phage_logits, distill_out, win_core_logit
                    return func10_logits, phage_logits, win_core_logit
                if return_seq_distill and is_r2_or_r3 and distill_out is not None:
                    return func10_logits, phage_logits, distill_out
                return func10_logits, phage_logits

            h = e_orf + self.ctx_pos_emb[:, :seq_len, :].to(e_orf.dtype)
            safe_pad = (~valid_mask) & ((pos > 0) | has_any[:, None])
            h = self.ctx_encoder(h, src_key_padding_mask=safe_pad)
            vm = valid_mask.unsqueeze(-1).to(h.dtype)
            h = h * vm

            func10_logits = self.func10_head(h) * vm
            phage_logits = self.phage_head(h).squeeze(-1) * valid_mask.to(h.dtype)
            return func10_logits, phage_logits

    return OrfFunctionalJudgeNet()


def predict_contig_orfs_with_judge(
    model,
    orfs: Sequence[Tuple[int, int, int, str]],
    *,
    device: str = "cpu",
    ctx_len: int = CTX_WIN_ORFS,
    stride: int = 16,
    max_aa_len: int = MAX_JUDGE_AA_LEN,
    batch_size: int = 64,
    return_logits: bool = False,
    active_experts: Sequence[str] | None = None,
    return_intact: bool = False,
) -> Dict[str, np.ndarray]:
    """
    使用训练好的 OrfFunctionalJudge 对一条 Contig 的全部连续 ORF 进行中心加权滑窗推理。
    支持 arch="unified" 下按需激活分支（共享 1 次底座前向即可同时产出排雷/分区与未经平滑的完整度分）。
    """
    import torch

    m = len(orfs)
    if m == 0:
        out_empty: Dict[str, np.ndarray] = {
            "phage_probs": np.zeros(0, dtype=np.float32),
            "func10_probs": np.zeros((0, NUM_JUDGE_CLASSES), dtype=np.float32),
        }
        if return_logits:
            out_empty["phage_logits"] = np.zeros(0, dtype=np.float32)
            out_empty["func10_logits"] = np.zeros((0, NUM_JUDGE_CLASSES), dtype=np.float32)
        if return_intact:
            out_empty["intact_func_probs"] = np.zeros((0, NUM_JUDGE_CLASSES), dtype=np.float32)
        return out_empty

    windows = slice_contig_orf_windows(orfs, ctx_len=ctx_len, stride=stride, max_aa_len=max_aa_len)
    acc_phage = np.zeros(m, dtype=np.float64)
    acc_func = np.zeros((m, NUM_JUDGE_CLASSES), dtype=np.float64)
    acc_intact = np.zeros((m, NUM_JUDGE_CLASSES), dtype=np.float64)
    acc_phage_l = np.zeros(m, dtype=np.float64)
    acc_func_l = np.zeros((m, NUM_JUDGE_CLASSES), dtype=np.float64)
    acc_weight = np.zeros(m, dtype=np.float64)

    was_training = bool(model.training)
    model.eval()
    dev = torch.device(device)
    center = 0.5 * (ctx_len - 1)
    half_span = max(1.0, 0.5 * ctx_len)
    is_uni = getattr(model, "arch", "baseline") in ("unified", "unified_v4_3")

    with torch.no_grad():
        for i in range(0, len(windows), max(1, int(batch_size))):
            chunk = windows[i : i + max(1, int(batch_size))]
            t_ids = torch.from_numpy(np.stack([w["aa_ids"] for w in chunk])).to(dev, dtype=torch.long)
            t_lens = torch.from_numpy(np.stack([w["aa_lens"] for w in chunk])).to(dev, dtype=torch.long)
            t_stat = torch.from_numpy(np.stack([w["stat_feats"] for w in chunk])).to(dev, dtype=torch.float32)
            t_cnt = torch.tensor([w["valid_count"] for w in chunk], device=dev, dtype=torch.long)

            intact_probs = None
            if is_uni and (return_intact or active_experts is not None):
                exp_d = model(t_ids, t_lens, t_stat, t_cnt, active_experts=active_experts, return_experts=True)
                f_logits = exp_d["func10_logits"] if exp_d["func10_logits"] is not None else exp_d["intact_func_logits"]
                p_logits = (
                    exp_d["phage_logits"]
                    if exp_d["phage_logits"] is not None
                    else torch.zeros(t_ids.shape[:2], device=dev, dtype=torch.float32)
                )
                if exp_d["intact_func_logits"] is not None:
                    intact_probs = torch.sigmoid(exp_d["intact_func_logits"]).float().cpu().numpy()
            else:
                f_logits, p_logits = model(t_ids, t_lens, t_stat, t_cnt)

            f_logits_np = f_logits.float().cpu().numpy()
            p_logits_np = p_logits.float().cpu().numpy()
            f_probs = torch.sigmoid(f_logits).float().cpu().numpy()
            p_probs = torch.sigmoid(p_logits).float().cpu().numpy()

            for wi, w in enumerate(chunk):
                st = w["start_idx"]
                vcnt = w["valid_count"]
                for k in range(vcnt):
                    # 对长 contig 给予窗中心位置更高权重，抑制滑窗边缘上下文截断抖动
                    wt = 1.0 - 0.7 * (abs(float(k) - center) / half_span)
                    acc_phage[st + k] += p_probs[wi, k] * wt
                    acc_func[st + k] += f_probs[wi, k] * wt
                    if intact_probs is not None:
                        acc_intact[st + k] += intact_probs[wi, k] * wt
                    elif return_intact:
                        acc_intact[st + k] += f_probs[wi, k] * wt
                    if return_logits:
                        acc_phage_l[st + k] += p_logits_np[wi, k] * wt
                        acc_func_l[st + k] += f_logits_np[wi, k] * wt
                    acc_weight[st + k] += wt

    if was_training:
        model.train()

    denom = np.maximum(acc_weight, 1e-6)
    res: Dict[str, np.ndarray] = {
        "phage_probs": (acc_phage / denom).astype(np.float32),
        "func10_probs": (acc_func / denom[:, None]).astype(np.float32),
    }
    if return_logits:
        res["phage_logits"] = (acc_phage_l / denom).astype(np.float32)
        res["func10_logits"] = (acc_func_l / denom[:, None]).astype(np.float32)
    if return_intact:
        res["intact_func_probs"] = (acc_intact / denom[:, None]).astype(np.float32)
    return res
