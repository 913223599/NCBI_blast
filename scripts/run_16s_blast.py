# -*- coding: utf-8 -*-
"""Run 16S BLAST on Sangon consensus sequences using project BlastManager."""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def parse_args() -> argparse.Namespace:
    default_seq_dir = Path(
        os.environ.get("SANGON_16S_SEQ_DIR", str(PROJECT_ROOT / "data" / "sangon_16s"))
    )
    parser = argparse.ArgumentParser(description="对生工 16S 一致序列批量发起 BLAST 鉴定任务")
    parser.add_argument("--seq-dir", type=Path, default=default_seq_dir, help="输入序列目录")
    parser.add_argument("--task-name", default="sangon_16s_batch", help="任务名称")
    parser.add_argument("--glob", dest="pattern", default="(-*_*_ORDER_ITEM.fasta", help="序列文件匹配模式")
    parser.add_argument("--max-workers", type=int, default=2, help="并发数")
    return parser.parse_args()


def main() -> None:
    os.chdir(PROJECT_ROOT)
    args = parse_args()
    seq_dir = args.seq_dir.resolve()
    if not seq_dir.is_dir():
        raise FileNotFoundError(f"序列目录不存在: {seq_dir}")

    from src.blast.manager import TaskStatus, get_blast_manager

    fasta_files = sorted(str(p) for p in seq_dir.glob(args.pattern))
    print(f"Found {len(fasta_files)} consensus primary fasta files in {seq_dir}")
    for f in fasta_files[:3]:
        print(f"  {Path(f).name}")
    print(f"  ... total {len(fasta_files)}")

    manager = get_blast_manager()
    task_params = {
        "task_name": args.task_name,
        "files": fasta_files,
        "program": "auto",
        "database": "ncbi_16s",
        "evalue": "0.05",
        "hitlist_size": "50",
        "max_workers": args.max_workers,
        "request_timeout": 10,
    }

    task_id = manager.create_task(task_params)
    print(f"\nTask created: {task_id}")
    print(f"Result dir: {manager.results_dir / task_id}")

    print("\nWaiting for BLAST to complete...")
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
            print(f"\nTask finished: {st}")
            if status.get("error"):
                print(f"Error: {status['error']}")
            break
        time.sleep(10)


if __name__ == "__main__":
    main()
