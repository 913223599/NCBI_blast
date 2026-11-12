# -*- coding: utf-8 -*-
"""
生工 16S 订单目录状态巡检与 11 列鉴定结果 CSV 导出服务
"""
import csv
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from .schemas import SANGON_CSV_HEADERS
from ...utils.blast_utils import parse_blast_csv, select_consensus_hit
from ....utils.translation.biology_translator import get_global_biology_translator

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent


def inspect_sangon_order_dir(order_dir: Path, project_root: Path = PROJECT_ROOT) -> Dict[str, Any]:
    """解析单个生工 16S 订单目录状态"""
    zip_dir = order_dir / "原始压缩包"
    raw_dir = order_dir / "原始数据"
    res_dir = order_dir / "BLAST结果"

    zips = sorted(zip_dir.glob("*.zip")) if zip_dir.exists() else []
    consensus_fastas: List[Path] = []
    ab1_count = 0
    total_raw_files = 0

    if raw_dir.exists():
        for p in raw_dir.rglob("*"):
            if p.is_file():
                total_raw_files += 1
                if p.name.endswith(".1.fasta") and "haplotype" not in p.name.lower():
                    consensus_fastas.append(p)
                elif p.suffix.lower() == ".ab1":
                    ab1_count += 1

    csv_file = res_dir / "16S鉴定结果.csv"
    has_result_csv = csv_file.exists()
    total_rows = 0
    with_hits = 0
    no_hits = 0
    csv_mtime = ""

    if has_result_csv:
        csv_mtime = datetime.fromtimestamp(csv_file.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
        try:
            with open(csv_file, "r", encoding="utf-8-sig", errors="replace") as f:
                reader = list(csv.reader(f))
                if len(reader) > 1:
                    for row in reader[1:]:
                        if not row:
                            continue
                        total_rows += 1
                        sp = row[3] if len(row) > 3 else ""
                        if "No Hits" in sp or "未找到匹配项" in sp:
                            no_hits += 1
                        else:
                            with_hits += 1
        except Exception:
            pass

    task_id = f"{order_dir.name}_16s"
    blast_reports_dir = project_root / "results" / "blast" / task_id / "reports"
    blast_csv_count = len(list(blast_reports_dir.glob("*.csv"))) if blast_reports_dir.exists() else 0

    parts = order_dir.name.split("_", 1)
    order_date = parts[0] if len(parts) > 1 else ""
    order_no = parts[1] if len(parts) > 1 else order_dir.name

    status = "pending"
    if has_result_csv and total_rows > 0:
        status = "completed"
    elif blast_csv_count > 0:
        status = "blasted"
    elif len(consensus_fastas) > 0:
        status = "extracted"
    elif len(zips) > 0:
        status = "downloaded"

    return {
        "dir_name": order_dir.name,
        "order_date": order_date,
        "order_no": order_no,
        "order_path": str(order_dir),
        "status": status,
        "zip_count": len(zips),
        "zip_files": [{"name": z.name, "size_kb": round(z.stat().st_size / 1024, 1)} for z in zips],
        "raw_file_count": total_raw_files,
        "consensus_fasta_count": len(consensus_fastas),
        "ab1_count": ab1_count,
        "blast_task_id": task_id,
        "blast_report_count": blast_csv_count,
        "has_result_csv": has_result_csv,
        "result_csv_path": str(csv_file) if has_result_csv else "",
        "result_mtime": csv_mtime,
        "total_samples": total_rows,
        "with_hits": with_hits,
        "no_hits": no_hits,
    }


def sangon_csv_sort_key(p: Path):
    m_num = re.search(r"_-(\d+)(?:_\d+)?\.csv$", p.name)
    if m_num:
        return (0, int(m_num.group(1)), p.name)
    return (1, 0, p.name)


def export_sangon_order_csv(task_id: str, out_dir: Path, project_root: Path = PROJECT_ROOT) -> Dict[str, int]:
    """解析 BLAST 报告并调用 BiologyTranslator 翻译导出 11 列 16S鉴定结果.csv"""
    out_dir.mkdir(parents=True, exist_ok=True)
    reports_dir = project_root / "results" / "blast" / task_id / "reports"
    csv_files = sorted(reports_dir.glob("*.csv"), key=sangon_csv_sort_key) if reports_dir.exists() else []

    all_species = set()
    results = []

    for csv_path in csv_files:
        m = re.search(r"_-(\d+)(?:_\d+)?\.csv$", csv_path.name)
        query_title = f"-{m.group(1)}" if m else csv_path.stem

        hits = parse_blast_csv(str(csv_path), limit=50)
        best = select_consensus_hit(hits) if hits else None
        if not best:
            results.append({
                "queryTitle": query_title,
                "speciesName": "未找到匹配项 (No Hits)",
                "genusStrain": "",
                "geneSource": "",
                "seqType": "",
                "identity": 0.0,
                "evalue": "-",
                "accession": "-",
                "hitTitle": "",
            })
            continue

        species = best.get("species", "Unknown")
        all_species.add(species)
        if best.get("consensusList"):
            for c in best["consensusList"]:
                if c.get("name"):
                    all_species.add(c["name"])

        results.append({
            "queryTitle": query_title,
            "speciesName": species,
            "genusStrain": f"{best.get('genus', '')} · {best.get('strain', '')}".strip(" ·"),
            "geneSource": best.get("gene_type", best.get("gene_source", "")),
            "seqType": best.get("seq_type", ""),
            "identity": float(str(best.get("similarity", "0")).replace("%", "")) if best.get("similarity") else 0.0,
            "evalue": str(best.get("evalue", "N/A")),
            "accession": best.get("acc", "N/A"),
            "hitTitle": best.get("title", ""),
        })

    translator = get_global_biology_translator()
    translated_map = translator.translate_batch(list(all_species), category="species") if all_species else {}

    def _format_row(hit: Dict[str, Any]) -> List[str]:
        full_trans = hit.get("translatedName") or ""
        main_trans = full_trans
        prob_trans = "-"

        full_orig = hit.get("speciesName") or ""
        main_orig = full_orig
        prob_orig = "-"

        if "(" in full_trans and "%" in full_trans:
            m_tr = re.match(r"^([^,(]+)\s*\(", full_trans)
            if m_tr:
                main_trans = m_tr.group(1).strip()
                prob_trans = full_trans

        if "(" in full_orig and "%" in full_orig:
            m_or = re.match(r"^([^,(]+)\s*\(", full_orig)
            if m_or:
                main_orig = m_or.group(1).strip()
                prob_orig = full_orig

        gene_seq = hit.get("geneSource", "")
        if hit.get("seqType"):
            gene_seq = f"{hit.get('geneSource', '')} ({hit.get('seqType', '')})"

        return [
            hit["queryTitle"],
            main_trans,
            prob_trans,
            main_orig,
            prob_orig,
            hit.get("genusStrain", ""),
            gene_seq,
            f"{hit.get('identity', 0.0):.1f}%",
            hit.get("evalue", "-"),
            hit.get("accession", "-"),
            hit.get("hitTitle", ""),
        ]

    for r in results:
        r["translatedName"] = translated_map.get(r["speciesName"])

    out_path = out_dir / "16S鉴定结果.csv"
    with open(out_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(SANGON_CSV_HEADERS)
        for r in results:
            writer.writerow(_format_row(r))

    with_hits = sum(1 for r in results if "No Hits" not in r["speciesName"])
    no_hits = sum(1 for r in results if "No Hits" in r["speciesName"])
    return {"total": len(results), "with_hits": with_hits, "no_hits": no_hits}

