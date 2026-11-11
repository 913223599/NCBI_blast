# -*- coding: utf-8 -*-
# Run 16S BLAST on new Sangon orders 2140616642 and 2140616649.
import sys, os, time
from pathlib import Path

PROJECT_ROOT = Path(r"F:\NCBI blast")
os.chdir(PROJECT_ROOT)
sys.path.insert(0, str(PROJECT_ROOT))

from src.blast.manager import get_blast_manager, TaskStatus

ORDERS = [
    {
        "task_name": "20261030_2140616642_16s",
        "seq_dir": Path(r"G:\测序数据\生工16s\20261030_2140616642\原始数据"),
    },
    {
        "task_name": "20261030_2140616649_16s",
        "seq_dir": Path(r"G:\测序数据\生工16s\20261030_2140616649\原始数据"),
    },
]

manager = get_blast_manager()

for order in ORDERS:
    task_name = order["task_name"]
    seq_dir = order["seq_dir"]

    # Collect consensus primary sequences: *.1.fasta (exclude haplotype)
    fasta_files = sorted([
        str(p) for p in seq_dir.glob("*.1.fasta")
        if "haplotype" not in p.name
    ])
    print(f"\n{'='*60}")
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
        "max_workers": 2,
        "request_timeout": 10,
    }

    task_id = manager.create_task(task_params)
    print(f"Task created: {task_id}")
    result_dir = manager.results_dir / task_id
    print(f"Result dir: {result_dir}")

    # Wait for completion
    print("Waiting for BLAST to complete...")
    last_prog = -1
    while True:
        status = manager.get_task_status(task_id)
        if not status:
            print("Cannot get task status!")
            break
        prog = status.get('progress', 0)
        st = status.get('status', 'unknown')
        if prog != last_prog:
            print(f"  Status: {st}, Progress: {prog}%")
            last_prog = prog
        if st in [TaskStatus.COMPLETED.value, TaskStatus.FAILED.value, TaskStatus.CANCELLED.value]:
            print(f"Task finished: {st}")
            if status.get('error'):
                print(f"Error: {status['error']}")
            break
        time.sleep(10)

    # List results
    reports_dir = result_dir / "reports"
    if reports_dir.exists():
        csvs = sorted(reports_dir.glob("*.csv"))
        print(f"Generated {len(csvs)} CSV reports in {reports_dir}")
