# -*- coding: utf-8 -*-
"""
阶段 0 (T0.1) 纯盲测集 Suite E 里程碑基线运行脚本（只读评测，禁止用于规则调参）。

职责：
1. 调用 build_and_freeze_suite_e 验证/加载冻结清单（零重叠 + SHA256 一致）；
2. 执行 FASTA / GBK 双格式全量管线并分片落盘 JSONL 断点；
3. 按里程碑标签（如 m1_baseline）保存报告，记录准确指标与只读诊断摘要。
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.benchmark_phage_structure import evaluate_suite_a  # noqa: E402
from scripts.validate_external_phage_structure import (  # noqa: E402
    _evaluate_by_family,
    evaluate_dual_concordance,
    run_dual_mode_pipeline,
)
from scripts.validation_datasets import build_and_freeze_suite_e  # noqa: E402

RESULTS_DIR = PROJECT_ROOT / "results" / "benchmarks" / "phage_structure_suite_e"


def main() -> None:
    parser = argparse.ArgumentParser(description="T0.1 Suite E 冻结盲测集里程碑运行")
    parser.add_argument("--milestone", default="m1_baseline", help="里程碑标签")
    parser.add_argument("--fresh", action="store_true", help="清除该里程碑历史断点重跑")
    args = parser.parse_args()

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    tag = str(args.milestone).strip()
    if args.fresh:
        for p in RESULTS_DIR.glob(f"suite_e_{tag}_*_checkpoints.jsonl"):
            p.unlink(missing_ok=True)

    t0 = time.perf_counter()
    print(f"=== [Suite E | {tag}] 加载冻结盲测集并校对 SHA256 与零重叠 ===")
    entries = build_and_freeze_suite_e(local_per_class=50)
    print(
        f"已锁定 {len(entries)} 株冻结基因组 "
        f"(外部 post-2025/08={sum(1 for e in entries if e['origin'] == 'ncbi_post_202508')}, "
        f"本地={sum(1 for e in entries if e['origin'] == 'local_unseen_pool')})"
    )

    fa_rows: List[Dict[str, Any]] = run_dual_mode_pipeline(
        entries,
        mode="fasta",
        checkpoint_path=RESULTS_DIR / f"suite_e_{tag}_fasta_checkpoints.jsonl",
        batch_size=20,
    )
    gb_rows: List[Dict[str, Any]] = run_dual_mode_pipeline(
        entries,
        mode="gbk",
        checkpoint_path=RESULTS_DIR / f"suite_e_{tag}_gbk_checkpoints.jsonl",
        batch_size=20,
    )

    for rows_list in (fa_rows, gb_rows):
        for r in rows_list:
            r.setdefault("family", r.get("desc") or "Unknown")
            r.setdefault("host", "Unspecified")
            r.setdefault("desc", "")

    conc = evaluate_dual_concordance(fa_rows, gb_rows)
    ext_fa = [r for r in fa_rows if r.get("origin") == "ncbi_post_202508"]
    ext_gb = [r for r in gb_rows if r.get("origin") == "ncbi_post_202508"]

    report = {
        "milestone": tag,
        "elapsed_sec": round(time.perf_counter() - t0, 2),
        "total": len(entries),
        "external_post_202508_total": len(ext_fa),
        "fasta_morph": evaluate_suite_a(fa_rows),
        "gbk_morph": evaluate_suite_a(gb_rows),
        "external_fasta_morph": evaluate_suite_a(ext_fa),
        "external_gbk_morph": evaluate_suite_a(ext_gb),
        "concordance": conc,
        "by_origin": {
            "ncbi_post_202508": {
                "fasta_acc": round(sum(1 for r in ext_fa if r["predicted"] == r["expected"]) / max(1, len(ext_fa)), 4),
                "gbk_acc": round(sum(1 for r in ext_gb if r["predicted"] == r["expected"]) / max(1, len(ext_gb)), 4),
            },
            "local_unseen_pool": {
                "fasta_acc": round(
                    sum(1 for r in fa_rows if r.get("origin") == "local_unseen_pool" and r["predicted"] == r["expected"])
                    / max(1, sum(1 for r in fa_rows if r.get("origin") == "local_unseen_pool")),
                    4,
                ),
                "gbk_acc": round(
                    sum(1 for r in gb_rows if r.get("origin") == "local_unseen_pool" and r["predicted"] == r["expected"])
                    / max(1, sum(1 for r in gb_rows if r.get("origin") == "local_unseen_pool")),
                    4,
                ),
            },
        },
        "by_family_fasta": _evaluate_by_family(fa_rows),
        "by_family_gbk": _evaluate_by_family(gb_rows),
    }

    report_path = RESULTS_DIR / f"suite_e_{tag}_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n================ Suite E ({tag}) 纯盲测基线 ================")
    print(f"总耗时: {report['elapsed_sec']}s | 报告: {report_path}")
    print(
        f"全量 ({report['total']}株): FASTA Acc={report['fasta_morph']['accuracy']} (F1={report['fasta_morph']['macro_f1']}), "
        f"GBK Acc={report['gbk_morph']['accuracy']} (F1={report['gbk_morph']['macro_f1']}), "
        f"双格式形态一致={conc['morph_concordance']} ({conc['morph_concordance_count']}/{report['total']})"
    )
    print(
        f"  post-2025/08 外部新株 ({report['external_post_202508_total']}株): "
        f"FASTA Acc={report['by_origin']['ncbi_post_202508']['fasta_acc']}, "
        f"GBK Acc={report['by_origin']['ncbi_post_202508']['gbk_acc']}"
    )
    print(
        f"  假TMP (Podo/Non): FASTA={conc['false_tmp_podo_nontailed_fasta']}, GBK={conc['false_tmp_podo_nontailed_gbk']} | "
        f"有尾TMP召回: FASTA={conc['tailed_tmp_recall_fasta']}, GBK={conc['tailed_tmp_recall_gbk']}"
    )


if __name__ == "__main__":
    main()
