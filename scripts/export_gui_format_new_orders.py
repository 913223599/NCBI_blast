# -*- coding: utf-8 -*-
# 导出新订单BLAST结果，对齐GUI格式。
import sys, os, csv, re
from pathlib import Path

PROJECT_ROOT = Path(r"F:\NCBI blast")
os.chdir(PROJECT_ROOT)
sys.path.insert(0, str(PROJECT_ROOT))

from src.backend.utils.blast_utils import parse_blast_csv, select_consensus_hit
from src.utils.translation.biology_translator import get_global_biology_translator

ORDERS = [
    {
        "task_id": "20261030_2140616642_16s",
        "out_dir": Path(r"G:\测序数据\生工16s\20261030_2140616642\BLAST结果"),
    },
    {
        "task_id": "20261030_2140616649_16s",
        "out_dir": Path(r"G:\测序数据\生工16s\20261030_2140616649\BLAST结果"),
    },
]

HEADERS = [
    '查询序列',
    '鉴定物种(中文翻译)',
    '鉴定概率分布(中文翻译)',
    '原始鉴定物种(拉丁文)',
    '原始鉴定概率分布(拉丁文)',
    '分类/菌株信息',
    '基因/序列库',
    '相似度 (Identity)',
    'E值',
    '访问号',
    '详细标题',
]

def format_row(hit):
    full_trans = hit.get('translatedName') or ''
    main_trans = full_trans
    prob_trans = '-'

    full_orig = hit.get('speciesName') or ''
    main_orig = full_orig
    prob_orig = '-'

    if '(' in full_trans and '%' in full_trans:
        m = re.match(r'^([^,(]+)\s*\(', full_trans)
        if m:
            main_trans = m.group(1).strip()
            prob_trans = full_trans

    if '(' in full_orig and '%' in full_orig:
        m = re.match(r'^([^,(]+)\s*\(', full_orig)
        if m:
            main_orig = m.group(1).strip()
            prob_orig = full_orig

    gene_seq = hit.get('geneSource', '')
    if hit.get('seqType'):
        gene_seq = f"{hit.get('geneSource','')} ({hit.get('seqType','')})"

    return [
        hit['queryTitle'],
        main_trans,
        prob_trans,
        main_orig,
        prob_orig,
        hit.get('genusStrain', ''),
        gene_seq,
        f"{hit.get('identity', 0):.1f}%",
        hit.get('evalue', '-'),
        hit.get('accession', '-'),
        hit.get('hitTitle', ''),
    ]

for order in ORDERS:
    task_id = order["task_id"]
    out_dir = order["out_dir"]
    out_dir.mkdir(parents=True, exist_ok=True)

    reports_dir = PROJECT_ROOT / "results" / "blast" / task_id / "reports"
    csv_files = sorted(reports_dir.glob("*.csv"))
    print(f"\n{'='*60}")
    print(f"Processing {task_id}: {len(csv_files)} CSV reports")

    all_species = set()
    results = []

    for csv_path in csv_files:
        m = re.search(r'_-(\d+)_1\.csv$', csv_path.name)
        query_title = f"-{m.group(1)}" if m else csv_path.stem

        hits = parse_blast_csv(str(csv_path), limit=50)
        if not hits:
            results.append({
                'queryTitle': query_title,
                'speciesName': '未找到匹配项 (No Hits)',
                'genusStrain': '',
                'geneSource': '',
                'seqType': '',
                'identity': 0,
                'evalue': '-',
                'accession': '-',
                'hitTitle': '',
            })
            continue

        best = select_consensus_hit(hits)
        if not best:
            results.append({
                'queryTitle': query_title,
                'speciesName': '未找到匹配项 (No Hits)',
                'genusStrain': '',
                'geneSource': '',
                'seqType': '',
                'identity': 0,
                'evalue': '-',
                'accession': '-',
                'hitTitle': '',
            })
            continue

        species = best.get('species', 'Unknown')
        all_species.add(species)
        if best.get('consensusList'):
            for c in best['consensusList']:
                if c.get('name'):
                    all_species.add(c['name'])

        results.append({
            'queryTitle': query_title,
            'speciesName': species,
            'genusStrain': f"{best.get('genus','')} · {best.get('strain','')}".strip(' ·'),
            'geneSource': best.get('gene_type', best.get('gene_source', '')),
            'seqType': best.get('seq_type', ''),
            'identity': float(str(best.get('similarity', '0')).replace('%', '')) if best.get('similarity') else 0,
            'evalue': str(best.get('evalue', 'N/A')),
            'accession': best.get('acc', 'N/A'),
            'hitTitle': best.get('title', ''),
        })

    print(f"Collected {len(results)} results, {len(all_species)} species to translate")

    # Batch translate
    translator = get_global_biology_translator()
    translated_map = translator.translate_batch(list(all_species), category='species')
    print(f"Translated {len(translated_map)} terms")

    for r in results:
        if r['speciesName'] in translated_map:
            r['translatedName'] = translated_map[r['speciesName']]
        else:
            r['translatedName'] = None

    # Write CSV
    out_path = out_dir / "16S鉴定结果.csv"
    with open(out_path, 'w', encoding='utf-8-sig', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(HEADERS)
        for r in results:
            writer.writerow(format_row(r))

    with_hits = sum(1 for r in results if 'No Hits' not in r['speciesName'])
    no_hits = sum(1 for r in results if 'No Hits' in r['speciesName'])
    print(f"Exported: {out_path}")
    print(f"Total: {len(results)}, With hits: {with_hits}, No hits: {no_hits}")

    # Preview
    print("\nPreview:")
    for r in results[:5]:
        trans = r.get('translatedName') or r['speciesName']
        print(f"  {r['queryTitle']:>5} | {trans[:50]:<50} | {r['identity']:.1f}%")
