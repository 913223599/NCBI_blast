# -*- coding: utf-8 -*-
# Run 16S BLAST on Sangon consensus sequences using project BlastManager.
import sys, os, time
from pathlib import Path

PROJECT_ROOT = Path(r"F:\NCBI blast")
os.chdir(PROJECT_ROOT)
sys.path.insert(0, str(PROJECT_ROOT))

SEQ_DIR = Path(r"G:\测序数据\生工16s\20261021_2140612440")

# Collect consensus primary sequences: (-N)_ORDER_ITEM_ID_ORDER_ITEM.fasta
fasta_files = sorted([str(p) for p in SEQ_DIR.glob("(-*_*_ORDER_ITEM.fasta")])
print(f"Found {len(fasta_files)} consensus primary fasta files")
for f in fasta_files[:3]:
    print(f"  {Path(f).name}")
print(f"  ... total {len(fasta_files)}")

from src.blast.manager import get_blast_manager, TaskStatus

manager = get_blast_manager()

task_params = {
    "task_name": "20261021_2140612440_16s",
    "files": fasta_files,
    "program": "auto",
    "database": "ncbi_16s",
    "evalue": "0.05",
    "hitlist_size": "50",
    "max_workers": 2,
    "request_timeout": 10,
}

task_id = manager.create_task(task_params)
print(f"\nTask created: {task_id}")
result_dir = manager.results_dir / task_id
print(f"Result dir: {result_dir}")

# Wait for completion
print("\nWaiting for BLAST to complete...")
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
        print(f"\nTask finished: {st}")
        if status.get('error'):
            print(f"Error: {status['error']}")
        break
    time.sleep(10)

# List results
reports_dir = result_dir / "reports"
if reports_dir.exists():
    csvs = sorted(reports_dir.glob("*.csv"))
    print(f"\nGenerated {len(csvs)} CSV reports in {reports_dir}")
    for c in csvs[:5]:
        print(f"  {c.name}")
