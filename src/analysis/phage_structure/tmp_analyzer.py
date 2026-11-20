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

# 直接编码或高度锚定尾部卷尺蛋白的权威 Pfam 结构域
_DIRECT_TMP_PFAMS = frozenset({
    "PF06791",  # TMP_2: Prophage tail length tape measure protein
    "PF09718",  # Tape_meas_lam_C: Lambda phage tail tape-measure protein
    "PF06120",  # Phage_HK97_TLTM: Tail length tape measure protein
    "PF10145",  # PhageMin_Tail: Phage-related minor tail / TMP core
    "PF12789",  # PTR: Phage tail repeat like (长链肌尾/巨型噬菌体尾尺重复单元)
})
_TMP_PFAM_DESC_RE = re.compile(
    r"(?:^|\b)(?:TMP_2|Tape_meas(?:_lam_C)?|Phage_HK97_TLTM|PhageMin_Tail|PTR|tape[-_ ]meas)",
    re.I,
)

# 常与长尾 TMP 融合存在的溶菌/肽聚糖水解域（仅结合高长度与尾操纵子位置挽救；PF00877 常出现于下游基板溶菌酶，仅在无其他强位点或紧密共线性时使用）
_LYTIC_TMP_PFAMS = frozenset({
    "PF18013",  # Phage_lysozyme2
    "PF01464",  # SLT
    "PF01551",  # Peptidase_M23
    "PF01832",  # Glucosaminidase
    "PF02557",  # VanY
    "PF06605",  # Prophage_tail
})
_LYTIC_TMP_PFAM_RE = re.compile(
    r"(?:Peptidase_M23|SLT|Transglycosylase|Phage_lysozyme2|Glucosaminidase|Amidase|LysM|CHAP|PG_binding|Prophage_tail)",
    re.I,
)

# 明确非 TMP 混淆域与非尾部酶类/尾纤维 Pfam（杜绝归巢内切酶、脂肪酶、DUF4815、尾刺纤维等混入）
_CONFOUNDER_PFAMS = frozenset({
    "PF05443",  # ROS_MUCR 转录调控因子 (关联 homing endonuclease)
    "PF18741",  # MTES_1575 限制性内切酶 (关联 homing endonuclease)
    "PF13472",  # Lipase_GDSL_2 脂肪酶
    "PF00657",  # Lipase_GDSL
    "PF16075",  # DUF4815 Ackermann/Pootjes 巨型非尺毒粒蛋白
    "PF01335",  # DED (非 TMP 域)
    "PF03406",  # Phage_fiber_2 长尾纤维蛋白
    "PF18668",  # Tail_spike_N 尾刺蛋白
    "PF13884",  # Peptidase_S74 尾纤维/尾刺伴侣内肽酶
    "PF01391",  # Collagen 尾纤维胶原螺旋重复
    "PF12708",  # Pectate_lyase_3 尾刺解聚酶
    "PF13229",  # Beta_helix 尾刺β螺旋
})
_NON_TAIL_PFAM_DESC_RE = re.compile(
    r"(?:DNA_pol|Methyltransf|Helicase|Primase|Ribonuc_red|RNR_|ResIII|Terminase|"
    r"Topoisom|SMC_N|Integrase|Recombinase|RNA_pol(?!_A_CTD)|DEAD|SNF2|Ligase|Sigma70|HTH_|"
    r"Lipase_GDSL|MTES_1575|ROS_MUCR|DUF4815|Phage_fiber_2|Tail_spike_N|Peptidase_S74|Beta_helix)",
    re.I,
)

# 用于操纵子邻域判别的高可信核心长尾干/基板/头部蛋白角色集合
_CORE_TAIL_TRUNK_ROLES = frozenset({"TSP", "TTP", "MTP", "TAP", "DIT", "CONN_TAIL_TERM"})
_HEAD_OR_NON_LONGTAIL_ROLES = frozenset({"MCP", "PORTAL", "INTERNAL_VIRION", "TERL", "TERS", "TTPA_B", "CONN_AD3", "CONN_HC3"})
_STRICT_NON_TMP_ROLES = frozenset({
    "MCP", "PORTAL", "TERL", "TERS", "INTERNAL_VIRION", "TTPA_B", "COLLAR_PODO", "TAIL_NEEDLE",
    "TAIL_FIBER_RBP", "FIBRITIN_COLLAR", "TSP", "TTP", "MTP", "TAP", "DIT",
    "CONN_AD1", "CONN_AD2", "CONN_AD3", "CONN_HC1", "CONN_HC2", "CONN_HC3", "CONN_NECK1", "CONN_TAIL_TERM", "CONN_GENERAL",
    "INTEGRASE", "T6SS_CONFOUNDER", "NON_TAILED_MARKER", "NON_TAIL_ENZYME",
})
_HEAD_SPECIFIC_KW_RE = re.compile(
    r"\b(?:capsid|major\s+head|portal|terminase|scaffolding|maturation\s+protease|hoc-like|head\s+decoration)\b",
    re.I,
)
_UNVERIFIED_SOURCES = frozenset({"unverified_text", "genbank_unverified", "faa_unverified"})


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


