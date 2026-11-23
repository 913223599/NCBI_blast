# -*- coding: utf-8 -*-
"""
移码拆分卷尺蛋白 (Frameshifted / Split TMP) 自动检测与合并器 (TmpSplitMerger)

职责：
1. 在基因组物理坐标上识别因程序性核糖体移码或参考注释分裂产生的相邻同链 TMP N端+C端片段
   (典型代表如 Pseudomonas 转座噬菌体 D3112 的 PF06791 + PF09718 重叠分裂构型)；
2. 严格排除尾组装伴侣 (TAP / gpG-gpGT)、非尺结构蛋白及无关相邻蛋白的误合并；
3. 按物理跨度精确扣除重叠密码子并拼接氨基酸序列，消除 FASTA 与 GBK 间下游起始位点偏差。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import FrozenSet, List, Sequence, Set

from .thresholds import DEFAULT_THRESHOLDS, SplitTmpThresholds
from .types import StructureProteinItem

_DIRECT_TMP_PFAMS: FrozenSet[str] = frozenset({
    "PF06791",  # TMP_2
    "PF09718",  # Tape_meas_lam_C
    "PF06120",  # Phage_HK97_TLTM
    "PF10145",  # PhageMin_Tail
    "PF12789",  # PTR
})

_EXCLUDED_ROLES: FrozenSet[str] = frozenset({
    "TAP",
    "MTP",
    "TSP",
    "TTP",
    "DIT",
    "BASEPLATE_MYO",
    "TAIL_FIBER_RBP",
    "FIBRITIN_COLLAR",
    "TAIL_OTHER",
    "TTPA_B",
    "INTERNAL_VIRION",
    "TAIL_NEEDLE",
    "COLLAR_PODO",
    "MCP",
    "PORTAL",
    "TERL",
    "TERS",
    "HEAD_SCAFFOLD_PROTEASE",
    "CONN_AD1",
    "CONN_AD2",
    "CONN_AD3",
    "CONN_HC1",
    "CONN_HC2",
    "CONN_HC3",
    "CONN_NECK1",
    "CONN_TAIL_TERM",
    "CONN_GENERAL",
    "INTEGRASE",
    "LYSIS",
    "NON_TAIL_ENZYME",
    "T6SS_CONFOUNDER",
    "NON_TAILED_MARKER",
})


@dataclass(frozen=True)
class MergedSplitTmpCandidate:
    """被识别并物理合并后的移码拆分卷尺蛋白对象与原始分裂位点列表。"""

    protein: StructureProteinItem
    source_loci: List[str]


def _collect_pfams(protein: StructureProteinItem) -> Set[str]:
    out: Set[str] = set()
    if protein.ptf_pfam:
        out.add(protein.ptf_pfam.strip().upper())
    for pf in (protein.ptf_all_pfams or []):
        if pf:
            out.add(str(pf).strip().upper())
    return out


def _is_verified_tmp_fragment(
    protein: StructureProteinItem,
    pfams: Set[str],
    thresholds: SplitTmpThresholds = DEFAULT_THRESHOLDS.split_tmp,
) -> bool:
    if protein.structural_role in _EXCLUDED_ROLES:
        return False
    if not (thresholds.frag_min_aa <= protein.length_aa <= thresholds.frag_max_aa):
        return False
    if pfams & _DIRECT_TMP_PFAMS:
        return True
    return (
        protein.structural_role == "TMP"
        and protein.evidence_source in ("pyhmmer_phrog", "phold_3d")
        and protein.hmm_score >= thresholds.verified_hmm_min_score
    )


def _merge_two_fragments(p_left: StructureProteinItem, p_right: StructureProteinItem) -> MergedSplitTmpCandidate:
    """按基因组物理跨度合并两个相邻同链分裂 TMP 片段（兼容正链与负链转录方向）。"""
    if p_left.strand == "+":
        p_5p, p_3p = p_left, p_right
    else:
        p_5p, p_3p = p_right, p_left

    merged_start = min(p_left.start, p_right.start)
    merged_end = max(p_left.end, p_right.end)
    span_bp = merged_end - merged_start + 1
    merged_aa_len = max(1, (span_bp - 3) // 3)

    seq_5p = (p_5p.translation or "").strip().upper().rstrip("*")
    seq_3p = (p_3p.translation or "").strip().upper().rstrip("*")
    if seq_5p and seq_3p:
        total_raw = len(seq_5p) + len(seq_3p)
        if total_raw >= merged_aa_len:
            overlap_aa = total_raw - merged_aa_len
            merged_seq = (seq_5p + seq_3p[overlap_aa:])[:merged_aa_len]
        else:
            pad_len = merged_aa_len - total_raw
            merged_seq = seq_5p + ("X" * pad_len) + seq_3p
    else:
        merged_seq = (seq_5p or seq_3p)[:merged_aa_len]

    pf_union = sorted(_collect_pfams(p_left) | _collect_pfams(p_right))
    merged_pfam = pf_union[0] if pf_union else (p_5p.ptf_pfam or p_3p.ptf_pfam)
    merged_pf_desc = ", ".join(
        d for d in (p_5p.ptf_pfam_desc, p_3p.ptf_pfam_desc) if d
    )

    merged_item = StructureProteinItem(
        locus_tag=f"{p_5p.locus_tag}+{p_3p.locus_tag}",
        contig_id=p_5p.contig_id,
        start=merged_start,
        end=merged_end,
        strand=p_5p.strand,
        length_aa=merged_aa_len,
        product=p_5p.product or "tail length tape measure protein (frameshift merged)",
        raw_product=f"{p_5p.raw_product or p_5p.product} + {p_3p.raw_product or p_3p.product}".strip(" +"),
        phrog_id=p_5p.phrog_id or p_3p.phrog_id,
        phrog_category=p_5p.phrog_category or p_3p.phrog_category,
        structural_role="TMP",
        role_label_cn=p_5p.role_label_cn or "尾部卷尺蛋白 (TMP)",
        hmm_score=round(max(p_5p.hmm_score, p_3p.hmm_score), 2),
        hmm_evalue=min(p_5p.hmm_evalue, p_3p.hmm_evalue),
        evidence_source=p_5p.evidence_source if p_5p.hmm_score >= p_3p.hmm_score else p_3p.evidence_source,
        ptf_is_tail=bool(p_5p.ptf_is_tail or p_3p.ptf_is_tail),
        ptf_tail_prob=round(max(p_5p.ptf_tail_prob, p_3p.ptf_tail_prob), 4),
        ptf_pfam=merged_pfam,
        ptf_pfam_desc=merged_pf_desc,
        ptf_all_pfams=pf_union,
        translation=merged_seq,
    )
    return MergedSplitTmpCandidate(
        protein=merged_item,
        source_loci=[p_5p.locus_tag, p_3p.locus_tag],
    )


def find_and_merge_split_tmps(
    sorted_prots: Sequence[StructureProteinItem],
    *,
    thresholds: SplitTmpThresholds = DEFAULT_THRESHOLDS.split_tmp,
) -> List[MergedSplitTmpCandidate]:
    """
    扫描按坐标排序的 Contig 蛋白列表，识别并合并相邻移码分裂的 TMP 片段。
    """
    prots = sorted(sorted_prots, key=lambda x: x.start)
    if len(prots) < 2:
        return []

    merged_candidates: List[MergedSplitTmpCandidate] = []
    consumed_loci: Set[str] = set()

    for idx in range(len(prots) - 1):
        p1 = prots[idx]
        p2 = prots[idx + 1]
        if p1.locus_tag in consumed_loci or p2.locus_tag in consumed_loci:
            continue
        if p1.strand != p2.strand:
            continue

        gap_bp = p2.start - p1.end - 1
        if not (thresholds.min_gap_bp <= gap_bp <= thresholds.max_gap_bp):
            continue

        pf1 = _collect_pfams(p1)
        pf2 = _collect_pfams(p2)
        if not (_is_verified_tmp_fragment(p1, pf1, thresholds) and _is_verified_tmp_fragment(p2, pf2, thresholds)):
            continue

        direct1 = pf1 & _DIRECT_TMP_PFAMS
        direct2 = pf2 & _DIRECT_TMP_PFAMS
        # 至少一侧具备权威直接 TMP 结构域；若两侧均带直接结构域，不能仅因各自重复同一单一小域误合并
        if not (direct1 or direct2):
            continue
        if direct1 and direct2 and direct1 == direct2 and len(direct1) == 1 and "PF12789" not in direct1:
            if not (
                p1.structural_role == "TMP"
                and p2.structural_role == "TMP"
                and p1.hmm_score >= thresholds.same_pfam_high_hmm_score
                and p2.hmm_score >= thresholds.same_pfam_high_hmm_score
            ):
                continue

        span_bp = max(p1.end, p2.end) - min(p1.start, p2.start) + 1
        merged_aa_len = (span_bp - 3) // 3
        if not (thresholds.merged_min_aa <= merged_aa_len <= thresholds.merged_max_aa):
            continue

        merged = _merge_two_fragments(p1, p2)
        merged_candidates.append(merged)
        consumed_loci.add(p1.locus_tag)
        consumed_loci.add(p2.locus_tag)

    return merged_candidates
