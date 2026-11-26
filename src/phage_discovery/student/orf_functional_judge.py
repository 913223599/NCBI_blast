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
    """
    if arch not in ("baseline", "r1", "r2", "r3", "unified", "unified_v4_3"):
        raise ValueError(f"不支持的 OrfFunctionalJudge 架构: {arch}")

    from .orf_judge_modules import OrfFunctionalJudgeNet

    return OrfFunctionalJudgeNet(
        stat_mean,
        stat_std,
        vocab_size=AA_VOCAB_SIZE,
        stat_dim=stat_dim,
        d_model=d_model,
        nhead=nhead,
        num_ctx_layers=num_ctx_layers,
        ctx_len=ctx_len,
        aa_embed_dim=aa_embed_dim,
        aa_channels=aa_channels,
        use_aa_seq=use_aa_seq,
        num_classes=num_classes,
        arch=arch,
        aa_mask_prob=aa_mask_prob,
        distill_dim=distill_dim,
    )


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
