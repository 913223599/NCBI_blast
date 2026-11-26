# -*- coding: utf-8 -*-
"""Run 16S BLAST on one or more Sangon order directories."""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path
from typing import List, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _resolve_orders(args: argparse.Namespace) -> List[Tuple[str, Path]]:
    base_dir = args.base_dir.resolve()
    orders: List[Tuple[str, Path]] = []
    for order_name in args.orders:
        seq_dir = base_dir / order_name / args.seq_subdir
        orders.append((f"{order_name}_16s", seq_dir))
    return orders


def parse_args() -> argparse.Namespace:
    default_base = Path(
        os.environ.get("SANGON_16S_BASE_DIR", str(PROJECT_ROOT / "data" / "sangon_16s"))
    )
    parser = argparse.ArgumentParser(description="批量执行多个生工 16S 订单 BLAST 鉴定")
    parser.add_argument("--base-dir", type=Path, default=default_base, help="生工 16S 订单根目录")
    parser.add_argument("--orders", nargs="+", required=True, help="订单目录名列表")
    parser.add_argument("--seq-subdir", default="原始数据", help="订单内原始序列子目录名")
    parser.add_argument("--max-workers", type=int, default=2, help="并发数")
    return parser.parse_args()


def main() -> None:
    os.chdir(PROJECT_ROOT)
    args = parse_args()
    from src.blast.manager import TaskStatus, get_blast_manager

    manager = get_blast_manager()
    for task_name, seq_dir in _resolve_orders(args):
        if not seq_dir.is_dir():
            print(f"[SKIP] 序列目录不存在: {seq_dir}")
            continue
        fasta_files = sorted(
            str(p) for p in seq_dir.glob("*.1.fasta") if "haplotype" not in p.name
        )
        print(f"\n{'=' * 60}")
        print(f"Order: {task_name}")
        print(f"Found {len(fasta_files)} consensus primary fasta files")
        for f in fasta_files[:3]:
            print(f"  {Path(f).name}")

        task_params = {
            "task_name": task_name,
            "files": fasta_files,
            "program": "auto",
            "database": "ncbi_16s",
            "evalue": "0.05",
            "hitlist_size": "50",
            "max_workers": args.max_workers,
            "request_timeout": 10,
        }

        task_id = manager.create_task(task_params)
        print(f"Task created: {task_id}")
        result_dir = manager.results_dir / task_id
        print(f"Result dir: {result_dir}")

        print("Waiting for BLAST to complete...")
        last_prog = -1
        while True:
            status = manager.get_task_status(task_id)
            if not status:
                print("Cannot get task status!")
                break
            prog = status.get("progress", 0)
            st = status.get("status", "unknown")
            if prog != last_prog:
                print(f"  Status: {st}, Progress: {prog}%")
                last_prog = prog
            if st in {TaskStatus.COMPLETED.value, TaskStatus.FAILED.value, TaskStatus.CANCELLED.value}:
                print(f"Task finished: {st}")
                if status.get("error"):
                    print(f"Error: {status['error']}")
                break
            time.sleep(10)

        reports_dir = result_dir / "reports"
        if reports_dir.exists():
            csvs = sorted(reports_dir.glob("*.csv"))
            print(f"Generated {len(csvs)} CSV reports in {reports_dir}")


if __name__ == "__main__":
    main()
