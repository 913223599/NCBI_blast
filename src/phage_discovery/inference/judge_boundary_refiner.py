"""Judge 候选区边界修剪、双峰切分、伴随峰吸收与核心 ORF 吸附模块。"""
from __future__ import annotations

from collections import defaultdict
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np

from ..benchmark.metrics import PredictedRegion, WindowPrediction
from .judge_scoring import _get_r2_core_probs, trim_triggered

def _is_phage_extension_orf(ph_p: float, f10_row: np.ndarray, *, min_phage_prob: float) -> bool:
    p9 = float(f10_row[9])
    if p9 >= 0.68 and ph_p < 0.70:
        return False
    core_max = float(np.max(f10_row[:5]))
    func_max = float(np.max(f10_row[:7]))
    if ph_p >= min_phage_prob:
        return True
    return (core_max >= 0.50 or func_max >= 0.62) and ph_p >= 0.30

def _is_strong_host_edge_orf(ph_p: float, f10_row: np.ndarray) -> bool:
    p9 = float(f10_row[9])
    func_max = float(np.max(f10_row[:7]))
    if func_max >= 0.35 or ph_p >= 0.25:
        return False
    return (p9 >= 0.55) or (ph_p < 0.12)

def merge_nearby_regions(
    regions: Sequence[PredictedRegion],
    *,
    merge_gap_bp: int = 3000,
) -> List[PredictedRegion]:
    """合并同一 Contig 上间距不超过 merge_gap_bp 的邻接预测区段。"""
    by_cid: Dict[str, List[PredictedRegion]] = defaultdict(list)
    for r in regions:
        by_cid[r.contig_id].append(r)

    merged_all: List[PredictedRegion] = []
    for cid in sorted(by_cid.keys()):
        items = sorted(by_cid[cid], key=lambda x: (x.start_bp, x.end_bp))
        cur: List[PredictedRegion] = []
        for r in items:
            if cur and (r.start_bp - cur[-1].end_bp) <= merge_gap_bp:
                prev = cur[-1]
                cur[-1] = PredictedRegion(
                    contig_id=cid,
                    start_bp=min(prev.start_bp, r.start_bp),
                    end_bp=max(prev.end_bp, r.end_bp),
                    peak_score=max(prev.peak_score, r.peak_score),
                    mean_score=round(0.5 * (prev.mean_score + r.mean_score), 5),
                    window_count=prev.window_count + r.window_count,
                )
            else:
                cur.append(r)
        merged_all.extend(cur)
    return merged_all

def _has_window_backbone_support(
    c_wps: Sequence[WindowPrediction],
    gs: int,
    ge: int,
    min_ext_backbone_score: float,
) -> bool:
    if not c_wps:
        return True
    best_s = 0.0
    for wp in c_wps:
        if wp.end_bp > gs and wp.start_bp < ge and wp.score > best_s:
            best_s = wp.score
    return best_s >= min_ext_backbone_score


def _trim_host_edges(
    reg: PredictedRegion,
    orfs: Sequence[Tuple[int, int, int, str]],
    ph_probs: np.ndarray,
    f10_probs: np.ndarray,
    first_i: int,
    last_i: int,
) -> Tuple[int, int, int, int]:
    new_start = reg.start_bp
    new_end = reg.end_bp
    for _ in range(2):
        if (last_i - first_i) < 4 or not _is_strong_host_edge_orf(float(ph_probs[first_i]), f10_probs[first_i]):
            break
        first_i += 1
        new_start = max(reg.start_bp, orfs[first_i][0])
    for _ in range(2):
        if (last_i - first_i) < 4 or not _is_strong_host_edge_orf(float(ph_probs[last_i]), f10_probs[last_i]):
            break
        last_i -= 1
        new_end = min(reg.end_bp, orfs[last_i][1])
    return first_i, last_i, new_start, new_end


