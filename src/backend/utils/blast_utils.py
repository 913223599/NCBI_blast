
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

# 分类学异名动态内存缓存 (避免频繁查库)
_canonical_species_cache: dict[str, str] = {}

def canonicalize_species_name(species: str) -> str:
    """
    规范化学名并通过本地 NCBI 分类学数据库 (taxa.sqlite) 动态映射异名到官方权威主学名
    纯动态数据库驱动，零硬编码。
    """
    if not species:
        return ""
    s_clean = species.strip()
    
    if s_clean in _canonical_species_cache:
        return _canonical_species_cache[s_clean]
        
    try:
        from ...utils.taxonomy_provider import get_taxonomy_provider
        provider = get_taxonomy_provider()
        if provider.is_ready:
            import sqlite3
            with sqlite3.connect(provider.db_path) as conn:
                cur = conn.cursor()
                # 1. 优先查主学名表 (species)
                cur.execute("SELECT spname FROM species WHERE spname = ? COLLATE NOCASE", (s_clean,))
                row = cur.fetchone()
                if row:
                    _canonical_species_cache[s_clean] = row[0]
                    return row[0]
                    
                # 2. 查异名表 (synonym) 精确匹配或前缀匹配并关联回主学名
                cur.execute("""
                    SELECT s.spname FROM synonym syn
                    JOIN species s ON syn.taxid = s.taxid
                    WHERE syn.spname = ? COLLATE NOCASE OR syn.spname LIKE ?
                    LIMIT 1
                """, (s_clean, f"{s_clean} %"))
                row = cur.fetchone()
                if row:
                    _canonical_species_cache[s_clean] = row[0]
                    return row[0]
    except Exception:
        pass
        
    _canonical_species_cache[s_clean] = s_clean
    return s_clean

def is_unclassified_or_genus_only(species: str) -> bool:
    """
    判断学名是否属于属级未定种（如 Vibrio sp. / Vibrio）或环境泛指样本
    """
    if not species:
        return True
    
    s_clean = species.strip()
    s_lower = s_clean.lower()
    
    # 泛指词库
    generic_words = {
        'bacterium', 'uncultured', 'organism', 'unidentified', 'unknown', 
        'n/a', 'na', 'metagenome', 'environmental sample', 'bacteria', 
        'archaeon', 'eukaryota', 'microorganism', 'clone', 'sample'
    }
    if s_lower in generic_words:
        return True
    
    for g in generic_words:
        if s_lower.startswith(g + ' ') or s_lower.endswith(' ' + g):
            return True
            
    # 仅有一个英文单词（通常是属名，如 "Vibrio", "Citrobacter"）
    words = s_clean.split()
    if len(words) == 1:
        return True
        
    # 双词/多次中第二个词为 sp, sp., spp., strain, isolate 等未定种标记
    if len(words) >= 2:
        second = words[1].lower().rstrip('.:;,')
        if second in {'sp', 'spp', 'strain', 'str', 'isolate', 'clone', 'sample', 'genomosp', 'group'}:
            return True
            
    return False

def select_consensus_hit(hits: list) -> Optional[dict]:
    """
    共识投票选择最佳命中 (前排优先与峰值相似度主导排名版)
    
    核心机制：
    1. 前排深度聚焦：优先考虑 Top 25 条内的高质量比对，避免第 40~50 名冗余条目通过数量逆袭。
    2. 位置衰减因子 (Rank Discount)：随命中排名自然衰减 (1 / (1 + 0.15 * rank))，强力保障前排高分条目的决定权。
    3. 峰值相似度惩罚 (Peak Penalty)：若某物种最高一条也显著低于第一名，严厉惩罚其总分。
    4. 属种分层判定：属级未定种不参与具体种争抢。
    5. 异名纯动态合并：本地 taxa.sqlite 数据库支撑。
    """
    if not hits:
        return None

    # 1. 提取绝对最高相似度基准
    try:
        first_sim = float(str(hits[0].get('similarity', '0')).replace('%', ''))
    except:
        first_sim = 0.0

    max_search_depth = min(len(hits), 25)
    
    # 动态门槛设定
    if first_sim >= 99.0:
        sim_threshold = max(98.5, first_sim - 0.3)
    elif first_sim >= 96.0:
        sim_threshold = max(94.0, first_sim - 0.4)
    else:
        sim_threshold = max(80.0, first_sim - 0.8)

    species_peak_sim: dict[str, float] = {}
    species_rank_score: dict[str, float] = {}
    species_to_best_hit: dict[str, dict] = {}
    
    for rank_idx, hit in enumerate(hits[:max_search_depth]):
        raw_species = (hit.get('species') or '').strip()
        if not raw_species:
            continue
            
        canon_species = canonicalize_species_name(raw_species)
        
        try:
            curr_sim = float(str(hit.get('similarity', '0')).replace('%', ''))
        except:
            curr_sim = 0.0
            
        if curr_sim < sim_threshold:
            continue
            
        # 排名位置衰减因子
        rank_discount = 1.0 / (1.0 + 0.15 * rank_idx)
        # 相似度差值衰减
        diff = max(0.0, first_sim - curr_sim)
        sim_weight = max(0.2, 1.0 - diff * 2.5)
        
        entry_score = rank_discount * sim_weight
        
        if canon_species not in species_peak_sim or curr_sim > species_peak_sim[canon_species]:
            species_peak_sim[canon_species] = curr_sim
            species_to_best_hit[canon_species] = hit
            
        species_rank_score[canon_species] = species_rank_score.get(canon_species, 0.0) + entry_score

    concrete_species_scores: dict[str, float] = {}
    unclassified_scores: dict[str, float] = {}
    
    for sp, score in species_rank_score.items():
        peak_sim = species_peak_sim.get(sp, 0.0)
        peak_diff = max(0.0, first_sim - peak_sim)
        # 峰值差距惩罚
        peak_penalty = max(0.1, 1.0 - peak_diff * 3.0)
        final_score = score * peak_penalty
        
        if is_unclassified_or_genus_only(sp):
            unclassified_scores[sp] = final_score
        else:
            concrete_species_scores[sp] = final_score

    target_counter = concrete_species_scores if concrete_species_scores else unclassified_scores
    if not target_counter:
        return hits[0]
        
    total_score = sum(target_counter.values())
    top_entries = sorted(target_counter.items(), key=lambda x: x[1], reverse=True)[:5]
    
    top1_species, top1_val = top_entries[0]
    top1_pct = (top1_val / total_score) * 100
    
    best_hit = dict(species_to_best_hit[top1_species])
    consensus_list = []
    prob_parts = []
    
    if len(top_entries) == 1:
        # 单一候选物种统一显示 100%
        top_name = top_entries[0][0]
        prob_parts.append(f"{top_name}(100%)")
        consensus_list.append({"name": top_name, "pct": 100})
    else:
        for name, val in top_entries:
            pct = (val / total_score) * 100
            if pct < 3 and len(prob_parts) > 0:
                continue
            pct_round = max(1, round(pct))
            prob_parts.append(f"{name}({pct_round}%)")
            consensus_list.append({"name": name, "pct": pct_round})
        
    best_hit['species'] = ", ".join(prob_parts) if prob_parts else f"{top1_species}(100%)"
    best_hit['consensusList'] = consensus_list
    return best_hit
