# -*- coding: utf-8 -*-
"""
BLAST 结果共识概率算法 (select_consensus_hit) 统一概率分布测试脚本
"""
import sys
import re
from pathlib import Path

# 添加项目根目录到 sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.backend.utils.blast_utils import (
    select_consensus_hit, 
    is_unclassified_or_genus_only,
    canonicalize_species_name
)

def test_unclassified_filtering():
    print("[1] 测试属级未定种识别与排除...")
    assert is_unclassified_or_genus_only("Vibrio"), "单个属名应识别为未定种"
    assert is_unclassified_or_genus_only("Vibrio sp."), "Vibrio sp. 应识别为未定种"
    assert is_unclassified_or_genus_only("Vibrio sp"), "Vibrio sp 应识别为未定种"
    assert is_unclassified_or_genus_only("uncultured bacterium"), "uncultured bacterium 应识别为未定种"
    assert is_unclassified_or_genus_only("Staphylococcus strain BICM1"), "纯菌株标记应识别为未定种"
    assert not is_unclassified_or_genus_only("Vibrio owensii"), "具体双名法物种不应识别为未定种"
    assert not is_unclassified_or_genus_only("Citrobacter freundii"), "具体双名法物种不应识别为未定种"
    print("    -> 属级未定种识别过滤测试通过！")

def test_dynamic_synonym_resolution():
    print("[2] 测试基于本地 NCBI 分类数据库的动态异名合并...")
    res = canonicalize_species_name("Staphylococcus sciuri")
    assert res == "Mammaliicoccus sciuri", f"动态数据库异名解析失败: {res}"
    
    res_velezensis = canonicalize_species_name("Bacillus methylotrophicus")
    assert res_velezensis == "Bacillus velezensis", f"动态数据库异名解析失败: {res_velezensis}"
    print(f"    -> 成功将 'Staphylococcus sciuri' 动态解析为 '{res}'")
    print(f"    -> 成功将 'Bacillus methylotrophicus' 动态解析为 '{res_velezensis}'")
    print("    -> 动态数据库异名解析测试通过！")

def test_consensus_unified_probability_format():
    print("[3] 测试全部样本统一概率分布格式输出...")
    # 案例 A：单一具体种（100% 格式）
    mock_hits_single = [
        {"species": "Mammaliicoccus sciuri", "similarity": "99.8%", "evalue": "0.0"},
        {"species": "Staphylococcus sciuri", "similarity": "99.8%", "evalue": "0.0"},
    ]
    best_single = select_consensus_hit(mock_hits_single)
    print(f"    -> 单一优势物种输出: '{best_single.get('species')}'")
    assert best_single.get("species") == "Mammaliicoccus sciuri(100%)", f"单一物种未统一为(100%): {best_single.get('species')}"

    # 案例 B：多物种共识分布（多项百分比格式）
    mock_hits_multi = [
        {"species": "Vibrio owensii", "similarity": "99.8%", "evalue": "0.0"},
        {"species": "Vibrio harveyi", "similarity": "99.8%", "evalue": "0.0"},
    ]
    best_multi = select_consensus_hit(mock_hits_multi)
    print(f"    -> 多物种分布输出: '{best_multi.get('species')}'")
    assert "Vibrio owensii(" in best_multi.get("species") and "Vibrio harveyi(" in best_multi.get("species")
    assert "%" in best_multi.get("species")
    print("    -> 统一概率分布格式验证通过！")

def test_no_emojis_in_blast_utils():
    print("[4] 检查 blast_utils.py 编码与 Emoji 规范...")
    fpath = PROJECT_ROOT / "src" / "backend" / "utils" / "blast_utils.py"
    emoji_pattern = re.compile(
        "[\U00010000-\U0010ffff]|[\uD800-\uDBFF][\uDC00-\uDFFF]|[\u2600-\u27BF]"
    )
    with open(fpath, 'r', encoding='utf-8') as f:
        content = f.read()
        match = emoji_pattern.search(content)
        assert match is None, f"发现 Emoji: {match.group(0)!r}"
    print("    -> blast_utils.py 编码与无 Emoji 检查通过！")

if __name__ == "__main__":
    print("=== 开始 BLAST 统一概率分布专项测试 ===")
    try:
        test_unclassified_filtering()
        test_dynamic_synonym_resolution()
        test_consensus_unified_probability_format()
        test_no_emojis_in_blast_utils()
        print("\n=== 全部测试顺利通过！ ===")
    except Exception as e:
        print(f"\n[测试失败] 遇到异常: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