def _protein_pfams(protein: StructureProteinItem) -> set[str]:
    """收集蛋白全部显著命中的 Pfam accession（兼容多结构域解析结果）。"""
    out: set[str] = set()
    if protein.ptf_pfam:
        out.add(protein.ptf_pfam.strip().upper())
    for acc in (protein.ptf_all_pfams or []):
        if acc:
            out.add(str(acc).strip().upper())
    return out


def _biophysical_plausibility(aa_seq: str) -> float:
    """评估氨基酸序列作为柔性长/肌尾标尺蛋白的物化组成适应度（不依赖外部注释文本）。"""
    s = (aa_seq or "").strip().upper().rstrip("*")
    n = len(s)
    if n < 50:
        return 0.0
    gast_frac = (s.count("G") + s.count("A") + s.count("S") + s.count("T")) / n
    helix_frac = sum(s.count(ch) for ch in "EALMQKRH") / n
    bonus = 0.0
    if gast_frac >= 0.28:
        bonus += 0.6
    if helix_frac >= 0.34:
        bonus += 0.6
    return bonus


def _inspect_operon_context(
    sorted_prots: Sequence[StructureProteinItem],
    pos: int,
    *,
    contig_length_bp: int = 0,
    window: int = 4,
) -> Dict[str, Any]:
    """
    审计候选蛋白在基因组局部操作子 (±window ORF，兼容窄间距环状边界) 中的结构邻域：
    识别核心长尾干基因、基板蛋白、紧邻 TAP 直接下游信号、以及纯头部/非长尾包装模块三明治冲突。
    """
    n = len(sorted_prots)
    cand = sorted_prots[pos]
    neighbor_indices: List[Tuple[int, int]] = []  # (index, signed_step)
    seen_idx = {pos}
    for d in range(1, window + 1):
        for sgn in (-1, 1):
            raw = pos + sgn * d
            if 0 <= raw < n:
                idx = raw
            elif n > window * 2 + 2 and contig_length_bp > 0:
                idx = raw % n
                # 只有当跨端点环绕真实基因间区较紧凑时才视作环状连续操纵子
                edge_gap = (
                    (sorted_prots[0].start - 1) + max(0, contig_length_bp - sorted_prots[-1].end)
                )
                if edge_gap > 3500:
                    continue
            else:
                continue
            if idx not in seen_idx:
                seen_idx.add(idx)
                neighbor_indices.append((idx, sgn * d))

    tail_trunk_anchors = 0
    same_strand_tail_anchors = 0
    same_strand_minor_tail_anchors = 0
    baseplate_anchors = 0
    neighbor_ptf_anchors = 0
    head_internal_anchors = 0
    same_strand_head_anchors = 0
    best_syntax_score = 0.0
    immediate_tap_downstream = False

    for ti, signed_step in neighbor_indices:
        anchor = sorted_prots[ti]
        dist = abs(signed_step)
        same_strand = anchor.strand == cand.strand
        expected_step = 1 if anchor.strand == "+" else -1

        if anchor.structural_role in _CORE_TAIL_TRUNK_ROLES:
            tail_trunk_anchors += 1
            if same_strand:
                same_strand_tail_anchors += 1
        if anchor.structural_role == "BASEPLATE_MYO":
            baseplate_anchors += 1
            if same_strand:
                same_strand_tail_anchors += 1
        if anchor.structural_role in {"TAIL_OTHER", "TAIL_FIBER_RBP"} and same_strand:
            same_strand_minor_tail_anchors += 1
        if anchor.ptf_is_tail and anchor.ptf_tail_prob >= 0.72 and anchor.length_aa >= 120:
            neighbor_ptf_anchors += 1
        if anchor.structural_role in _HEAD_OR_NON_LONGTAIL_ROLES:
            head_internal_anchors += 1
            if same_strand:
                same_strand_head_anchors += 1

        if anchor.structural_role == "TAP" and same_strand:
            # signed_step = ti - pos：当 anchor 位于候选上游第1位时，signed_step == -expected_step
            if signed_step == -expected_step:
                immediate_tap_downstream = True
                best_syntax_score = max(best_syntax_score, 8.2)
            elif signed_step == -2 * expected_step:
                mid = sorted_prots[(ti + expected_step) % n]
                if mid.structural_role in {"OTHER", "TAP"} and mid.length_aa <= 220:
                    immediate_tap_downstream = True
                    best_syntax_score = max(best_syntax_score, 7.2)
            elif dist <= 3:
                best_syntax_score = max(best_syntax_score, 4.8)
        elif anchor.structural_role in {"MTP", "TTP", "DIT", "TSP"}:
            if dist <= 2:
                best_syntax_score = max(best_syntax_score, 4.4 if same_strand else 2.2)
            elif dist <= 4:
                best_syntax_score = max(best_syntax_score, 2.8 if same_strand else 1.4)
        elif anchor.structural_role == "BASEPLATE_MYO" and dist <= 3:
            best_syntax_score = max(best_syntax_score, 3.0 if same_strand else 1.6)
        elif anchor.structural_role == "TAIL_OTHER" and same_strand and dist <= 3:
            best_syntax_score = max(best_syntax_score, 2.6)

    # 检测两侧夹心冲突（如 MCP — [假TMP/通道蛋白] — PORTAL 且局部无任何长尾干核心）
    left_roles = [
        sorted_prots[idx].structural_role
        for idx, step in neighbor_indices
        if step < 0 and abs(step) <= 3 and sorted_prots[idx].structural_role != "OTHER"
    ]
    right_roles = [
        sorted_prots[idx].structural_role
        for idx, step in neighbor_indices
        if step > 0 and abs(step) <= 3 and sorted_prots[idx].structural_role != "OTHER"
    ]
    has_left_head = any(r in _HEAD_OR_NON_LONGTAIL_ROLES for r in left_roles)
    has_right_head = any(r in _HEAD_OR_NON_LONGTAIL_ROLES for r in right_roles)
    immediate_head_sandwich = (has_left_head and has_right_head and tail_trunk_anchors == 0)

    return {
        "tail_trunk_anchors": tail_trunk_anchors,
        "same_strand_tail_anchors": same_strand_tail_anchors,
        "same_strand_minor_tail_anchors": same_strand_minor_tail_anchors,
        "baseplate_anchors": baseplate_anchors,
        "neighbor_ptf_anchors": neighbor_ptf_anchors,
        "head_internal_anchors": head_internal_anchors,
        "same_strand_head_anchors": same_strand_head_anchors,
        "immediate_head_sandwich": immediate_head_sandwich,
        "immediate_tap_downstream": immediate_tap_downstream,
        "best_syntax_score": best_syntax_score,
        "ptf_support": neighbor_ptf_anchors >= 1,
    }


