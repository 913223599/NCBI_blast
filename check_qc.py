import json

with open("f:/NCBI blast/results/assembly/test_SRR19213853_jumbo/qualitycontrolstep/fastp_report.json") as f:
    d = json.load(f)

s = d["summary"]
bf = s["before_filtering"]
af = s["after_filtering"]

print("=== SRR19213853 Fastp QC Report ===")
print(f"Raw total reads:   {bf['total_reads']:,}")
print(f"Raw total bases:   {bf['total_bases']:,}")
print(f"Clean total reads: {af['total_reads']:,}")
print(f"Clean total bases: {af['total_bases']:,}")
print(f"GC content:        {af['gc_content']*100:.1f}%")
print(f"Q20 rate:          {af['q20_rate']*100:.1f}%")
print(f"Q30 rate:          {af['q30_rate']*100:.1f}%")
print(f"Read1 mean length: {af['read1_mean_length']}")
print(f"Read2 mean length: {af['read2_mean_length']}")

# Estimate coverage
clean_bases = af["total_bases"]
for genome_size in [150000, 300000, 500000, 2800000]:
    cov = clean_bases / genome_size
    print(f"  Coverage @ {genome_size/1000:.0f}kb genome: {cov:.0f}x")
