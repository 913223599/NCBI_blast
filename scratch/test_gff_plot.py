import sys
import json
from pathlib import Path
from Bio import SeqIO
import subprocess
import urllib.parse

def _sync_gff_annotations(records, orig_gff: Path, new_gff: Path, audit_data: dict | None = None):
    if not orig_gff.exists():
        print(f"Orig GFF {orig_gff} not found")
        return
    prod_map = {}
    func_map = {}
    for rec in records:
        for feat in rec.features:
            if feat.type in ["CDS", "tRNA", "tmRNA"]:
                cid = feat.qualifiers.get("locus_tag", [feat.qualifiers.get("ID", [""])[0]])[0]
                prod = feat.qualifiers.get("product", [""])[0]
                func = feat.qualifiers.get("function", [""])[0]
                if cid:
                    if prod: prod_map[cid] = prod
                    if func: func_map[cid] = func
                    
    amr_vf_map = {}
    if audit_data:
        for hit in audit_data.get("amr_genes_direct", []):
            if hit.get("cds_id"):
                val = hit.get("description", "AMR_Gene")
                amr_vf_map[hit["cds_id"]] = ("AMR_Gene_Family", urllib.parse.quote(val))
        for hit in audit_data.get("virulent_factors_direct", []):
            if hit.get("cds_id"):
                val = hit.get("description", "Virulence_Factor")
                amr_vf_map[hit["cds_id"]] = ("vfdb_short_name", urllib.parse.quote(val))

    with open(orig_gff, "r", encoding="utf-8") as fin, open(new_gff, "w", encoding="utf-8") as fout:
        for line in fin:
            if line.startswith("#") or not line.strip():
                fout.write(line)
                continue
            parts = line.strip().split("\t")
            if len(parts) >= 9:
                attrs = parts[8].split(";")
                new_attrs = []
                cid = None
                for attr in attrs:
                    if attr.startswith("ID="):
                        cid = attr[3:]
                        break
                
                if cid in prod_map or cid in func_map or cid in amr_vf_map:
                    for attr in attrs:
                        if attr.startswith("product=") and cid in prod_map:
                            new_attrs.append(f"product={prod_map[cid]}")
                        elif attr.startswith("function=") and cid in func_map:
                            new_attrs.append(f"function={func_map[cid]}")
                        else:
                            new_attrs.append(attr)
                    
                    if cid in prod_map and not any(a.startswith("product=") for a in new_attrs):
                        new_attrs.append(f"product={prod_map[cid]}")
                    if cid in func_map and not any(a.startswith("function=") for a in new_attrs):
                        new_attrs.append(f"function={func_map[cid]}")
                    if cid in amr_vf_map:
                        key, val = amr_vf_map[cid]
                        if not any(a.startswith(f"{key}=") for a in new_attrs):
                            new_attrs.append(f"{key}={val}")
                        
                    parts[8] = ";".join(new_attrs)
                    fout.write("\t".join(parts) + "\n")
                else:
                    fout.write(line)
            else:
                fout.write(line)
    print(f"✅ Generated {new_gff}")

# Load context
context_path = Path("F:/NCBI blast/scratch/context_AS.json")
if context_path.exists():
    with open(context_path, "r", encoding="utf-8") as f:
        ctx = json.load(f)
        audit_data = ctx.get("phagescope_audit", {})
else:
    audit_data = {}

base_dir = Path("/mnt/f/NCBI blast/results/assembly/AS_1778654314959/phageannotationstep")
gbk_path = base_dir / "phold_res" / "phold.gbk"
orig_gff = base_dir / "pharokka_res" / "PHAGE.gff"
new_gff = base_dir / "updated_phage.gff"

if not gbk_path.exists():
    gbk_path = base_dir / "pharokka_res" / "PHAGE.gbk"

print(f"Reading {gbk_path}")
records = list(SeqIO.parse(gbk_path, "genbank"))
_sync_gff_annotations(records, orig_gff, new_gff, audit_data)

fasta_path = base_dir.parent / "scaffoldingstep" / "scaffolds.clean.fasta"
if not fasta_path.exists():
    fasta_path = base_dir.parent / "assemblerstep" / "scaffolds.clean.fasta"

plot_dir = base_dir / "test_phage_plot"
plot_dir.mkdir(parents=True, exist_ok=True)

cmd = [
    "pharokka_plotter.py", "-i", str(fasta_path), 
    "--gff", str(new_gff), 
    "--genbank", str(gbk_path), 
    "-o", str(plot_dir), "-f", "-p", "phage_plot_test"
]
print("Running:", " ".join(cmd))
subprocess.run(cmd, check=True)
