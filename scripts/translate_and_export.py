# -*- coding: utf-8 -*-
"""Translate BLAST CSV reports and generate summary CSV."""
from __future__ import annotations

import argparse
import csv
import os
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def parse_args() -> argparse.Namespace:
    default_base = Path(
        os.environ.get("SANGON_16S_BASE_DIR", str(PROJECT_ROOT / "results" / "sangon_16s"))
    )
    parser = argparse.ArgumentParser(description="翻译 BLAST CSV 报告并输出 16S 鉴定汇总表")
    parser.add_argument("--task-id", required=True, help="results/blast 下的任务 ID")
    parser.add_argument("--reports-dir", type=Path, default=None, help="自定义 CSV 报告目录")
    parser.add_argument("--out-dir", type=Path, default=None, help="输出目录")
    parser.add_argument("--base-dir", type=Path, default=default_base, help="默认输出根目录")
    return parser.parse_args()


def main() -> None:
    os.chdir(PROJECT_ROOT)
    args = parse_args()
    reports_dir = (
        args.reports_dir.resolve()
        if args.reports_dir
        else PROJECT_ROOT / "results" / "blast" / args.task_id / "reports"
    )
    out_dir = (
        args.out_dir.resolve()
        if args.out_dir
        else args.base_dir.resolve() / args.task_id / "BLAST结果"
    )
    out_dir.mkdir(parents=True, exist_ok=True)

    from src.utils.translation.blast_result_translator import get_blast_result_translator

    translator = get_blast_result_translator()
    summary_rows = []
    csv_files = sorted(reports_dir.glob("*.csv"))

    for csv_path in csv_files:
        m = re.search(r"_-(\d+)__(\d+)_ORDER_ITEM", csv_path.name)
        if m:
            sample_num = f"-{m.group(1)}"
            order_item = m.group(2)
        else:
            sample_num = csv_path.stem
            order_item = ""

        with open(csv_path, "r", encoding="utf-8-sig") as f:
            rows = list(csv.reader(f))

        if len(rows) <= 1:
            summary_rows.append(
                {
                    "sample": sample_num,
                    "order_item": order_item,
                    "species_en": "(无匹配)",
                    "species_cn": "",
                    "genus_en": "",
                    "genus_cn": "",
                    "strain": "",
                    "identity": "",
                    "evalue": "",
                    "accession": "",
                }
            )
            continue

        best = rows[1]
        species_en = best[3] if len(best) > 3 else ""
        genus_en = best[4] if len(best) > 4 else ""
        strain = best[5] if len(best) > 5 else ""
        accession = best[2] if len(best) > 2 else ""
        identity = best[13] if len(best) > 13 else ""
        evalue = best[10] if len(best) > 10 else ""

        summary_rows.append(
            {
                "sample": sample_num,
                "order_item": order_item,
                "species_en": species_en,
                "species_cn": translator.translate_species(species_en),
                "genus_en": genus_en,
                "genus_cn": translator.translate_genus(genus_en),
                "strain": strain,
                "identity": identity,
                "evalue": evalue,
                "accession": accession,
            }
        )

    summary_path = out_dir / "16S鉴定汇总.csv"
    fieldnames = [
        "sample",
        "order_item",
        "species_en",
        "species_cn",
        "genus_en",
        "genus_cn",
        "strain",
        "identity",
        "evalue",
        "accession",
    ]
    with open(summary_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(summary_rows)

    print(f"\nSummary written: {summary_path}")
    print(f"Total samples: {len(summary_rows)}")
    print(f"With hits: {sum(1 for r in summary_rows if r['species_en'] != '(无匹配)')}")
    print(f"No hits: {sum(1 for r in summary_rows if r['species_en'] == '(无匹配)')}")


if __name__ == "__main__":
    main()
