# -*- coding: utf-8 -*-
"""
卷尺蛋白 (Tape Measure Protein, TMP) 分子标尺深度分析器

功能依据生信研究机理实现：
1. TMP 主蛋白优选及共线性启发式捕获（有效区分真实全长 TMP 与短伴侣/碎片）；
2. 多聚氨基酸微区 (polyX) 精密检测（涵盖 >= 4 aa 同聚寡肽 run 与低复杂度单/双残基富集滑动窗口）；
3. 串联重复序列 (Tandem Repeats, TRs) 快速周期探测（同时兼容严格一致性重复及物化保守替代重复）；
4. Kyte-Doolittle 疏水性分布剖面及高疏水潜在锚定区间提取；
5. 基于 α-螺旋分子卷尺物理换算常数 (0.145 nm/aa, 区间 0.140~0.150 nm/aa) 估算相对尾长尺度。
"""
from __future__ import annotations

import concurrent.futures
import os
import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .types import (
    HydrophobicSegment,
    PolyXRegion,
    StructureProteinItem,
    TandemRepeatUnit,
    TmpAnalysisItem,
)

# Kyte-Doolittle 疏水指数字典
_KD_HYDROPATHY: Dict[str, float] = {
    "A": 1.8, "R": -4.5, "N": -3.5, "D": -3.5, "C": 2.5,
    "Q": -3.5, "E": -3.5, "G": -0.4, "H": -3.2, "I": 4.5,
    "L": 3.8, "K": -3.9, "M": 1.9, "F": 2.8, "P": -1.6,
    "S": -0.8, "T": -0.7, "W": -0.9, "Y": -1.3, "V": 4.2,
}

# 理化等价基团（用于容许保守氨基酸替换的串联重复阵列检出）
_PHYSICO_GROUP: Dict[str, int] = {
    ch: gid
    for gid, group in enumerate(["AVILM", "FYW", "ST", "NQ", "DE", "KRH", "GP", "C"])
    for ch in group
}

_TMP_HELM_ALPHA_NM_PER_AA = 0.145
_TMP_MIN_NM_PER_AA = 0.140
_TMP_MAX_NM_PER_AA = 0.150

# 专有 Pfam 卷尺结构域（用于直接挽救融合了溶菌域而 PHROG 标成 endolysin 的真 TMP）
_TMP_PFAM_ACC = frozenset({"PF06791", "PF09718"})
_TMP_PFAM_DESC_RE = re.compile(r"(?:^|\b)(?:TMP_2|Tape_meas(?:_lam_C)?|tape[-_ ]meas)", re.I)
# 明确属于非尾部 DNA/RNA 代谢或酶类的 Pfam 描述（共线性补全严禁选中）
_NON_TAIL_PFAM_DESC_RE = re.compile(
    r"(?:DNA_pol|Methyltransf|Helicase|Primase|Ribonuc_red|RNR_|ResIII|Terminase|"
    r"Topoisom|SMC_N|Integrase|Recombinase|RNA_pol|DEAD|SNF2|Ligase|Sigma70|HTH_)",
    re.I,
)
# 常与 TMP 融合的水解/溶菌域（有助于在局部共线性邻域识别融合型 TMP）
_LYTIC_TMP_PFAM_RE = re.compile(
    r"(?:Peptidase_M23|SLT|Transglycosylase|Lysozyme|Amidase|LysM|CHAP|Hydrolase|PG_binding)",
    re.I,
)
# 用于局部邻域打分的高可信尾干锚点角色
_CORE_TAIL_TRUNK_ROLES = frozenset({"TSP", "TTP", "MTP", "TAP", "DIT"})