def _extend_boundary_direction(
    orfs: Sequence[Tuple[int, int, int, str]],
    ph_probs: np.ndarray,
    f10_probs: np.ndarray,
    c_wps: Optional[Sequence[WindowPrediction]],
    *,
    start_idx: int,
    step: int,
    initial_edge: int,
    anchor_bp: int,
    boundary_bp: int,
    max_flank_bp: int,
    max_step_gap_bp: int,
    min_ext_backbone_score: float,
    min_ext_phage_prob: float,
    max_host_gap_orfs: int,
) -> int:
    cur_edge = initial_edge
    gap_cnt = 0
    idx = start_idx
    while 0 <= idx < len(orfs):
        gs, ge, _, _ = orfs[idx]
        flank_dist = (anchor_bp - gs) if step < 0 else (ge - anchor_bp)
        step_gap = (cur_edge - ge) if step < 0 else (gs - cur_edge)
        if flank_dist > max_flank_bp or step_gap > max_step_gap_bp:
            break
        if c_wps is not None and not _has_window_backbone_support(c_wps, gs, ge, min_ext_backbone_score):
            break
        if _is_phage_extension_orf(float(ph_probs[idx]), f10_probs[idx], min_phage_prob=min_ext_phage_prob):
            boundary_bp = min(boundary_bp, gs) if step < 0 else max(boundary_bp, ge)
            cur_edge = gs if step < 0 else ge
            gap_cnt = 0
        else:
            if _is_strong_host_edge_orf(float(ph_probs[idx]), f10_probs[idx]):
                break
            gap_cnt += 1
            if gap_cnt > max_host_gap_orfs:
                break
            cur_edge = gs if step < 0 else ge
        idx += step
    return boundary_bp


def refine_region_boundaries_with_judge(
    regions: Sequence[PredictedRegion],
    orfs_by_contig: Dict[str, List[Tuple[int, int, int, str]]],
    scored_by_contig: Dict[str, Dict[str, np.ndarray]],
    contigs_bp: Dict[str, int],
    *,
    window_preds: Optional[Sequence[WindowPrediction]] = None,
    min_ext_backbone_score: float = 0.22,
    max_flank_bp: int = 8000,
    max_step_gap_bp: int = 2400,
    min_ext_phage_prob: float = 0.72,
    max_host_gap_orfs: int = 0,
    allow_edge_trim: bool = False,
    merge_gap_bp: int = 3000,
) -> List[PredictedRegion]:
    """
    利用 R3 逐 ORF 精判对 Stage 1.2 初筛区段执行受 DNA 主干过渡带约束的侧翼延展
    与可选边缘强宿主 ORF 裁边。仅当外侧邻接区域仍具备一定 DNA 主干响应 (>= min_ext_backbone_score)
    且连续呈现高置信噬菌体蛋白语义时才适度扩边，保护原 200bp SubBin 边界不被滑窗传染拉宽。
    """
    wp_by_cid: Dict[str, List[WindowPrediction]] = defaultdict(list)
    if window_preds is not None:
        for wp in window_preds:
            wp_by_cid[wp.contig_id].append(wp)

    refined: List[PredictedRegion] = []
    for reg in regions:
        cid = reg.contig_id
        orfs = orfs_by_contig.get(cid, [])
        sc = scored_by_contig.get(cid)
        if not orfs or sc is None or len(sc["phage_probs"]) != len(orfs):
            refined.append(reg)
            continue

        ph_probs = sc["phage_probs"]
        f10_probs = sc["func10_probs"]
        c_len = contigs_bp.get(cid, orfs[-1][1])
        in_idxs = [i for i, (gs, ge, _, _) in enumerate(orfs) if reg.start_bp <= 0.5 * (gs + ge) <= reg.end_bp]
        if not in_idxs:
            refined.append(reg)
            continue

        first_i, last_i = in_idxs[0], in_idxs[-1]
        new_start, new_end = reg.start_bp, reg.end_bp
        if allow_edge_trim and len(in_idxs) >= 5:
            first_i, last_i, new_start, new_end = _trim_host_edges(
                reg, orfs, ph_probs, f10_probs, first_i, last_i
            )

        c_wps = wp_by_cid.get(cid, []) if window_preds is not None else None
        new_start = _extend_boundary_direction(
            orfs, ph_probs, f10_probs, c_wps,
            start_idx=first_i - 1,
            step=-1,
            initial_edge=orfs[first_i][0] if trim_triggered(new_start, reg.start_bp) else new_start,
            anchor_bp=reg.start_bp,
            boundary_bp=new_start,
            max_flank_bp=max_flank_bp,
            max_step_gap_bp=max_step_gap_bp,
            min_ext_backbone_score=min_ext_backbone_score,
            min_ext_phage_prob=min_ext_phage_prob,
            max_host_gap_orfs=max_host_gap_orfs,
        )
        new_end = _extend_boundary_direction(
            orfs, ph_probs, f10_probs, c_wps,
            start_idx=last_i + 1,
            step=1,
            initial_edge=orfs[last_i][1] if new_end < reg.end_bp else new_end,
            anchor_bp=reg.end_bp,
            boundary_bp=new_end,
            max_flank_bp=max_flank_bp,
            max_step_gap_bp=max_step_gap_bp,
            min_ext_backbone_score=min_ext_backbone_score,
            min_ext_phage_prob=min_ext_phage_prob,
            max_host_gap_orfs=max_host_gap_orfs,
        )

        refined.append(
            PredictedRegion(
                contig_id=cid,
                start_bp=max(0, min(new_start, new_end)),
                end_bp=min(c_len, max(new_start, new_end)),
                peak_score=reg.peak_score,
                mean_score=reg.mean_score,
                window_count=reg.window_count,
            )
        )
    return merge_nearby_regions(refined, merge_gap_bp=merge_gap_bp)

