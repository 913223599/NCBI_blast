# -*- coding: utf-8 -*-
"""
噬菌体基因组完整度门控与稀疏注释诊断模块 (CompletenessGate)

职责：
1. 识别基因组末端直接重复 (DTR) 与末端反向重复 (ITR)；
2. 诊断稀疏或半截残缺的 GenBank 注释，触发后续 Pyrodigal 间隙回补；
3. 评估头部包装核心完备度与长/肌尾截断残骸特征，门控 Podoviridae-like 负向排他规则，
   防止截断片段与不完整嵌合前噬菌体误判为短尾噬菌体。
"""
from __future__ import annotations

from typing import List, Optional, Sequence, Tuple

from .types import (
    CompletenessAssessment,
    ConnectorProfile,
    StructuralModuleMatrix,
    StructureProteinItem,
    TailFinderCluster,
    TmpAnalysisItem,
)

_LONG_TAIL_TRUNK_OR_CONNECTOR_ROLES = frozenset({
    "TSP",
    "TTP",
    "MTP",
    "TAP",
    "DIT",
    "BASEPLATE_MYO",
    "CONN_AD1",
    "CONN_HC1",
    "CONN_NECK1",
    "CONN_TAIL_TERM",
})
_PODO_POSITIVE_ROLES = frozenset({"TTPA_B", "INTERNAL_VIRION", "TAIL_NEEDLE", "COLLAR_PODO"})
_REV_COMP = str.maketrans("ACGTUN", "TGCAAN")


def _rev_comp(seq: str) -> str:
    return seq.translate(_REV_COMP)[::-1]


def detect_terminal_repeats(dna_seq: str) -> Tuple[bool, int, bool]:
    """
    检测噬菌体基因组 5' 与 3' 端是否存在直接末端重复 (DTR) 或反向末端重复 (ITR)。
    返回: (has_dtr, dtr_length_bp, has_itr)
    """
    seq = (dna_seq or "").strip().upper()
    n = len(seq)
    if n < 2500:
        return False, 0, False

    has_dtr = False
    dtr_len = 0
    has_itr = False

    # 1. DTR 检测：在 3' 端末尾搜索与 5' 端首部匹配的 20-mer 种子并向外延展校验
    seed_len = 20
    edge_limit = min(15_000, n // 3)
    if edge_limit >= 60:
        prefix = seq[:edge_limit]
        suffix = seq[n - edge_limit :]
        head_seed = prefix[:seed_len]
        if "N" not in head_seed:
            pos = suffix.rfind(head_seed)
            if pos >= 0:
                cand_len = edge_limit - pos
                if 20 <= cand_len <= edge_limit:
                    a = prefix[:cand_len]
                    b = suffix[pos:]
                    matches = sum(1 for x, y in zip(a, b) if x == y)
                    if (matches / cand_len) >= 0.95:
                        has_dtr = True
                        dtr_len = cand_len

        if not has_dtr:
            tail_seed = suffix[-seed_len:]
            if "N" not in tail_seed:
                pos_l = prefix.find(tail_seed)
                if pos_l >= 0:
                    cand_len = pos_l + seed_len
                    if 20 <= cand_len <= edge_limit:
                        a = prefix[:cand_len]
                        b = suffix[edge_limit - cand_len :]
                        matches = sum(1 for x, y in zip(a, b) if x == y)
                        if (matches / cand_len) >= 0.95:
                            has_dtr = True
                            dtr_len = cand_len

    # 2. ITR 检测：检查首尾 200 bp 是否呈反向互补对称
    itr_win = min(200, n // 4)
    if itr_win >= 24:
        p5 = seq[:itr_win]
        rc3 = _rev_comp(seq[n - itr_win :])
        itr_seed_len = 18
        for start in range(0, min(30, itr_win - itr_seed_len + 1)):
            seed = p5[start : start + itr_seed_len]
            if "N" in seed:
                continue
            if rc3.startswith(seed) or seed in rc3[:40]:
                has_itr = True
                break

    return has_dtr, dtr_len, has_itr


def assess_sparse_gbk_annotation(
    length_bp: int,
    proteins: Sequence[StructureProteinItem],
) -> Tuple[bool, float, int]:
    """
    评估已有 GenBank 注释是否存在严重稀疏遗漏，触发 Pyrodigal 间隙回补。
    返回: (is_sparse, coding_coverage, max_gap_bp)
    """
    if length_bp < 8000:
        return False, 1.0, 0
    if not proteins:
        return True, 0.0, length_bp

    intervals = sorted(
        (max(1, min(p.start, p.end)), min(length_bp, max(p.start, p.end)))
        for p in proteins
        if p.end >= p.start
    )
    if not intervals:
        return True, 0.0, length_bp

    merged: List[Tuple[int, int]] = []
    for s, e in intervals:
        if not merged or s > merged[-1][1] + 1:
            merged.append((s, e))
        else:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))

    covered_bp = sum(e - s + 1 for s, e in merged)
    coding_cov = covered_bp / max(1, length_bp)

    gaps: List[int] = [merged[0][0] - 1, max(0, length_bp - merged[-1][1])]
    for i in range(1, len(merged)):
        gaps.append(max(0, merged[i][0] - merged[i - 1][1] - 1))
    max_gap_bp = max(gaps, default=0)

    is_sparse = (coding_cov < 0.48) or (coding_cov < 0.68 and max_gap_bp >= 14_000)
    return is_sparse, round(coding_cov, 4), max_gap_bp


