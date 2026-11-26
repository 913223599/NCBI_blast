"""Judge 灰区挽救、串联拆分、片段桥接、过滤否决与区域汇总模块。"""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from ..benchmark.metrics import PredictedRegion
from ..student.orf_functional_judge import JUDGE_CLASS_NAMES
from .judge_boundary_refiner import merge_nearby_regions
from .judge_scoring import _get_r2_core_probs

def _region_overlaps_any(
    cand: PredictedRegion,
    others: Sequence[PredictedRegion],
    min_overlap_bp: int = 500,
    min_clearance_bp: int = 0,
) -> bool:
    for r in others:
        if r.contig_id != cand.contig_id:
            continue
        if min_clearance_bp > 0:
            if max(r.start_bp - min_clearance_bp, cand.start_bp) < min(r.end_bp + min_clearance_bp, cand.end_bp):
                return True
        elif min(r.end_bp, cand.end_bp) - max(r.start_bp, cand.start_bp) >= min_overlap_bp:
            return True
    return False

def _should_veto_base_region(
    ph_sub: np.ndarray,
    f10_sub: np.ndarray,
    *,
    strict_veto_max_mean_phage: float,
    morph_veto_max_mean_phage: float,
    r2_sub: Optional[np.ndarray] = None,
    enable_cross_head_mge_veto: bool = True,
) -> bool:
    """判定主干候选是否属于无形态结构核心的宿主防御岛、质粒 MGE 或接合耐药移动岛假阳性。"""
    mean_ph = float(np.mean(ph_sub))
    max_f10 = np.max(f10_sub, axis=0)
    core_mods = int(np.sum(max_f10[:5] >= 0.50))
    morph_mods = int(np.sum(max_f10[:3] >= 0.50))
    max_p8 = float(max_f10[8])
    max_p9 = float(max_f10[9])
    # 极低蛋白响应且零核心模块（Head/Conn/Tail/Lysis/Int 全无）：安全清除纯粹 DNA 误提质粒或纯复制型片段（如 V583 2227k ICE 残片）
    if mean_ph <= 0.10 and core_mods == 0 and int(np.sum(ph_sub >= 0.50)) == 0:
        return True
    if mean_ph < strict_veto_max_mean_phage and core_mods == 0 and max_p9 >= 0.65:
        return True
    if morph_mods == 0 and mean_ph < morph_veto_max_mean_phage:
        if (max_p9 >= 0.65 and max_p8 >= 0.50) or max_p9 >= 0.72 or (max_p8 >= 0.60 and mean_ph < 0.46):
            return True

    # Opt-1a 跨头联合排雷：Head B 确认零形态/裂解蛋白，同时 Head A 并发高 MGE(P8) 与高防御(P9) 载荷
    if enable_cross_head_mge_veto and r2_sub is not None and len(r2_sub) > 0:
        r2_morph_cnt = int(np.sum(np.max(r2_sub[:, :4], axis=0) >= 0.50))
        mean_p9 = float(np.mean(f10_sub[:, 9]))
        if r2_morph_cnt == 0 and max_p8 >= 0.55 and max_p9 >= 0.45 and mean_p9 >= 0.18 and mean_ph < 0.72:
            return True

    return False

def _is_gray_tailocin_like(
    f10_sub: np.ndarray,
    r2_sub: np.ndarray,
) -> bool:
    """识别灰区中缺乏衣壳(Head)、颈环(Connector)与整合酶(Int)的纯尾部+裂解细菌素(Tailocin)。"""
    max_f10 = np.max(f10_sub, axis=0)
    max_r2 = np.max(r2_sub, axis=0)
    r2_tail_cnt = int(np.sum(r2_sub[:, 2] >= 0.50))
    r2_head_max = float(max_r2[0])
    r2_conn_max = float(max_r2[1])
    int_max = float(max(max_r2[4], max_f10[4]))
    if r2_tail_cnt >= 3 and r2_head_max < 0.45 and r2_conn_max < 0.45 and int_max < 0.45:
        return True

    # 校准后 Head A (f10_sub) 明确为纯尾+裂解且无 Head/Connector/Integrase 时，允许容忍 Head B 至多 1 个单 ORF 噪音
    f10_tail_cnt = int(np.sum(f10_sub[:, 2] >= 0.50))
    f10_head_cnt = int(np.sum(f10_sub[:, 0] >= 0.50))
    f10_conn_cnt = int(np.sum(f10_sub[:, 1] >= 0.50))
    r2_head_cnt = int(np.sum(r2_sub[:, 0] >= 0.55))
    r2_conn_cnt = int(np.sum(r2_sub[:, 1] >= 0.55))
    return (
        f10_tail_cnt >= 3
        and f10_head_cnt == 0
        and f10_conn_cnt == 0
        and float(max_f10[0]) < 0.48
        and float(max_f10[1]) < 0.48
        and r2_head_cnt <= 1
        and r2_conn_cnt <= 1
        and int_max < 0.45
    )

