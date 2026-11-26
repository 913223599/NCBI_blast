"""V4.1 区域级上下文精修器（Region Context Refiner）推理与训练模块。"""
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from ..experts.expert_c_orf import MAX_ORFS_PER_WIN
from ..experts.seq_dataset import reverse_complement_codes
from ..features.window_features import SUB_BINS
from .v4_arch import (
    REFINER_STEP_FEAT_DIM,
    SEMANTIC_DIM,
    build_region_context_refiner,
)

logger = logging.getLogger(__name__)

def extract_refiner_step_features(
    win_logits: np.ndarray,
    sem_logits: np.ndarray,
    sub_probs: np.ndarray,
    lengths: np.ndarray,
    max_len: int = 5000,
    func_logits: Optional[np.ndarray] = None,
) -> np.ndarray:
    """将单窗模型输出汇总为与绝对基因组无关的 15 维时间步特征（支持融合 9 维功能模块共现度），供 RegionContextRefiner 使用。"""
    n = len(win_logits)
    out = np.zeros((n, REFINER_STEP_FEAT_DIM), dtype=np.float32)
    if n == 0:
        return out
    eff_sem_logits = np.asarray(sem_logits, dtype=np.float32).copy()
    if func_logits is not None and len(func_logits) == n and func_logits.shape[1] >= 8:
        f_probs = 1.0 / (1.0 + np.exp(-np.clip(func_logits[:, :8].astype(np.float64), -20.0, 20.0)))
        part_sorted = np.sort(f_probs, axis=1)
        top2_prob = np.clip(part_sorted[:, -2], 1e-4, 1.0 - 1e-4).astype(np.float32)
        top2_logit = np.log(top2_prob / (1.0 - top2_prob)).astype(np.float32)
        # 融合多模块共现度（Top-2 噬菌体功能模块 logit），抑制仅单模块孤立同源命中的虚高 hallmark
        eff_sem_logits[:, 0] = 0.60 * eff_sem_logits[:, 0] + 0.40 * top2_logit
        if func_logits.shape[1] >= 9:
            eff_sem_logits[:, 2] = np.maximum(eff_sem_logits[:, 2], func_logits[:, 8].astype(np.float32))

    win_probs = 1.0 / (1.0 + np.exp(-np.clip(win_logits, -20.0, 20.0)))
    sem_probs = 1.0 / (1.0 + np.exp(-np.clip(eff_sem_logits, -20.0, 20.0)))
    sub_mean = sub_probs.mean(axis=1)
    sub_max = sub_probs.max(axis=1)
    sub_std = sub_probs.std(axis=1)
    sub_hi = (sub_probs >= 0.5).mean(axis=1)
    valid_frac = lengths.astype(np.float32) / max(1.0, float(max_len))
    log_len = np.log1p(lengths.astype(np.float32)) / float(np.log1p(max_len))

    out[:, 0] = win_logits
    out[:, 1] = win_probs
    out[:, 2:6] = np.clip(eff_sem_logits, -12.0, 12.0)
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
    *,
    drop_tabular_prob: float = 0.0,
    drop_orf_prob: float = 0.0,
    seed: int = 0,
    return_orf_preds: bool = False,
) -> Dict[str, np.ndarray]:
    import torch

    model.eval()
    n = len(feats)
    func_dim = int(getattr(model, "func_dim", 0))
    out_win_logit = np.zeros(n, dtype=np.float32)
    out_win_prob = np.zeros(n, dtype=np.float32)
    out_sub_prob = np.zeros((n, SUB_BINS), dtype=np.float32)
    out_sem_logit = np.zeros((n, SEMANTIC_DIM), dtype=np.float32)
    out_func_logit = np.zeros((n, func_dim), dtype=np.float32) if func_dim > 0 else None
    out_orf_phage = np.zeros((n, MAX_ORFS_PER_WIN), dtype=np.float32) if (return_orf_preds and func_dim > 0) else None
    out_orf_func = np.zeros((n, MAX_ORFS_PER_WIN, func_dim), dtype=np.float32) if (return_orf_preds and func_dim > 0) else None
    if n == 0:
        res_empty = {
            "win_logits": out_win_logit,
            "win_probs": out_win_prob,
            "sub_probs": out_sub_prob,
            "sem_logits": out_sem_logit,
        }
        if out_func_logit is not None:
            res_empty["func_logits"] = out_func_logit
        if out_orf_phage is not None:
            res_empty["orf_phage_probs"] = out_orf_phage
        if out_orf_func is not None:
            res_empty["orf_func_probs"] = out_orf_func
        return res_empty

    rc = reverse_complement_codes(codes, lengths)
    max_len = codes.shape[1]
    rng_drop = np.random.default_rng(seed) if (drop_tabular_prob > 0.0 or drop_orf_prob > 0.0) else None
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
            if rng_drop is not None:
                m_sz = len(tb)
                if drop_orf_prob > 0.0:
                    orf_d = torch.from_numpy(rng_drop.random(m_sz) < drop_orf_prob).to(device)
                    cn = torch.where(orf_d, torch.zeros_like(cn), cn)
                    tk = torch.where(orf_d[:, None, None], torch.zeros_like(tk), tk)
                if drop_tabular_prob > 0.0 and hasattr(model, "feat_mean"):
                    tab_d = torch.from_numpy(rng_drop.random(m_sz) < drop_tabular_prob).to(device)
                    tb = torch.where(tab_d[:, None], model.feat_mean.unsqueeze(0).expand_as(tb), tb)

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
            if out_func_logit is not None and "func_logits" in r1 and "func_logits" in r2:
                out_func_logit[sl] = ((r1["func_logits"].float() + r2["func_logits"].float()) * 0.5).cpu().numpy()
            if out_orf_phage is not None and "orf_phage_logits" in r1 and "orf_phage_logits" in r2:
                op_mean = (torch.sigmoid(r1["orf_phage_logits"].float()) + torch.sigmoid(r2["orf_phage_logits"].float())) * 0.5
                out_orf_phage[sl] = op_mean.cpu().numpy()
            if out_orf_func is not None and "orf_func_logits" in r1 and "orf_func_logits" in r2:
                of_mean = (torch.sigmoid(r1["orf_func_logits"].float()) + torch.sigmoid(r2["orf_func_logits"].float())) * 0.5
                out_orf_func[sl] = of_mean.cpu().numpy()

    res_out = {
        "win_logits": out_win_logit,
        "win_probs": out_win_prob,
        "sub_probs": out_sub_prob,
        "sem_logits": out_sem_logit,
    }
    if out_func_logit is not None:
        res_out["func_logits"] = out_func_logit
    if out_orf_phage is not None:
        res_out["orf_phage_probs"] = out_orf_phage
    if out_orf_func is not None:
        res_out["orf_func_probs"] = out_orf_func
    return res_out

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
    func_logits: Optional[np.ndarray] = None,
) -> np.ndarray:
    """使用 RegionContextRefiner 对按 contig 排好序且物理连续的窗口序列进行跨窗精修。"""
    import torch

    n = len(win_logits)
    out_probs = 1.0 / (1.0 + np.exp(-np.clip(win_logits, -20.0, 20.0)))
    if refiner is None or n == 0:
        return out_probs.astype(np.float32)

    refiner.eval()
    step_feats = extract_refiner_step_features(
        win_logits, sem_logits, sub_probs, lengths, max_len=max_len, func_logits=func_logits,
    )
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
    """
    针对隐蔽退化弱前噬菌体（>=3 窗连续簇）与 1~2 窗孤立假阳脉冲（含转座酶脉冲与单模块同源诱饵脉冲）合成训练增强，
    消除长训 Student 在训练集上零假阳导致的暴露偏差（Exposure Bias）。
    """
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

    # 1) 搜索连续正前噬菌体片段 (>=3 窗)，模拟隐蔽/退化中置信度分布并保持多模块协同语义
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
        ceil_logit = float(rng.uniform(1.25, 2.95))
        degraded = rng.uniform(0.70, ceil_logit, size=span).astype(np.float32)
        if span >= 5 and rng.random() < 0.30:
            dip_idx = int(rng.integers(1, span - 1))
            degraded[dip_idx] = float(rng.uniform(0.40, 1.05))
        _sync_logit_and_prob(sl, np.minimum(rl[sl], degraded))
        hall_floor = rng.uniform(0.45, 2.0, size=span).astype(np.float32)
        sf[sl, 2] = np.maximum(sf[sl, 2], hall_floor)
        sf[sl, 6] = 1.0 / (1.0 + np.exp(-np.clip(sf[sl, 2], -20.0, 20.0)))
        sf[sl, 4] = np.minimum(sf[sl, 4], rng.uniform(-2.8, -1.0, size=span).astype(np.float32))
        sf[sl, 8] = 1.0 / (1.0 + np.exp(-np.clip(sf[sl, 4], -20.0, 20.0)))

    # 2) 在远离正前噬菌体（前后各至少 2 窗均为 0）的纯阴性背景注入 1~2 窗孤立假阳脉冲
    safe_neg_starts: List[int] = []
    for i in range(w):
        if labels[i] != 0:
            continue
        left_ok = all(labels[k] == 0 for k in range(max(0, i - 2), i))
        right_ok = all(labels[k] == 0 for k in range(i + 1, min(w, i + 3)))
        if left_ok and right_ok:
            safe_neg_starts.append(i)

    if safe_neg_starts and rng.random() < 0.55:
        pos0 = int(rng.choice(safe_neg_starts))
        mode = float(rng.random())
        max_width = 2 if (pos0 + 1 in safe_neg_starts and pos0 + 1 < w) else 1
        width = 2 if (mode >= 0.55 and max_width == 2) else int(rng.integers(1, max_width + 1))
        sl = slice(pos0, pos0 + width)
        spike_logit = rng.uniform(1.6, 3.9, size=width).astype(np.float32)
        _sync_logit_and_prob(sl, spike_logit)

        if mode < 0.25:
            # 模式 1：显式高 transposase 孤立脉冲
            sf[sl, 2] = rng.uniform(-3.4, -1.0, size=width).astype(np.float32)
            sf[sl, 6] = 1.0 / (1.0 + np.exp(-np.clip(sf[sl, 2], -20.0, 20.0)))
            sf[sl, 4] = rng.uniform(1.0, 3.5, size=width).astype(np.float32)
            sf[sl, 8] = 1.0 / (1.0 + np.exp(-np.clip(sf[sl, 4], -20.0, 20.0)))
            sf[sl, 5] = np.minimum(sf[sl, 5], rng.uniform(-2.6, -0.7, size=width).astype(np.float32))
            sf[sl, 9] = 1.0 / (1.0 + np.exp(-np.clip(sf[sl, 5], -20.0, 20.0)))
        elif mode < 0.65:
            # 模式 2/3：低 hallmark 且无明显语义的 1~2 窗孤立脉冲
            sf[sl, 2] = rng.uniform(-3.4, -1.0, size=width).astype(np.float32)
            sf[sl, 6] = 1.0 / (1.0 + np.exp(-np.clip(sf[sl, 2], -20.0, 20.0)))
            sf[sl, 3] = rng.uniform(-5.0, -1.5, size=width).astype(np.float32)
            sf[sl, 7] = 1.0 / (1.0 + np.exp(-np.clip(sf[sl, 3], -20.0, 20.0)))
            sf[sl, 4] = rng.uniform(-5.0, -1.5, size=width).astype(np.float32)
            sf[sl, 8] = 1.0 / (1.0 + np.exp(-np.clip(sf[sl, 4], -20.0, 20.0)))
            sf[sl, 5] = np.minimum(sf[sl, 5], rng.uniform(-2.6, -0.7, size=width).astype(np.float32))
            sf[sl, 9] = 1.0 / (1.0 + np.exp(-np.clip(sf[sl, 5], -20.0, 20.0)))
        else:
            # 模式 4：1~2 窗孤立单模块同源诱饵脉冲（带中高 tail/hallmark 与 sub_probs，但左右邻居全为 0）
            sf[sl, 2] = rng.uniform(-0.8, 1.4, size=width).astype(np.float32)
            sf[sl, 6] = 1.0 / (1.0 + np.exp(-np.clip(sf[sl, 2], -20.0, 20.0)))
            sf[sl, 3] = rng.uniform(-4.5, -1.2, size=width).astype(np.float32)
            sf[sl, 7] = 1.0 / (1.0 + np.exp(-np.clip(sf[sl, 3], -20.0, 20.0)))
            sf[sl, 4] = rng.uniform(-4.5, -1.2, size=width).astype(np.float32)
            sf[sl, 8] = 1.0 / (1.0 + np.exp(-np.clip(sf[sl, 4], -20.0, 20.0)))
            sf[sl, 5] = rng.uniform(0.2, 2.2, size=width).astype(np.float32)
            sf[sl, 9] = 1.0 / (1.0 + np.exp(-np.clip(sf[sl, 5], -20.0, 20.0)))
            sf[sl, 10] = rng.uniform(0.50, 0.85, size=width).astype(np.float32)
            sf[sl, 11] = rng.uniform(0.75, 0.96, size=width).astype(np.float32)
            sf[sl, 13] = rng.uniform(0.55, 0.92, size=width).astype(np.float32)
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