def detect_polyx_regions(
    aa_seq: str,
    *,
    min_homorun: int = 4,
    win_len: int = 12,
    win_frac: float = 0.50,
    dual_frac: float = 0.75,
) -> Tuple[List[PolyXRegion], int, Dict[str, int]]:
    """
    扫描蛋白质一级序列中的多聚氨基酸微区 (polyX)。
    返回: (PolyXRegion 列表, 总覆盖氨基酸数, 各主导残基覆盖字典)
    """
    s = (aa_seq or "").strip().upper().rstrip("*")
    n = len(s)
    if n == 0:
        return [], 0, {}

    mask = [False] * n
    tags: List[str] = [""] * n
    kinds: List[str] = [""] * n

    # 1. 严格同聚寡肽连续区段 (如 AAAA, GGGG, SSSS)
    i = 0
    while i < n:
        j = i + 1
        while j < n and s[j] == s[i]:
            j += 1
        if (j - i) >= min_homorun and s[i].isalpha():
            for k in range(i, j):
                mask[k] = True
                tags[k] = s[i]
                kinds[k] = "homorun"
        i = j

    # 2. 局部低复杂度成分偏倚窗口 (单残基 >= 50% 或前双残基之和 >= 75%)
    if n >= win_len:
        for i in range(0, n - win_len + 1):
            win = s[i : i + win_len]
            counts: Dict[str, int] = {}
            for ch in win:
                if ch.isalpha():
                    counts[ch] = counts.get(ch, 0) + 1
            if not counts:
                continue
            top_sorted = sorted(counts.items(), key=lambda x: -x[1])
            aa1, c1 = top_sorted[0]
            c2 = c1 + (top_sorted[1][1] if len(top_sorted) > 1 else 0)
            if (c1 / win_len) >= win_frac or (c2 / win_len) >= dual_frac:
                dom = aa1 if (c1 / win_len) >= win_frac else f"{aa1}/{top_sorted[1][0]}"
                for k in range(i, i + win_len):
                    mask[k] = True
                    if not tags[k]:
                        tags[k] = dom
                    if not kinds[k]:
                        kinds[k] = "biased_window"

    regions: List[PolyXRegion] = []
    aa_summary: Dict[str, int] = {}
    idx = 0
    while idx < n:
        if mask[idx]:
            j = idx
            dom_cnt: Dict[str, int] = {}
            has_homorun = False
            while j < n and mask[j]:
                t = tags[j] or s[j]
                dom_cnt[t] = dom_cnt.get(t, 0) + 1
                if kinds[j] == "homorun":
                    has_homorun = True
                j += 1
            dom_aa = max(dom_cnt.items(), key=lambda x: x[1])[0]
            seg_len = j - idx
            regions.append(
                PolyXRegion(
                    start_aa=idx + 1,
                    end_aa=j,
                    length_aa=seg_len,
                    dominant_aa=dom_aa,
                    kind="homorun" if has_homorun else "biased_window",
                    snippet=s[idx:j][:48],
                )
            )
            primary_key = dom_aa.split("/")[0]
            aa_summary[primary_key] = aa_summary.get(primary_key, 0) + seg_len
            idx = j
        else:
            idx += 1

    total_aa = sum(r.length_aa for r in regions)
    return regions, total_aa, aa_summary