def _passes_gray_rescue_criteria(
    ph_sub: np.ndarray,
    f10_sub: np.ndarray,
    *,
    rescue_min_orfs: int,
    rescue_min_mean_phage: float,
    rescue_min_frac_phage: float,
    rescue_min_active_modules: int,
    rescue_max_mean_p9: float,
    rescue_min_morph_prob: float,
    require_structural_evidence: bool,
    r2_sub: Optional[np.ndarray] = None,
    enable_elastic_rescue: bool = True,
    enable_tailocin_guard: bool = True,
    cand_len_bp: int = 0,
    cand_peak_score: float = 0.0,
    cand_mean_score: float = 0.0,
) -> bool:
    """对 SubBin 灰区候选执行梯度核验与 Tailocin 排雷，兼顾极短隐蔽前噬菌体挽救与零误报防线。"""
    n_orf = len(ph_sub)
    mean_ph = float(np.mean(ph_sub))
    frac_ph = float(np.mean(ph_sub >= 0.50))
    pos_cnt = int(np.sum(ph_sub >= 0.50))
    max_f10 = np.max(f10_sub, axis=0)
    r2_use = r2_sub if r2_sub is not None else f10_sub[:, :5]
    max_r2 = np.max(r2_use, axis=0)
    active_phage_mods = int(np.sum(max_f10[:7] >= 0.50))
    df_cnt = int(np.sum(f10_sub[:, 9] >= 0.65))
    mean_p9 = float(np.mean(f10_sub[:, 9]))

    passed = (
        mean_ph >= rescue_min_mean_phage
        and frac_ph >= rescue_min_frac_phage
        and pos_cnt >= max(3, rescue_min_orfs - 1)
        and active_phage_mods >= rescue_min_active_modules
        and mean_p9 <= rescue_max_mean_p9
        and df_cnt <= pos_cnt // 2
    )
    if passed and require_structural_evidence:
        morph_mods = int(np.sum(max_f10[:3] >= rescue_min_morph_prob))
        core_mods = int(np.sum(max_f10[:5] >= 0.50))
        has_lysis_pair = float(max_f10[3]) >= 0.65 and core_mods >= 2
        if morph_mods == 0 and not has_lysis_pair:
            passed = False
        # 质粒/转座酶高风险标签激活时需多形态模块交叉佐证，防范孤立假结构蛋白误召
        elif float(max_f10[8]) >= 0.55 and morph_mods < 2:
            passed = False

    if not passed and require_structural_evidence and enable_elastic_rescue:
        # Opt-3a 弹性高置信梯度：整合 Head A/B 形态核心并集，在多模块齐备时放宽边缘 P8 阻断（如 Sakai Sp17）
        comb_morph = np.maximum(max_f10[:3], max_r2[:3])
        comb_morph_mods = int(np.sum(comb_morph >= rescue_min_morph_prob))
        comb_core = int(np.sum(np.maximum(max_f10[:5], max_r2[:5]) >= 0.50))
        if (
            n_orf >= rescue_min_orfs
            and mean_ph >= 0.72
            and frac_ph >= 0.75
            and active_phage_mods >= 3
            and mean_p9 <= 0.45
            and df_cnt <= 2
            and comb_morph_mods >= 1
            and comb_core >= 2
        ):
            passed = True

    if not passed and require_structural_evidence and enable_elastic_rescue:
        # Opt-3b2 短形态簇挽救：针对 6..10 ORF、零防御零 MGE 且具备 Head B 核实尾/头的紧致碎片（如 LT2 STM2234）
        r2_tail_or_head = int(np.sum(r2_use[:, 0] >= 0.50)) + int(np.sum(r2_use[:, 2] >= 0.50))
        if (
            6 <= n_orf <= 10
            and mean_ph >= 0.62
            and frac_ph >= 0.60
            and pos_cnt >= 3
            and df_cnt == 0
            and float(max_f10[8]) < 0.25
            and float(max_f10[2]) >= 0.75
            and r2_tail_or_head >= 1
        ):
            passed = True

    if not passed and require_structural_evidence and enable_elastic_rescue:
        # Opt-3c 非尾丝状噬菌体(Inovirus)高平台 DNA + 双流双衣壳与整合酶协同挽救（如 PAO1 Pf4）
        r2_head_cnt = int(np.sum(r2_use[:, 0] >= 0.50))
        if (
            cand_len_bp >= 10000
            and cand_peak_score >= 0.98
            and cand_mean_score >= 0.90
            and n_orf >= 12
            and mean_ph >= 0.28
            and df_cnt == 0
            and mean_p9 <= 0.28
            and float(max_f10[8]) < 0.75
            and float(max_f10[0]) >= 0.65
            and float(max_r2[0]) >= 0.65
            and r2_head_cnt >= 2
            and float(max(max_f10[4], max_r2[4])) >= 0.70
        ):
            passed = True

    if not passed:
        return False

    if require_structural_evidence and enable_tailocin_guard and _is_gray_tailocin_like(f10_sub, r2_use):
        return False

    return True

