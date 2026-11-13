# -*- coding: utf-8 -*-
"""
统一前噬菌体发现评测指标与滞回边界解码器

包含两级核心评测契约：
1. 窗口级指标（Window-level）：AUROC, AUPRC, F1, Precision, Recall, Recall@0.5%FPR, FPR@95%TPR；
2. 区域级指标（Region-level）：IoU>=0.5 / IoU>=0.8 精确率/召回率/F1、断点边界 MAE/MedianAE (bp)、每 Mb 假阳性率 (FP/Mb)。
"""
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Dict, List, Sequence, Tuple

import numpy as np
from sklearn.metrics import average_precision_score, roc_auc_score, roc_curve


@dataclass
class WindowPrediction:
    contig_id: str
    start_bp: int
    end_bp: int
    score: float


@dataclass
class TruthRegion:
    contig_id: str
    start_bp: int
    end_bp: int
    mode: str = "intact"


@dataclass
class PredictedRegion:
    contig_id: str
    start_bp: int
    end_bp: int
    peak_score: float
    mean_score: float
    window_count: int


def compute_interval_iou(a_start: int, a_end: int, b_start: int, b_end: int) -> float:
    """计算两个半开区间 [start, end) 的交并比 IoU。"""
    inter = max(0, min(a_end, b_end) - max(a_start, b_start))
    if inter <= 0:
        return 0.0
    union = max(0, a_end - a_start) + max(0, b_end - b_start) - inter
    return float(inter) / float(union) if union > 0 else 0.0


def compute_window_metrics(
    y_true: Sequence[int],
    y_score: Sequence[float],
    threshold: float = 0.5,
) -> Dict[str, Any]:
    """计算窗口级二分类与极低假阳性工作点指标。"""
    yt = np.asarray(y_true, dtype=np.int32)
    ys = np.asarray(y_score, dtype=np.float64)
    n_total = int(yt.size)
    n_pos = int(np.sum(yt == 1))
    n_neg = int(np.sum(yt == 0))

    if n_total == 0:
        return {"total": 0, "positives": 0, "negatives": 0}

    y_pred = (ys >= threshold).astype(np.int32)
    tp = int(np.sum((yt == 1) & (y_pred == 1)))
    fp = int(np.sum((yt == 0) & (y_pred == 1)))
    fn = int(np.sum((yt == 1) & (y_pred == 0)))
    tn = int(np.sum((yt == 0) & (y_pred == 0)))

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0
    fpr_at_thresh = fp / (fp + tn) if (fp + tn) > 0 else 0.0

    auroc = None
    auprc = None
    recall_at_fpr_0_5pct = None
    fpr_at_tpr_95pct = None

    if n_pos > 0 and n_neg > 0:
        auroc = float(roc_auc_score(yt, ys))
        auprc = float(average_precision_score(yt, ys))
        fpr_arr, tpr_arr, _ = roc_curve(yt, ys)

        mask_low_fpr = fpr_arr <= 0.005
        recall_at_fpr_0_5pct = float(np.max(tpr_arr[mask_low_fpr])) if np.any(mask_low_fpr) else 0.0

        mask_high_tpr = tpr_arr >= 0.95
        fpr_at_tpr_95pct = float(np.min(fpr_arr[mask_high_tpr])) if np.any(mask_high_tpr) else 1.0

    return {
        "total": n_total,
        "positives": n_pos,
        "negatives": n_neg,
        "threshold": threshold,
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "fpr_at_threshold": round(fpr_at_thresh, 5),
        "auroc": round(auroc, 4) if auroc is not None else None,
        "auprc": round(auprc, 4) if auprc is not None else None,
        "recall_at_fpr_0_5pct": round(recall_at_fpr_0_5pct, 4) if recall_at_fpr_0_5pct is not None else None,
        "fpr_at_tpr_95pct": round(fpr_at_tpr_95pct, 5) if fpr_at_tpr_95pct is not None else None,
    }


