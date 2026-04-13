
import os
import csv
import logging
import re
from pathlib import Path
from collections import Counter

logger = logging.getLogger("api_server")

# 全局缓存，防止频繁读取大文件
_result_cache = {}

def parse_blast_csv(csv_path: str, limit: int = None) -> list:
    """带缓存的 BLAST CSV 解析器 (复刻自原 api_server.py)"""
    csv_path_obj = Path(csv_path)
    if not csv_path_obj.exists():
        return []

    curr_mtime = None
    if limit is None:
        curr_mtime = csv_path_obj.stat().st_mtime
        if csv_path in _result_cache:
            old_mtime, cached_data = _result_cache[csv_path]
            if curr_mtime <= old_mtime:
                return cached_data

    data = []
    try:
        # 使用 utf-8-sig 兼容可能的 BOM
        with open(csv_path, 'r', encoding='utf-8-sig') as fobj:
            reader = csv.DictReader(fobj)
            count = 0
            for row in reader:
                raw_title = row.get('标题', 'Unknown')
                if '>' in raw_title:
                    raw_title = raw_title.split('>')[0].strip()
                clean_title = raw_title
                gi_match = re.match(r'^gi\|\d+\|[a-z]+\|[A-Za-z0-9_.]+\|\s*', raw_title)
                if gi_match:
                    clean_title = raw_title[gi_match.end():].strip()

                species_raw = row.get('物种', 'N/A').strip()
                species_final = species_raw
                # 如果物种名太短或不规范，尝试从标题中提取
                if len(species_raw) < 4 or species_raw.lower() in ['newman', 'strain', 'str.', 'subsp.', 'aureus']:
                    match = re.search(r'([A-Z][a-z]+(?:\s+[a-z]+)?)', clean_title)
                    if match:
                        species_final = match.group(1)

                data.append({
                    'title': clean_title,
                    'len': row.get('长度', '0'),
                    'acc': row.get('访问号', 'N/A'),
                    'species': species_final,
                    'genus': row.get('属名', ''),
                    'strain': row.get('菌株', ''),
                    'evalue': row.get('E值', 'N/A'),
                    'similarity': row.get('相似度', '0%'),
                    'align_len': row.get('比对长度', '0'),
                    'query_range': row.get('查询起始-结束', ''),
                    'hit_range': row.get('命中起始-结束', '')
                })
                count += 1
                if limit and count >= limit:
                    break
        
        if limit is None:
            _result_cache[csv_path] = (curr_mtime, data)
            # 简单的缓存淘汰
            if len(_result_cache) > 20:
                first_key = next(iter(_result_cache))
                del _result_cache[first_key]
                
    except Exception as exc:
        logger.error(f"CSV Parse Error in blast_utils: {exc}")
    return data

def select_consensus_hit(hits: list) -> dict:
    """共识投票选择最佳命中 (复刻自原 api_server.py)"""
    from collections import Counter
    if not hits:
        return None

    high_identity_hits = []
    for hit in hits:
        sim_str = str(hit.get('similarity', '0%')).replace('%', '').strip()
        try:
            if float(sim_str) >= 98.0:
                high_identity_hits.append(hit)
        except (ValueError, TypeError):
            continue

    target_hits = high_identity_hits if high_identity_hits else hits
    if len(target_hits) == 1:
        return target_hits[0]

    generic_names = {'bacterium', 'uncultured bacterium', 'uncultured organism', 'unidentified', 'unknown', 'n/a', ''}
    species_counter = Counter()
    species_to_hit = {}
    for hit in target_hits:
        species = (hit.get('species') or '').strip()
        species_lower = species.lower()
        if species_lower and species_lower not in generic_names:
            species_counter[species] += 1
            if species not in species_to_hit:
                species_to_hit[species] = hit

    if not species_counter:
        return target_hits[0]

    total_valid = sum(species_counter.values())
    top_entries = species_counter.most_common(5)
    prob_parts = []
    consensus_list = []
    for name, count in top_entries:
        pct = (count / total_valid) * 100
        prob_parts.append(f"{name}({pct:.0f}%)")
        consensus_list.append({"name": name, "pct": round(pct)})

    consensus_species = top_entries[0][0]
    best_hit = dict(species_to_hit[consensus_species])
    best_hit['species'] = ", ".join(prob_parts)
    best_hit['consensusList'] = consensus_list
    return best_hit