def evaluate_contig_completeness(
    *,
    dna_seq: str = "",
    length_bp: int = 0,
    proteins: Sequence[StructureProteinItem],
    module_matrix: StructuralModuleMatrix,
    connector_profile: ConnectorProfile,
    tmp_analyses: Sequence[TmpAnalysisItem],
    ptf_clusters: Optional[Sequence[TailFinderCluster]] = None,
    sparse_rescued_orfs: int = 0,
) -> CompletenessAssessment:
    """
    综合序列末端重复与结构模块完备性评估当前 Contig 的完整度状态，
    并对 Podoviridae-like 的负向排他判定执行安全门控。
    """
    eff_bp = max(length_bp, len(dna_seq or ""), max((p.end for p in proteins), default=0))
    has_dtr, dtr_len, has_itr = detect_terminal_repeats(dna_seq) if dna_seq else (False, 0, False)

    roles = {p.structural_role for p in proteins}
    has_mcp = "MCP" in roles
    has_portal = "PORTAL" in roles
    has_full_terl = any(p.structural_role == "TERL" and p.length_aa >= 300 for p in proteins)
    has_conn_general = "CONN_GENERAL" in roles
    has_intact_head_packaging = bool(has_mcp and (has_portal or has_full_terl or has_conn_general))

    has_podo_pfam_t7 = any(
        p.structural_role != "TTPA_B"
        and (p.ptf_pfam == "PF03906" or "phage_t7_tail" in (p.ptf_pfam_desc or "").lower())
        and p.ptf_tail_prob >= 0.70
        for p in proteins
    )
    has_podo_positive = bool(
        (roles & _PODO_POSITIVE_ROLES)
        or connector_profile.type_hint == "Type_3_Podoviridae"
        or has_podo_pfam_t7
    )

    valid_long_tmps = [
        t
        for t in tmp_analyses
        if t.evidence_kind in ("confirmed_tmp", "merged_split_tmp", "gp29_tail_length", "putative_syntenic_tmp")
        and t.length_aa >= 350
    ]
    has_long_tail_core = bool({"TSP", "MTP"} & roles) or bool(valid_long_tmps)

    has_type1_conn_markers = connector_profile.type_hint == "Type_1_Sipho_Myo" or bool(
        roles & {"CONN_AD1", "CONN_HC1", "CONN_NECK1", "CONN_TAIL_TERM"}
    )
    has_long_tail_remnants = bool(roles & {"TTP", "TAP", "BASEPLATE_MYO"})

    has_truncated_long_tail_remnant = bool(
        (not has_long_tail_core)
        and (not has_podo_positive)
        and (has_type1_conn_markers or has_long_tail_remnants)
    )

    reasons: List[str] = []
    if has_dtr:
        reasons.append(f"检出末端直接重复 DTR ({dtr_len} bp)")
    elif has_itr:
        reasons.append("检出末端反向重复 ITR")

    if sparse_rescued_orfs > 0:
        reasons.append(f"原始注释过于稀疏，已自动回补 {sparse_rescued_orfs} 个间隙预测 ORF")

    if has_truncated_long_tail_remnant:
        reasons.append(
            "检测到长/肌尾特异连接器或尾管组装组件但缺失尾主干与全长卷尺蛋白，提示尾部区域发生截断，已禁止负向推断为短尾"
        )
    elif not has_intact_head_packaging and module_matrix.head_packaging_count > 0:
        reasons.append("头部包装模块不完整（缺少 MCP 或核心 Portal/完整 TerL），已禁用负向短尾排他推断")

    allow_negative_podo_inference = bool(
        has_intact_head_packaging
        and not has_truncated_long_tail_remnant
        and (eff_bp >= 25_000 or has_dtr or has_itr)
    )

    has_tail_signal = bool(has_long_tail_core or has_podo_positive or (ptf_clusters and len(ptf_clusters) >= 1))
    has_non_tailed_core = bool(roles & {"NON_TAILED_MARKER"})

    if has_truncated_long_tail_remnant:
        status = "partial_or_truncated"
        score = 0.45
    elif (has_dtr or has_itr) and (has_intact_head_packaging or has_tail_signal or has_non_tailed_core):
        status = "complete"
        score = 1.0
    elif (has_intact_head_packaging and (has_tail_signal or allow_negative_podo_inference)) or (
        has_non_tailed_core and eff_bp >= 2500
    ):
        status = "high_quality"
        score = 0.90
    elif has_intact_head_packaging or has_tail_signal or module_matrix.head_packaging_count >= 2:
        status = "partial_or_truncated"
        score = 0.50
    else:
        status = "incomplete"
        score = 0.20

    return CompletenessAssessment(
        status=status,  # type: ignore[arg-type]
        score=score,
        has_dtr=has_dtr,
        dtr_length_bp=dtr_len,
        has_itr=has_itr,
        has_intact_head_packaging=has_intact_head_packaging,
        has_truncated_long_tail_remnant=has_truncated_long_tail_remnant,
        allow_negative_podo_inference=allow_negative_podo_inference,
        sparse_annotation_rescued_orfs=sparse_rescued_orfs,
        reasons=reasons,
    )