def decode_window_scores_to_regions(
    window_preds: Sequence[WindowPrediction],
    seed_threshold: float = 0.85,
    extend_threshold: float = 0.50,
    merge_gap_bp: int = 3000,
    min_region_bp: int = 3000,
) -> List[PredictedRegion]:
    """
    双阈值滞回扫描解码器（Hysteresis Region Caller）：
    - 当连续滑窗中存在得分 >= extend_threshold 的片段且片段峰值 >= seed_threshold 时，确立候选病毒岛；
    - 间距 <= merge_gap_bp 的同 contig 候选岛自动合并；
    - 长度 < min_region_bp 的孤立碎片予以丢弃以防单窗假阳性。
    """
    by_contig: Dict[str, List[WindowPrediction]] = defaultdict(list)
    for wp in window_preds:
        by_contig[wp.contig_id].append(wp)

    regions: List[PredictedRegion] = []
    for contig_id, items in sorted(by_contig.items()):
        items.sort(key=lambda w: (w.start_bp, w.end_bp))
        raw_islands: List[Tuple[int, int, float, List[float]]] = []

        cur_start: int = -1
        cur_end: int = -1
        cur_scores: List[float] = []

        for w in items:
            if w.score >= extend_threshold:
                if cur_start < 0:
                    cur_start = w.start_bp
                    cur_end = w.end_bp
                    cur_scores = [w.score]
                elif w.start_bp <= cur_end:
                    cur_end = max(cur_end, w.end_bp)
                    cur_scores.append(w.score)
                else:
                    raw_islands.append((cur_start, cur_end, max(cur_scores), cur_scores))
                    cur_start = w.start_bp
                    cur_end = w.end_bp
                    cur_scores = [w.score]
            else:
                if cur_start >= 0:
                    raw_islands.append((cur_start, cur_end, max(cur_scores), cur_scores))
                    cur_start = -1
                    cur_end = -1
                    cur_scores = []

        if cur_start >= 0:
            raw_islands.append((cur_start, cur_end, max(cur_scores), cur_scores))

        # 仅保留达到高置信 seed_threshold 的核心岛，随后合并近邻岛屿
        seeded = [isl for isl in raw_islands if isl[2] >= seed_threshold]
        if not seeded:
            continue

        merged: List[Tuple[int, int, List[float]]] = [(seeded[0][0], seeded[0][1], list(seeded[0][3]))]
        for s_bp, e_bp, _, sc_list in seeded[1:]:
            prev_s, prev_e, prev_scores = merged[-1]
            if s_bp - prev_e <= merge_gap_bp:
                merged[-1] = (prev_s, max(prev_e, e_bp), prev_scores + sc_list)
            else:
                merged.append((s_bp, e_bp, list(sc_list)))

        for s_bp, e_bp, sc_list in merged:
            if (e_bp - s_bp) >= min_region_bp:
                regions.append(
                    PredictedRegion(
                        contig_id=contig_id,
                        start_bp=s_bp,
                        end_bp=e_bp,
                        peak_score=round(max(sc_list), 5),
                        mean_score=round(sum(sc_list) / len(sc_list), 5),
                        window_count=len(sc_list),
                    )
                )

    return regions


