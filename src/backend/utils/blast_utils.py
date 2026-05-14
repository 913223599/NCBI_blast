
import os
import csv
import logging
import re
from pathlib import Path
from collections import Counter
from typing import Optional

logger = logging.getLogger("api_server")

# 全局缓存，防止频繁读取大文件
_result_cache = {}

def parse_blast_csv(csv_path: str, limit: Optional[int] = None) -> list:
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

def select_consensus_hit(hits: list) -> Optional[dict]:
    """共识投票选择最佳命中 (优化版)"""
    if not hits:
        return None

    # 1. 获取最高相似度作为基准，动态确定门槛
    try:
        first_sim = float(str(hits[0].get('similarity', '0')).replace('%', ''))
    except:
        first_sim = 0.0
    
    # 动态门槛：只要进入最高分 0.5% 范围内的都视为“高可信”候选
    # 如果最高分很高 (>98)，则门槛更严；如果最高分一般，则门槛放宽
    threshold = max(90.0, first_sim - 0.5)
    
    high_identity_hits = []
    for hit in hits:
        try:
            sim = float(str(hit.get('similarity', '0')).replace('%', ''))
            if sim >= threshold:
                high_identity_hits.append(hit)
        except:
            continue

    # 如果有多个最高分的 hit (例如相似度完全一样)，则进入共识统计
    target_hits = high_identity_hits if high_identity_hits else [hits[0]]
    if len(target_hits) == 1:
        return target_hits[0]

    generic_names = {
        'bacterium', 'uncultured bacterium', 'uncultured organism', 'unidentified', 
        'unknown', 'n/a', '', 'bacteria', 'archaea', 'eukaryota', 'metagenome', 
        'environmental sample', 'uncultured', 'organism'
    }
    species_counter: dict[str, float] = {}
    species_to_hit: dict[str, dict] = {}
    
    max_sim = first_sim

    for hit in target_hits:
        species = (hit.get('species') or '').strip()
        species_lower = species.lower()
        if species_lower and species_lower not in generic_names:
            # 权重计算：相似度越接近最高值，权重越高
            try:
                curr_sim = float(str(hit.get('similarity', '0')).replace('%', ''))
                # 权重因子：距离最高分越远，权重衰减越快
                # 如果 diff 是 0，权重是 2.0 (给绝对第一名加成)；如果 diff 是 0.5，权重是 0.5
                diff = max_sim - curr_sim
                weight = 2.0 if diff < 0.01 else max(0.2, 1.0 - diff * 2.0)
            except:
                weight = 1.0
                
            species_counter[species] = species_counter.get(species, 0.0) + weight
            if species not in species_to_hit:
                species_to_hit[species] = hit

    if not species_counter:
        return target_hits[0]

    total_weight = sum(species_counter.values())
    top_entries = sorted(species_counter.items(), key=lambda x: x[1], reverse=True)[:5]
    
    prob_parts = []
    consensus_list = []
    for name, weight in top_entries:
        pct = (weight / total_weight) * 100
        if pct < 5 and len(prob_parts) > 0:
            continue
        prob_parts.append(f"{name}({pct:.0f}%)")
        consensus_list.append({"name": name, "pct": round(pct)})

    consensus_species = top_entries[0][0]
    best_hit = dict(species_to_hit[consensus_species])
    
    # 极致优化：如果第一名权重占比极高 (>80%)，直接显示具体物种，不显示混合列表
    first_weight_pct = (top_entries[0][1] / total_weight) * 100
    if first_weight_pct > 80:
        best_hit['species'] = consensus_species
    else:
        best_hit['species'] = ", ".join(prob_parts)
        
    best_hit['consensusList'] = consensus_list
    return best_hit
