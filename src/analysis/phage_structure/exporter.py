# -*- coding: utf-8 -*-
"""
噬菌体结构与尾部形态预测结果导出器

职责：
1. 将预测结果原子性落盘为 structure_report.json、morphotype_summary.tsv、
   structure_features.tsv、tmp_analysis.tsv 四种标准交付物；
2. 生成携带 PHROG ID、结构角色分组与 TMP polyX/TR 定量标注的标准 GenBank 文件 (annotated_structure.gbk)，
   支持直接在工作台 GenomeViewer 中渲染展示。
"""
from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

from Bio import SeqIO
from Bio.Seq import Seq
from Bio.SeqFeature import FeatureLocation, SeqFeature
from Bio.SeqRecord import SeqRecord

from .types import PhageStructureResult


def _atomic_write_text(dst: Path, content: str) -> None:
    tmp = dst.with_suffix(dst.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(dst)


def export_structure_artifacts(
    result: PhageStructureResult,
    contig_seqs: Dict[str, str],
    out_dir: Path,
) -> Dict[str, str]:
    """将完整预测数据与多格式结构分析表导出到任务目录。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    files: Dict[str, str] = {}

    # 1. JSON 全量报告（供详情页秒开及结果持久化）
    report_json = out_dir / "structure_report.json"
    _atomic_write_text(report_json, json.dumps(result.model_dump(), ensure_ascii=False, indent=2))
    files["json"] = str(report_json)

    # 2. 形态预测汇总 TSV
    morph_tsv = out_dir / "morphotype_summary.tsv"
    with morph_tsv.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, delimiter="\t")
        w.writerow([
            "contig_id", "length_bp", "gc_percent", "total_orfs", "hmm_matched_orfs",
            "morphotype_code", "morphotype_label", "confidence", "lifestyle_hint",
            "connector_type", "estimated_tail_length_nm", "decision_basis",
        ])
        for c in result.contigs:
            w.writerow([
                c.contig_id,
                c.length_bp,
                c.gc_percent,
                c.total_orfs,
                c.hmm_matched_orfs,
                c.prediction.morphotype_code,
                c.prediction.morphotype_label_cn,
                c.prediction.confidence,
                c.prediction.lifestyle_hint,
                c.connector_profile.type_hint,
                c.prediction.estimated_tail_length_nm if c.prediction.estimated_tail_length_nm is not None else "",
                c.prediction.decision_basis,
            ])
    files["summary_tsv"] = str(morph_tsv)

    # 3. 识别结构蛋白明细 TSV
    feat_tsv = out_dir / "structure_features.tsv"
    with feat_tsv.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, delimiter="\t")
        w.writerow([
            "contig_id", "locus_tag", "start_bp", "end_bp", "strand", "length_aa",
            "structural_role", "role_label_cn", "phrog_id", "phrog_category",
            "hmm_score", "hmm_evalue", "evidence_source",
            "ptf_is_tail", "ptf_tail_prob", "ptf_pfam", "product",
        ])
        for c in result.contigs:
            for p in c.structural_proteins:
                if p.structural_role == "OTHER" and not p.phrog_id and not p.ptf_is_tail:
                    continue
                w.writerow([
                    p.contig_id, p.locus_tag, p.start, p.end, p.strand, p.length_aa,
                    p.structural_role, p.role_label_cn, p.phrog_id, p.phrog_category,
                    p.hmm_score, f"{p.hmm_evalue:.2e}", p.evidence_source,
                    1 if p.ptf_is_tail else 0, p.ptf_tail_prob, p.ptf_pfam, p.product,
                ])
    files["features_tsv"] = str(feat_tsv)

    # 4. TMP 分子标尺量化 TSV
    tmp_tsv = out_dir / "tmp_analysis.tsv"
    with tmp_tsv.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, delimiter="\t")
        w.writerow([
            "contig_id", "locus_tag", "evidence_kind", "length_aa",
            "est_tail_length_nm", "est_range_nm",
            "polyx_count", "polyx_total_aa", "polyx_fraction_pct",
            "tr_count", "tr_total_aa", "tr_fraction_pct", "max_tr_period_aa",
            "interpretation",
        ])
        for c in result.contigs:
            for t in c.tmp_analyses:
                rng = "-".join(str(x) for x in t.est_tail_range_nm)
                w.writerow([
                    t.contig_id, t.locus_tag, t.evidence_kind, t.length_aa,
                    t.est_tail_length_nm, rng,
                    t.polyx_count, t.polyx_total_aa, t.polyx_fraction_pct,
                    t.tr_count, t.tr_total_aa, t.tr_fraction_pct, t.max_tr_period_aa,
                    t.interpretation,
                ])
    files["tmp_tsv"] = str(tmp_tsv)

    # 5. 生成可用于 GenomeViewer 交互浏览的结构注释 GenBank
    gbk_path = out_dir / "annotated_structure.gbk"
    records = []
    date_tag = datetime.now().strftime("%d-%b-%Y").upper()
    for c in result.contigs:
        dna = contig_seqs.get(c.contig_id, "")
        if not dna:
            continue
        safe_id = c.contig_id[:16]
        rec = SeqRecord(
            Seq(dna),
            id=safe_id,
            name=safe_id,
            description=f"{result.task_name} | {c.prediction.morphotype_code} (conf={c.prediction.confidence:.2f})",
            annotations={
                "molecule_type": "DNA",
                "topology": "linear",
                "data_file_division": "PHG",
                "date": date_tag,
            },
        )
        rec.features.append(
            SeqFeature(
                FeatureLocation(0, len(dna)),
                type="source",
                qualifiers={"organism": [result.task_name], "note": [c.prediction.decision_basis]},
            )
        )
        tmp_by_lt = {t.locus_tag: t for t in c.tmp_analyses}
        for p in c.structural_proteins:
            sb = max(0, p.start - 1)
            eb = min(len(dna), p.end)
            if eb <= sb:
                continue
            strand = 1 if p.strand == "+" else -1
            note_parts = [f"StructuralRole={p.structural_role} ({p.role_label_cn})"]
            if p.phrog_id:
                note_parts.append(f"PHROG={p.phrog_id} (score={p.hmm_score}, E={p.hmm_evalue:.2e})")
            if p.locus_tag in tmp_by_lt:
                ti = tmp_by_lt[p.locus_tag]
                note_parts.append(
                    f"TMP EstLength={ti.est_tail_length_nm}nm; polyX={ti.polyx_total_aa}aa; TR={ti.tr_total_aa}aa"
                )
            quals: Dict[str, Any] = {
                "locus_tag": [p.locus_tag],
                "product": [p.product],
                "note": ["; ".join(note_parts)],
            }
            if p.phrog_category:
                quals["function"] = [p.phrog_category]
            if p.translation:
                quals["translation"] = [p.translation]
            rec.features.append(SeqFeature(FeatureLocation(sb, eb, strand=strand), type="CDS", qualifiers=quals))
        records.append(rec)

    if records:
        with gbk_path.open("w", encoding="utf-8") as fh:
            SeqIO.write(records, fh, "genbank")
        files["gbk"] = str(gbk_path)

    return files