def detect_tandem_repeats(
    aa_seq: str,
    *,
    min_period: int = 3,
    max_period: int = 120,
    min_copies: float = 2.0,
) -> Tuple[List[TandemRepeatUnit], int]:
    """
    检测 TMP 中的串联重复阵列 (TRs)，支持精确匹配与理化等价保守替换。
    返回: (去重叠非谐波主 TR 单元列表, TR 覆盖总氨基酸数)
    """
    s = (aa_seq or "").strip().upper().rstrip("*")
    n = len(s)
    if n < max(8, min_period * 2):
        return [], 0

    g_seq = [_PHYSICO_GROUP.get(ch, -1) for ch in s]
    raw_hits: List[Dict[str, Any]] = []
    upper_p = min(max_period, n // 2)

    for p in range(min_period, upper_p + 1):
        diff_len = n - p
        scores = [
            1.0 if s[i] == s[i + p] else (0.6 if g_seq[i] == g_seq[i + p] and g_seq[i] >= 0 else 0.0)
            for i in range(diff_len)
        ]
        exact = [1 if s[i] == s[i + p] else 0 for i in range(diff_len)]

        min_extra = max(8 - p, round(p * (min_copies - 1.0)))
        if min_extra <= 0 or min_extra > diff_len:
            continue

        thresh = 0.72 if p < 12 else 0.62
        min_exact_id = 0.55 if p < 10 else 0.42

        cur_s = sum(scores[:min_extra])
        i = 0
        while i <= diff_len - min_extra:
            if (cur_s / min_extra) >= thresh:
                end_m = i + min_extra
                while end_m < diff_len:
                    tail_slice = scores[max(i, end_m - p + 1) : end_m + 1]
                    if (sum(tail_slice) / len(tail_slice)) >= (thresh - 0.08):
                        end_m += 1
                    else:
                        break
                seg_len = end_m - i
                seg_sim = sum(scores[i:end_m]) / max(1, seg_len)
                seg_id = sum(exact[i:end_m]) / max(1, seg_len)
                total_len = seg_len + p
                copies = total_len / p
                if seg_sim >= thresh and seg_id >= min_exact_id and copies >= min_copies and total_len >= 8:
                    raw_hits.append(
                        {
                            "start_aa": i + 1,
                            "end_aa": i + total_len,
                            "period_aa": p,
                            "copy_number": round(copies, 2),
                            "length_aa": total_len,
                            "identity": round(seg_id, 3),
                            "similarity": round(seg_sim, 3),
                            "unit_sample": s[i : i + p][:32],
                        }
                    )
                    i = end_m + 1
                    if i <= diff_len - min_extra:
                        cur_s = sum(scores[i : i + min_extra])
                    continue
            if i + min_extra < diff_len:
                cur_s += scores[i + min_extra] - scores[i]
            i += 1

    # 优先保留高覆盖且非冗余最小周期的 TR
    raw_hits.sort(key=lambda x: (-x["length_aa"] * x["similarity"], x["period_aa"]))
    kept: List[TandemRepeatUnit] = []
    for h in raw_hits:
        overlapping = any(
            max(0, min(h["end_aa"], k.end_aa) - max(h["start_aa"], k.start_aa) + 1)
            > 0.35 * min(h["length_aa"], k.length_aa)
            for k in kept
        )
        if not overlapping:
            kept.append(TandemRepeatUnit(**h))

    kept.sort(key=lambda x: x.start_aa)
    covered = [False] * n
    for tr in kept:
        for pos in range(tr.start_aa - 1, min(n, tr.end_aa)):
            covered[pos] = True
    return kept, sum(covered)


def compute_hydropathy_profile(
    aa_seq: str,
    *,
    win_len: int = 19,
    n_bins: int = 40,
    tm_threshold: float = 1.4,
) -> Tuple[List[float], List[HydrophobicSegment]]:
    """计算归一化长度上的 Kyte-Doolittle 平均疏水性折线及强疏水/潜在跨膜段。"""
    s = (aa_seq or "").strip().upper().rstrip("*")
    n = len(s)
    if n == 0:
        return [], []

    vals = [_KD_HYDROPATHY.get(ch, 0.0) for ch in s]
    w = min(win_len, n)
    half = w // 2
    smooth: List[float] = []
    for i in range(n):
        lo = max(0, i - half)
        hi = min(n, i + half + 1)
        smooth.append(sum(vals[lo:hi]) / max(1, hi - lo))

    # 降采样至 n_bins 供前端交互曲线渲染
    bins: List[float] = []
    actual_bins = min(n_bins, n)
    for b in range(actual_bins):
        lo = int(b * n / actual_bins)
        hi = max(lo + 1, int((b + 1) * n / actual_bins))
        bins.append(round(sum(smooth[lo:hi]) / (hi - lo), 3))

    # 提取高疏水核心段落 (候选跨膜螺旋锚定段)
    segs: List[HydrophobicSegment] = []
    i = 0
    while i < n:
        if smooth[i] >= tm_threshold:
            j = i
            while j < n and smooth[j] >= tm_threshold:
                j += 1
            if (j - i) >= 12:
                segs.append(
                    HydrophobicSegment(
                        start_aa=i + 1,
                        end_aa=j,
                        mean_kd=round(sum(smooth[i:j]) / (j - i), 2),
                    )
                )
            i = j
        else:
            i += 1
    return bins, segs


def analyze_single_tmp(
    protein: StructureProteinItem,
    *,
    evidence_kind: str = "confirmed_tmp",
) -> TmpAnalysisItem:
    """对单条 TMP 或候选尺蛋白执行全量化分析。"""
    aa = (protein.translation or "").strip().upper().rstrip("*")
    L = max(protein.length_aa, len(aa))

    px_list, px_tot, px_sum = detect_polyx_regions(aa)
    tr_list, tr_tot = detect_tandem_repeats(aa)
    hydro_bins, hydro_segs = compute_hydropathy_profile(aa)

    px_pct = round(px_tot * 100.0 / max(1, L), 2)
    tr_pct = round(tr_tot * 100.0 / max(1, L), 2)
    max_p = max((tr.period_aa for tr in tr_list), default=0)

    est_nm = round(L * _TMP_HELM_ALPHA_NM_PER_AA, 1)
    lo_nm = round(L * _TMP_MIN_NM_PER_AA, 1)
    hi_nm = round(L * _TMP_MAX_NM_PER_AA, 1)

    # 依据文献定性判读
    if evidence_kind == "gp29_tail_length":
        interp = (
            f"检测到肌尾基板尺蛋白同源基因 ({L} aa)，理论基准伸展长度约 {est_nm} nm "
            f"(经验区间 {lo_nm}~{hi_nm} nm)；检出 polyX {px_tot} aa ({px_pct}%)、TR {tr_tot} aa ({tr_pct}%)。"
        )
    elif tr_list and px_tot > 0:
        interp = (
            f"同时富含多聚氨基酸微区 ({len(px_list)} 处 / {px_tot} aa, {px_pct}%) 与串联重复阵列 "
            f"({len(tr_list)} 处 / {tr_tot} aa, {tr_pct}%)，呈现典型的柔性长尾卷尺蛋白构象特征；"
            f"按 α-螺旋标尺 (0.145 nm/aa) 理论估测尾部延伸长度约 {est_nm} nm ({lo_nm}~{hi_nm} nm)。"
        )
    elif px_tot > 0:
        interp = (
            f"主要依赖多聚氨基酸偏倚区 (polyX: {len(px_list)} 处 / {px_tot} aa, {px_pct}%)，"
            f"理论估测尾长约 {est_nm} nm ({lo_nm}~{hi_nm} nm)；实际物理长度受末端折叠及与尾管亚基堆积紧密度调控。"
        )
    else:
        interp = (
            f"全长 {L} aa，未检出显著同聚 polyX 或串联重复阵列，结构较为致密保守；"
            f"按 α-螺旋标尺估算基础延伸尺度约 {est_nm} nm ({lo_nm}~{hi_nm} nm)。"
        )

    conf = 0.95 if evidence_kind == "confirmed_tmp" else (0.85 if evidence_kind == "gp29_tail_length" else 0.55)
    return TmpAnalysisItem(
        locus_tag=protein.locus_tag,
        contig_id=protein.contig_id,
        product=protein.product,
        phrog_id=protein.phrog_id,
        evidence_kind=evidence_kind,  # type: ignore[arg-type]
        confidence=conf,
        start_bp=protein.start,
        end_bp=protein.end,
        strand=protein.strand,
        length_aa=L,
        est_tail_length_nm=est_nm,
        est_tail_range_nm=[lo_nm, hi_nm],
        polyx_count=len(px_list),
        polyx_total_aa=px_tot,
        polyx_fraction_pct=px_pct,
        polyx_aa_summary=px_sum,
        tr_count=len(tr_list),
        tr_total_aa=tr_tot,
        tr_fraction_pct=tr_pct,
        max_tr_period_aa=max_p,
        polyx_regions=px_list,
        tandem_repeats=tr_list,
        hydrophobic_segments=hydro_segs,
        hydropathy_profile=hydro_bins,
        interpretation=interp,
    )


def select_and_analyze_tmps(
    proteins: Sequence[StructureProteinItem],
    *,
    has_tailed_context: bool = False,
    max_workers: Optional[int] = None,
) -> List[TmpAnalysisItem]:
    """
    在单个 Contig/基因组蛋白列表中甄别并并发剖析所有真实 TMP 或 gp29 尺蛋白：
    - 严滤 < 250 aa 的碎片与 TMP 伴侣蛋白（除 gp29 >= 350 aa 外）；
    - 支持基于专有 Pfam 域 (PF06791 TMP_2 / PF09718 Tape_meas_lam_C) 直接识别携带溶菌域的融合型 TMP；
    - 当存在强有尾结构背景（MTP/TSP/TTP/TAP）但 TMP 注释缺失时，仅在核心尾干蛋白紧邻局部邻域 (±3 ORF)
      捕捉共线性大蛋白作为 putative_syntenic_tmp，同时通过非尾 Pfam 排除规则杜绝 DNA 甲基转移酶等误捕获。
    """
    candidates: List[Tuple[StructureProteinItem, str]] = []
    chosen_loci: set[str] = set()

    for p in proteins:
        is_tmp_pfam = (p.ptf_pfam in _TMP_PFAM_ACC) or bool(_TMP_PFAM_DESC_RE.search(p.ptf_pfam_desc or ""))
        if p.structural_role == "TMP":
            # 过滤 P22_orf54 (sc=14.4, 203aa) 或 BUCT551_orf67 (73aa) 类的伴侣/碎片误标
            if p.length_aa >= 250 and (p.hmm_score >= 30.0 or p.evidence_source != "pyhmmer_phrog"):
                candidates.append((p, "confirmed_tmp"))
                chosen_loci.add(p.locus_tag)
        elif is_tmp_pfam and p.length_aa >= 450:
            # 直接挽救含端肽聚糖水解域而被 PHROG 标成 endolysin 的经典分枝杆菌/前噬菌体 TMP
            candidates.append((p, "confirmed_tmp"))
            chosen_loci.add(p.locus_tag)
        elif p.structural_role == "BASEPLATE_MYO" and re.search(r"\btail\s+length\b", p.product, re.I) and p.length_aa >= 350:
            candidates.append((p, "gp29_tail_length"))
            chosen_loci.add(p.locus_tag)

    # 局部共线性操纵子补全：仅当确认存在有尾核心基因却 0 个 TMP 时触发
    if not candidates and has_tailed_context:
        sorted_prots = sorted(proteins, key=lambda x: x.start)
        n_prots = len(sorted_prots)
        trunk_indices = [
            idx
            for idx, p in enumerate(sorted_prots)
            if p.structural_role in _CORE_TAIL_TRUNK_ROLES
        ]
        # 若只有 BASEPLATE_MYO 但没有其他干尾，也可以其为锚点但窗口收紧
        if not trunk_indices:
            trunk_indices = [
                idx
                for idx, p in enumerate(sorted_prots)
                if p.structural_role == "BASEPLATE_MYO"
            ]

        if trunk_indices:
            best_cand: Optional[StructureProteinItem] = None
            best_score = -1.0
            near_set: set[int] = set()
            for ti in trunk_indices:
                for offset in range(-3, 4):
                    pos = ti + offset
                    if 0 <= pos < n_prots:
                        near_set.add(pos)

            for pos in sorted(near_set):
                cand = sorted_prots[pos]
                if cand.locus_tag in chosen_loci or not cand.translation:
                    continue
                if cand.structural_role not in {"OTHER", "TAIL_OTHER", "LYSIS"}:
                    continue
                if _NON_TAIL_PFAM_DESC_RE.search(cand.ptf_pfam_desc or ""):
                    continue

                is_lysin_tail = cand.structural_role == "LYSIS" or bool(
                    re.search(r"\btail\s+(?:protein\s+with\s+|associated\s+)?lysin\b", cand.product or "", re.I)
                )
                if is_lysin_tail:
                    if cand.length_aa < 700 and "tail" not in (cand.product or "").lower():
                        continue
                elif cand.length_aa < 480:
                    continue

                # 局部操纵子共线性打分（严格遵循基因转录顺序：MTP/TTP -> TAP -> [第1下游ORF即为真TMP]）
                score = 0.0
                for ti in trunk_indices:
                    dist = abs(pos - ti)
                    if dist == 0 or dist > 3:
                        continue
                    anchor = sorted_prots[ti]
                    same_strand = anchor.strand == cand.strand
                    expected_step = 1 if anchor.strand == "+" else -1
                    is_immediate_tap_downstream = (
                        anchor.structural_role == "TAP"
                        and same_strand
                        and (pos - ti) == expected_step
                    )
                    if is_immediate_tap_downstream:
                        score = max(score, 7.8)
                    elif anchor.structural_role == "TAP" and dist <= 2:
                        score = max(score, 4.8 if same_strand else 2.8)
                    elif anchor.structural_role in {"MTP", "TTP", "DIT"} and dist <= 2:
                        score = max(score, 4.2 if same_strand else 2.2)
                    elif dist <= 3:
                        score = max(score, 2.8 if same_strand else 1.5)

                if cand.structural_role == "TAIL_OTHER":
                    score += 1.8
                if is_lysin_tail and cand.length_aa >= 700:
                    score += 1.6
                if _LYTIC_TMP_PFAM_RE.search(cand.ptf_pfam_desc or ""):
                    score += 1.2
                if cand.ptf_is_tail or cand.ptf_tail_prob >= 0.40:
                    score += 1.8
                if 580 <= cand.length_aa <= 2100:
                    score += 0.8
                elif cand.length_aa > 2200 and not cand.ptf_is_tail and cand.structural_role == "OTHER":
                    score -= 1.2

                if score >= 2.5 and (score > best_score or (score == best_score and best_cand and cand.length_aa > best_cand.length_aa)):
                    best_score = score
                    best_cand = cand

            if best_cand is not None:
                candidates.append((best_cand, "putative_syntenic_tmp"))

    if not candidates:
        return []

    cpu_cnt = os.cpu_count() or 4
    workers = max_workers if max_workers is not None else max(1, min(len(candidates), cpu_cnt - 2, 8))
    if len(candidates) > 1 and workers > 1:
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
            items = list(pool.map(lambda pair: analyze_single_tmp(pair[0], evidence_kind=pair[1]), candidates))
    else:
        items = [analyze_single_tmp(p, evidence_kind=kind) for p, kind in candidates]

    items.sort(key=lambda x: (-int(x.evidence_kind == "confirmed_tmp"), -x.length_aa))
    return items
