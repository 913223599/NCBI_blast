# -*- coding: utf-8 -*-
"""
UnifiedPhageModel 标准化生信产物导出模块。

导出文件（全部采用 UTF-8 编码）：
1. regions.tsv       : 区段坐标、置信度、完整度与功能模块汇总表；
2. regions.gff3      : 兼容主流生信可视化的标准 1-based inclusive GFF3 注释；
3. prophages.fna     : 按区段区间切分提取的 DNA 序列（流式按需提取，不囤积全基因组）；
4. scan_summary.json : 全量扫描规模、路由跳过统计、分段耗时与可选抑制候选审计摘要。
"""
from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.parse import quote

from ..benchmark.metrics import PredictedRegion
from ..data.feature_dataset import iter_fasta


def _write_wrapped_fasta_record(fh: Any, header: str, seq: str, width: int = 80) -> None:
    fh.write(f">{header}\n")
    for idx in range(0, len(seq), width):
        fh.write(seq[idx : idx + width])
        fh.write("\n")


def _export_regions_tsv(
    tsv_path: Path,
    regions: Sequence[PredictedRegion],
    region_annotations: Dict[str, Dict[str, Any]],
) -> None:
    fieldnames = [
        "contig_id",
        "start_bp",
        "end_bp",
        "length_bp",
        "peak_score",
        "mean_score",
        "window_count",
        "n_orfs",
        "mean_phage_prob",
        "max_p9_defense_prob",
        "r2_core_completeness_sum",
        "r2_core_active_count",
        "completeness_class",
        "active_modules",
    ]
    tmp_path = tsv_path.with_name(f".{tsv_path.name}.tmp")
    with tmp_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames, delimiter="\t")
        writer.writeheader()
        for reg in regions:
            key = f"{reg.contig_id}:{reg.start_bp}-{reg.end_bp}"
            ann = region_annotations.get(key, {})
            mods = ann.get("active_modules") or []
            writer.writerow(
                {
                    "contig_id": reg.contig_id,
                    "start_bp": int(reg.start_bp),
                    "end_bp": int(reg.end_bp),
                    "length_bp": int(reg.end_bp - reg.start_bp),
                    "peak_score": round(float(reg.peak_score), 4),
                    "mean_score": round(float(reg.mean_score), 4),
                    "window_count": int(reg.window_count),
                    "n_orfs": int(ann.get("n_orfs", 0)),
                    "mean_phage_prob": ann.get("mean_phage_prob", ""),
                    "max_p9_defense_prob": ann.get("max_p9_defense_prob", ""),
                    "r2_core_completeness_sum": ann.get("r2_core_completeness_sum", ""),
                    "r2_core_active_count": ann.get("r2_core_active_count", ""),
                    "completeness_class": ann.get("completeness_class", ""),
                    "active_modules": ",".join(str(m) for m in mods),
                }
            )
    tmp_path.replace(tsv_path)


def _export_regions_gff3(
    gff_path: Path,
    regions: Sequence[PredictedRegion],
    region_annotations: Dict[str, Dict[str, Any]],
) -> None:
    tmp_path = gff_path.with_name(f".{gff_path.name}.tmp")
    with tmp_path.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write("##gff-version 3\n")
        for idx, reg in enumerate(regions, start=1):
            key = f"{reg.contig_id}:{reg.start_bp}-{reg.end_bp}"
            ann = region_annotations.get(key, {})
            gff_start = max(1, int(reg.start_bp) + 1)
            gff_end = max(gff_start, int(reg.end_bp))
            mods = ",".join(str(m) for m in (ann.get("active_modules") or []))
            attrs = [
                f"ID={quote(f'{reg.contig_id}_prophage_{idx}')}",
                f"peak_score={float(reg.peak_score):.4f}",
                f"mean_score={float(reg.mean_score):.4f}",
            ]
            if ann:
                attrs.append(f"completeness={quote(str(ann.get('completeness_class', '')))}")
                if "mean_phage_prob" in ann:
                    attrs.append(f"mean_phage_prob={float(ann['mean_phage_prob']):.4f}")
                if "r2_core_completeness_sum" in ann:
                    attrs.append(f"core_sum={float(ann['r2_core_completeness_sum']):.4f}")
                if mods:
                    attrs.append(f"modules={quote(mods)}")
            cols = [
                reg.contig_id,
                "UnifiedPhageModel",
                "prophage",
                str(gff_start),
                str(gff_end),
                f"{float(reg.peak_score):.4f}",
                ".",
                ".",
                ";".join(attrs),
            ]
            fh.write("\t".join(cols) + "\n")
    tmp_path.replace(gff_path)


