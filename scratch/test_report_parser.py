import sys
import os
from pathlib import Path
import json

# 设置项目根目录以便导入
PROJECT_ROOT = Path("f:/NCBI blast").resolve()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

def test_parser():
    from src.backend.utils.assembly_report import AssemblyReportParser
    from src.backend.utils.assembly_db import assembly_db
    
    task_id = "AS_1776601910417"
    task_dir = PROJECT_ROOT / "results" / "assembly" / task_id
    
    td = assembly_db.get_task(task_id)
    if not td or not td.get('results'):
        print("Error: No data in database")
        return

    r_json = json.loads(td['results'])
    
    print("--- Nested Structure Diagnosis ---")
    print(f"Top level keys: {list(r_json.keys())}")
    
    inner_data = r_json
    if "results" in r_json:
        print("Found double nesting! results['results'] detected.")
        inner_data = r_json["results"]
    
    print(f"Inner data keys: {list(inner_data.keys())}")
    print(f"GC found in inner: {inner_data.get('genomic_metrics', {}).get('gc_content')}")
    print(f"Audit found in inner: {inner_data.get('phagescope_audit', {}).get('lifestyle')}")

if __name__ == "__main__":
    test_parser()