def bridge_complementary_phage_fragments(
    regions: Sequence[PredictedRegion],
    orfs_by_contig: Dict[str, List[Tuple[int, int, int, str]]],
    scored_by_contig: Dict[str, Dict[str, np.ndarray]],
    *,
    max_subarm_gap_bp: int = 10000,
    max_bridge_gap_bp: int = 20000,
) -> Tuple[List[PredictedRegion], int]:
    """
    Opt-4b2 两级严格互补半臂桥接：
    - Pass 1（结构子臂合拢 <=10kb）：先将中间无强宿主防御且各自专精互补的 Head 臂 (h>=3, l==0, i==0)
      与 Tail+Lysis 臂 (h==0, t>=3, l>=1, i==0) 合拢成完整结构大臂；
    - Pass 2（早臂-结构臂桥接 <=20kb）：一方是缺失 Head 的 >=30kb 早期复制/整合长臂、
      另一方是缺失 Integrase 的完整 Head+Tail+Lysis 结构臂，总跨度 >= 75kb 且 gap 内无宿主防御墙并含锚点支持时，
      桥接回单株完整巨型前噬菌体（如 B. subtilis SPbeta），严禁合并两株独立完整噬菌体或独立小卫星岛。
    """
    if len(regions) <= 1:
        return list(regions), 0

    by_cid: Dict[str, List[PredictedRegion]] = defaultdict(list)
    for r in regions:
        by_cid[r.contig_id].append(r)

    def _arm_stats(
        reg: PredictedRegion,
        orfs: Sequence[Tuple[int, int, int, str]],
        sc: Dict[str, np.ndarray],
    ) -> Tuple[int, int, int, int, int, int]:
        idxs = [i for i, (gs, ge, _, _) in enumerate(orfs) if reg.start_bp <= 0.5 * (gs + ge) <= reg.end_bp]
        span = reg.end_bp - reg.start_bp
        if not idxs:
            return 0, 0, 0, 0, 0, span
        r2 = _get_r2_core_probs(sc)[idxs]
        f10 = sc["func10_probs"][idxs]
        n_head = int(np.sum(r2[:, 0] >= 0.50))
        n_tail = int(np.sum(r2[:, 2] >= 0.50))
        n_lysis = int(np.sum(r2[:, 3] >= 0.50))
        n_int = int(np.sum(r2[:, 4] >= 0.50))
        n_rep = int(np.sum(f10[:, 5] >= 0.50)) + int(np.sum(f10[:, 6] >= 0.50))
        return n_head, n_tail, n_lysis, n_int, n_rep, span

    def _gap_supports_bridge(
        cur: PredictedRegion,
        nxt: PredictedRegion,
        orfs: Sequence[Tuple[int, int, int, str]],
        sc: Dict[str, np.ndarray],
    ) -> bool:
        gap_idxs = [i for i, (gs, ge, _, _) in enumerate(orfs) if cur.end_bp <= 0.5 * (gs + ge) <= nxt.start_bp]
        if not gap_idxs:
            return False
        ph_arr = sc["phage_probs"]
        f10 = sc["func10_probs"]
        r2 = _get_r2_core_probs(sc)
        p9_host = sum(1 for i in gap_idxs if float(f10[i, 9]) >= 0.65 and float(ph_arr[i]) < 0.40)
        if p9_host >= 2:
            return False
        strong_anchors = sum(1 for i in gap_idxs if float(ph_arr[i]) >= 0.70)
        core_or_ph = sum(1 for i in gap_idxs if float(np.max(r2[i, :5])) >= 0.45 or float(ph_arr[i]) >= 0.55)
        return (strong_anchors >= 2) or (p9_host == 0 and core_or_ph >= 3)

    def _merge_pair(cur: PredictedRegion, nxt: PredictedRegion, cid: str) -> PredictedRegion:
        return PredictedRegion(
            contig_id=cid,
            start_bp=cur.start_bp,
            end_bp=nxt.end_bp,
            peak_score=max(cur.peak_score, nxt.peak_score),
            mean_score=round(0.5 * (cur.mean_score + nxt.mean_score), 5),
            window_count=cur.window_count + nxt.window_count,
        )

    out: List[PredictedRegion] = []
    bridged_cnt = 0
    for cid in sorted(by_cid.keys()):
        regs_s = sorted(by_cid[cid], key=lambda x: (x.start_bp, x.end_bp))
        orfs = orfs_by_contig.get(cid, [])
        sc = scored_by_contig.get(cid)
        if not orfs or sc is None:
            out.extend(regs_s)
            continue

        # Pass 1: 结构子臂优先合拢
        pass1: List[PredictedRegion] = [regs_s[0]]
        for nxt in regs_s[1:]:
            cur = pass1[-1]
            gap = nxt.start_bp - cur.end_bp
            if 1000 < gap <= max_subarm_gap_bp:
                h1, t1, l1, i1, _, _ = _arm_stats(cur, orfs, sc)
                h2, t2, l2, i2, _, _ = _arm_stats(nxt, orfs, sc)
                sub_12 = (h1 >= 3 and i1 == 0 and l1 == 0) and (h2 == 0 and t2 >= 3 and l2 >= 1 and i2 == 0)
                sub_21 = (h2 >= 3 and i2 == 0 and l2 == 0) and (h1 == 0 and t1 >= 3 and l1 >= 1 and i1 == 0)
                if (sub_12 or sub_21) and _gap_supports_bridge(cur, nxt, orfs, sc):
                    pass1[-1] = _merge_pair(cur, nxt, cid)
                    bridged_cnt += 1
                    continue
            pass1.append(nxt)

        # Pass 2: 早臂-结构臂桥接
        pass2: List[PredictedRegion] = [pass1[0]]
        for nxt in pass1[1:]:
            cur = pass2[-1]
            gap = nxt.start_bp - cur.end_bp
            if 3000 < gap <= max_bridge_gap_bp:
                h1, t1, l1, i1, rep1, len1 = _arm_stats(cur, orfs, sc)
                h2, t2, l2, i2, rep2, len2 = _arm_stats(nxt, orfs, sc)
                arm_1_early = (h1 == 0 and len1 >= 30000 and rep1 >= 10 and i1 >= 1) and (
                    h2 >= 3 and t2 >= 5 and l2 >= 1 and i2 == 0
                )
                arm_2_early = (h2 == 0 and len2 >= 30000 and rep2 >= 10 and i2 >= 1) and (
                    h1 >= 3 and t1 >= 5 and l1 >= 1 and i1 == 0
                )
                if (arm_1_early or arm_2_early) and (nxt.end_bp - cur.start_bp) >= 75000 and _gap_supports_bridge(cur, nxt, orfs, sc):
                    pass2[-1] = _merge_pair(cur, nxt, cid)
                    bridged_cnt += 1
                    continue
            pass2.append(nxt)

        out.extend(pass2)
    return out, bridged_cnt