def select_and_analyze_tmps(
    proteins: Sequence[StructureProteinItem],
    *,
    has_tailed_context: bool = False,
    contig_length_bp: int = 0,
    max_workers: Optional[int] = None,
) -> List[TmpAnalysisItem]:
    """
    在单个 Contig/基因组蛋白列表中通过「多结构域 HMM/Pfam + 操纵子共线性语境 + 生物物理尺度」
    统一验证并剖析所有真实 TMP 或 gp29 尺蛋白：
    1. 彻底解除对外部 GenBank/FAA 文本标签的盲从，未核实文本且缺域/缺尾干语境一律拦截；
    2. 结合全量 Pfam 多结构域识别（包含 PF06791/PF09718/PF06120/PF10145/PF12789 及融合溶菌域），
       精准区分真实 TMP 与归巢内切酶/脂肪酶/DUF4815/头模块内部通道蛋白；
    3. 当出现纯头部包装三明治（如 MCP-候选-PORTAL 且无核心长尾干）时自动基于上下文否定，不依赖硬编码 PHROG 补丁。
    """
    sorted_prots = sorted(proteins, key=lambda x: x.start)
    if not sorted_prots:
        return []

    max_end_bp = max((p.end for p in sorted_prots), default=0)
    eff_bp = max(contig_length_bp, max_end_bp)

    # 客观判断全基因组是否真实编码了长尾/肌尾结构骨架，不轻信孤立未核实 TMP 文本或单点 PTF 溶菌域自证
    ptf_tail_loci_cnt = sum(
        1 for p in sorted_prots if p.ptf_is_tail and p.ptf_tail_prob >= 0.72 and p.length_aa >= 150
    )
    has_true_tail_backbone = (
        any(p.structural_role in _CORE_TAIL_TRUNK_ROLES for p in sorted_prots)
        or sum(1 for p in sorted_prots if p.structural_role == "BASEPLATE_MYO") >= 2
        or ptf_tail_loci_cnt >= 2
    )

    contexts: List[Dict[str, Any]] = [
        _inspect_operon_context(sorted_prots, pos, contig_length_bp=eff_bp)
        for pos in range(len(sorted_prots))
    ]
    wide_contexts: List[Dict[str, Any]] = [
        _inspect_operon_context(sorted_prots, pos, contig_length_bp=eff_bp, window=8)
        for pos in range(len(sorted_prots))
    ]

    # 先判断 Contig 内是否已存在带有权威直接 TMP Pfam 的全长主蛋白 (>=380 aa)，以防短截断碎片干扰
    has_direct_pfam_primary = any(
        (
            bool(_protein_pfams(p) & (_DIRECT_TMP_PFAMS - {"PF12789"}))
            or p.ptf_pfam.strip().upper() in _DIRECT_TMP_PFAMS
            or bool(_TMP_PFAM_DESC_RE.search(p.ptf_pfam_desc or ""))
        )
        and not ((p.ptf_pfam.strip().upper() in _CONFOUNDER_PFAMS) or bool(_NON_TAIL_PFAM_DESC_RE.search(p.ptf_pfam_desc or "")))
        and p.structural_role != "BASEPLATE_MYO"
        and p.length_aa >= 380
        and not contexts[pos]["immediate_head_sandwich"]
        for pos, p in enumerate(sorted_prots)
    )

    candidates: List[Tuple[StructureProteinItem, str]] = []
    chosen_loci: set[str] = set()

    for pos, p in enumerate(sorted_prots):
        ctx = contexts[pos]
        pfams = _protein_pfams(p)
        primary_pf = (p.ptf_pfam or "").strip().upper()
        primary_is_confounder = (primary_pf in _CONFOUNDER_PFAMS) or bool(_NON_TAIL_PFAM_DESC_RE.search(p.ptf_pfam_desc or ""))
        # 核心直接 TMP 域：若主域就是明确的非尾/尾纤维冲突域（如 PF03406），则不允许尾端微弱 PTR 域将其强行升格
        has_strong_tmp_pfam = bool(pfams & (_DIRECT_TMP_PFAMS - {"PF12789"})) or bool(_TMP_PFAM_DESC_RE.search(p.ptf_pfam_desc or ""))
        has_direct_pfam = has_strong_tmp_pfam or (
            "PF12789" in pfams and not primary_is_confounder and p.structural_role != "BASEPLATE_MYO"
        )
        has_lytic_pfam = bool(pfams & _LYTIC_TMP_PFAMS) or bool(_LYTIC_TMP_PFAM_RE.search(p.ptf_pfam_desc or ""))
        has_confounder_pfam = primary_is_confounder or bool(pfams & _CONFOUNDER_PFAMS)

        is_high_conf_verified_tmp = (
            p.structural_role == "TMP"
            and p.evidence_source in ("pyhmmer_phrog", "phold_3d")
            and p.hmm_score >= 80.0
            and ctx["tail_trunk_anchors"] >= 1
            and not primary_pf in _CONFOUNDER_PFAMS
        )
        if has_confounder_pfam and not (has_strong_tmp_pfam and not primary_is_confounder) and not is_high_conf_verified_tmp:
            continue
        if p.structural_role in _STRICT_NON_TMP_ROLES:
            if not (has_direct_pfam and p.length_aa >= 400 and p.structural_role not in {"MCP", "PORTAL", "TERL", "TERS", "NON_TAIL_ENZYME", "INTEGRASE", "T6SS_CONFOUNDER", "NON_TAILED_MARKER", "TAIL_FIBER_RBP"}):
                continue

        is_unverified = (
            p.evidence_source in _UNVERIFIED_SOURCES
            or (p.hmm_score <= 0.0 and not has_direct_pfam and p.evidence_source in {"genbank", "annotation", "faa_header", "pyrodigal"})
        )
        # 远缘极端嗜热/巨型噬菌体 TMP 自证豁免（如 Thermus P74-26 5006aa sc=11604）：极高分+超长+无任何头部邻接
        self_authenticating_tmp = (
            p.structural_role == "TMP"
            and not is_unverified
            and p.hmm_score >= 60.0
            and p.length_aa >= 650
            and ctx["head_internal_anchors"] == 0
        )

        # 操纵子语境硬性否决：纯头部夹心或完全无长尾骨架的孤立非典型区段
        if ctx["immediate_head_sandwich"] and not has_direct_pfam:
            continue
        if not has_true_tail_backbone and ctx["tail_trunk_anchors"] == 0 and not has_direct_pfam and not self_authenticating_tmp:
            continue
        if not has_direct_pfam and not self_authenticating_tmp and ctx["head_internal_anchors"] >= 2 and ctx["tail_trunk_anchors"] == 0 and ctx["baseplate_anchors"] == 0:
            continue

        # 路径 1: 拥有权威直接 TMP/PTR/PhageMin_Tail Pfam 结构域的蛋白（最不依赖 PHROG 名称与 GBK 文本）
        if has_direct_pfam and p.length_aa >= 400:
            candidates.append((p, "confirmed_tmp"))
            chosen_loci.add(p.locus_tag)
            continue

        # 路径 2: PHROG HMM / 标注为 TMP 的蛋白，必须通过 HMM 实证 + 尾操纵子语境 + 最小长度校验
        if p.structural_role == "TMP":
            if is_unverified:
                # 绝不放行未经序列核实的外部 .gbk 纯字符串声明，除非同链尾部干区明确共线性证实
                if p.length_aa >= 400 and ctx["same_strand_tail_anchors"] >= 1:
                    candidates.append((p, "putative_syntenic_tmp"))
                    chosen_loci.add(p.locus_tag)
                continue

            in_tail_operon = ctx["tail_trunk_anchors"] >= 1 or ctx["baseplate_anchors"] >= 1 or ctx["ptf_support"] or self_authenticating_tmp
            # 带有溶菌水解 Pfam（如 PF18013）且缺少直接 TMP 域的中短蛋白 (<650aa) 必须具备真实邻域尾干/邻近 PTF 锚点，严防孤立通道蛋白自证
            if has_lytic_pfam and p.length_aa < 650 and not in_tail_operon:
                continue
            min_sc = 20.0 if in_tail_operon else 30.0
            min_len = 300 if (ctx["immediate_tap_downstream"] and p.hmm_score >= 60.0) else 380
            if p.length_aa >= 250 and p.hmm_score >= min_sc:
                # 当基因组附近已存在带权威结构域的主蛋白时，屏蔽 <380 aa 的同源小碎片
                if p.length_aa < min_len and (has_direct_pfam_primary or not in_tail_operon):
                    continue
                if p.length_aa >= min_len or (in_tail_operon and p.hmm_score >= 45.0 and not has_direct_pfam_primary):
                    candidates.append((p, "confirmed_tmp"))
                    chosen_loci.add(p.locus_tag)
            continue

        # 路径 3: 肌尾 T4-gp29 型基板尺蛋白
        if p.structural_role == "BASEPLATE_MYO" and re.search(r"\btail\s+length\b", p.product, re.I) and p.length_aa >= 350:
            candidates.append((p, "gp29_tail_length"))
            chosen_loci.add(p.locus_tag)
            continue

        # 路径 4: 多结构域融合型溶菌-卷尺蛋白（须具备溶菌水解 Pfam + 较长尺度 + 真实尾干同向语境）
        if has_lytic_pfam and p.length_aa >= 650 and ctx["same_strand_tail_anchors"] >= 1 and (ctx["tail_trunk_anchors"] >= 1 or ctx["immediate_tap_downstream"] or (ctx["baseplate_anchors"] >= 1 and ctx["ptf_support"])):
            candidates.append((p, "confirmed_tmp"))
            chosen_loci.add(p.locus_tag)

    # 路径 5: 局部共线性操纵子智能补全（仅当确有真实尾干骨架或明确有尾背景却未检出主 TMP 时激活）
    allow_syntenic = has_true_tail_backbone or (
        has_tailed_context and any(p.structural_role not in _HEAD_OR_NON_LONGTAIL_ROLES and p.structural_role != "TMP" for p in sorted_prots)
    )
    if not candidates and allow_syntenic:
        has_core_trunk_in_genome = any(p.structural_role in {"TSP", "TTP", "MTP"} for p in sorted_prots)
        best_cand: Optional[StructureProteinItem] = None
        best_score = -1.0

        for pos, cand in enumerate(sorted_prots):
            if cand.locus_tag in chosen_loci or not cand.translation:
                continue
            ctx = contexts[pos]
            wctx = wide_contexts[pos]
            # 对确有 MTP/TSP/TTP 核心尾干但局部相隔 5-8 ORF 的放线菌/微杆菌长尾溶菌-TMP 放宽共线邻域支撑
            has_wide_tail_syntax = (
                has_core_trunk_in_genome
                and cand.length_aa >= 650
                and (wctx["same_strand_tail_anchors"] >= 1 and ctx["same_strand_minor_tail_anchors"] >= 1)
            )
            if ctx["same_strand_tail_anchors"] == 0 and not has_wide_tail_syntax:
                continue
            if ctx["immediate_head_sandwich"] or (
                ctx["same_strand_head_anchors"] >= 1
                and ctx["tail_trunk_anchors"] == 0
                and not ctx["ptf_support"]
                and not has_wide_tail_syntax
            ):
                continue

            pfams = _protein_pfams(cand)
            if (pfams & _CONFOUNDER_PFAMS) or _NON_TAIL_PFAM_DESC_RE.search(cand.ptf_pfam_desc or ""):
                continue

            # 兼容被 PHROG 宽泛标为 "virion structural protein" 或 N端带 YqaJ(PF09588) 却严格坐落在 TAP->+1 且邻接基板的长 TMP（如 Chaseviridae）
            is_generic_virion = (
                cand.structural_role == "HEAD_SCAFFOLD_PROTEASE"
                and not _HEAD_SPECIFIC_KW_RE.search(cand.product or "")
                and cand.length_aa >= 650
                and (ctx["immediate_tap_downstream"] or ctx["tail_trunk_anchors"] >= 1)
            )
            is_yqaj_tap_fusion = (
                cand.structural_role == "NON_TAIL_ENZYME"
                and ctx["immediate_tap_downstream"]
                and cand.length_aa >= 500
                and ctx["baseplate_anchors"] >= 1
                and ("PF09588" in pfams or "exonuclease" in (cand.product or "").lower())
            )
            if cand.structural_role not in {"OTHER", "TAIL_OTHER", "LYSIS"} and not is_generic_virion and not is_yqaj_tap_fusion:
                continue

            is_lysin_tail = cand.structural_role == "LYSIS" or bool(
                re.search(r"\btail\s+(?:protein\s+with\s+|associated\s+)?lysin\b", cand.product or "", re.I)
            )
            if is_lysin_tail:
                if cand.length_aa < 650 and "tail" not in (cand.product or "").lower() and not ctx["immediate_tap_downstream"]:
                    continue
            elif cand.length_aa < 480:
                continue

            score = max(ctx["best_syntax_score"], (wctx["best_syntax_score"] * 0.85 if has_wide_tail_syntax else 0.0))
            if has_wide_tail_syntax and ctx["same_strand_minor_tail_anchors"] >= 1:
                score += 1.2 * min(ctx["same_strand_minor_tail_anchors"], 2)
            if cand.structural_role == "TAIL_OTHER":
                score += 1.8
            if (is_generic_virion or is_yqaj_tap_fusion) and ctx["immediate_tap_downstream"]:
                score += 2.2
            if is_lysin_tail and cand.length_aa >= 700:
                score += 1.6
            if bool(pfams & _LYTIC_TMP_PFAMS) or _LYTIC_TMP_PFAM_RE.search(cand.ptf_pfam_desc or ""):
                score += 1.5
            if cand.ptf_is_tail or cand.ptf_tail_prob >= 0.40:
                score += 1.8
            if cand.length_aa >= 580:
                score += 0.8
            score += _biophysical_plausibility(cand.translation)

            if score >= 3.0 and (score > best_score or (score == best_score and best_cand and cand.length_aa > best_cand.length_aa)):
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