def _export_prophage_fasta(
    fasta_out: Path,
    regions: Sequence[PredictedRegion],
    region_annotations: Dict[str, Dict[str, Any]],
    *,
    contig_seqs: Optional[Dict[str, str]] = None,
    source_fasta_path: Optional[Path] = None,
) -> None:
    by_cid: Dict[str, List[PredictedRegion]] = defaultdict(list)
    for reg in regions:
        by_cid[reg.contig_id].append(reg)

    tmp_path = fasta_out.with_name(f".{fasta_out.name}.tmp")
    with tmp_path.open("w", encoding="utf-8", newline="\n") as fh:
        if not by_cid:
            pass
        elif contig_seqs is not None:
            for reg in regions:
                seq = contig_seqs.get(reg.contig_id)
                if not seq:
                    continue
                sub = seq[max(0, int(reg.start_bp)) : max(0, int(reg.end_bp))]
                if not sub:
                    continue
                key = f"{reg.contig_id}:{reg.start_bp}-{reg.end_bp}"
                ann = region_annotations.get(key, {})
                cls = ann.get("completeness_class", "")
                header = f"{key} {cls}".strip()
                _write_wrapped_fasta_record(fh, header, sub)
        elif source_fasta_path is not None and Path(source_fasta_path).is_file():
            targets: Iterable[Tuple[str, str]] = iter_fasta(Path(source_fasta_path))
            for cid, seq in targets:
                regs = by_cid.get(cid)
                if not regs:
                    continue
                for reg in regs:
                    sub = seq[max(0, int(reg.start_bp)) : max(0, int(reg.end_bp))]
                    if not sub:
                        continue
                    key = f"{reg.contig_id}:{reg.start_bp}-{reg.end_bp}"
                    ann = region_annotations.get(key, {})
                    cls = ann.get("completeness_class", "")
                    header = f"{key} {cls}".strip()
                    _write_wrapped_fasta_record(fh, header, sub)
    tmp_path.replace(fasta_out)


def export_unified_scan_outputs(
    out_dir: Path,
    *,
    regions: Sequence[PredictedRegion],
    region_annotations: Dict[str, Dict[str, Any]],
    routing_stats: Optional[Dict[str, Any]] = None,
    timings_sec: Optional[Dict[str, float]] = None,
    total_bp: int = 0,
    total_windows: int = 0,
    contig_seqs: Optional[Dict[str, str]] = None,
    source_fasta_path: Optional[Path] = None,
    suppressed_candidates: Optional[Sequence[Dict[str, Any]]] = None,
) -> Dict[str, Path]:
    """将统一模型扫描结果导出为 TSV / GFF3 / FASTA / JSON 标准化生信产物。"""
    out_root = Path(out_dir)
    out_root.mkdir(parents=True, exist_ok=True)

    tsv_path = out_root / "regions.tsv"
    gff_path = out_root / "regions.gff3"
    fna_path = out_root / "prophages.fna"
    summary_path = out_root / "scan_summary.json"

    _export_regions_tsv(tsv_path, regions, region_annotations)
    _export_regions_gff3(gff_path, regions, region_annotations)
    _export_prophage_fasta(
        fna_path,
        regions,
        region_annotations,
        contig_seqs=contig_seqs,
        source_fasta_path=source_fasta_path,
    )

    summary_obj: Dict[str, Any] = {
        "total_bp": int(total_bp),
        "total_windows": int(total_windows),
        "region_count": len(regions),
        "routing_stats": dict(routing_stats or {}),
        "timings_sec": dict(timings_sec or {}),
        "suppressed_candidate_count": len(suppressed_candidates or ()),
    }
    if suppressed_candidates:
        summary_obj["suppressed_candidates_preview"] = list(suppressed_candidates[:50])
    tmp_sum = summary_path.with_name(f".{summary_path.name}.tmp")
    tmp_sum.write_text(json.dumps(summary_obj, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_sum.replace(summary_path)

    return {
        "tsv": tsv_path,
        "gff3": gff_path,
        "fasta": fna_path,
        "summary": summary_path,
    }
