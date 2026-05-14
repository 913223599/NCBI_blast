import subprocess
import os

def run_wsl(cmd):
    return subprocess.check_output(f'wsl -d Ubuntu bash -c "{cmd}"', shell=True).decode()

ref = "/mnt/f/NCBI blast/test_data/ref_staph.fasta"
old = "/mnt/f/NCBI blast/results/assembly/test_SRR37941745_1777303058/scaffoldingstep/scaffolds.clean.fasta"
new = "/mnt/f/NCBI blast/results/assembly/test_SRR37941745_1777342611/consensuscorrectionstep/polished_assembly.fasta"

print("Building DB...")
run_wsl(f"cp '{ref}' /tmp/ref.fasta && makeblastdb -in /tmp/ref.fasta -dbtype nucl")

def get_stats(query, name):
    print(f"Analyzing {name}...")
    out = run_wsl(f"blastn -query '{query}' -db '/tmp/ref.fasta' -outfmt '6 nident mismatch length'")
    nident = 0
    mismatch = 0
    length = 0
    for line in out.strip().split('\n'):
        if not line: continue
        ni, mis, le = map(int, line.split('\t'))
        nident += ni
        mismatch += mis
        length += le
    
    identity = (nident / length) * 100 if length > 0 else 0
    return identity, mismatch, length

id_old, mis_old, len_old = get_stats(old, "OLD")
id_new, mis_new, len_new = get_stats(new, "NEW")

print(f"\n--- Results ---")
print(f"OLD vs REF: Identity={id_old:.4f}%, Mismatches={mis_old}, Len={len_old}")
print(f"NEW vs REF: Identity={id_new:.4f}%, Mismatches={mis_new}, Len={len_new}")