def split_tandem_prophage_regions(
    regions: Sequence[PredictedRegion],
    orfs_by_contig: Dict[str, List[Tuple[int, int, int, str]]],
    scored_by_contig: Dict[str, Dict[str, np.ndarray]],
) -> Tuple[List[PredictedRegion], int]:
    """
    Opt-4a2 严格串联前噬菌体拆分：
    仅当长区段 (>=65kb, >=40 ORFs) 内部存在 >=2 个间距 >=25kb 的多基因强衣壳核心簇 (每簇 >=3 个 P0>=0.80)，
    且两簇之间同时呈现深度低噬菌体谷底 (>=2 个 ph<0.35) 与高置信整合酶界桩 (>=2 个 P4>=0.70) 时，
    在谷底/界桩前沿将其精准拆分为两株独立前噬菌体，零误切巨噬菌体。
    """
    out: List[PredictedRegion] = []
    split_cnt = 0
    for reg in regions:
        if (reg.end_bp - reg.start_bp) < 65000:
            out.append(reg)
            continue
        orfs = orfs_by_contig.get(reg.contig_id, [])
        sc = scored_by_contig.get(reg.contig_id)
        if not orfs or sc is None:
            out.append(reg)
            continue
        idxs = [i for i, (gs, ge, _, _) in enumerate(orfs) if reg.start_bp <= 0.5 * (gs + ge) <= reg.end_bp]
        if len(idxs) < 40:
            out.append(reg)
            continue

        r2_probs = _get_r2_core_probs(sc)
        ph_probs = sc["phage_probs"]
        p0_positions = [int(0.5 * (orfs[i][0] + orfs[i][1])) for i in idxs if float(r2_probs[i, 0]) >= 0.80]
        if len(p0_positions) < 6:
            out.append(reg)
            continue

        clusters: List[List[int]] = [[p0_positions[0]]]
        for pos in p0_positions[1:]:
            if pos - clusters[-1][-1] <= 12000:
                clusters[-1].append(pos)
            else:
                clusters.append([pos])
        strong_clusters = [c for c in clusters if len(c) >= 3]
        if len(strong_clusters) < 2:
            out.append(reg)
            continue

        c0_end = strong_clusters[0][-1]
        c1_start = strong_clusters[1][0]
        if (c1_start - c0_end) < 25000:
            out.append(reg)
            continue

        mid_idxs = [
            i
            for i in idxs
            if (c0_end + 5000) <= 0.5 * (orfs[i][0] + orfs[i][1]) <= (c1_start - 5000)
        ]
        p4_strong = [i for i in mid_idxs if float(r2_probs[i, 4]) >= 0.70]
        deep_valley = [i for i in mid_idxs if float(ph_probs[i]) < 0.35]
        if len(p4_strong) >= 2 and len(deep_valley) >= 2:
            p4_onset = orfs[p4_strong[0]][0]
            pre_val = [i for i in deep_valley if orfs[i][1] <= p4_onset + 3000]
            split_bp = orfs[pre_val[-1]][1] if pre_val else p4_onset
            if (split_bp - reg.start_bp) >= 20000 and (reg.end_bp - split_bp) >= 20000:
                half_win = max(1, reg.window_count // 2)
                out.append(
                    PredictedRegion(
                        contig_id=reg.contig_id,
                        start_bp=reg.start_bp,
                        end_bp=split_bp,
                        peak_score=reg.peak_score,
                        mean_score=reg.mean_score,
                        window_count=half_win,
                    )
                )
                out.append(
                    PredictedRegion(
                        contig_id=reg.contig_id,
                        start_bp=split_bp,
                        end_bp=reg.end_bp,
                        peak_score=reg.peak_score,
                        mean_score=reg.mean_score,
                        window_count=max(1, reg.window_count - half_win),
                    )
                )
                split_cnt += 1
                continue
        out.append(reg)
    return out, split_cnt

def reconcile_tentative_siblings(
    regions: Sequence[PredictedRegion],
    tentative_siblings: Sequence[Dict[str, Any]],
    *,
    stats: Optional[Dict[str, int]] = None,
    suppressed_out: Optional[List[Dict[str, Any]]] = None,
) -> List[PredictedRegion]:
    """
    验证暂存邻接兄弟臂是否在拓扑桥接阶段真正并入了更大前噬菌体；
    凡未与主臂合拢的孤立碎片均安全撤回并计为 gray_rejected，严防新增独立误报。
    """
    if not tentative_siblings:
        return list(regions)

    sib_entries = list(tentative_siblings)
    kept_out: List[PredictedRegion] = []

    for reg in regions:
        matched_isolated = False
        for ent in sib_entries:
            cand: PredictedRegion = ent["region"]
            if reg.contig_id != cand.contig_id:
                continue
            ov = min(reg.end_bp, cand.end_bp) - max(reg.start_bp, cand.start_bp)
            cand_len = max(1, cand.end_bp - cand.start_bp)
            reg_len = reg.end_bp - reg.start_bp
            # 若最终输出区段就是该暂存孤岛自己（未被其他臂桥接扩大），判定为未并入，安全剔除
            if ov >= 0.8 * cand_len and reg_len <= cand_len + 1500:
                matched_isolated = True
                break
        if not matched_isolated:
            kept_out.append(reg)

    for ent in sib_entries:
        cand = ent["region"]
        cand_len = max(1, cand.end_bp - cand.start_bp)
        merged_into_host = any(
            reg.contig_id == cand.contig_id
            and (min(reg.end_bp, cand.end_bp) - max(reg.start_bp, cand.start_bp)) >= 0.7 * cand_len
            and (reg.end_bp - reg.start_bp) >= cand_len + 2000
            for reg in kept_out
        )
        if merged_into_host:
            if stats is not None:
                if not ent.get("is_shadow", False):
                    stats["gray_rescued"] = stats.get("gray_rescued", 0) + 1
                stats["sibling_rescued"] = stats.get("sibling_rescued", 0) + 1
        else:
            if not ent.get("is_shadow", False):
                if stats is not None:
                    stats["gray_rejected"] = stats.get("gray_rejected", 0) + 1
                if suppressed_out is not None:
                    suppressed_out.append({
                        "contig_id": cand.contig_id,
                        "start_bp": cand.start_bp,
                        "end_bp": cand.end_bp,
                        "reason": "gray_rejected",
                        "mean_phage_prob": ent["mean_phage_prob"],
                        "max_p9": ent["max_p9"],
                    })
    return kept_out

def rescue_and_filter_regions_with_judge(
    base_regions: Sequence[PredictedRegion],
    relaxed_regions: Sequence[PredictedRegion],
    orfs_by_contig: Dict[str, List[Tuple[int, int, int, str]]],
    scored_by_contig: Dict[str, Dict[str, np.ndarray]],
    *,
    rescue_min_orfs: int = 6,
    rescue_min_mean_phage: float = 0.58,
    rescue_min_frac_phage: float = 0.60,
    rescue_min_active_modules: int = 2,
    rescue_max_mean_p9: float = 0.35,
    rescue_min_morph_prob: float = 0.55,
    require_structural_evidence: bool = True,
    min_base_clearance_bp: int = 10000,
    strict_veto_max_mean_phage: float = 0.22,
    morph_veto_max_mean_phage: float = 0.48,
    merge_gap_bp: int = 3000,
    enable_cross_head_mge_veto: bool = True,
    enable_elastic_rescue: bool = True,
    enable_tailocin_guard: bool = True,
    enable_topology_postprocess: bool = True,
    enable_sibling_arm_rescue: bool = True,
    max_bridge_gap_bp: int = 20000,
    suppressed_out: Optional[List[Dict[str, Any]]] = None,
    tentative_siblings_out: Optional[List[Dict[str, Any]]] = None,
) -> Tuple[List[PredictedRegion], Dict[str, int]]:
    """
    主干双通道区段级仲裁与拓扑精修：
      1. 保留高置信主干区段，联合 Head A/B 拦截强防御岛、质粒 MGE 与复合接合耐药移动岛；
      2. 对远离主区段 (>= min_base_clearance_bp) 的 SubBin 灰区候选执行弹性梯度审核，并拦截纯尾簇细菌素；
      3. 协同挽救紧邻已知前噬菌体的互补分离子臂并执行两级互补半臂桥接及严格双芯串联拆分。
    """
    kept: List[PredictedRegion] = []
    stats = {
        "base_kept": 0,
        "base_vetoed": 0,
        "gray_candidates": 0,
        "gray_rescued": 0,
        "gray_rejected": 0,
        "sibling_rescued": 0,
        "topology_bridged": 0,
        "topology_split": 0,
    }

    for reg in base_regions:
        orfs = orfs_by_contig.get(reg.contig_id, [])
        sc = scored_by_contig.get(reg.contig_id)
        if not orfs or sc is None:
            kept.append(reg)
            stats["base_kept"] += 1
            continue
        idxs = [i for i, (gs, ge, _, _) in enumerate(orfs) if reg.start_bp <= 0.5 * (gs + ge) <= reg.end_bp]
        if len(idxs) >= 5:
            ph_sub = sc["phage_probs"][idxs]
            f10_sub = sc["func10_probs"][idxs]
            r2_sub = _get_r2_core_probs(sc)[idxs]
            if _should_veto_base_region(
                ph_sub,
                f10_sub,
                strict_veto_max_mean_phage=strict_veto_max_mean_phage,
                morph_veto_max_mean_phage=morph_veto_max_mean_phage,
                r2_sub=r2_sub,
                enable_cross_head_mge_veto=enable_cross_head_mge_veto,
            ):
                stats["base_vetoed"] += 1
                if suppressed_out is not None:
                    suppressed_out.append({
                        "contig_id": reg.contig_id,
                        "start_bp": reg.start_bp,
                        "end_bp": reg.end_bp,
                        "reason": "base_veto",
                        "mean_phage_prob": round(float(np.mean(ph_sub)), 4),
                        "max_p9": round(float(np.max(f10_sub[:, 9])), 4),
                    })
                continue
        kept.append(reg)
        stats["base_kept"] += 1

    deferred_gray_rejects: List[Tuple[PredictedRegion, Optional[np.ndarray], Optional[np.ndarray], int, bool]] = []
    for cand in relaxed_regions:
        if _region_overlaps_any(cand, base_regions, min_overlap_bp=500, min_clearance_bp=0):
            continue
        in_clearance_shadow = _region_overlaps_any(cand, base_regions, min_overlap_bp=500, min_clearance_bp=min_base_clearance_bp)
        if not in_clearance_shadow:
            stats["gray_candidates"] += 1
        elif not enable_sibling_arm_rescue:
            continue

        orfs = orfs_by_contig.get(cand.contig_id, [])
        sc = scored_by_contig.get(cand.contig_id)
        if not orfs or sc is None:
            if not in_clearance_shadow:
                stats["gray_rejected"] += 1
            continue
        idxs = [i for i, (gs, ge, _, _) in enumerate(orfs) if cand.start_bp <= 0.5 * (gs + ge) <= cand.end_bp]
        if len(idxs) < rescue_min_orfs:
            if enable_sibling_arm_rescue and len(idxs) >= 3 and (cand.end_bp - cand.start_bp) >= 4000:
                deferred_gray_rejects.append((cand, sc["phage_probs"][idxs], sc["func10_probs"][idxs], len(idxs), in_clearance_shadow))
            elif not in_clearance_shadow:
                stats["gray_rejected"] += 1
            continue

        ph_sub = sc["phage_probs"][idxs]
        f10_sub = sc["func10_probs"][idxs]
        if in_clearance_shadow:
            # 紧邻 base 区段的碎片仅允许进入暂存兄弟臂判定，绝不放行成为独立区段
            deferred_gray_rejects.append((cand, ph_sub, f10_sub, len(idxs), True))
            continue

        r2_sub = _get_r2_core_probs(sc)[idxs]
        if _passes_gray_rescue_criteria(
            ph_sub,
            f10_sub,
            rescue_min_orfs=rescue_min_orfs,
            rescue_min_mean_phage=rescue_min_mean_phage,
            rescue_min_frac_phage=rescue_min_frac_phage,
            rescue_min_active_modules=rescue_min_active_modules,
            rescue_max_mean_p9=rescue_max_mean_p9,
            rescue_min_morph_prob=rescue_min_morph_prob,
            require_structural_evidence=require_structural_evidence,
            r2_sub=r2_sub,
            enable_elastic_rescue=enable_elastic_rescue,
            enable_tailocin_guard=enable_tailocin_guard,
            cand_len_bp=cand.end_bp - cand.start_bp,
            cand_peak_score=cand.peak_score,
            cand_mean_score=cand.mean_score,
        ):
            kept.append(cand)
            stats["gray_rescued"] += 1
        else:
            deferred_gray_rejects.append((cand, ph_sub, f10_sub, len(idxs), False))

    tentative_siblings: List[Dict[str, Any]] = []
    if deferred_gray_rejects:
        kept_by_cid: Dict[str, List[PredictedRegion]] = defaultdict(list)
        if enable_sibling_arm_rescue and kept:
            for kr in kept:
                kept_by_cid[kr.contig_id].append(kr)

        for cand, ph_sub, f10_sub, n_orfs, is_shadow in deferred_gray_rejects:
            assert ph_sub is not None and f10_sub is not None
            mean_ph_v = round(float(np.mean(ph_sub)), 4)
            max_p9_v = round(float(np.max(f10_sub[:, 9])), 4)
            queued_sibling = False
            if enable_sibling_arm_rescue and (cand.end_bp - cand.start_bp) >= 4000 and n_orfs >= 3:
                anchors = kept_by_cid.get(cand.contig_id, [])
                near_anchor = any(
                    0 <= max(a.start_bp - cand.end_bp, cand.start_bp - a.end_bp) <= max_bridge_gap_bp
                    for a in anchors
                )
                if near_anchor and mean_ph_v >= 0.70 and max_p9_v < 0.55 and float(np.max(f10_sub[:, :5])) >= 0.50:
                    tentative_siblings.append({
                        "region": cand,
                        "mean_phage_prob": mean_ph_v,
                        "max_p9": max_p9_v,
                        "is_shadow": is_shadow,
                    })
                    queued_sibling = True
            if not queued_sibling and not is_shadow:
                stats["gray_rejected"] += 1
                if suppressed_out is not None:
                    suppressed_out.append({
                        "contig_id": cand.contig_id,
                        "start_bp": cand.start_bp,
                        "end_bp": cand.end_bp,
                        "reason": "gray_rejected",
                        "mean_phage_prob": mean_ph_v,
                        "max_p9": max_p9_v,
                    })

    # 重要：仅正式通过单岛核验的区段走邻接合并，暂存兄弟臂严禁靠 merge_nearby_regions 粘合，
    # 必须直接进入互补拓扑桥接验证并在未成功并入主臂时安全剔除。
    merged = merge_nearby_regions(kept, merge_gap_bp=merge_gap_bp)
    if enable_topology_postprocess:
        bridge_input = list(merged) + [ent["region"] for ent in tentative_siblings]
        merged, stats["topology_bridged"] = bridge_complementary_phage_fragments(
            bridge_input,
            orfs_by_contig,
            scored_by_contig,
            max_bridge_gap_bp=max_bridge_gap_bp,
        )
        merged = reconcile_tentative_siblings(
            merged,
            tentative_siblings,
            stats=stats,
            suppressed_out=suppressed_out,
        )
        merged, stats["topology_split"] = split_tandem_prophage_regions(
            merged,
            orfs_by_contig,
            scored_by_contig,
        )
    elif tentative_siblings:
        if tentative_siblings_out is not None:
            tentative_siblings_out.extend(tentative_siblings)
        else:
            for ent in tentative_siblings:
                if not ent.get("is_shadow", False):
                    stats["gray_rejected"] += 1
                    if suppressed_out is not None:
                        cand = ent["region"]
                        suppressed_out.append({
                            "contig_id": cand.contig_id,
                            "start_bp": cand.start_bp,
                            "end_bp": cand.end_bp,
                            "reason": "gray_rejected",
                            "mean_phage_prob": ent["mean_phage_prob"],
                            "max_p9": ent["max_p9"],
                        })
    return merged, stats

def summarize_region_with_judge(
    reg: PredictedRegion,
    orfs: Sequence[Tuple[int, int, int, str]],
    scored: Dict[str, np.ndarray],
    *,
    module_threshold: float = 0.5,
) -> Dict[str, Any]:
    """汇总 R3 分区/排雷与 R2 核心完整度，输出标准化的区段级功能报告。"""
    idxs = [i for i, (gs, ge, _, _) in enumerate(orfs) if reg.start_bp <= 0.5 * (gs + ge) <= reg.end_bp]
    if not idxs:
        return {"n_orfs": 0, "active_modules": [], "completeness_class": "cryptic_or_incomplete"}

    ph_sub = scored["phage_probs"][idxs]
    f10_sub = scored["func10_probs"][idxs]
    r2_sub = _get_r2_core_probs(scored)[idxs]

    max_f10 = np.max(f10_sub, axis=0)
    active_mods = [JUDGE_CLASS_NAMES[c] for c in range(9) if float(max_f10[c]) >= module_threshold]
    r2_core_max = np.max(r2_sub, axis=0)
    core_sum = float(np.sum(r2_core_max))
    core_cnt = int(np.sum(r2_core_max >= 0.45))
    has_head = float(r2_core_max[0]) >= 0.45 or float(max_f10[0]) >= module_threshold
    comp_cls = "complete_structural_core" if (core_cnt >= 3 and has_head) else "cryptic_or_incomplete"

    return {
        "n_orfs": len(idxs),
        "mean_phage_prob": round(float(np.mean(ph_sub)), 4),
        "max_p9_defense_prob": round(float(max_f10[9]), 4),
        "r2_core_completeness_sum": round(core_sum, 4),
        "r2_core_active_count": core_cnt,
        "completeness_class": comp_cls,
        "active_modules": active_mods,
    }
