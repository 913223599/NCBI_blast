# -*- coding: utf-8 -*-
# Translate BLAST CSV reports and generate summary.
import sys, os, csv, re
from pathlib import Path

PROJECT_ROOT = Path(r"F:\NCBI blast")
os.chdir(PROJECT_ROOT)
sys.path.insert(0, str(PROJECT_ROOT))

from src.utils.translation.blast_result_translator import get_blast_result_translator

reports_dir = Path(r"F:\NCBI blast\results\blast\20261021_2140612440_16s\reports")
out_dir = Path(r"G:\测序数据\生工16s\20261021_2140612440\BLAST结果")
out_dir.mkdir(parents=True, exist_ok=True)

translator = get_blast_result_translator()

# Test translation
print("Translation test:")
print(f"  Proteus -> {translator.translate_genus('Proteus')}")
print(f"  Proteus mirabilis -> {translator.translate_species('Proteus mirabilis')}")
print(f"  Alcaligenes -> {translator.translate_genus('Alcaligenes')}")

# Process each CSV
summary_rows = []
csv_files = sorted(reports_dir.glob("*.csv"))

for csv_path in csv_files:
    # Parse sample name from filename
    # Pattern: _-N__ORDERITEM_ORDER_ITEM__ORDERITEM__-N__1.csv
    m = re.search(r'_-(\d+)__(\d+)_ORDER_ITEM', csv_path.name)
    if m:
        sample_num = f"-{m.group(1)}"
        order_item = m.group(2)
    else:
        sample_num = csv_path.stem
        order_item = ""

    with open(csv_path, 'r', encoding='utf-8-sig') as f:
        reader = csv.reader(f)
        rows = list(reader)

    if len(rows) <= 1:
        summary_rows.append({
            'sample': sample_num,
            'order_item': order_item,
            'species_en': '(无匹配)',
            'species_cn': '',
            'genus_en': '',
            'genus_cn': '',
            'strain': '',
            'identity': '',
            'evalue': '',
            'accession': '',
        })
        continue

    header = rows[0]
    best = rows[1]  # top hit

    # Column indices based on header
    # 标题,长度,访问号,物种,属名,菌株,基因类型,序列类型,宿主信息,HSPs,E值,比对长度,相同碱基数,相似度,缺口数,查询起始-结束,命中起始-结束
    species_en = best[3] if len(best) > 3 else ""
    genus_en = best[4] if len(best) > 4 else ""
    strain = best[5] if len(best) > 5 else ""
    accession = best[2] if len(best) > 2 else ""
    identity = best[13] if len(best) > 13 else ""
    evalue = best[10] if len(best) > 10 else ""

    # Translate
    species_cn = translator.translate_species(species_en)
    genus_cn = translator.translate_genus(genus_en)

    summary_rows.append({
        'sample': sample_num,
        'order_item': order_item,
        'species_en': species_en,
        'species_cn': species_cn,
        'genus_en': genus_en,
        'genus_cn': genus_cn,
        'strain': strain,
        'identity': identity,
        'evalue': evalue,
        'accession': accession,
    })

# Write summary CSV
summary_path = out_dir / "16S鉴定汇总.csv"
with open(summary_path, 'w', encoding='utf-8-sig', newline='') as f:
    writer = csv.DictWriter(f, fieldnames=['sample','order_item','species_en','species_cn','genus_en','genus_cn','strain','identity','evalue','accession'])
    writer.writeheader()
    writer.writerows(summary_rows)

print(f"\nSummary written: {summary_path}")
print(f"Total samples: {len(summary_rows)}")
print(f"With hits: {sum(1 for r in summary_rows if r['species_en'] != '(无匹配)')}")
print(f"No hits: {sum(1 for r in summary_rows if r['species_en'] == '(无匹配)')}")

# Print first 10
print("\n=== Top 10 results ===")
for r in summary_rows[:10]:
    print(f"  {r['sample']:>5} | {r['genus_cn'] or r['genus_en']:<20} | {r['species_cn'] or r['species_en']:<40} | {r['identity']}")
