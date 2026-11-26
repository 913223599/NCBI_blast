# -*- coding: utf-8 -*-
"""
噬菌体形态与尾部分型多证据融合判别器 (MorphotypeClassifier)

综合整合以下 4 维生信机理证据：
1. 尾部核心蛋白标志组合：TSP（尾鞘）-> 肌尾; MTP + TAP + TMP -> 长尾; TTPA/B + Internal Virion + Tail Needle -> 短尾;
2. Virfam 头-颈-尾连接器蛋白分型规律：Type 1 (Ad1/Hc1/Neck1/Tr1) vs Type 2 vs Type 3 (Ad3/Hc3/Collar)；
3. 非有尾噬菌体 (Inoviridae M13 / Microviridae 等) 识别与宿主 T6SS (tssB/C) 收缩鞘防误报剔除；
4. 卷尺蛋白 (TMP) 分子标尺辅助验证（polyX + TRs 耦合特征与估算物理尾长）。
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Sequence, Tuple

from .completeness_gate import evaluate_contig_completeness
from .thresholds import (
    CompletenessThresholds,
    DEFAULT_THRESHOLDS,
    MorphotypeClassifierThresholds,
)
from .types import (
    CompletenessAssessment,
    ConnectorProfile,
    EvidenceItem,
    MorphotypePrediction,
    StructuralModuleMatrix,
    StructureProteinItem,
    TailFinderCluster,
    TmpAnalysisItem,
)

MORPHOTYPE_META: Dict[str, Tuple[str, str]] = {
    "Myoviridae-like": ("肌尾形态 (Myoviridae-like)", "长可收缩双层尾部 (含尾鞘 TSP + 尾管)"),
    "Siphoviridae-like": ("长尾形态 (Siphoviridae-like)", "长而柔韧不可收缩尾部 (含 MTP/TAP/TMP)"),
    "Podoviridae-like": ("短尾形态 (Podoviridae-like)", "极短不可收缩尾部 (含短尾管状蛋白/内注射核心或缺乏长尾机制)"),
    "Non-tailed": ("非有尾噬菌体 (Non-tailed)", "丝状 (Inoviridae) 或无尾二十面体衣壳特征"),
    "Incomplete": ("结构不完整 / 证据不足", "未见完整包装-尾模块组合，疑似截断 Contig 或退化残骸"),
}


def build_module_matrix(proteins: Sequence[StructureProteinItem]) -> StructuralModuleMatrix:
    counts: Dict[str, int] = {}
    for p in proteins:
        counts[p.structural_role] = counts.get(p.structural_role, 0) + 1

    head_cnt = sum(counts.get(r, 0) for r in ("PORTAL", "TERL", "TERS", "MCP", "HEAD_SCAFFOLD_PROTEASE"))
    conn_cnt = sum(
        counts.get(r, 0)
        for r in ("CONN_AD1", "CONN_AD2", "CONN_AD3", "CONN_HC1", "CONN_HC2", "CONN_HC3", "CONN_NECK1", "CONN_TAIL_TERM", "CONN_GENERAL")
    )
    return StructuralModuleMatrix(
        head_packaging_count=head_cnt,
        connector_count=conn_cnt,
        tail_sheath_count=counts.get("TSP", 0),
        tail_tube_count=counts.get("TTP", 0),
        major_tail_count=counts.get("MTP", 0),
        tail_assembly_chaperone_count=counts.get("TAP", 0),
        tape_measure_count=sum(1 for p in proteins if p.structural_role == "TMP" and p.length_aa >= 250),
        tail_tubular_ab_count=counts.get("TTPA_B", 0),
        internal_virion_count=counts.get("INTERNAL_VIRION", 0),
        tail_needle_count=counts.get("TAIL_NEEDLE", 0),
        baseplate_count=counts.get("BASEPLATE_MYO", 0),
        tail_fiber_rbp_count=counts.get("TAIL_FIBER_RBP", 0),
        lysis_count=counts.get("LYSIS", 0),
        integrase_count=counts.get("INTEGRASE", 0),
        non_tailed_marker_count=counts.get("NON_TAILED_MARKER", 0),
        t6ss_confounder_count=counts.get("T6SS_CONFOUNDER", 0),
    )


def build_connector_profile(proteins: Sequence[StructureProteinItem]) -> ConnectorProfile:
    counts: Dict[str, int] = {}
    for p in proteins:
        counts[p.structural_role] = counts.get(p.structural_role, 0) + 1

    ad1, ad2, ad3 = counts.get("CONN_AD1", 0), counts.get("CONN_AD2", 0), counts.get("CONN_AD3", 0)
    hc1, hc2, hc3 = counts.get("CONN_HC1", 0), counts.get("CONN_HC2", 0), counts.get("CONN_HC3", 0)
    neck1 = counts.get("CONN_NECK1", 0)
    tr1 = counts.get("CONN_TAIL_TERM", 0)
    podo_collar = counts.get("COLLAR_PODO", 0)
    gen_conn = counts.get("CONN_GENERAL", 0)
    portal = counts.get("PORTAL", 0)

    t1_sig = ad1 + hc1 + neck1 + tr1
    t2_sig = ad2 + hc2
    t3_sig = ad3 + hc3 + podo_collar

    if t3_sig > 0 and t3_sig >= t1_sig and t1_sig == 0:
        hint = "Type_3_Podoviridae"
        label = "Type 3 连接器模块 (典型短尾 Ad3/Hc3/Collar 构型)"
    elif t1_sig > 0 and t1_sig >= max(t2_sig, t3_sig):
        hint = "Type_1_Sipho_Myo"
        label = "Type 1 连接器模块 (经典长尾/肌尾 Ad1/Hc1/Neck1/Tr 构型)"
    elif t2_sig > 0 and t2_sig > t3_sig:
        hint = "Type_2_Sipho_Podo"
        label = "Type 2 连接器模块 (Ad2/Hc2 构型)"
    elif (t1_sig + t2_sig + t3_sig + gen_conn) > 0:
        hint = "Mixed_or_Uncertain"
        label = "通用/混合头-尾连接器模块"
    else:
        hint = "Absent"
        label = "未检出典型连接器模块"

    return ConnectorProfile(
        type_hint=hint,  # type: ignore[arg-type]
        type_label_cn=label,
        portal_count=portal,
        ad1_count=ad1,
        ad2_count=ad2,
        ad3_count=ad3,
        hc1_count=hc1,
        hc2_count=hc2,
        hc3_count=hc3,
        neck1_count=neck1,
        tail_terminator_count=tr1,
        collar_podo_count=podo_collar,
        general_connector_count=gen_conn,
    )


_NT_HELPER_RE = re.compile(
    r"(?:genome\s+terminal\s+protein|nicking\s+at\s+origin|rolling\s+circle\s+dna\s+replication|"
    r"replication\s+initiation)",
    re.I,
)
_NT_HELPER_PHROGS = {"phrog_91", "phrog_453", "phrog_942", "phrog_2969", "phrog_3419", "phrog_8330"}
_NT_CAPSID_PHROGS = {"phrog_514", "phrog_5863", "phrog_8536", "phrog_4286", "phrog_4419", "phrog_7959"}


def _detect_background_signals(
    proteins: Sequence[StructureProteinItem],
    by_role: Dict[str, List[StructureProteinItem]],
    mm: StructuralModuleMatrix,
    cp: ConnectorProfile,
    est_bp: int,
    thresholds: MorphotypeClassifierThresholds,
) -> Dict[str, object]:
    """检测 N4/Schitoviridae 巨型病毒粒 RNA 聚合酶及非有尾小型无 Portal 基因组背景信号。"""
    n4_vrnap_prots = [
        p
        for p in by_role.get("INTERNAL_VIRION", [])
        if "rna polymerase" in (p.product or "").lower()
    ]
    is_n4_like = bool(n4_vrnap_prots)
    nt_all = by_role.get("NON_TAILED_MARKER", [])
    # 遵循 sequence-first：未经过序列 HMM/3D 验证的纯文本 "coat protein" 在大中型有尾基因组中不得拥有一票否决权
    verified_nt_list = [p for p in nt_all if p.evidence_source != "unverified_text"]
    has_true_tail_backbone = any(
        by_role.get(role)
        for role in ("TSP", "MTP", "TAP", "TTP", "DIT", "TTPA_B", "TAIL_NEEDLE")
    )
    nt_helper_prots = [
        p
        for p in proteins
        if _NT_HELPER_RE.search(p.product or "") or p.phrog_id in _NT_HELPER_PHROGS
    ]
    short_p9_atpase = [
        p
        for p in by_role.get("TERL", [])
        if p.length_aa <= thresholds.short_p9_atpase_max_aa and cp.portal_count == 0
    ]
    non_tailed_capsid_phrogs = [
        p for p in proteins if p.phrog_id in _NT_CAPSID_PHROGS
    ]
    is_compact_tailless_bg = (
        est_bp <= thresholds.compact_tailless_max_bp
        and len(proteins) <= thresholds.compact_tailless_max_orfs
        and cp.portal_count == 0
        and mm.connector_count == 0
        and not has_true_tail_backbone
    )
    # 若小型紧凑且无 Portal 基因组的注释仅存在文本标记，仍允许参与辅助判定；中大型有尾基因组只认序列实证
    nt_list = verified_nt_list if (verified_nt_list or not is_compact_tailless_bg) else nt_all
    has_non_tailed_signal = bool(nt_list) or (
        is_compact_tailless_bg
        and (len(nt_helper_prots) + len(short_p9_atpase) + len(non_tailed_capsid_phrogs)) >= 2
    )
    return {
        "n4_vrnap_prots": n4_vrnap_prots,
        "is_n4_like": is_n4_like,
        "nt_list": nt_list,
        "nt_helper_prots": nt_helper_prots,
        "short_p9_atpase": short_p9_atpase,
        "non_tailed_capsid_phrogs": non_tailed_capsid_phrogs,
        "is_compact_tailless_bg": is_compact_tailless_bg,
        "has_non_tailed_signal": has_non_tailed_signal,
    }


def _score_myo_evidence(
    by_role: Dict[str, List[StructureProteinItem]],
    scores: Dict[str, float],
    evidence: List[EvidenceItem],
    thresholds: MorphotypeClassifierThresholds,
) -> Tuple[List[StructureProteinItem], List[StructureProteinItem], List[StructureProteinItem]]:
    """评定肌尾特征：TSP 尾鞘、Fibritin 脖须及收缩基板复合物。"""
    tsp_list = by_role.get("TSP", [])
    if tsp_list:
        w = thresholds.tsp_base_weight + 1.5 * min(len(tsp_list) - 1, 2)
        scores["Myoviridae-like"] += w
        evidence.append(
            EvidenceItem(
                rule="TSP_TAIL_SHEATH_PRESENT",
                target_morphotype="Myoviridae-like",
                weight=round(w, 2),
                detail=f"检测到关键尾鞘蛋白 (TSP x{len(tsp_list)})，具备可收缩肌尾决定性标志",
                loci=[p.locus_tag for p in tsp_list[:4]],
            )
        )

    fib_list = by_role.get("FIBRITIN_COLLAR", [])
    if fib_list:
        w = 2.0
        scores["Myoviridae-like"] += w
        evidence.append(
            EvidenceItem(
                rule="MYO_FIBRITIN_WHISKER",
                target_morphotype="Myoviridae-like",
                weight=w,
                detail=f"检测到肌尾特征脖须/短尾丝 (Fibritin/Short tail fiber x{len(fib_list)})",
                loci=[p.locus_tag for p in fib_list[:3]],
            )
        )

    bp_myo_list = by_role.get("BASEPLATE_MYO", [])
    mtp_list = by_role.get("MTP", [])
    multi_myo_baseplate = (not tsp_list) and (not mtp_list) and (len(bp_myo_list) >= 2)
    if bp_myo_list:
        if tsp_list:
            w_myo = 2.2
        elif multi_myo_baseplate:
            w_myo = round(1.1 + 1.6 * min(len(bp_myo_list) - 1, 3), 2)
        else:
            w_myo = 1.1
        scores["Myoviridae-like"] += w_myo
        evidence.append(
            EvidenceItem(
                rule="CONTRACTILE_BASEPLATE_CLUSTER",
                target_morphotype="Myoviridae-like",
                weight=w_myo,
                detail=f"检测到基板楔形/枢纽复合蛋白 (x{len(bp_myo_list)})",
                loci=[p.locus_tag for p in bp_myo_list[:4]],
            )
        )
    return tsp_list, bp_myo_list, mtp_list


def _score_sipho_and_tmp_evidence(
    by_role: Dict[str, List[StructureProteinItem]],
    tmp_analyses: Sequence[TmpAnalysisItem],
    tsp_list: List[StructureProteinItem],
    bp_myo_list: List[StructureProteinItem],
    mtp_list: List[StructureProteinItem],
    is_n4_like: bool,
    scores: Dict[str, float],
    evidence: List[EvidenceItem],
    thresholds: MorphotypeClassifierThresholds,
) -> bool:
    """评定长尾核心特征（MTP/TAP/Dit 与 TMP 分子标尺）并返回是否存在长尾有效 TMP。"""
    if mtp_list:
        w_s = thresholds.mtp_base_weight if not tsp_list else 1.0
        scores["Siphoviridae-like"] += w_s
        evidence.append(
            EvidenceItem(
                rule="MTP_MAJOR_TAIL_PRESENT",
                target_morphotype="Siphoviridae-like",
                weight=w_s,
                detail=f"检测到主要尾蛋白 (MTP x{len(mtp_list)})",
                loci=[p.locus_tag for p in mtp_list[:3]],
            )
        )

    tap_list = by_role.get("TAP", [])
    if tap_list:
        if is_n4_like and not mtp_list and not tsp_list:
            w_tap = 0.8
        else:
            w_tap = thresholds.tap_base_weight if not tsp_list else 0.8
        scores["Siphoviridae-like"] += w_tap
        if tsp_list:
            scores["Myoviridae-like"] += 0.8
        evidence.append(
            EvidenceItem(
                rule="TAP_TAIL_ASSEMBLY_CHAPERONE",
                target_morphotype="Siphoviridae-like",
                weight=w_tap,
                detail=f"检测到尾部装配蛋白/伴侣 (TAP x{len(tap_list)})",
                loci=[p.locus_tag for p in tap_list[:4]],
            )
        )

    dit_list = by_role.get("DIT", [])
    if dit_list:
        w_dit = 1.8 if not tsp_list else 0.6
        scores["Siphoviridae-like"] += w_dit
        evidence.append(
            EvidenceItem(
                rule="DIT_CENTRAL_TAIL_FIBER",
                target_morphotype="Siphoviridae-like",
                weight=w_dit,
                detail=f"检测到长尾远端尾蛋白/中心尾丝 (Dit/J x{len(dit_list)})",
                loci=[p.locus_tag for p in dit_list[:3]],
            )
        )

    confirmed_tmps = [
        t
        for t in tmp_analyses
        if t.evidence_kind in ("confirmed_tmp", "merged_split_tmp", "gp29_tail_length")
    ]
    has_real_long_tmp = any(
        t.length_aa >= thresholds.real_long_tmp_min_aa
        or (not is_n4_like and t.length_aa >= thresholds.real_long_tmp_non_n4_min_aa and not by_role.get("TTPA_B"))
        for t in confirmed_tmps
    )
    if confirmed_tmps:
        best_tmp = confirmed_tmps[0]
        if is_n4_like and best_tmp.length_aa < 520 and not mtp_list and not tsp_list:
            w_tmp_s = 0.5
        else:
            w_tmp_s = (
                1.6 if (len(bp_myo_list) >= 3 and not mtp_list and best_tmp.length_aa < 400) else thresholds.tmp_base_weight
            ) if not tsp_list else 0.9
            scores["Siphoviridae-like"] += w_tmp_s
            if tsp_list:
                scores["Myoviridae-like"] += 1.0
            if best_tmp.polyx_count > 0 and best_tmp.tr_count > 0 and not tsp_list:
                scores["Siphoviridae-like"] += 0.8
        if w_tmp_s >= 1.0:
            evidence.append(
                EvidenceItem(
                    rule="TMP_MOLECULAR_RULER",
                    target_morphotype="Siphoviridae-like" if not tsp_list else "Myoviridae-like",
                    weight=w_tmp_s,
                    detail=f"检测到完整卷尺蛋白 ({best_tmp.locus_tag}, {best_tmp.length_aa} aa, 估测约 {best_tmp.est_tail_length_nm} nm)",
                    loci=[t.locus_tag for t in confirmed_tmps[:2]],
                )
            )
    return has_real_long_tmp


def _score_podo_and_connector_evidence(
    proteins: Sequence[StructureProteinItem],
    by_role: Dict[str, List[StructureProteinItem]],
    cp: ConnectorProfile,
    tsp_list: List[StructureProteinItem],
    bp_myo_list: List[StructureProteinItem],
    mtp_list: List[StructureProteinItem],
    n4_vrnap_prots: List[StructureProteinItem],
    is_n4_like: bool,
    is_compact_tailless_bg: bool,
    scores: Dict[str, float],
    evidence: List[EvidenceItem],
) -> None:
    """评定短尾标志（TTPA_B/Internal Virion/Tail Needle/Collar）、Pfam T7 尾域及 Virfam 连接器。"""
    podo_specific: List[Tuple[str, float, str]] = [
        ("TTPA_B", 4.5, "短尾特异性管状尾蛋白 TTPA/TTPB"),
        ("INTERNAL_VIRION", 4.0, "短尾/T7/N4样内部病毒粒注射核心或 vRNAP"),
        ("TAIL_NEEDLE", 3.8, "短尾 P22 样尾刺针蛋白"),
        ("COLLAR_PODO", 3.2, "短尾项圈/附器/非收缩性短尾鞘蛋白"),
    ]
    for role_key, rw, desc in podo_specific:
        plist = by_role.get(role_key, [])
        if not plist:
            continue
        raw_w = rw + 0.8 * min(len(plist) - 1, 2)
        if tsp_list and role_key in ("COLLAR_PODO", "INTERNAL_VIRION"):
            total_w = round(raw_w * 0.45, 2)
            note = "（存在 TSP 尾鞘背景，已对非特异性短尾标记降权）"
        elif role_key == "INTERNAL_VIRION" and is_compact_tailless_bg and max(p.hmm_score for p in plist) < 55.0:
            total_w = 1.5
            note = "（小型无 Portal 基因组中的低分跨膜域，已抑制权值）"
        else:
            total_w = round(raw_w, 2)
            note = ""
        scores["Podoviridae-like"] += total_w
        evidence.append(
            EvidenceItem(
                rule=f"PODO_{role_key}",
                target_morphotype="Podoviridae-like",
                weight=total_w,
                detail=f"检测到{desc} (x{len(plist)}){note}",
                loci=[p.locus_tag for p in plist[:4]],
            )
        )

    podo_pfam_hits = [
        p
        for p in proteins
        if p.structural_role != "TTPA_B"
        and (p.ptf_pfam == "PF03906" or "phage_t7_tail" in (p.ptf_pfam_desc or "").lower())
        and p.ptf_tail_prob >= 0.70
    ]
    if podo_pfam_hits and not tsp_list and not mtp_list:
        scores["Podoviridae-like"] += 3.6
        evidence.append(
            EvidenceItem(
                rule="PFAM_PODO_T7_TAIL_DOMAIN",
                target_morphotype="Podoviridae-like",
                weight=3.6,
                detail=f"PhageTailFinder Pfam 检测到 T7 样短尾特征结构域 (PF03906 Phage_T7_tail x{len(podo_pfam_hits)})",
                loci=[p.locus_tag for p in podo_pfam_hits[:3]],
            )
        )

    if is_n4_like and not tsp_list and not mtp_list:
        scores["Podoviridae-like"] += 3.2
        evidence.append(
            EvidenceItem(
                rule="SCHITOVIRIDAE_VRNAP_HALLMARK",
                target_morphotype="Podoviridae-like",
                weight=3.2,
                detail=f"检测到 N4/Schitoviridae 标志性病毒粒封装 RNA 聚合酶 (x{len(n4_vrnap_prots)})，明确指向非收缩短尾噬菌体",
                loci=[p.locus_tag for p in n4_vrnap_prots[:3]],
            )
        )

    if cp.type_hint == "Type_3_Podoviridae":
        scores["Podoviridae-like"] += 3.5
        evidence.append(
            EvidenceItem(
                rule="VIRFAM_CONNECTOR_TYPE3",
                target_morphotype="Podoviridae-like",
                weight=3.5,
                detail="Virfam 连接器识别为 Type 3 (Ad3/Hc3 典型短尾形态特征)",
                loci=[],
            )
        )
    elif cp.type_hint == "Type_1_Sipho_Myo":
        target = "Myoviridae-like" if (tsp_list or len(bp_myo_list) >= 3 and not mtp_list) else "Siphoviridae-like"
        scores[target] += 1.6
        evidence.append(
            EvidenceItem(
                rule="VIRFAM_CONNECTOR_TYPE1",
                target_morphotype=target,
                weight=1.6,
                detail="Virfam 连接器识别为 Type 1 (Ad1/Hc1/Neck1/Tr1 长/肌尾通用型)",
                loci=[],
            )
        )


def _score_negative_podo_and_non_tailed(
    proteins: Sequence[StructureProteinItem],
    by_role: Dict[str, List[StructureProteinItem]],
    mm: StructuralModuleMatrix,
    cp: ConnectorProfile,
    comp: CompletenessAssessment,
    ptf_clusters: Optional[Sequence[TailFinderCluster]],
    est_bp: int,
    has_long_tail_hallmark: bool,
    bg_signals: Dict[str, object],
    scores: Dict[str, float],
    evidence: List[EvidenceItem],
    warnings: List[str],
    thresholds: MorphotypeClassifierThresholds,
    comp_thresholds: CompletenessThresholds,
) -> None:
    """评定短尾“有头无长尾”负向排他证据及非有尾噬菌体专项识别。"""
    nt_list: List[StructureProteinItem] = bg_signals["nt_list"]  # type: ignore[assignment]
    nt_helper_prots: List[StructureProteinItem] = bg_signals["nt_helper_prots"]  # type: ignore[assignment]
    short_p9_atpase: List[StructureProteinItem] = bg_signals["short_p9_atpase"]  # type: ignore[assignment]
    non_tailed_capsid_phrogs: List[StructureProteinItem] = bg_signals["non_tailed_capsid_phrogs"]  # type: ignore[assignment]
    is_compact_tailless_bg: bool = bool(bg_signals["is_compact_tailless_bg"])
    has_non_tailed_signal: bool = bool(bg_signals["has_non_tailed_signal"])

    has_tailed_packaging_chassis = (
        cp.portal_count > 0
        or mm.connector_count > 0
        or any(p.length_aa >= comp_thresholds.terl_full_min_aa for p in by_role.get("TERL", []))
        or est_bp >= comp_thresholds.podo_negative_min_bp
    )
    has_head_core = (
        (by_role.get("PORTAL") or by_role.get("MCP") or by_role.get("TERL"))
        and mm.head_packaging_count >= 2
        and has_tailed_packaging_chassis
    )
    if has_head_core and not has_long_tail_hallmark and not has_non_tailed_signal:
        if comp.allow_negative_podo_inference:
            has_terl_full = any(p.length_aa >= comp_thresholds.terl_full_min_aa for p in by_role.get("TERL", []))
            has_ptf_or_lysis_ctx = (
                bool(ptf_clusters)
                or any(p.ptf_is_tail and p.ptf_tail_prob >= 0.72 for p in proteins)
                or (mm.lysis_count > 0 and len(proteins) >= 20)
            )
            has_complete_head_tail_podo = bool(
                by_role.get("PORTAL")
                and has_terl_full
                and by_role.get("MCP")
                and est_bp >= comp_thresholds.podo_negative_min_bp
                and (bool(by_role.get("TAIL_OTHER")) or has_ptf_or_lysis_ctx)
            )
            w_abs = (
                thresholds.podo_negative_strong_weight
                if (mm.tail_fiber_rbp_count > 0 or mm.connector_count > 0 or has_complete_head_tail_podo)
                else thresholds.podo_negative_weak_weight
            )
            scores["Podoviridae-like"] += w_abs
            evidence.append(
                EvidenceItem(
                    rule="HEAD_PRESENT_LONG_TAIL_ABSENT",
                    target_morphotype="Podoviridae-like",
                    weight=w_abs,
                    detail="具备完整头部包装核心 (MCP+Portal/TerL) 且无长/肌尾残骸，但全面缺失 TSP、MTP 及长 TMP 等尾部结构蛋白",
                    loci=[p.locus_tag for p in (by_role.get("PORTAL", []) + by_role.get("MCP", []))[:3]],
                )
            )
        else:
            for reason in comp.reasons:
                if reason not in warnings:
                    warnings.append(reason)

    if nt_list and not has_long_tail_hallmark:
        base_nt = 6.2 if is_compact_tailless_bg else 5.0
        w_nt = base_nt + 1.5 * min(len(nt_list) - 1, 3)
        scores["Non-tailed"] += w_nt
        evidence.append(
            EvidenceItem(
                rule="NON_TAILED_CAPSID_OR_FILAMENTOUS",
                target_morphotype="Non-tailed",
                weight=round(w_nt, 2),
                detail=f"检测到非有尾噬菌体特异性外壳/装配/递送蛋白 (Ino/Micro/Fiers/Tectiviridae 等 x{len(nt_list)})",
                loci=[p.locus_tag for p in nt_list[:4]],
            )
        )
    elif is_compact_tailless_bg and not has_long_tail_hallmark:
        helper_cnt = len(nt_helper_prots) + len(short_p9_atpase) + len(non_tailed_capsid_phrogs)
        if helper_cnt >= 2:
            w_cmp = round(min(7.5, 4.2 + 0.8 * helper_cnt), 2)
            scores["Non-tailed"] += w_cmp
            evidence.append(
                EvidenceItem(
                    rule="COMPACT_TAILLESS_CAPSID_REPL",
                    target_morphotype="Non-tailed",
                    weight=w_cmp,
                    detail=f"紧凑基因组 ({est_bp} bp) 缺失 Portal/Connector/Tail 骨架且具非有尾复制包装与衣壳标志 (x{helper_cnt})",
                    loci=[p.locus_tag for p in (non_tailed_capsid_phrogs + short_p9_atpase + nt_helper_prots)[:4]],
                )
            )


def _resolve_decision_and_warnings(
    proteins: Sequence[StructureProteinItem],
    tmp_analyses: Sequence[TmpAnalysisItem],
    mm: StructuralModuleMatrix,
    ptf_clusters: Optional[Sequence[TailFinderCluster]],
    tsp_list: List[StructureProteinItem],
    nt_list: List[StructureProteinItem],
    scores: Dict[str, float],
    evidence: List[EvidenceItem],
    warnings: List[str],
    genetic_code_used: int,
    genetic_code_auto_selected: bool,
    sparse_rescued_orfs: int,
    thresholds: MorphotypeClassifierThresholds,
) -> Tuple[str, float, str, str]:
    """汇总得分决断、置信度、生活史提示并追加辅助印证与告警。"""
    best_code = max(scores, key=lambda k: scores[k])
    best_score = scores[best_code]
    sorted_vals = sorted(scores.values(), reverse=True)
    second_score = sorted_vals[1] if len(sorted_vals) > 1 else 0.0

    if mm.integrase_count > 0:
        lifestyle = "Temperate"
    elif len(proteins) >= 20 and mm.head_packaging_count >= 2:
        lifestyle = "Lytic"
    else:
        lifestyle = "Unknown"

    if best_score < thresholds.incomplete_score_cutoff:
        best_code = "Incomplete"
        conf = 0.25 if best_score > 0.5 else 0.10
        basis = "未检测到足够置信的头部包装蛋白或尾部特征模块，该序列可能为极短 Contig、高度退化前噬菌体残片或宿主区域。"
    else:
        margin = best_score - second_score
        raw_conf = 0.58 + 0.045 * min(best_score, 8.0) + 0.025 * min(margin, 4.0)
        conf = round(max(0.50, min(0.99, raw_conf)), 4)
        top_rules = [
            e.detail
            for e in sorted([ev for ev in evidence if ev.target_morphotype == best_code], key=lambda x: -x.weight)[:3]
        ]
        basis = "；".join(top_rules) + "。" if top_rules else f"综合结构特征得分最高 ({best_score:.2f})。"

        if best_code != "Non-tailed" and margin < thresholds.low_margin_warning_cutoff and second_score > 2.0:
            second_code = [k for k, v in scores.items() if v == second_score][0]
            warnings.append(
                f"与次高候选形态 ({second_code}) 分差较小 ({best_score:.1f} vs {second_score:.1f})，建议结合全基因注释与 3D 结构增强复核。"
            )

    if genetic_code_used != 11 and genetic_code_auto_selected:
        warnings.append(
            f"检测到非标准遗传密码重编码特征，已自动切换至 Translation Table {genetic_code_used} 进行 ORF 预测。"
        )
    if sparse_rescued_orfs > 0:
        warnings.append(
            f"原始注释存在大段编码空缺，已自动回补 {sparse_rescued_orfs} 个间隙预测 ORF 并联合核实尾部结构。"
        )
    if mm.tail_fiber_rbp_count > 0 and best_code in ("Siphoviridae-like", "Myoviridae-like") and not tmp_analyses:
        warnings.append("虽判定为长/肌尾形态，但未定位到全长卷尺蛋白 (TMP)，可能存在假定蛋白遗漏或基因预测跨距断裂。")

    if ptf_clusters:
        tot_ptf_orfs = sum(cl.orf_count for cl in ptf_clusters)
        tot_novel = sum(cl.novel_orf_count for cl in ptf_clusters)
        top_cluster = max(ptf_clusters, key=lambda c: (c.orf_count, c.mean_tail_prob))
        if tot_ptf_orfs >= 2 and not nt_list:
            target_morph = (
                "Myoviridae-like"
                if tsp_list
                else ("Podoviridae-like" if best_code == "Podoviridae-like" else "Siphoviridae-like")
            )
            evidence.append(
                EvidenceItem(
                    rule="PHAGETAILFINDER_TWO_STATE_HMM",
                    target_morphotype=target_morph,
                    weight=1.2,
                    detail=f"PhageTailFinder 双状态 HMM 识别 {len(ptf_clusters)} 个尾部基因簇 (共 {tot_ptf_orfs} 蛋白，新捕获未知 ORF x{tot_novel})",
                    loci=top_cluster.loci[:5],
                )
            )
            if best_code == "Incomplete" and tot_ptf_orfs >= 3:
                warnings.append(
                    f"虽 PHROG 同源标志不足，但 PhageTailFinder 双状态 HMM 在 [{top_cluster.start_bp}..{top_cluster.end_bp}] 发现高置信共线性尾部簇 ({top_cluster.orf_count} 蛋白)，提示可能为极度分异的新颖有尾噬菌体。"
                )

    if best_code == "Myoviridae-like" and mm.head_packaging_count == 0 and len(proteins) >= 12:
        warnings.append("检测到收缩尾鞘等尾部组件但完全缺失头部与包装核心 (MCP/Portal/TerL)，请警惕细菌收缩型尾素 (Tailocin/eCIS) 或严重截断片段。")

    return best_code, conf, basis, lifestyle


def _resolve_tail_length_estimate(
    best_code: str,
    tmp_analyses: Sequence[TmpAnalysisItem],
    warnings: List[str],
) -> Tuple[Optional[float], List[float]]:
    """根据生物物理一致性约束输出估算尾长与区间（短尾与非有尾严禁套用 TMP 标尺）。"""
    primary_tmp = tmp_analyses[0] if tmp_analyses else None
    if best_code in ("Podoviridae-like", "Non-tailed", "Incomplete"):
        if tmp_analyses and best_code in ("Podoviridae-like", "Non-tailed"):
            loci_preview = ", ".join(t.locus_tag for t in tmp_analyses[:2])
            warnings.append(
                f"注释中存在疑似 TMP 误标片段 ({loci_preview})，但该噬菌体属 {best_code} 构型（无 TMP 分子标尺），已自动抑制标尺推算以免高估尾长。"
            )
        return None, []
    return (
        primary_tmp.est_tail_length_nm if primary_tmp else None,
        list(primary_tmp.est_tail_range_nm) if primary_tmp else [],
    )


def classify_morphotype(
    proteins: Sequence[StructureProteinItem],
    tmp_analyses: Sequence[TmpAnalysisItem],
    module_matrix: Optional[StructuralModuleMatrix] = None,
    connector_profile: Optional[ConnectorProfile] = None,
    ptf_clusters: Optional[Sequence[TailFinderCluster]] = None,
    genome_length_bp: Optional[int] = None,
    dna_seq: str = "",
    completeness: Optional[CompletenessAssessment] = None,
    genetic_code_used: int = 11,
    genetic_code_auto_selected: bool = False,
    sparse_rescued_orfs: int = 0,
    thresholds: MorphotypeClassifierThresholds = DEFAULT_THRESHOLDS.classifier,
    comp_thresholds: CompletenessThresholds = DEFAULT_THRESHOLDS.completeness,
) -> MorphotypePrediction:
    """
    结合尾部核心组件、Virfam 连接器模块、基因组完整度门控与 TMP 标尺蛋白开展可解释形态预测。
    """
    mm = module_matrix or build_module_matrix(proteins)
    cp = connector_profile or build_connector_profile(proteins)

    by_role: Dict[str, List[StructureProteinItem]] = {}
    for p in proteins:
        by_role.setdefault(p.structural_role, []).append(p)

    est_bp = genome_length_bp or max((p.end for p in proteins), default=0)
    comp = completeness or evaluate_contig_completeness(
        dna_seq=dna_seq,
        length_bp=est_bp,
        proteins=proteins,
        module_matrix=mm,
        connector_profile=cp,
        tmp_analyses=tmp_analyses,
        ptf_clusters=ptf_clusters,
        sparse_rescued_orfs=sparse_rescued_orfs,
        thresholds=comp_thresholds,
    )

    scores: Dict[str, float] = {
        "Myoviridae-like": 0.0,
        "Siphoviridae-like": 0.0,
        "Podoviridae-like": 0.0,
        "Non-tailed": 0.0,
    }
    evidence: List[EvidenceItem] = []
    warnings: List[str] = []

    if mm.t6ss_confounder_count > 0:
        warnings.append(
            f"已自动隔离 {mm.t6ss_confounder_count} 个宿主 VI 型分泌系统 (T6SS) 相似组件，避免将细菌收缩鞘误判为肌尾噬菌体。"
        )

    bg_signals = _detect_background_signals(proteins, by_role, mm, cp, est_bp, thresholds)
    is_n4_like = bool(bg_signals["is_n4_like"])
    n4_vrnap_prots: List[StructureProteinItem] = bg_signals["n4_vrnap_prots"]  # type: ignore[assignment]
    nt_list: List[StructureProteinItem] = bg_signals["nt_list"]  # type: ignore[assignment]
    is_compact_tailless_bg = bool(bg_signals["is_compact_tailless_bg"])

    tsp_list, bp_myo_list, mtp_list = _score_myo_evidence(by_role, scores, evidence, thresholds)
    has_real_long_tmp = _score_sipho_and_tmp_evidence(
        by_role, tmp_analyses, tsp_list, bp_myo_list, mtp_list, is_n4_like, scores, evidence, thresholds
    )
    _score_podo_and_connector_evidence(
        proteins, by_role, cp, tsp_list, bp_myo_list, mtp_list, n4_vrnap_prots,
        is_n4_like, is_compact_tailless_bg, scores, evidence
    )
    has_long_tail_hallmark = bool(tsp_list or mtp_list or has_real_long_tmp)
    _score_negative_podo_and_non_tailed(
        proteins, by_role, mm, cp, comp, ptf_clusters, est_bp, has_long_tail_hallmark,
        bg_signals, scores, evidence, warnings, thresholds, comp_thresholds
    )
    best_code, conf, basis, lifestyle = _resolve_decision_and_warnings(
        proteins, tmp_analyses, mm, ptf_clusters, tsp_list, nt_list,
        scores, evidence, warnings, genetic_code_used, genetic_code_auto_selected,
        sparse_rescued_orfs, thresholds
    )
    est_len_nm, est_range_nm = _resolve_tail_length_estimate(best_code, tmp_analyses, warnings)
    label_cn, feature_tag = MORPHOTYPE_META[best_code]

    return MorphotypePrediction(
        morphotype_code=best_code,  # type: ignore[arg-type]
        morphotype_label_cn=label_cn,
        tail_feature_tag=feature_tag,
        confidence=conf,
        class_scores={k: round(v, 2) for k, v in scores.items()},
        decision_basis=basis,
        lifestyle_hint=lifestyle,  # type: ignore[arg-type]
        estimated_tail_length_nm=est_len_nm,
        estimated_tail_range_nm=est_range_nm,
        evidence_chain=sorted(evidence, key=lambda x: -x.weight),
        warnings=warnings,
    )
