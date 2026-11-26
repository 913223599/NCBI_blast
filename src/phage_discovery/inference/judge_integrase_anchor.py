"""整合酶侧翼锚定闭合与亚窗口灰区候选区提取模块。"""
from __future__ import annotations

from collections import defaultdict
from typing import Dict, List, Mapping, Optional, Sequence, Set, Tuple

import numpy as np

from ..benchmark.metrics import PredictedRegion, WindowPrediction, assemble_contig_subbin_profile
from .judge_boundary_refiner import _subbin_interval_stats
from .judge_scoring import _get_r2_core_probs

def _is_true_integrase_orf(ph: np.ndarray, f10: np.ndarray, idx_o: int) -> bool:
    """区分高置信噬菌体整合酶 (P4) 与插入序列转座酶 (P8)，杜绝将宿主 IS 元件误作整合极点。"""
    p4 = float(f10[idx_o, 4])
    p8 = float(f10[idx_o, 8])
    return p4 >= 0.65 and p4 >= p8 + 0.05 and float(ph[idx_o]) >= 0.72 and float(f10[idx_o, 9]) < 0.35

def _has_unannotated_dead_moat(
    prof: np.ndarray,
    orfs: Sequence[Tuple[int, int, int, str]],
    ph: np.ndarray,
    f10: np.ndarray,
    s_bp: int,
    e_bp: int,
    *,
    max_moat_bp: int = 3000,
    bin_bp: int = 200,
) -> bool:
    """检测跨越区间是否存在 >= max_moat_bp 且不被强噬菌体 ORF (ph>=0.80) 支撑的全冷 DNA 死水沟。"""
    b0 = max(0, s_bp // bin_bp)
    b1 = min(len(prof), (e_bp + bin_bp - 1) // bin_bp)
    if b1 <= b0:
        return False
    strong_bins = np.zeros(b1 - b0, dtype=bool)
    for idx_o, (gs, ge, _, _) in enumerate(orfs):
        if ge <= s_bp or gs >= e_bp:
            continue
        if float(ph[idx_o]) >= 0.80 and float(f10[idx_o, 9]) < 0.40:
            ib0 = max(b0, gs // bin_bp) - b0
            ib1 = min(b1, (ge + bin_bp - 1) // bin_bp) - b0
            strong_bins[ib0:ib1] = True

    need_bins = max_moat_bp // bin_bp
    run = 0
    for offset, v in enumerate(prof[b0:b1]):
        if float(v) < 0.035 and not strong_bins[offset]:
            run += 1
            if run >= need_bins:
                return True
        else:
            run = 0
    return False

def _passes_integrase_span_quality(
    prof: np.ndarray,
    orfs: Sequence[Tuple[int, int, int, str]],
    sc: Dict[str, np.ndarray],
    r2: np.ndarray,
    span_idxs: List[int],
    anch_i: int,
    dist_bp: int,
    s_bp: int,
    e_bp: int,
    *,
    max_search_bp: int,
    min_long_sub_mean: float,
    max_moat_bp: int,
    bin_bp: int,
) -> bool:
    """基于碱基长度 (bp) 加权与死水沟校验判定 Integrase 闭环检索跨度是否安全可靠。"""
    ph = sc["phage_probs"]
    f10 = sc["func10_probs"]
    if not span_idxs or dist_bp > max_search_bp or not _is_true_integrase_orf(ph, f10, anch_i):
        return False

    span_ph = ph[span_idxs]
    span_f10 = f10[span_idxs]
    span_r2 = r2[span_idxs]
    if int(np.sum((span_r2[:, 0] >= 0.60) | (span_f10[:, 0] >= 0.65))) > 0:
        return False
    if _has_unannotated_dead_moat(prof, orfs, ph, f10, s_bp, e_bp, max_moat_bp=max_moat_bp, bin_bp=bin_bp):
        return False

    consec_host = 0
    for si in span_idxs:
        if float(ph[si]) < 0.20 and float(f10[si, 4]) < 0.20:
            consec_host += 1
            if consec_host >= 3:
                return False
        else:
            consec_host = 0

    lens = np.array([max(50, orfs[si][1] - orfs[si][0]) for si in span_idxs], dtype=np.float64)
    bp_tot = float(np.sum(lens))
    bp_mean = float(np.sum(span_ph * lens) / bp_tot)
    bp_frac = float(np.sum(lens[span_ph >= 0.50]) / bp_tot)
    host_bp = float(np.sum(lens[(span_ph < 0.20) | (span_f10[:, 9] >= 0.62)]))
    max_p9 = float(np.max(span_f10[:, 9]))
    sm, sx = _subbin_interval_stats(prof, s_bp, e_bp, bin_bp=bin_bp)

    if dist_bp <= 2200:
        return bp_mean >= 0.72 and host_bp == 0.0 and max_p9 < 0.35 and sx >= 0.25
    return (
        bp_mean >= 0.62
        and bp_frac >= 0.56
        and max_p9 < 0.62
        and host_bp <= 2500.0
        and (sm >= min_long_sub_mean or sx >= 0.28)
    )

def _search_directional_integrase_anchor(
    orfs: Sequence[Tuple[int, int, int, str]],
    sc: Dict[str, np.ndarray],
    r2: np.ndarray,
    prof: np.ndarray,
    *,
    anchor_edge_bp: int,
    limit_bp: int,
    boundary_orf_idx: int,
    direction: int,
    edge_in_int: float,
    locked_side: bool,
    max_search_bp: int,
    min_long_sub_mean: float,
    max_moat_bp: int,
    bin_bp: int,
) -> Optional[int]:
    """沿单向 (direction=-1 向左, +1 向右) 搜索未封口端点的真 Integrase 锚点并延拓同族整合酶簇。"""
    if locked_side or edge_in_int >= 0.55:
        return None

    ph = sc["phage_probs"]
    f10 = sc["func10_probs"]
    cand_indices = (
        range(boundary_orf_idx - 1, -1, -1)
        if direction < 0
        else range(boundary_orf_idx + 1, len(orfs))
    )

    best_idx: Optional[int] = None
    for ci in cand_indices:
        cand_bound = orfs[ci][0] if direction < 0 else orfs[ci][1]
        if (cand_bound < limit_bp) if direction < 0 else (cand_bound > limit_bp):
            break
        dist_bp = (anchor_edge_bp - cand_bound) if direction < 0 else (cand_bound - anchor_edge_bp)
        if dist_bp > max_search_bp:
            break
        span_idxs = list(range(ci, boundary_orf_idx)) if direction < 0 else list(range(boundary_orf_idx + 1, ci + 1))
        s_bp, e_bp = (cand_bound, anchor_edge_bp) if direction < 0 else (anchor_edge_bp, cand_bound)
        if _passes_integrase_span_quality(
            prof,
            orfs,
            sc,
            r2,
            span_idxs,
            ci,
            dist_bp,
            s_bp,
            e_bp,
            max_search_bp=max_search_bp,
            min_long_sub_mean=min_long_sub_mean,
            max_moat_bp=max_moat_bp,
            bin_bp=bin_bp,
        ):
            best_idx = ci

    if best_idx is None:
        return None

    # 同一末端 <=500 bp 内的连续 Integrase 碎片簇整体囊括
    while True:
        next_idx = best_idx + direction
        if next_idx < 0 or next_idx >= len(orfs):
            break
        next_bound = orfs[next_idx][0] if direction < 0 else orfs[next_idx][1]
        within_limit = (next_bound >= limit_bp) if direction < 0 else (next_bound <= limit_bp)
        adj_gap = (orfs[best_idx][0] - orfs[next_idx][1]) if direction < 0 else (orfs[next_idx][0] - orfs[best_idx][1])
        next_dist = abs(next_bound - anchor_edge_bp)
        if (
            within_limit
            and adj_gap <= 500
            and next_dist <= max_search_bp
            and _is_true_integrase_orf(ph, f10, next_idx)
        ):
            best_idx = next_idx
        else:
            break

    final_bound = orfs[best_idx][0] if direction < 0 else orfs[best_idx][1]
    if (final_bound < anchor_edge_bp) if direction < 0 else (final_bound > anchor_edge_bp):
        return final_bound
    return None

def close_flanks_to_integrase_anchors(
    regions: Sequence[PredictedRegion],
    orfs_by_contig: Mapping[str, Sequence[Tuple[int, int, int, str]]],
    scored_by_contig: Mapping[str, Dict[str, np.ndarray]],
    profiles_by_contig: Mapping[str, np.ndarray],
    contigs_bp: Mapping[str, int],
    *,
    locked_keys: Optional[Set[str]] = None,
    max_search_bp: int = 18000,
    min_long_sub_mean: float = 0.040,
    max_moat_bp: int = 3000,
    bin_bp: int = 200,
) -> Tuple[List[PredictedRegion], int]:
    """
    基于真整合酶 (Integrase P4) 极点锚定的侧翼闭环定界：
    - 严禁修改已被精确 attL/attR 对齐锁死的区段 (locked_keys)；
    - 严禁重新合并区段，并锁死串联/紧贴边界 (<=1.5 kb)，永久保护背靠背前噬菌体对；
    - 仅在未封口侧翼搜索受高蛋白连续度与非死水沟支撑保护的 Integrase 极点延伸。
    """
    if not regions:
        return [], 0

    locked = locked_keys or set()
    by_cid: Dict[str, List[PredictedRegion]] = defaultdict(list)
    for r in regions:
        by_cid[r.contig_id].append(r)

    closed_cnt = 0
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
        c_len = contigs_bp.get(cid, max(len(prof) * bin_bp, orfs[-1][1]))

        for idx_r, reg in enumerate(regs_s):
            if f"{cid}:{reg.start_bp}-{reg.end_bp}" in locked:
                out.append(reg)
                continue

            ns, ne = reg.start_bp, reg.end_bp
            prev_end = regs_s[idx_r - 1].end_bp if idx_r > 0 else 0
            next_start = regs_s[idx_r + 1].start_bp if idx_r + 1 < len(regs_s) else c_len
            lock_l = idx_r > 0 and (ns - prev_end) <= 1500
            lock_r = (idx_r + 1 < len(regs_s)) and (next_start - ne) <= 1500
            prev_limit = prev_end + 3500 if idx_r > 0 else 0
            next_limit = next_start - 3500 if idx_r + 1 < len(regs_s) else c_len

            in_idxs = [i for i, (gs, ge, _, _) in enumerate(orfs) if ns <= 0.5 * (gs + ge) <= ne]
            if not in_idxs:
                out.append(reg)
                continue

            left_in_int = max((float(f10[i, 4]) for i in in_idxs[:3] if float(ph[i]) >= 0.65), default=0.0)
            right_in_int = max((float(f10[i, 4]) for i in in_idxs[-3:] if float(ph[i]) >= 0.65), default=0.0)

            new_l = _search_directional_integrase_anchor(
                orfs,
                sc,
                r2,
                prof,
                anchor_edge_bp=ns,
                limit_bp=prev_limit,
                boundary_orf_idx=in_idxs[0],
                direction=-1,
                edge_in_int=left_in_int,
                locked_side=lock_l,
                max_search_bp=max_search_bp,
                min_long_sub_mean=min_long_sub_mean,
                max_moat_bp=max_moat_bp,
                bin_bp=bin_bp,
            )
            if new_l is not None:
                ns = new_l
                closed_cnt += 1

            new_r = _search_directional_integrase_anchor(
                orfs,
                sc,
                r2,
                prof,
                anchor_edge_bp=ne,
                limit_bp=next_limit,
                boundary_orf_idx=in_idxs[-1],
                direction=1,
                edge_in_int=right_in_int,
                locked_side=lock_r,
                max_search_bp=max_search_bp,
                min_long_sub_mean=min_long_sub_mean,
                max_moat_bp=max_moat_bp,
                bin_bp=bin_bp,
            )
            if new_r is not None:
                ne = new_r
                closed_cnt += 1

            out.append(PredictedRegion(cid, ns, ne, reg.peak_score, reg.mean_score, reg.window_count))

    return out, closed_cnt

def extract_subbin_gray_candidates(
    window_preds: Sequence[WindowPrediction],
    sub_probs: np.ndarray,
    *,
    bin_bp: int = 200,
    sub_active_threshold: float = 0.40,
    min_region_bp: int = 5000,
    min_peak_sub_prob: float = 0.90,
    min_mean_sub_prob: float = 0.55,
    merge_gap_bp: int = 2000,
) -> List[PredictedRegion]:
    """
    从 200bp 亚窗口 (sub_probs) 局部剖面抽取被全局 ContextRefiner 压低 window_score、
    但具备强烈局域连续 200bp 响应的灰区候选片段（供 R3 Judge 二审筛选隐蔽短前噬菌体）。
    """
    if not window_preds or sub_probs is None or len(sub_probs) == 0:
        return []

    by_cid: Dict[str, List[int]] = defaultdict(list)
    max_end: Dict[str, int] = defaultdict(int)
    for i, wp in enumerate(window_preds):
        by_cid[wp.contig_id].append(i)
        if wp.end_bp > max_end[wp.contig_id]:
            max_end[wp.contig_id] = wp.end_bp

    cands: List[PredictedRegion] = []
    for cid, idxs in sorted(by_cid.items()):
        contig_end = max_end[cid]
        prof = assemble_contig_subbin_profile(
            [window_preds[i] for i in idxs],
            [sub_probs[i] for i in idxs],
            contig_end,
            bin_bp=bin_bp,
            smooth_profile=True,
        )
        if len(prof) == 0:
            continue
        active = (prof >= sub_active_threshold).copy()
        if active.size >= 3:
            active[1:-1] = active[1:-1] | ((~active[1:-1]) & active[:-2] & active[2:])

        segs: List[Tuple[int, int]] = []
        seg_s = -1
        for bi, fl in enumerate(active):
            if fl and seg_s < 0:
                seg_s = bi
            elif not fl and seg_s >= 0:
                segs.append((seg_s, bi))
                seg_s = -1
        if seg_s >= 0:
            segs.append((seg_s, len(active)))

        merged_segs: List[Tuple[int, int]] = []
        gap_bins = max(0, merge_gap_bp // bin_bp)
        for bs, be in segs:
            if merged_segs and (bs - merged_segs[-1][1]) <= gap_bins:
                merged_segs[-1] = (merged_segs[-1][0], be)
            else:
                merged_segs.append((bs, be))

        for bs, be in merged_segs:
            s_bp = bs * bin_bp
            e_bp = min(contig_end, be * bin_bp)
            if (e_bp - s_bp) < min_region_bp:
                continue
            seg_vals = prof[bs:be]
            pk = float(np.max(seg_vals))
            mn = float(np.mean(seg_vals))
            if pk >= min_peak_sub_prob and mn >= min_mean_sub_prob:
                cands.append(
                    PredictedRegion(
                        contig_id=cid,
                        start_bp=s_bp,
                        end_bp=e_bp,
                        peak_score=round(pk, 5),
                        mean_score=round(mn, 5),
                        window_count=max(1, (e_bp - s_bp) // 2500),
                    )
                )
    return cands
