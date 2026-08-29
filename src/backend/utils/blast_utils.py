
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
    共识投票选择最佳命中 (分层生物学算法重构版)
    
    核心特性：
    1. 动态收紧候选池：根据最高分自适应确定近缘门槛。
    2. 满分优先通道：100% 匹配时直接判定优势物种。
    3. 属种分层判定：属级未定种 (如 Vibrio sp.) 不与具体种 (如 Vibrio owensii) 平级争抢百分比。
    4. 分类学异名智能合并：自动合并已知同物异名条目。
    5. 清晰简洁输出：优势显著 (>65%) 时直接输出单物种，势均力敌时才输出概率分布。
    """
    if not hits:
        return None

    # 1. 获取最高相似度作为基准
    try:
        first_sim = float(str(hits[0].get('similarity', '0')).replace('%', ''))
    except:
        first_sim = 0.0

    # 动态门槛设定：在极高相似度区（如 16S 全长）严格收紧门槛
    if first_sim >= 99.0:
        threshold = max(98.5, first_sim - 0.3)
    elif first_sim >= 95.0:
        threshold = max(94.0, first_sim - 0.5)
    else:
        threshold = max(80.0, first_sim - 1.0)
    
    high_identity_hits = []
    for hit in hits:
        try:
            sim = float(str(hit.get('similarity', '0')).replace('%', ''))
            if sim >= threshold:
                high_identity_hits.append(hit)
        except:
            continue

    target_hits = high_identity_hits if high_identity_hits else [hits[0]]
    if len(target_hits) == 1:
        return target_hits[0]

    max_sim = first_sim
    concrete_species_counter: dict[str, float] = {}
    unclassified_counter: dict[str, float] = {}
    species_to_hit: dict[str, dict] = {}

    for hit in target_hits:
        raw_species = (hit.get('species') or '').strip()
        if not raw_species:
            continue
            
        canon_species = canonicalize_species_name(raw_species)
        
        # 权重计算：最高分给予强加成，微小差异按梯度衰减
        try:
            curr_sim = float(str(hit.get('similarity', '0')).replace('%', ''))
            diff = max_sim - curr_sim
            if diff < 0.01:
                weight = 3.0  # 绝对同分第一名强加成
            elif diff <= 0.1:
                weight = 1.5
            else:
                weight = max(0.2, 1.0 - diff * 2.0)
        except:
            weight = 1.0

        if is_unclassified_or_genus_only(canon_species):
            unclassified_counter[canon_species] = unclassified_counter.get(canon_species, 0.0) + weight
        else:
            concrete_species_counter[canon_species] = concrete_species_counter.get(canon_species, 0.0) + weight
            
        if canon_species not in species_to_hit:
            species_to_hit[canon_species] = hit

    # 决策阶段：分层评估
    # 分支 A: 存在明确的具体种 -> 属级未定种不参与具体种的争抢
    if concrete_species_counter:
        total_weight = sum(concrete_species_counter.values())
        top_entries = sorted(concrete_species_counter.items(), key=lambda x: x[1], reverse=True)[:5]
        
        top1_species, top1_weight = top_entries[0]
        top1_pct = (top1_weight / total_weight) * 100
        
        # 检查是否具备绝对优势：第一名占比 >= 65% 或仅有 1 个具体种，或第一名是第二名的 2 倍以上
        has_clear_winner = False
        if len(top_entries) == 1:
            has_clear_winner = True
        elif top1_pct >= 65.0:
            has_clear_winner = True
        elif len(top_entries) >= 2 and top1_weight >= top_entries[1][1] * 2.0:
            has_clear_winner = True

        best_hit = dict(species_to_hit[top1_species])
        consensus_list = []
        prob_parts = []
        
        for name, weight in top_entries:
            pct = (weight / total_weight) * 100
            if pct < 5 and len(prob_parts) > 0:
                continue
            prob_parts.append(f"{name}({pct:.0f}%)")
            consensus_list.append({"name": name, "pct": round(pct)})

        if has_clear_winner:
            best_hit['species'] = top1_species
        else:
            best_hit['species'] = ", ".join(prob_parts)
            
        best_hit['consensusList'] = consensus_list
        return best_hit

    # 分支 B: 只有未定种 (如均为 Vibrio sp.)
    if unclassified_counter:
        total_weight = sum(unclassified_counter.values())
        top_entries = sorted(unclassified_counter.items(), key=lambda x: x[1], reverse=True)[:5]
        
        top1_species, top1_weight = top_entries[0]
        best_hit = dict(species_to_hit[top1_species])
        
        consensus_list = []
        prob_parts = []
        for name, weight in top_entries:
            pct = (weight / total_weight) * 100
            if pct < 5 and len(prob_parts) > 0:
                continue
            prob_parts.append(f"{name}({pct:.0f}%)")
            consensus_list.append({"name": name, "pct": round(pct)})
            
        if len(top_entries) == 1 or (top1_weight / total_weight) * 100 >= 70.0:
            best_hit['species'] = top1_species
        else:
            best_hit['species'] = ", ".join(prob_parts)
            
        best_hit['consensusList'] = consensus_list
        return best_hit

    return target_hits[0]
