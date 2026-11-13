# -*- coding: utf-8 -*-
"""
场景 A 专用 200 bp 亚窗口多模态跨窗上下文边界精修模块（SubBinContextRefiner）：
1. 从冻结的 StudentV4 OrfStream 抽取逐 ORF 神经网络注意力显著性得分，并与基因起止/链向/GC 投影至 25 个 200 bp 亚窗；
2. 构建 28 维（或回退 18 维）物理连续 200 bp 分箱序列（整合窗口中心加权置信、语义概率与 ORF 空间跳变沿）；
3. 通过纯并行多尺度空洞残差卷积（DilatedResBlock1D, d=1..16）结合分块滑窗与前向/反向 TTA 精修断点边界。
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from ..experts.expert_c_orf import MAX_ORFS_PER_WIN
from ..features.window_features import SUB_BINS

logger = logging.getLogger(__name__)

BIN_BP_DEFAULT = 200
SUBBIN_BASE_FEAT_DIM = 18
ORF_BIN_FEAT_DIM = 10
SUBBIN_TOTAL_FEAT_DIM = SUBBIN_BASE_FEAT_DIM + ORF_BIN_FEAT_DIM
# 28 维输入中第 19 列对应序列内部局部转录链平均方向（反向对称 TTA 时需取反）
ORF_STRAND_FEAT_INDEX = 19


def _logit_np(p: np.ndarray, eps: float = 1e-4) -> np.ndarray:
    pc = np.clip(p.astype(np.float64), eps, 1.0 - eps)
    return np.log(pc / (1.0 - pc)).astype(np.float32)


def _sig_np(x: np.ndarray) -> np.ndarray:
    xc = np.clip(x.astype(np.float64), -20.0, 20.0)
    return (1.0 / (1.0 + np.exp(-xc))).astype(np.float32)


def extract_per_orf_viral_scores(
    model,
    tokens: np.ndarray,
    counts: np.ndarray,
    device,
    batch_size: int = 512,
) -> np.ndarray:
    """
    从冻结的 StudentV4 OrfStream 中抽取每个窗口内最多 MAX_ORFS_PER_WIN 个基因的
    神经网络注意力概率 (N, MAX_ORFS_PER_WIN)，用于亚窗口精准断点识别。
    """
    import torch

    n = len(tokens)
    out_attn = np.zeros((n, MAX_ORFS_PER_WIN), dtype=np.float32)
    if n == 0 or not hasattr(model, "orf_stream"):
        return out_attn

    was_training = bool(model.training)
    model.eval()
    orf_stream = model.orf_stream
    with torch.no_grad():
        for i in range(0, n, batch_size):
            sl = slice(i, i + batch_size)
            tk = torch.from_numpy(tokens[sl]).to(device)
            cn = torch.from_numpy(counts[sl].astype(np.int64)).to(device)
            _, seq_len, _ = tk.shape
            pos = torch.arange(seq_len, device=device)[None, :]
            valid_mask = pos < cn[:, None]
            has_any = cn > 0
            h = orf_stream.proj(tk) + orf_stream.pos_emb[:, :seq_len, :]
            safe_pad = (~valid_mask) & ((pos > 0) | has_any[:, None])
            h = orf_stream.encoder(h, src_key_padding_mask=safe_pad)
            logits = orf_stream.attn_score(h).squeeze(-1)
            logits_masked = logits.masked_fill(~valid_mask, 0.0)
            probs = torch.sigmoid(logits_masked) * valid_mask.to(logits.dtype)
            out_attn[sl] = probs.float().cpu().numpy()

    if was_training:
        model.train()
    return out_attn


def project_orf_to_25bins(
    tokens: np.ndarray,
    counts: np.ndarray,
    orf_viral_scores: np.ndarray,
    *,
    sub_bins: int = SUB_BINS,
) -> np.ndarray:
    """
    全向量化将每个窗口最多 32 个 ORF tokens 精确投影到 sub_bins 个 200 bp 亚窗 (N, sub_bins, 10)：
      [0] coding_cov, [1] mean_strand, [2] strand_mix, [3] gene_edge_density,
      [4] orf_gc_mean, [5] orf_gc_diff, [6] orf_log_len, [7] orf_gap_before,
      [8] orf_viral_attn, [9] orf_viral_edge_diff
    """
    n = len(tokens)
    out = np.zeros((n, sub_bins, ORF_BIN_FEAT_DIM), dtype=np.float32)
    if n == 0:
        return out

    b_s = (np.arange(sub_bins, dtype=np.float32) / float(sub_bins))[None, :, None]
    b_e = ((np.arange(sub_bins, dtype=np.float32) + 1.0) / float(sub_bins))[None, :, None]
    bw = 1.0 / float(sub_bins)

    max_orfs = tokens.shape[1]
    idx_t = np.arange(max_orfs, dtype=np.int32)[None, :]
    valid_t = (idx_t < counts[:, None]).astype(np.float32)

    rs = np.clip(tokens[:, :, 6], 0.0, 1.0)[:, None, :]
    re = np.clip(tokens[:, :, 7], 0.0, 1.0)[:, None, :]
    ov = np.maximum(0.0, np.minimum(b_e, re) - np.maximum(b_s, rs)) / bw
    ov = ov * valid_t[:, None, :]

    cov_sum = np.sum(ov, axis=2)
    denom = np.maximum(cov_sum, 1e-6)
    w_norm = ov / denom[:, :, None]

    strand = tokens[:, :, 1][:, None, :]
    orf_gc = tokens[:, :, 2][:, None, :]
    orf_gc_diff = tokens[:, :, 3][:, None, :]
    orf_len = (tokens[:, :, 0] / 10.0)[:, None, :]
    orf_gap = (tokens[:, :, 4] / 8.0)[:, None, :]
    v_attn = orf_viral_scores[:, None, :]

    m_strand = np.sum(w_norm * strand, axis=2)
    m_abs_strand = np.sum(w_norm * np.abs(strand), axis=2)
    strand_conflict = np.maximum(0.0, m_abs_strand - np.abs(m_strand))

    hit_s = ((rs >= b_s) & (rs < b_e) & (valid_t[:, None, :] > 0.5)).astype(np.float32)
    hit_e = ((re > b_s) & (re <= b_e) & (valid_t[:, None, :] > 0.5)).astype(np.float32)
    edge_hit = np.clip(np.sum(hit_s + hit_e, axis=2) * 0.5, 0.0, 1.5)

    out[:, :, 0] = np.clip(cov_sum, 0.0, 1.5)
    out[:, :, 1] = m_strand
    out[:, :, 2] = strand_conflict
    out[:, :, 3] = edge_hit
    out[:, :, 4] = np.sum(w_norm * orf_gc, axis=2)
    out[:, :, 5] = np.sum(w_norm * orf_gc_diff, axis=2)
    out[:, :, 6] = np.sum(w_norm * orf_len, axis=2)
    out[:, :, 7] = np.sum(w_norm * orf_gap, axis=2)
    out[:, :, 8] = np.sum(w_norm * v_attn, axis=2)

    if sub_bins >= 3:
        ds = np.zeros_like(m_strand)
        ds[:, 1:-1] = 0.5 * np.abs(m_strand[:, 2:] - m_strand[:, :-2])
        out[:, :, 2] = np.clip(out[:, :, 2] + 0.5 * ds, 0.0, 1.5)
        dv = np.zeros_like(m_strand)
        dv[:, 1:-1] = 0.5 * (
            np.abs(out[:, 2:, 8] - out[:, :-2, 8]) + np.abs(out[:, 2:, 5] - out[:, :-2, 5])
        )
        out[:, :, 9] = np.clip(dv, 0.0, 1.5)
    return out


def build_contig_subbin_sequences(
    groups: Sequence[np.ndarray],
    starts: np.ndarray,
    ends: np.ndarray,
    win_ref_probs: np.ndarray,
    win_raw_probs: np.ndarray,
    sem_logits: np.ndarray,
    sub_probs: np.ndarray,
    *,
    win_orf_25bins: Optional[np.ndarray] = None,
    sub_targets: Optional[np.ndarray] = None,
    valid_win_mask: Optional[np.ndarray] = None,
    bin_bp: int = BIN_BP_DEFAULT,
    sub_bins: int = SUB_BINS,
) -> List[Dict[str, Any]]:
    """
    将按物理连续区间拆分好的滑窗列表聚合为逐 200 bp 序列特征张量（28 维或 18 维）。
    对标准 5000 bp / 200 bp 对齐滑窗走 O(1) 切片累加快速路径，短残窗自动走等比例区间映射。
    """
    k_pos = np.arange(sub_bins, dtype=np.float64)
    half_k = max(1.0, (sub_bins - 1) * 0.5)
    edge_dist_k = np.abs(k_pos - half_k) / half_k
    w_center = 1.0 - 0.65 * edge_dist_k
    w_sharp = np.maximum(0.05, 1.0 - 0.90 * edge_dist_k)
    ones_k = np.ones(sub_bins, dtype=np.float64)

    sem_probs = _sig_np(sem_logits)
    sub_logits_all = _logit_np(sub_probs)
    use_orf = win_orf_25bins is not None
    d_dim = SUBBIN_TOTAL_FEAT_DIM if use_orf else SUBBIN_BASE_FEAT_DIM
    aligned_span = bin_bp * sub_bins

    seqs: List[Dict[str, Any]] = []
    for g in groups:
        if len(g) == 0:
            continue
        origin = int(starts[g[0]])
        max_e = int(np.max(ends[g]))
        n_bins = max(1, (max_e - origin + bin_bp - 1) // bin_bp)

        s_z_unif = np.zeros(n_bins, dtype=np.float64)
        s_z_cent = np.zeros(n_bins, dtype=np.float64)
        s_z_shrp = np.zeros(n_bins, dtype=np.float64)
        w_sum_unif = np.zeros(n_bins, dtype=np.float64)
        w_sum_cent = np.zeros(n_bins, dtype=np.float64)
        w_sum_shrp = np.zeros(n_bins, dtype=np.float64)

        sp_max = np.zeros(n_bins, dtype=np.float64)
        sp_min = np.ones(n_bins, dtype=np.float64)
        min_edist = np.ones(n_bins, dtype=np.float64)

        w_ref_s = np.zeros(n_bins, dtype=np.float64)
        w_raw_s = np.zeros(n_bins, dtype=np.float64)
        w_ref_max = np.zeros(n_bins, dtype=np.float64)
        sem_s = np.zeros((n_bins, sem_probs.shape[1]), dtype=np.float64)
        orf_s = np.zeros((n_bins, ORF_BIN_FEAT_DIM), dtype=np.float64) if use_orf else None

        tgt_s = np.zeros(n_bins, dtype=np.float64)
        tgt_cnt = np.zeros(n_bins, dtype=np.float64)

        for idx in g:
            s_bp = int(starts[idx])
            e_bp = int(ends[idx])
            w_span = max(1, e_bp - s_bp)
            sp = sub_probs[idx]
            sz = sub_logits_all[idx]
            wr = float(win_ref_probs[idx])
            ww = float(win_raw_probs[idx])
            sm = sem_probs[idx]
            ob = win_orf_25bins[idx] if win_orf_25bins is not None else None
            is_valid_t = True if valid_win_mask is None else bool(valid_win_mask[idx])
            tg = sub_targets[idx] if sub_targets is not None else None

            rel_s = s_bp - origin
            if w_span == aligned_span and rel_s >= 0 and (rel_s % bin_bp == 0):
                b0 = rel_s // bin_bp
                b1 = b0 + sub_bins
                if b1 <= n_bins:
                    sl = slice(b0, b1)
                    s_z_unif[sl] += sz
                    w_sum_unif[sl] += ones_k
                    s_z_cent[sl] += sz * w_center
                    w_sum_cent[sl] += w_center
                    s_z_shrp[sl] += sz * w_sharp
                    w_sum_shrp[sl] += w_sharp

                    sp_max[sl] = np.maximum(sp_max[sl], sp)
                    sp_min[sl] = np.minimum(sp_min[sl], sp)
                    min_edist[sl] = np.minimum(min_edist[sl], edge_dist_k)

                    w_ref_s[sl] += wr * w_center
                    w_raw_s[sl] += ww * w_center
                    w_ref_max[sl] = np.maximum(w_ref_max[sl], wr)
                    sem_s[sl] += w_center[:, None] * sm[None, :]
                    if orf_s is not None and ob is not None:
                        orf_s[sl] += ob * w_center[:, None]
                    if tg is not None and is_valid_t:
                        tgt_s[sl] += tg
                        tgt_cnt[sl] += ones_k
                    continue

            sub_w = float(w_span) / float(sub_bins)
            for k in range(sub_bins):
                bs = s_bp + round(k * sub_w) - origin
                be = s_bp + round((k + 1) * sub_w) - origin
                b0 = max(0, min(n_bins - 1, bs // bin_bp))
                b1 = max(b0 + 1, min(n_bins, (be + bin_bp - 1) // bin_bp))

                wc = float(w_center[k])
                ws = float(w_sharp[k])
                ed = float(edge_dist_k[k])
                pk = float(sp[k])
                zk = float(sz[k])

                s_z_unif[b0:b1] += zk
                w_sum_unif[b0:b1] += 1.0
                s_z_cent[b0:b1] += zk * wc
                w_sum_cent[b0:b1] += wc
                s_z_shrp[b0:b1] += zk * ws
                w_sum_shrp[b0:b1] += ws

                sp_max[b0:b1] = np.maximum(sp_max[b0:b1], pk)
                sp_min[b0:b1] = np.minimum(sp_min[b0:b1], pk)
                min_edist[b0:b1] = np.minimum(min_edist[b0:b1], ed)

                w_ref_s[b0:b1] += wr * wc
                w_raw_s[b0:b1] += ww * wc
                w_ref_max[b0:b1] = np.maximum(w_ref_max[b0:b1], wr)
                sem_s[b0:b1] += sm[None, :] * wc
                if orf_s is not None and ob is not None:
                    orf_s[b0:b1] += ob[k][None, :] * wc
                if tg is not None and is_valid_t:
                    tgt_s[b0:b1] += float(tg[k])
                    tgt_cnt[b0:b1] += 1.0

        cov_mask = w_sum_unif > 0
        z_unif = s_z_unif / np.maximum(w_sum_unif, 1.0)
        p_unif = _sig_np(z_unif)
        z_cent = s_z_cent / np.maximum(w_sum_cent, 1e-6)
        z_shrp = s_z_shrp / np.maximum(w_sum_shrp, 1e-6)
        p_shrp = _sig_np(z_shrp)
        sp_min_clean = np.where(cov_mask, sp_min, 0.0)

        feats = np.zeros((n_bins, d_dim), dtype=np.float32)
        feats[:, 0] = z_unif
        feats[:, 1] = p_unif
        feats[:, 2] = z_cent
        feats[:, 3] = z_shrp
        feats[:, 4] = p_shrp
        feats[:, 5] = z_shrp - z_unif
        feats[:, 6] = sp_max
        feats[:, 7] = sp_min_clean
        feats[:, 8] = sp_max - sp_min_clean
        feats[:, 9] = np.clip(w_sum_unif / 2.0, 0.0, 1.5)
        feats[:, 10] = np.where(cov_mask, min_edist, 1.0)
        feats[:, 11] = w_ref_s / np.maximum(w_sum_cent, 1e-6)
        feats[:, 12] = w_raw_s / np.maximum(w_sum_cent, 1e-6)
        feats[:, 13] = w_ref_max
        feats[:, 14:18] = sem_s / np.maximum(w_sum_cent[:, None], 1e-6)
        if orf_s is not None:
            feats[:, 18:28] = (orf_s / np.maximum(w_sum_cent[:, None], 1e-6)).astype(np.float32)

        target = (tgt_s / np.maximum(tgt_cnt, 1.0)).astype(np.float32) if sub_targets is not None else None
        valid_t = (tgt_cnt > 0).astype(np.float32) if sub_targets is not None else cov_mask.astype(np.float32)
        seqs.append({
            "g": g,
            "origin": origin,
            "max_e": max_e,
            "n_bins": n_bins,
            "feats": feats,
            "base_logit": z_cent.astype(np.float32),
            "target": target,
            "valid": valid_t,
        })
    return seqs


def flip_subbin_features(feat: np.ndarray, has_orf: bool = True) -> np.ndarray:
    """序列反向镜像变换：翻转 bin 顺序并对有向链特征（strand）取反。"""
    f = feat[::-1].copy()
    if has_orf and f.shape[1] >= SUBBIN_TOTAL_FEAT_DIM:
        f[:, ORF_STRAND_FEAT_INDEX] = -f[:, ORF_STRAND_FEAT_INDEX]
    return f


def _make_dilated_res_block(channels: int, dilation: int, kernel_size: int = 5, dropout: float = 0.1):
    import torch
    import torch.nn as nn
    import torch.nn.functional as F

    class DilatedResBlock1D(nn.Module):
        """带序列掩码的一维空洞残差卷积块，支持超长基因组全并行零串行推理。"""

        def __init__(self) -> None:
            super().__init__()
            pad = ((kernel_size - 1) * dilation) // 2
            self.conv1 = nn.Conv1d(channels, channels, kernel_size=kernel_size, padding=pad, dilation=dilation)
            self.norm1 = nn.GroupNorm(8, channels)
            self.conv2 = nn.Conv1d(channels, channels, kernel_size=kernel_size, padding=pad, dilation=dilation)
            self.norm2 = nn.GroupNorm(8, channels)
            self.drop = nn.Dropout(dropout)

        def forward(self, x: torch.Tensor, mask: torch.Tensor) -> torch.Tensor:
            h = F.gelu(self.norm1(self.conv1(x * mask))) * mask
            h = self.drop(h)
            h = self.norm2(self.conv2(h)) * mask
            return F.gelu(x + h) * mask

    return DilatedResBlock1D()


def build_subbin_context_refiner(
    feat_mean: np.ndarray,
    feat_std: np.ndarray,
    *,
    hidden_dim: int = 96,
    max_delta: float = 2.4,
    kernel_size: int = 5,
    dilations: Sequence[int] = (1, 2, 4, 8, 16),
    dropout: float = 0.1,
    use_orf_bins: bool = True,
):
    """构建带输入标准化缓冲与零初始化残差头的 SubBinContextRefiner 模型。"""
    import torch
    import torch.nn as nn

    mean_arr = np.asarray(feat_mean, dtype=np.float32)
    std_arr = np.asarray(feat_std, dtype=np.float32)
    std_arr = np.where(std_arr < 1e-4, 1.0, std_arr).astype(np.float32)
    in_dim = len(mean_arr)
    dils = tuple(d for d in dilations)

    class SubBinContextRefiner(nn.Module):
        feat_mean: torch.Tensor
        feat_std: torch.Tensor

        def __init__(self) -> None:
            super().__init__()
            self.in_dim = in_dim
            self.hidden_dim = hidden_dim
            self.max_delta = float(max_delta)
            self.kernel_size = kernel_size
            self.dilations = dils
            self.use_orf_bins = use_orf_bins
            self.register_buffer("feat_mean", torch.tensor(mean_arr, dtype=torch.float32))
            self.register_buffer("feat_std", torch.tensor(std_arr, dtype=torch.float32))

            self.in_proj = nn.Sequential(
                nn.Conv1d(in_dim, self.hidden_dim, kernel_size=3, padding=1),
                nn.GroupNorm(8, self.hidden_dim),
                nn.GELU(),
            )
            self.blocks = nn.ModuleList([
                _make_dilated_res_block(self.hidden_dim, dilation=d, kernel_size=self.kernel_size, dropout=dropout)
                for d in dils
            ])
            self.head = nn.Sequential(
                nn.Conv1d(self.hidden_dim, 64, kernel_size=3, padding=1),
                nn.GELU(),
                nn.Conv1d(64, 1, kernel_size=1),
            )
            # 零初始化最后一层保证 epoch=0 严格退化为无偏中心加权基线，平稳收敛
            nn.init.zeros_(self.head[-1].weight)
            nn.init.zeros_(self.head[-1].bias)

        def forward(
            self,
            x: torch.Tensor,
            base_logit: torch.Tensor,
            seq_lens: Optional[torch.Tensor] = None,
        ) -> torch.Tensor:
            bsz, seq_len, _ = x.shape
            xn = ((x - self.feat_mean.view(1, 1, -1)) / self.feat_std.view(1, 1, -1)).clamp(-12.0, 12.0)
            if seq_lens is not None:
                pos = torch.arange(seq_len, device=x.device)[None, :]
                mask = (pos < seq_lens[:, None]).unsqueeze(1).to(x.dtype)
            else:
                mask = torch.ones((bsz, 1, seq_len), dtype=x.dtype, device=x.device)
            h = self.in_proj(xn.permute(0, 2, 1) * mask) * mask
            for blk in self.blocks:
                h = blk(h, mask)
            delta = torch.tanh(self.head(h).squeeze(1)) * self.max_delta
            return base_logit + delta * mask.squeeze(1)

    return SubBinContextRefiner()


def save_subbin_refiner_checkpoint(model, out_path: Path, *, bin_bp: int = BIN_BP_DEFAULT) -> None:
    """将 SubBinContextRefiner 结构配置及权重安全落盘为自适应 checkpoint。"""
    import torch

    out_p = Path(out_path)
    out_p.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "arch": "subbin_v1_dilated_tcn",
        "in_dim": int(model.in_dim),
        "hidden_dim": int(model.hidden_dim),
        "max_delta": float(model.max_delta),
        "kernel_size": int(model.kernel_size),
        "dilations": [int(d) for d in model.dilations],
        "use_orf_bins": bool(model.use_orf_bins),
        "bin_bp": bin_bp,
        "state_dict": model.state_dict(),
    }
    tmp = out_p.with_name(f".{out_p.name}.tmp")
    torch.save(payload, tmp)
    tmp.replace(out_p)


def load_subbin_refiner_checkpoint(ckpt_path: Path, device):
    """自适应读取 SubBinContextRefiner checkpoint，无需外部硬编码超参数。"""
    import torch

    raw = torch.load(Path(ckpt_path), map_location=device, weights_only=True)
    if isinstance(raw, dict) and "state_dict" in raw:
        state_dict = raw["state_dict"]
        in_dim = int(raw.get("in_dim", len(state_dict["feat_mean"])))
        hidden_dim = int(raw.get("hidden_dim", 96))
        max_delta = float(raw.get("max_delta", 2.4))
        kernel_size = int(raw.get("kernel_size", 5))
        dilations = tuple(int(d) for d in raw.get("dilations", (1, 2, 4, 8, 16)))
        use_orf_bins = bool(raw.get("use_orf_bins", in_dim >= SUBBIN_TOTAL_FEAT_DIM))
    else:
        state_dict = raw
        in_dim = len(state_dict["feat_mean"])
        hidden_dim = int(state_dict["in_proj.0.weight"].shape[0])
        max_delta = 2.4
        kernel_size = 5
        dilations = (1, 2, 4, 8, 16)
        use_orf_bins = in_dim >= SUBBIN_TOTAL_FEAT_DIM

    dummy_mean = np.zeros(in_dim, dtype=np.float32)
    dummy_std = np.ones(in_dim, dtype=np.float32)
    model = build_subbin_context_refiner(
        dummy_mean,
        dummy_std,
        hidden_dim=hidden_dim,
        max_delta=max_delta,
        kernel_size=kernel_size,
        dilations=dilations,
        use_orf_bins=use_orf_bins,
    ).to(device)
    model.load_state_dict(state_dict)
    model.eval()
    return model


def _infer_single_sequence_logits(
    model,
    feats: np.ndarray,
    base_logit: np.ndarray,
    device,
    *,
    has_orf: bool,
    max_chunk_bins: int = 4096,
    overlap_bins: int = 256,
    tta_flip: bool = True,
) -> np.ndarray:
    """对任意长度 200 bp 特征序列执行安全分块前向与反向镜像 TTA，防止超长染色体 OOM。"""
    import torch

    n_bins = len(base_logit)
    if n_bins == 0:
        return np.zeros(0, dtype=np.float32)

    def _run_slice(sl_f: np.ndarray, sl_b: np.ndarray) -> np.ndarray:
        lb = len(sl_b)
        with torch.no_grad():
            xt = torch.from_numpy(sl_f[None, ...]).to(device)
            bt = torch.from_numpy(sl_b[None, ...]).to(device)
            lt = torch.tensor([lb], dtype=torch.long, device=device)
            lf = model(xt, bt, lt).squeeze(0).detach().float().cpu().numpy()
            if not tta_flip:
                return lf
            xf = flip_subbin_features(sl_f, has_orf=has_orf)
            xft = torch.from_numpy(xf[None, ...]).to(device)
            bft = torch.from_numpy(sl_b[::-1].copy()[None, ...]).to(device)
            lbwd = model(xft, bft, lt).squeeze(0).detach().float().cpu().numpy()[::-1].copy()
            return (0.5 * (lf + lbwd)).astype(np.float32)

    if n_bins <= max_chunk_bins:
        return _run_slice(feats, base_logit)

    out_logits = np.zeros(n_bins, dtype=np.float32)
    stride = max(256, max_chunk_bins - 2 * overlap_bins)
    start = 0
    while start < n_bins:
        end = min(n_bins, start + max_chunk_bins)
        chunk_l = _run_slice(feats[start:end], base_logit[start:end])
        keep_l = 0 if start == 0 else min(overlap_bins, len(chunk_l) // 3)
        keep_r = len(chunk_l) if end >= n_bins else max(keep_l + 1, len(chunk_l) - overlap_bins)
        out_logits[start + keep_l:start + keep_r] = chunk_l[keep_l:keep_r]
        if end >= n_bins:
            break
        start += stride
    return out_logits


def train_subbin_context_refiner(
    tr_seqs: Sequence[Dict[str, Any]],
    va_seqs: Sequence[Dict[str, Any]],
    *,
    out_path: Path,
    hidden_dim: int = 96,
    max_delta: float = 2.4,
    epochs: int = 16,
    lr: float = 8e-4,
    patience: int = 6,
    batch_size: int = 32,
    chunk_len: int = 1536,
    chunk_stride: int = 1280,
    seed: int = 42,
    bin_bp: int = BIN_BP_DEFAULT,
) -> Tuple[Any, Dict[str, Any]]:
    """
    基于连续滑窗 200 bp 序列训练 SubBinContextRefiner：
    采用仅训练集的标准化统计、分片长切分按序分桶、边界跳变高权重损失与过渡区早停机制。
    """
    import torch
    import torch.nn.functional as F

    rng = np.random.default_rng(seed)
    torch.manual_seed(seed)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    tr_use: List[Dict[str, Any]] = []
    for s in tr_seqs:
        vl = s.get("valid")
        if vl is None or float(np.sum(vl)) <= 0.0:
            continue
        length = int(s["n_bins"])
        if length <= chunk_len:
            tr_use.append(s)
        else:
            for st in range(0, length, chunk_stride):
                en = min(length, st + chunk_len)
                if float(np.sum(vl[st:en])) > 0.0:
                    tr_use.append({
                        "n_bins": en - st,
                        "feats": s["feats"][st:en],
                        "base_logit": s["base_logit"][st:en],
                        "target": s["target"][st:en],
                        "valid": vl[st:en],
                    })
                if en >= length:
                    break

    if not tr_use:
        in_dim = int(tr_seqs[0]["feats"].shape[1]) if tr_seqs else SUBBIN_TOTAL_FEAT_DIM
        model = build_subbin_context_refiner(
            np.zeros(in_dim, dtype=np.float32),
            np.ones(in_dim, dtype=np.float32),
            hidden_dim=hidden_dim,
            max_delta=max_delta,
            use_orf_bins=(in_dim >= SUBBIN_TOTAL_FEAT_DIM),
        ).to(device)
        save_subbin_refiner_checkpoint(model, out_path, bin_bp=bin_bp)
        return model, {"best_epoch": 0, "best_val_metric": -1.0, "tr_chunks": 0, "in_dim": in_dim}

    in_dim = int(tr_use[0]["feats"].shape[1])
    has_orf = in_dim >= SUBBIN_TOTAL_FEAT_DIM
    all_f = np.concatenate([s["feats"] for s in tr_use], axis=0)
    f_mean = np.nan_to_num(all_f.mean(axis=0), nan=0.0).astype(np.float32)
    f_std = np.nan_to_num(all_f.std(axis=0), nan=1.0).astype(np.float32)
    f_std = np.where(f_std < 1e-4, 1.0, f_std).astype(np.float32)
    del all_f

    tr_use.sort(key=lambda x: int(x["n_bins"]))
    batches = [list(range(i0, min(len(tr_use), i0 + batch_size))) for i0 in range(0, len(tr_use), batch_size)]

    va_trans_masks: List[np.ndarray] = []
    for s in va_seqs:
        tg = s.get("target")
        vl = s.get("valid")
        if tg is None or vl is None:
            va_trans_masks.append(np.zeros(int(s["n_bins"]), dtype=bool))
            continue
        vl_b = vl > 0.5
        jm = np.zeros(len(tg), dtype=bool)
        if len(tg) > 1:
            dj = (np.abs(tg[1:] - tg[:-1]) > 0.2) & vl_b[1:] & vl_b[:-1]
            for k in np.where(dj)[0]:
                jm[max(0, k - 4):min(len(tg), k + 6)] = True
        va_trans_masks.append(jm & vl_b)

    model = build_subbin_context_refiner(
        f_mean,
        f_std,
        hidden_dim=hidden_dim,
        max_delta=max_delta,
        use_orf_bins=has_orf,
    ).to(device)
    opt = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=1e-2)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=max(1, epochs))

    best_metric = 1e9
    best_ep = -1
    bad_ep = 0
    best_state = {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}
    history: List[Dict[str, Any]] = []

    for ep in range(1, epochs + 1):
        model.train()
        ep_loss = 0.0
        n_b = 0
        for bi in rng.permutation(len(batches)):
            b_idx = batches[int(bi)]
            max_l = max(int(tr_use[j]["n_bins"]) for j in b_idx)
            xb = np.zeros((len(b_idx), max_l, in_dim), dtype=np.float32)
            bb = np.zeros((len(b_idx), max_l), dtype=np.float32)
            yb = np.zeros((len(b_idx), max_l), dtype=np.float32)
            vb = np.zeros((len(b_idx), max_l), dtype=np.float32)
            lnb = np.zeros(len(b_idx), dtype=np.int64)
            for row, j in enumerate(b_idx):
                s = tr_use[j]
                seq_l = int(s["n_bins"])
                lnb[row] = seq_l
                feat, bl, tg, vl = s["feats"], s["base_logit"], s["target"], s["valid"]
                if rng.random() < 0.5:
                    feat = flip_subbin_features(feat, has_orf=has_orf)
                    bl = bl[::-1].copy()
                    tg = tg[::-1].copy()
                    vl = vl[::-1].copy()
                xb[row, :seq_l] = feat
                bb[row, :seq_l] = bl
                yb[row, :seq_l] = tg
                vb[row, :seq_l] = vl

            xt = torch.from_numpy(xb).to(device)
            bt = torch.from_numpy(bb).to(device)
            yt = torch.from_numpy(yb).to(device)
            vt = torch.from_numpy(vb).to(device)
            lt = torch.from_numpy(lnb).to(device)

            ew = vt.clone()
            if max_l > 1:
                jumps = (torch.abs(yt[:, 1:] - yt[:, :-1]) > 0.2).float() * vt[:, 1:] * vt[:, :-1]
                jpad = F.max_pool1d(F.pad(jumps.unsqueeze(1), (0, 1)), kernel_size=7, stride=1, padding=3).squeeze(1)
                ew = ew * (1.0 + 3.5 * jpad)

            opt.zero_grad(set_to_none=True)
            logits = model(xt, bt, lt)
            loss_bce = (F.binary_cross_entropy_with_logits(logits, yt, reduction="none") * ew).sum() / ew.sum().clamp(min=1.0)
            probs = torch.sigmoid(logits) * vt
            y_m = yt * vt
            inter = (probs * y_m).sum(dim=1)
            denom = probs.sum(dim=1) + y_m.sum(dim=1)
            has_pos = (y_m.sum(dim=1) > 0.5).float()
            dice_loss = ((1.0 - (2.0 * inter + 1.0) / (denom + 1.0)) * has_pos).sum() / has_pos.sum().clamp(min=1.0)
            loss = loss_bce + 0.12 * dice_loss
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()
            ep_loss += float(loss.item())
            n_b += 1
        sched.step()

        model.eval()
        all_bce: List[float] = []
        trans_bce: List[float] = []
        with torch.no_grad():
            for si, s in enumerate(va_seqs):
                vl = s.get("valid")
                tg = s.get("target")
                if vl is None or tg is None:
                    continue
                l_avg = _infer_single_sequence_logits(
                    model, s["feats"], s["base_logit"], device, has_orf=has_orf, tta_flip=True,
                )
                vl_b = vl > 0.5
                if np.any(vl_b):
                    la = np.clip(l_avg[vl_b], -20.0, 20.0)
                    ya = tg[vl_b]
                    all_bce.append(float(np.mean(np.maximum(la, 0.0) - la * ya + np.log1p(np.exp(-np.abs(la))))))
                tm = va_trans_masks[si]
                if np.any(tm):
                    la = np.clip(l_avg[tm], -20.0, 20.0)
                    ya = tg[tm]
                    trans_bce.append(float(np.mean(np.maximum(la, 0.0) - la * ya + np.log1p(np.exp(-np.abs(la))))))

        v_all = float(np.mean(all_bce)) if all_bce else (ep_loss / max(1, n_b))
        v_trn = float(np.mean(trans_bce)) if trans_bce else v_all
        em = 0.75 * v_trn + 0.25 * v_all
        history.append({
            "epoch": ep,
            "train_loss": round(ep_loss / max(1, n_b), 5),
            "val_trans_bce": round(v_trn, 5),
            "val_all_bce": round(v_all, 5),
            "val_joint": round(em, 5),
        })
        if em < best_metric or best_ep < 0:
            best_metric = em
            best_ep = ep
            bad_ep = 0
            best_state = {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}
        else:
            bad_ep += 1
            if bad_ep >= patience:
                break

    model.load_state_dict(best_state)
    model.eval()
    save_subbin_refiner_checkpoint(model, out_path, bin_bp=bin_bp)
    if device.type == "cuda":
        torch.cuda.empty_cache()

    return model, {
        "arch": "subbin_v1_dilated_tcn",
        "in_dim": in_dim,
        "hidden_dim": hidden_dim,
        "max_delta": float(max_delta),
        "use_orf_bins": has_orf,
        "best_epoch": best_ep,
        "best_val_joint_bce": round(best_metric, 6),
        "tr_chunks": len(tr_use),
        "va_seqs": len(va_seqs),
        "history": history,
    }


def predict_subbin_probs_with_refiner(
    subbin_refiner,
    groups: Sequence[np.ndarray],
    contig_ids: np.ndarray,
    starts: np.ndarray,
    ends: np.ndarray,
    win_ref_probs: np.ndarray,
    win_raw_probs: np.ndarray,
    sem_logits: np.ndarray,
    sub_probs: np.ndarray,
    device,
    *,
    win_orf_25bins: Optional[np.ndarray] = None,
    min_windows: int = 2,
    bin_bp: int = BIN_BP_DEFAULT,
    sub_bins: int = SUB_BINS,
    max_chunk_bins: int = 4096,
    overlap_bins: int = 256,
    tta_flip: bool = True,
) -> Tuple[Dict[str, List[Tuple[int, np.ndarray]]], np.ndarray]:
    """
    使用训练好的 SubBinContextRefiner 对各连续滑窗片段生成 200 bp 亚窗精修概率：
    返回 (contig_bin_profiles: cid -> [(origin_bp, prof_1d), ...], refined_win_sub_probs: (N, sub_bins))。
    对窗口数少于 min_windows 的超短孤立片段保留原始 sub_probs。
    """
    import torch

    refined_win_sub = sub_probs.astype(np.float32, copy=True)
    contig_profiles: Dict[str, List[Tuple[int, np.ndarray]]] = {}
    if subbin_refiner is None or len(sub_probs) == 0:
        return contig_profiles, refined_win_sub

    has_orf = bool(getattr(subbin_refiner, "use_orf_bins", True)) and win_orf_25bins is not None
    eligible_groups = [g for g in groups if len(g) >= min_windows]
    if not eligible_groups:
        return contig_profiles, refined_win_sub

    seqs = build_contig_subbin_sequences(
        eligible_groups,
        starts,
        ends,
        win_ref_probs,
        win_raw_probs,
        sem_logits,
        sub_probs,
        win_orf_25bins=win_orf_25bins if has_orf else None,
        bin_bp=bin_bp,
        sub_bins=sub_bins,
    )
    subbin_refiner.eval()
    with torch.no_grad():
        for seq in seqs:
            g = seq["g"]
            cid = str(contig_ids[g[0]])
            origin = int(seq["origin"])
            logits = _infer_single_sequence_logits(
                subbin_refiner,
                seq["feats"],
                seq["base_logit"],
                device,
                has_orf=has_orf,
                max_chunk_bins=max_chunk_bins,
                overlap_bins=overlap_bins,
                tta_flip=tta_flip,
            )
            prof = _sig_np(logits)
            contig_profiles.setdefault(cid, []).append((origin, prof))

            # 将连续 200 bp 精修结果映射回逐窗 (SUB_BINS,) 以兼容标准数组输出
            n_bins = len(prof)
            aligned_span = bin_bp * sub_bins
            for idx in g:
                s_bp = int(starts[idx])
                e_bp = int(ends[idx])
                w_span = max(1, e_bp - s_bp)
                rel_s = s_bp - origin
                if w_span == aligned_span and rel_s >= 0 and (rel_s % bin_bp == 0):
                    b0 = rel_s // bin_bp
                    if b0 + sub_bins <= n_bins:
                        refined_win_sub[idx] = prof[b0:b0 + sub_bins]
                        continue
                sub_w = float(w_span) / float(sub_bins)
                for k in range(sub_bins):
                    bs = s_bp + round(k * sub_w) - origin
                    be = s_bp + round((k + 1) * sub_w) - origin
                    b0 = max(0, min(n_bins - 1, bs // bin_bp))
                    b1 = max(b0 + 1, min(n_bins, (be + bin_bp - 1) // bin_bp))
                    refined_win_sub[idx, k] = float(np.mean(prof[b0:b1]))

    if getattr(device, "type", None) == "cuda":
        torch.cuda.empty_cache()
    return contig_profiles, refined_win_sub
