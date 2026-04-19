
import os
import sys
import json
import csv
from pathlib import Path

# 1. 模拟环境
project_root = Path(os.getcwd()).resolve()
meta_base = project_root / "database" / "phagescope" / "metadata"

def simulate_audit(target_id):
    print(f"--- [Audit] Searching for Accession: {target_id} ---")
    audit = {
        "lifestyle": "Unknown",
        "host_origin": "--",
        "amr_count": 0,
        "vf_count": 0,
        "protein_entries": 0
    }

    # A. 搜生活史
    phage_dir = meta_base / "phage"
    for f_name in ["refseq_phage_meta_data.tsv", "genbank_phage_meta_data.tsv"]:
        p = phage_dir / f_name
        if not p.exists(): continue
        with open(p, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f, delimiter="\t")
            for row in reader:
                if row.get("Phage_ID") == target_id or row.get("Accession") == target_id:
                    audit["lifestyle"] = row.get("Lifestyle", "Unknown")
                    audit["host_origin"] = row.get("Host", "--")
                    break
            if audit["lifestyle"] != "Unknown": break

    # B. 搜蛋白详情
    p_meta_dir = meta_base / "annotated_protein"
    for f_name in ["refseq_phage_annotated_protein_meta_data.tsv"]:
        p_file = p_meta_dir / f_name
        if not p_file.exists(): continue
        print(f"--- [Bio-Map] Loading large protein table: {f_name} ---")
        with open(p_file, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f, delimiter="\t")
            for row in reader:
                if row.get("Phage_ID") == target_id:
                    audit["protein_entries"] += 1
            if audit["protein_entries"] > 0: break
    
    return audit

if __name__ == "__main__":
    # 我们测试一个已知存在的 ID: NC_004313.1 (Salmonella phage)
    test_id = "NC_004313.1"
    res = simulate_audit(test_id)
    
    print("\n" + "="*50)
    print(f"VERIFICATION RESULT FOR {test_id}")
    print("="*50)
    print(f"Lifestyle Found:   {res['lifestyle']}")
    print(f"Host Origin:       {res['host_origin']}")
    print(f"Protein Data:      {res['protein_entries']} genes found in bio-map")
    
    if res['lifestyle'] != "Unknown" and res['protein_entries'] > 0:
        print("\n✅ SUCCESS: The mining logic and database connection are FULLY functional.")
    else:
        print("\n❌ FAILED: Data not retrieved. Please check database path or ID.")