def decode_subwindow_probs_to_regions(
    window_preds: Sequence[WindowPrediction],
    sub_probs: np.ndarray,
    seed_threshold: float = 0.85,
    extend_threshold: float = 0.50,
    sub_threshold: float = 0.45,
    merge_gap_bp: int = 3000,
    min_region_bp: int = 3000,
    bin_bp: int = 200,
) -> List[PredictedRegion]:
    """
    两阶段亚窗口精细边界解码器（Coarse-to-Fine Hysteresis + 200bp Segmentation Refiner）：
    1. 先用窗口级双阈值滞回扫描锁定高置信候选病毒岛（继承低 FP/Mb 抗噪优势）；
    2. 将同 contig 所有滑窗输出的 25-bin (200bp) 亚窗口概率投影回 contig 200bp 网格，做轻量三点平滑；
    3. 在每个候选岛 [cs - 2000, ce + 2000] 搜索邻域内，按 sub_threshold 精修起止断点。
    """
    coarse = decode_window_scores_to_regions(
        window_preds,
        seed_threshold=seed_threshold,
        extend_threshold=extend_threshold,
        merge_gap_bp=merge_gap_bp,
        min_region_bp=min_region_bp,
    )
    if not coarse or sub_probs is None or len(sub_probs) == 0:
        return coarse

    by_contig_idx: Dict[str, List[int]] = defaultdict(list)
    max_end_by_contig: Dict[str, int] = defaultdict(int)
    for idx, wp in enumerate(window_preds):
        by_contig_idx[wp.contig_id].append(idx)
        if wp.end_bp > max_end_by_contig[wp.contig_id]:
            max_end_by_contig[wp.contig_id] = wp.end_bp

    coarse_by_contig: Dict[str, List[PredictedRegion]] = defaultdict(list)
    for reg in coarse:
        coarse_by_contig[reg.contig_id].append(reg)

    refined_all: List[PredictedRegion] = []
    for cid, c_regs in sorted(coarse_by_contig.items()):
        contig_end = max_end_by_contig.get(cid, 0)
        n_bins = max(1, (contig_end + bin_bp - 1) // bin_bp)
        prof_sum = np.zeros(n_bins, dtype=np.float64)
        prof_cnt = np.zeros(n_bins, dtype=np.float64)

        for idx in by_contig_idx[cid]:
            wp = window_preds[idx]
            sp = np.asarray(sub_probs[idx], dtype=np.float64)
            n_sub = max(1, len(sp))
            w_span = max(1, wp.end_bp - wp.start_bp)
            sub_w = float(w_span) / float(n_sub)
            for k in range(n_sub):
                bs = wp.start_bp + int(round(k * sub_w))
                be = wp.start_bp + int(round((k + 1) * sub_w))
                i0 = max(0, min(n_bins - 1, bs // bin_bp))
                i1 = max(i0 + 1, min(n_bins, (be + bin_bp - 1) // bin_bp))
                prof_sum[i0:i1] += float(sp[k])
                prof_cnt[i0:i1] += 1.0

        prof = np.divide(prof_sum, np.maximum(prof_cnt, 1.0))
        if n_bins >= 3:
            smoothed = prof.copy()
            smoothed[1:-1] = 0.2 * prof[:-2] + 0.6 * prof[1:-1] + 0.2 * prof[2:]
            prof = smoothed

        refined_contig: List[PredictedRegion] = []
        pad_bins = max(1, 2000 // bin_bp)
        for reg in sorted(c_regs, key=lambda r: (r.start_bp, r.end_bp)):
            b_cs = max(0, reg.start_bp // bin_bp)
            b_ce = min(n_bins, max(b_cs + 1, (reg.end_bp + bin_bp - 1) // bin_bp))
            win_s = max(0, b_cs - pad_bins)
            win_e = min(n_bins, b_ce + pad_bins)

            active = (prof[win_s:win_e] >= sub_threshold).copy()
            if active.size >= 3:
                gap_bridge = (~active[1:-1]) & active[:-2] & active[2:]
                active[1:-1] = active[1:-1] | gap_bridge

            new_s, new_e = reg.start_bp, reg.end_bp
            segments: List[Tuple[int, int]] = []
            seg_s = -1
            for local_i, flag in enumerate(active):
                abs_i = win_s + local_i
                if flag:
                    if seg_s < 0:
                        seg_s = abs_i
                elif seg_s >= 0:
                    segments.append((seg_s, abs_i))
                    seg_s = -1
            if seg_s >= 0:
                segments.append((seg_s, win_e))

            overlapping = [
                (s0, e0) for s0, e0 in segments
                if min(e0, b_ce) > max(s0, b_cs)
            ]
            if overlapping:
                cand_s = overlapping[0][0] * bin_bp
                cand_e = min(contig_end, overlapping[-1][1] * bin_bp)
                if (cand_e - cand_s) >= min_region_bp:
                    new_s, new_e = cand_s, cand_e

            if refined_contig and (new_s - refined_contig[-1].end_bp) <= merge_gap_bp:
                prev = refined_contig[-1]
                refined_contig[-1] = PredictedRegion(
                    contig_id=cid,
                    start_bp=prev.start_bp,
                    end_bp=max(prev.end_bp, new_e),
                    peak_score=max(prev.peak_score, reg.peak_score),
                    mean_score=round((prev.mean_score + reg.mean_score) / 2.0, 5),
                    window_count=prev.window_count + reg.window_count,
                )
            else:
                refined_contig.append(
                    PredictedRegion(
                        contig_id=cid,
                        start_bp=new_s,
                        end_bp=new_e,
                        peak_score=reg.peak_score,
                        mean_score=reg.mean_score,
                        window_count=reg.window_count,
                    )
                )

        refined_all.extend(refined_contig)

    return refined_all


def _match_regions_at_iou(
    truths: Sequence[TruthRegion],
    preds: Sequence[PredictedRegion],
    iou_threshold: float,
) -> Dict[str, Any]:
    """按 IoU 降序做同一 contig 内的严格一对一贪心匹配。"""
    t_by_contig: Dict[str, List[Tuple[int, TruthRegion]]] = defaultdict(list)
    p_by_contig: Dict[str, List[Tuple[int, PredictedRegion]]] = defaultdict(list)
    for idx, t in enumerate(truths):
        t_by_contig[t.contig_id].append((idx, t))
    for idx, p in enumerate(preds):
        p_by_contig[p.contig_id].append((idx, p))

    pairs: List[Tuple[float, int, int, int]] = []
    all_contigs = set(t_by_contig.keys()) & set(p_by_contig.keys())
    for cid in all_contigs:
        for t_idx, t in t_by_contig[cid]:
            for p_idx, p in p_by_contig[cid]:
                iou = compute_interval_iou(t.start_bp, t.end_bp, p.start_bp, p.end_bp)
                if iou >= iou_threshold:
                    boundary_err = (abs(p.start_bp - t.start_bp) + abs(p.end_bp - t.end_bp)) / 2.0
                    pairs.append((iou, t_idx, p_idx, int(round(boundary_err))))

    pairs.sort(key=lambda x: x[0], reverse=True)
    matched_t: set[int] = set()
    matched_p: set[int] = set()
    boundary_errors: List[int] = []
    matched_ious: List[float] = []

    for iou, t_idx, p_idx, b_err in pairs:
        if t_idx in matched_t or p_idx in matched_p:
            continue
        matched_t.add(t_idx)
        matched_p.add(p_idx)
        matched_ious.append(iou)
        boundary_errors.append(b_err)

    tp = len(matched_t)
    fp = len(preds) - tp
    fn = len(truths) - tp
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0

    return {
        "iou_threshold": iou_threshold,
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "mean_iou": round(float(np.mean(matched_ious)), 4) if matched_ious else 0.0,
        "breakpoint_mae_bp": round(float(np.mean(boundary_errors)), 1) if boundary_errors else None,
        "breakpoint_median_ae_bp": round(float(np.median(boundary_errors)), 1) if boundary_errors else None,
    }


def compute_region_metrics(
    truth_regions: Sequence[TruthRegion],
    pred_regions: Sequence[PredictedRegion],
    contig_lengths: Dict[str, int],
    iou_threshold: float = 0.5,
) -> Dict[str, Any]:
    """
    计算区域级前噬菌体定位核心指标（含严格 IoU>=0.8 对比与每 Mb 假阳性率 FP/Mb）。
    """
    primary = _match_regions_at_iou(truth_regions, pred_regions, iou_threshold=iou_threshold)
    strict = _match_regions_at_iou(truth_regions, pred_regions, iou_threshold=0.8)

    truth_contigs = {t.contig_id for t in truth_regions}
    neg_only_bp = sum(length for cid, length in contig_lengths.items() if cid not in truth_contigs)
    neg_only_preds = sum(1 for p in pred_regions if p.contig_id not in truth_contigs)
    total_bp = sum(contig_lengths.values())

    neg_only_fp_per_mb = (
        neg_only_preds / (neg_only_bp / 1_000_000.0) if neg_only_bp > 0 else None
    )
    overall_fp_per_mb = (
        primary["fp"] / (total_bp / 1_000_000.0) if total_bp > 0 else None
    )

    return {
        "truth_count": len(truth_regions),
        "predicted_count": len(pred_regions),
        "total_scanned_mb": round(total_bp / 1_000_000.0, 3),
        "pure_negative_scanned_mb": round(neg_only_bp / 1_000_000.0, 3),
        "pure_negative_false_positives": neg_only_preds,
        "pure_negative_fp_per_mb": round(neg_only_fp_per_mb, 4) if neg_only_fp_per_mb is not None else None,
        "overall_fp_per_mb": round(overall_fp_per_mb, 4) if overall_fp_per_mb is not None else None,
        "primary": primary,
        "strict_iou_0_8": strict,
    }