def _subbin_interval_stats(
    prof: Optional[np.ndarray],
    start_bp: int,
    end_bp: int,
    *,
    bin_bp: int = 200,
) -> Tuple[float, float]:
    """计算指定 DNA 区间在 200 bp SubBin 连续置信度曲线上的均值与峰值。"""
    if prof is None or len(prof) == 0 or end_bp <= start_bp:
        return 0.0, 0.0
    b0 = max(0, start_bp // bin_bp)
    b1 = min(len(prof), max(b0 + 1, (end_bp + bin_bp - 1) // bin_bp))
    sl = prof[b0:b1]
    if len(sl) == 0:
        return 0.0, 0.0
    return float(np.mean(sl)), float(np.max(sl))

def refine_region_boundaries_bimodal(
    regions: Sequence[PredictedRegion],
    orfs_by_contig: Dict[str, List[Tuple[int, int, int, str]]],
    scored_by_contig: Dict[str, Dict[str, np.ndarray]],
    contigs_bp: Dict[str, int],
    profiles_by_contig: Mapping[str, np.ndarray],
    *,
    snap_out_sub_mean: float = 0.15,
    snap_out_sub_max: float = 0.24,
    snap_min_phage: float = 0.80,
    min_hang_bp: int = 25,
    min_region_bp: int = 3000,
    merge_gap_bp: int = 3000,
    bin_bp: int = 200,
) -> Tuple[List[PredictedRegion], int]:
    """
    DNA 200 bp SubBin 与 UnifiedJudge 双模态门控边界防劈断校准：
    1. 仅当被边界劈断的 ORF 既具备高置信噬菌体蛋白语义 (phage >= snap_min_phage 或核心模块支持)
       又在其基因外露部分保有明确 200 bp SubBin 过渡支持时，外扩囊括完整 ORF，防止把跨界嵌合片段盲目拖入；
    2. 若被劈断 ORF 为强宿主/防御基因 (p9 >= 0.62 或 phage < 0.15 且非核心模块) 且外露 SubBin 偏低，则回退缩进至该基因外缘。
    """
    if not regions:
        return [], 0

    refined: List[PredictedRegion] = []
    snapped_edges = 0

    for reg in regions:
        cid = reg.contig_id
        orfs = orfs_by_contig.get(cid, [])
        sc = scored_by_contig.get(cid)
        prof = profiles_by_contig.get(cid)
        if not orfs or sc is None or len(sc.get("phage_probs", ())) != len(orfs):
            refined.append(reg)
            continue

        ph_p = sc["phage_probs"]
        f10_p = sc["func10_probs"]
        c_len = contigs_bp.get(cid, orfs[-1][1])
        ns, ne = reg.start_bp, reg.end_bp

        # 左边界劈断检查
        for idx, (gs, ge, _, _) in enumerate(orfs):
            if gs >= ns:
                break
            if ge > ns + min_hang_bp:
                overhang = ns - gs
                out_mean, out_max = _subbin_interval_stats(prof, gs, ns, bin_bp=bin_bp)
                p_val = float(ph_p[idx])
                p9_val = float(f10_p[idx, 9])
                core_max = float(np.max(f10_p[idx, :5]))
                func_max = float(np.max(f10_p[idx, :8]))

                if p9_val < 0.55 and (p_val >= snap_min_phage or (core_max >= 0.55 and p_val >= 0.65)):
                    if (out_mean >= snap_out_sub_mean) or (overhang <= 300 and out_max >= snap_out_sub_max):
                        if gs < ns:
                            ns = gs
                            snapped_edges += 1
                elif (p9_val >= 0.62 and p_val < 0.45) or (p_val < 0.15 and func_max < 0.30 and float(f10_p[idx, 4]) < 0.25):
                    if out_mean < 0.20 and (ne - ge) >= min_region_bp and ge > ns:
                        ns = ge
                        snapped_edges += 1

        # 右边界劈断检查
        for idx in range(len(orfs) - 1, -1, -1):
            gs, ge, _, _ = orfs[idx]
            if ge <= ne:
                break
            if gs < ne - min_hang_bp:
                overhang = ge - ne
                out_mean, out_max = _subbin_interval_stats(prof, ne, ge, bin_bp=bin_bp)
                p_val = float(ph_p[idx])
                p9_val = float(f10_p[idx, 9])
                core_max = float(np.max(f10_p[idx, :5]))
                func_max = float(np.max(f10_p[idx, :8]))

                if p9_val < 0.55 and (p_val >= snap_min_phage or (core_max >= 0.55 and p_val >= 0.65)):
                    if (out_mean >= snap_out_sub_mean) or (overhang <= 300 and out_max >= snap_out_sub_max):
                        if ge > ne:
                            ne = ge
                            snapped_edges += 1
                elif (p9_val >= 0.62 and p_val < 0.45) or (p_val < 0.15 and func_max < 0.30 and float(f10_p[idx, 4]) < 0.25):
                    if out_mean < 0.20 and (gs - ns) >= min_region_bp and gs < ne:
                        ne = gs
                        snapped_edges += 1

        refined.append(
            PredictedRegion(
                contig_id=cid,
                start_bp=max(0, min(ns, ne)),
                end_bp=min(c_len, max(ns, ne)),
                peak_score=reg.peak_score,
                mean_score=reg.mean_score,
                window_count=reg.window_count,
            )
        )
    return merge_nearby_regions(refined, merge_gap_bp=merge_gap_bp), snapped_edges

def _extract_active_subbin_segments(
    prof: np.ndarray,
    start_bp: int,
    end_bp: int,
    contig_len: int,
    *,
    sub_thr: float = 0.45,
    bin_bp: int = 200,
) -> List[Tuple[int, int]]:
    """提取指定区间内平滑填充单 bin 缺口后的连续 >= sub_thr 的 SubBin 活跃片段。"""
    n_bins = len(prof)
    b0 = max(0, start_bp // bin_bp)
    b1 = min(n_bins, (end_bp + bin_bp - 1) // bin_bp)
    if b1 <= b0:
        return []
    act = prof[b0:b1] >= sub_thr
    if act.size >= 3:
        act = act.copy()
        act[1:-1] = act[1:-1] | ((~act[1:-1]) & act[:-2] & act[2:])
    segs: List[Tuple[int, int]] = []
    cur_s = -1
    for offset, flag in enumerate(act):
        ab = b0 + offset
        if flag and cur_s < 0:
            cur_s = ab
        elif not flag and cur_s >= 0:
            segs.append((cur_s * bin_bp, min(contig_len, ab * bin_bp)))
            cur_s = -1
    if cur_s >= 0:
        segs.append((cur_s * bin_bp, min(contig_len, b1 * bin_bp)))
    return segs

def _can_absorb_companion_peak(
    prof: np.ndarray,
    orfs: Sequence[Tuple[int, int, int, str]],
    ph: np.ndarray,
    f10: np.ndarray,
    r2: np.ndarray,
    ps: int,
    pe: int,
    valley_s: int,
    valley_e: int,
    *,
    min_peak_len_bp: int = 4200,
    bin_bp: int = 200,
) -> bool:
    """校验窄谷对面的伴生 SubBin 次级峰是否属于同一前噬菌体的早期/极点侧翼臂。"""
    if (pe - ps) < min_peak_len_bp:
        return False
    sm, sx = _subbin_interval_stats(prof, ps, pe, bin_bp=bin_bp)
    if sx < 0.85 or sm < 0.65:
        return False

    v_idxs = [i for i, (gs, ge, _, _) in enumerate(orfs) if valley_s <= 0.5 * (gs + ge) <= valley_e]
    p_idxs = [i for i, (gs, ge, _, _) in enumerate(orfs) if ps <= 0.5 * (gs + ge) <= pe]
    if not p_idxs:
        return False

    if v_idxs:
        if float(np.max(f10[v_idxs, 9])) >= 0.65:
            return False
        consec_host = 0
        for vi in v_idxs:
            if float(ph[vi]) < 0.15 and float(f10[vi, 4]) < 0.20:
                consec_host += 1
                if consec_host >= 3:
                    return False
            else:
                consec_host = 0

    n_head = int(np.sum((r2[p_idxs, 0] >= 0.55) | (f10[p_idxs, 0] >= 0.60)))
    if n_head > 0:
        return False
    if float(np.max(f10[p_idxs, 9])) >= 0.65:
        return False
    return any(float(ph[pi]) >= 0.70 or float(f10[pi, 4]) >= 0.70 for pi in p_idxs)

def absorb_companion_subbin_peaks(
    regions: Sequence[PredictedRegion],
    orfs_by_contig: Mapping[str, Sequence[Tuple[int, int, int, str]]],
    scored_by_contig: Mapping[str, Dict[str, np.ndarray]],
    profiles_by_contig: Mapping[str, np.ndarray],
    contigs_bp: Mapping[str, int],
    *,
    max_valley_bp: int = 4500,
    search_span_bp: int = 16000,
    min_peak_len_bp: int = 4200,
    sub_thr: float = 0.45,
    merge_gap_bp: int = 3000,
    bin_bp: int = 200,
) -> Tuple[List[PredictedRegion], int]:
    """
    吸纳与主区段仅隔窄低谷 (<=4.5 kb) 且未独立成区的强 SubBin 伴生次级峰。
    通过谷内宿主墙校验、次级峰无冗余 Head 核约束与邻近主区段间隔保护杜绝错误并发。
    """
    if not regions:
        return [], 0

    by_cid: Dict[str, List[PredictedRegion]] = defaultdict(list)
    for r in regions:
        by_cid[r.contig_id].append(r)

    absorbed_cnt = 0
    out: List[PredictedRegion] = []
    for cid, regs in sorted(by_cid.items()):
        regs_s = sorted(regs, key=lambda x: (x.start_bp, x.end_bp))
        prof = profiles_by_contig.get(cid)
        orfs = orfs_by_contig.get(cid, [])
        sc = scored_by_contig.get(cid)
        if prof is None or len(prof) == 0 or not orfs or sc is None or len(sc.get("phage_probs", ())) != len(orfs):
            out.extend(regs_s)
            continue

        ph = sc["phage_probs"]
        f10 = sc["func10_probs"]
        r2 = _get_r2_core_probs(sc)
        c_len = contigs_bp.get(cid, max(len(prof) * bin_bp, orfs[-1][1]))

        for idx_r, reg in enumerate(regs_s):
            ns, ne = reg.start_bp, reg.end_bp
            prev_limit = regs_s[idx_r - 1].end_bp + 2000 if idx_r > 0 else 0
            next_limit = regs_s[idx_r + 1].start_bp - 2000 if idx_r + 1 < len(regs_s) else c_len

            l_lim = max(prev_limit, ns - search_span_bp)
            l_peaks = _extract_active_subbin_segments(prof, l_lim, max(l_lim, ns - bin_bp), c_len, sub_thr=sub_thr, bin_bp=bin_bp)
            if l_peaks:
                ps, pe = l_peaks[-1]
                if 0 < (ns - pe) <= max_valley_bp and _can_absorb_companion_peak(
                    prof, orfs, ph, f10, r2, ps, pe, pe, ns, min_peak_len_bp=min_peak_len_bp, bin_bp=bin_bp
                ):
                    ns = ps
                    absorbed_cnt += 1

            r_lim = min(next_limit, ne + search_span_bp)
            r_peaks = _extract_active_subbin_segments(prof, min(r_lim, ne + bin_bp), r_lim, c_len, sub_thr=sub_thr, bin_bp=bin_bp)
            if r_peaks:
                ps, pe = r_peaks[0]
                if 0 < (ps - ne) <= max_valley_bp and _can_absorb_companion_peak(
                    prof, orfs, ph, f10, r2, ps, pe, ne, ps, min_peak_len_bp=min_peak_len_bp, bin_bp=bin_bp
                ):
                    ne = pe
                    absorbed_cnt += 1

            out.append(PredictedRegion(cid, ns, ne, reg.peak_score, reg.mean_score, reg.window_count))

    return merge_nearby_regions(out, merge_gap_bp=merge_gap_bp), absorbed_cnt

def _should_snap_core_orf(
    ph: np.ndarray,
    f10: np.ndarray,
    r2: np.ndarray,
    prof: np.ndarray,
    idx_o: int,
    out_s: int,
    out_e: int,
    *,
    min_r2_core: float,
    min_ph_core: float,
    max_p9_core: float,
    min_out_sub_max: float,
    bin_bp: int,
) -> bool:
    """判定被边界轻度切分的边缘 ORF 是否属于具备外侧 DNA 残余支持的高置信噬菌体核心/整合酶蛋白。"""
    if float(ph[idx_o]) < min_ph_core or float(f10[idx_o, 9]) >= max_p9_core:
        return False
    if float(np.max(r2[idx_o, :5])) < min_r2_core:
        return False
    _, out_max = _subbin_interval_stats(prof, out_s, out_e, bin_bp=bin_bp)
    return out_max >= min_out_sub_max

def snap_split_core_orfs(
    regions: Sequence[PredictedRegion],
    orfs_by_contig: Mapping[str, Sequence[Tuple[int, int, int, str]]],
    scored_by_contig: Mapping[str, Dict[str, np.ndarray]],
    profiles_by_contig: Mapping[str, np.ndarray],
    *,
    min_r2_core: float = 0.70,
    min_ph_core: float = 0.90,
    max_p9_core: float = 0.20,
    min_out_sub_max: float = 0.05,
    max_snap_out_bp: int = 2200,
    min_hang_bp: int = 25,
    tandem_touch_bp: int = 200,
    bin_bp: int = 200,
) -> Tuple[List[PredictedRegion], int]:
    """
    在串联切分之后、att 对齐之前执行的精确核心与整合蛋白防劈断校准：
    - 锁定紧邻同 Contig 相邻区段 (<=200 bp) 的串联切分点，绝不越线吞入邻近前噬菌体；
    - 精确接纳高置信形态/整合酶核心边缘断口，要求外露段具备 >= min_out_sub_max 的 DNA 残余支持。
    """
    if not regions:
        return [], 0

    by_cid: Dict[str, List[PredictedRegion]] = defaultdict(list)
    for r in regions:
        by_cid[r.contig_id].append(r)

    snapped = 0
    out: List[PredictedRegion] = []
    for cid, regs in sorted(by_cid.items()):
        regs_s = sorted(regs, key=lambda x: (x.start_bp, x.end_bp))
        orfs = orfs_by_contig.get(cid, [])
        sc = scored_by_contig.get(cid)
        prof = profiles_by_contig.get(cid)
        if not orfs or sc is None or prof is None or len(sc.get("phage_probs", ())) != len(orfs):
            out.extend(regs_s)
            continue

        ph = sc["phage_probs"]
        f10 = sc["func10_probs"]
        r2 = _get_r2_core_probs(sc)
        for idx_r, reg in enumerate(regs_s):
            ns, ne = reg.start_bp, reg.end_bp
            prev_end = regs_s[idx_r - 1].end_bp if idx_r > 0 else 0
            next_start = regs_s[idx_r + 1].start_bp if idx_r + 1 < len(regs_s) else 10**12
            touch_prev = idx_r > 0 and (ns - prev_end) <= tandem_touch_bp
            touch_next = (idx_r + 1 < len(regs_s)) and (next_start - ne) <= tandem_touch_bp

            if not touch_prev:
                for i, (gs, ge, _, _) in enumerate(orfs):
                    if gs >= ns:
                        break
                    if gs >= prev_end and ge > ns + min_hang_bp and (ns - gs) <= max_snap_out_bp:
                        if _should_snap_core_orf(
                            ph,
                            f10,
                            r2,
                            prof,
                            i,
                            gs,
                            ns,
                            min_r2_core=min_r2_core,
                            min_ph_core=min_ph_core,
                            max_p9_core=max_p9_core,
                            min_out_sub_max=min_out_sub_max,
                            bin_bp=bin_bp,
                        ):
                            ns = min(ns, gs)
                            snapped += 1

            if not touch_next:
                for i in range(len(orfs) - 1, -1, -1):
                    gs, ge, _, _ = orfs[i]
                    if ge <= ne:
                        break
                    if ge <= next_start and gs < ne - min_hang_bp and (ge - ne) <= max_snap_out_bp:
                        if _should_snap_core_orf(
                            ph,
                            f10,
                            r2,
                            prof,
                            i,
                            ne,
                            ge,
                            min_r2_core=min_r2_core,
                            min_ph_core=min_ph_core,
                            max_p9_core=max_p9_core,
                            min_out_sub_max=min_out_sub_max,
                            bin_bp=bin_bp,
                        ):
                            ne = max(ne, ge)
                            snapped += 1

            out.append(PredictedRegion(cid, ns, ne, reg.peak_score, reg.mean_score, reg.window_count))
    return out, snapped
