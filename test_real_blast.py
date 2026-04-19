import sys
import os
from pathlib import Path
from Bio import SeqIO
from Bio.SeqRecord import SeqRecord
import subprocess

# Setup paths
task_id = "AS_1776518668936"
gbk_path = Path(f"results/assembly/{task_id}/phageannotationstep/phold_res/phold.gbk")

print(f"--- BLAST Refinement Test for {task_id} ---")

if not gbk_path.exists():
    print("Error: Target GBK not found.")
    sys.exit(1)

# 1. Extract unknown proteins
records = list(SeqIO.parse(gbk_path, "genbank"))
unknown_records = []
for rec in records:
    for feat in rec.features:
        if feat.type == "CDS":
            prod = feat.qualifiers.get("product", [""])[0].lower()
            if not prod or "unknown" in prod or "hypothetical" in prod:
                cid = feat.qualifiers.get("locus_tag", [feat.qualifiers.get("ID", ["unknown"])[0]])[0]
                seq_ptr = feat.extract(rec.seq).translate(table=11, to_stop=True)
                unknown_records.append(SeqRecord(seq_ptr, id=cid, description="unknown protein"))

print(f"Found {len(unknown_records)} proteins with unknown/hypothetical function.")

if not unknown_records:
    print("Nothing to refine.")
    sys.exit(0)

# Save to temp fasta for testing
test_faa = Path("test_refinement.faa")
SeqIO.write(unknown_records, test_faa, "fasta")
print(f"Sequences saved to {test_faa}")

# 2. Run a small sample (first 3) against remote NR to see what we get
sample_count = 3
sample_faa = Path("sample_refinement.faa")
SeqIO.write(unknown_records[:sample_count], sample_faa, "fasta")

print(f"\nRunning Remote BLASTp for the first {sample_count} samples (this might take a minute)...")
try:
    # We'll use the local blastp client but with -remote
    cmd = [
        "blastp", "-query", str(sample_faa), "-db", "nr", "-remote",
        "-outfmt", "6 qseqid sseqid stitle evalue", "-max_target_seqs", "1"
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    
    if result.stdout.strip():
        print("\n--- BLAST Hits Result ---")
        lines = result.stdout.strip().split("\n")
        for line in lines:
            parts = line.split("\t")
            if len(parts) >= 4:
                q_id, s_id, title, evalue = parts[0], parts[1], parts[2], parts[3]
                print(f"Target: {q_id}")
                print(f"  Match: {title}")
                print(f"  E-value: {evalue}")
                print("-" * 20)
    else:
        print("No hits found for the sample.")
except Exception as e:
    print(f"BLAST Error: {e}")
