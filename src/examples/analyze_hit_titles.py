#!/usr/bin/env python3
"""
测试文件：分析BLAST结果XML文件中的标题信息
提取并分析所有命中标题，识别其中的生物物种信息
"""

import sys
import os
import re
from pathlib import Path

# 添加项目根目录到Python路径
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from Bio.Blast import NCBIXML


def extract_species_from_title(title):
    """
    从标题中提取物种名称
    
    Args:
        title (str): BLAST命中标题
        
    Returns:
        str: 提取的物种名称
    """
    # 常见的物种名称模式
    patterns = [
        r'([A-Z][a-z]+(?:\s+[a-z]+)+)',  # 属名+种名
        r'([A-Z][a-z]+\s+sp\.)',         # 属名 sp.
        r'([A-Z][a-z]+\s+strain\s+\w+)', # 属名 strain 名称
    ]
    
    for pattern in patterns:
        match = re.search(pattern, title)
        if match:
            return match.group(1)
    
    return "未知物种"


def analyze_hit_titles(xml_file_path):
    """
    分析BLAST结果XML文件中的所有命中标题
    
    Args:
        xml_file_path (str): XML文件路径
    """
    try:
        with open(xml_file_path, 'r') as file:
            blast_records = NCBIXML.parse(file)
            
            # 存储物种统计信息
            species_count = {}
            
            # 遍历BLAST记录（通常只有一个）
            for blast_record in blast_records:
                print(f"查询序列: {blast_record.query}")
                print(f"命中数量: {len(blast_record.alignments)}")
                print("=" * 80)
                
                # 遍历所有命中
                for i, alignment in enumerate(blast_record.alignments):
                    print(f"命中 {i+1}:")
                    print(f"  标题: {alignment.title}")
                    
                    # 提取物种名称
                    species = extract_species_from_title(alignment.title)
                    print(f"  物种: {species}")
                    
                    # 统计物种出现次数
                    if species in species_count:
                        species_count[species] += 1
                    else:
                        species_count[species] = 1
                    
                    print(f"  长度: {alignment.length}")
                    print(f"  访问号: {alignment.accession}")
                    
                    # 显示第一个HSP的信息
                    if alignment.hsps:
                        hsp = alignment.hsps[0]
                        print(f"  E值: {hsp.expect}")
                        print(f"  得分: {hsp.score}")
                        print(f"  相似度: {hsp.identities / hsp.align_length * 100:.2f}%")
                    
                    print("-" * 40)
                
                # 输出物种统计信息
                print("\n物种统计:")
                print("=" * 40)
                for species, count in sorted(species_count.items(), key=lambda x: x[1], reverse=True):
                    print(f"  {species}: {count} 次")
                    
    except Exception as e:
        print(f"处理文件时出错: {e}")


def main():
    """主函数"""
    # XML文件路径
    xml_file = Path(__file__).parent.parent.parent / "results" / "2.1492R.SP506300620002_blast_result.xml"
    
    if not xml_file.exists():
        print(f"错误: 文件 {xml_file} 不存在")
        return
    
    print(f"正在处理文件: {xml_file}")
    print()
    
    analyze_hit_titles(xml_file)


if __name__ == "__main__":
    main()