"""
BLAST结果转换模块
负责将BLAST的XML格式结果转换为CSV格式
"""

import xml.etree.ElementTree as ET
import csv
import re
from pathlib import Path
from typing import List, Dict
from Bio.Blast import NCBIXML

from src.utils.translation import get_blast_result_translator


class BlastResultConverter:
    """
    BLAST结果转换器
    负责将BLAST的XML格式结果转换为CSV格式，并生成描述文件
    """
    
    def __init__(self):
        """
        初始化结果转换器
        """
        self.translator = get_blast_result_translator()
        # 不再需要_processed_terms，因为我们不在转换阶段处理翻译
    
    def convert_xml_to_csv(self, xml_file: str, csv_file: str, desc_file: str = None):
        """
        将BLAST XML结果文件转换为CSV格式
        
        Args:
            xml_file (str): 输入的XML文件路径
            csv_file (str): 输出的CSV文件路径
            desc_file (str, optional): 输出的描述文件路径
        """
        try:
            # 解析XML文件
            with open(xml_file, 'r', encoding='utf-8') as f:
                blast_record = NCBIXML.read(f)
            
            # 准备CSV数据
            csv_data = []
            
            # 处理每个比对结果
            for i, alignment in enumerate(blast_record.alignments):
                # 获取标题
                title = alignment.title
                
                # 提取信息
                accession = ""
                species = ""
                genus = ""
                strain = ""
                gene_type = ""
                sequence_type = ""
                
                # 提取访问号
                accession_match = re.search(r'gi\|.*?\|.*?\|([A-Za-z0-9_.]+)\|', title)
                if accession_match:
                    accession = accession_match.group(1)
                else:
                    # 尝试其他格式的访问号
                    other_accession_match = re.search(r'([A-Za-z0-9_.]+)(?:\.[0-9]+)?', title)
                    if other_accession_match:
                        accession = other_accession_match.group(1)
                
                # 提取基因类型
                gene_patterns = [
                    r'((?:16S|23S|18S)\s+ribosomal\s+RNA(?:\s+gene)?)',
                    r'(16S\s+rRNA\s+gene)',
                    r'(ribosomal\s+RNA\s+gene)',
                    r'(gene\s+for\s+16S\s+rRNA)'
                ]
                
                for pattern in gene_patterns:
                    gene_match = re.search(pattern, title, re.IGNORECASE)
                    if gene_match:
                        gene_type = gene_match.group(1)
                        break
                
                # 提取序列类型
                sequence_patterns = [
                    r'(partial|complete)\s+(?:sequence|genome)',
                    r'(partial\s+16S\s+rRNA\s+gene)'
                ]
                
                for pattern in sequence_patterns:
                    seq_match = re.search(pattern, title, re.IGNORECASE)
                    if seq_match:
                        sequence_type = seq_match.group(0)
                        break
                
                # 提取菌株信息
                strain_patterns = [
                    r'(strain\s+[A-Za-z0-9\-._]+)',
                    r'(isolate\s+[A-Za-z0-9\-._]+)',
                    r'(clone\s+[A-Za-z0-9\-._]+)'
                ]
                
                for pattern in strain_patterns:
                    strain_match = re.search(pattern, title, re.IGNORECASE)
                    if strain_match:
                        strain = strain_match.group(1)
                        break
                
                # 提取物种和属名
                # 先尝试从标题中提取完整的物种名
                species_match = re.search(r'([A-Z][a-z]+(?:\s+[a-z]+)?)\s+(?:16S|23S|18S)', title)
                if not species_match:
                    species_match = re.search(r'([A-Z][a-z]+(?:\s+[a-z]+)?)\s+(?:strain|isolate|clone)', title)
                if not species_match:
                    species_match = re.search(r'([A-Z][a-z]+(?:\s+[a-z]+)?)\b', title)
                
                if species_match:
                    species = species_match.group(1)
                    # 提取属名（第一个单词）
                    genus_match = re.search(r'^([A-Z][a-z]+)', species)
                    if genus_match:
                        genus = genus_match.group(1)
                
                # 处理每个HSP（高得分片段对）
                for hsp in alignment.hsps:
                    # 计算相似度
                    identity_pct = (hsp.identities / hsp.align_length * 100) if hsp.align_length > 0 else 0
                    
                    # 准备CSV行数据
                    csv_row = {
                        '标题': title,
                        '长度': alignment.length,
                        '访问号': accession,
                        '物种': species,
                        '属名': genus,
                        '菌株': strain,
                        '基因类型': gene_type,
                        '序列类型': sequence_type,
                        '高得分片段对(HSPs)': 1,  # 每行代表一个HSP
                        'E值': f"{hsp.expect:.2e}",
                        '比对长度': hsp.align_length,
                        '相同碱基数': hsp.identities,
                        '相似度': f"{identity_pct:.2f}%",
                        '缺口数': hsp.gaps,
                        '查询起始-结束': f"{hsp.query_start}-{hsp.query_end}",
                        '命中起始-结束': f"{hsp.sbjct_start}-{hsp.sbjct_end}"
                    }
                    csv_data.append(csv_row)

            
            # 写入CSV文件
            if csv_data:
                fieldnames = [
                    '标题', '长度', '访问号', '物种', '属名', '菌株', '基因类型', '序列类型',
                    '高得分片段对(HSPs)', 'E值', '比对长度', '相同碱基数', '相似度', '缺口数',
                    '查询起始-结束', '命中起始-结束'
                ]
                
                # 确保输出目录存在
                Path(csv_file).parent.mkdir(parents=True, exist_ok=True)
                
                with open(csv_file, 'w', newline='', encoding='utf-8-sig') as f:
                    writer = csv.DictWriter(f, fieldnames=fieldnames)
                    writer.writeheader()
                    writer.writerows(csv_data)
                
                print(f"成功转换XML到CSV: {csv_file}")
                
                # 提取并保存术语到预定义术语文件
                self._extract_and_save_terms(csv_file)
            else:
                # 创建空的CSV文件
                Path(csv_file).parent.mkdir(parents=True, exist_ok=True)
                with open(csv_file, 'w', newline='', encoding='utf-8-sig') as f:
                    pass
                print(f"没有找到比对结果，创建了空的CSV文件: {csv_file}")
            
            # 生成描述文件
            if desc_file:
                self._generate_description_file(blast_record, desc_file)
                
        except Exception as e:
            print(f"转换过程中出错: {e}")
            raise
    
    def _generate_description_file(self, blast_record, desc_file: str):
        """
        生成描述文件
        
        Args:
            blast_record: BLAST记录对象
            desc_file (str): 描述文件路径
        """
        try:
            # 确保输出目录存在
            Path(desc_file).parent.mkdir(parents=True, exist_ok=True)
            
            with open(desc_file, 'w', encoding='utf-8') as f:
                f.write("BLAST结果统计信息\n")
                f.write("=" * 50 + "\n")
                f.write(f"查询序列长度: {blast_record.query_length}\n")
                f.write(f"查询序列名称: {blast_record.query}\n")
                f.write(f"找到的比对数: {len(blast_record.alignments)}\n")
                
                # 统计信息
                if blast_record.alignments:
                    f.write("\n详细统计:\n")
                    f.write("-" * 30 + "\n")
                    
                    # E值分布
                    e_values = []
                    identities = []
                    
                    for alignment in blast_record.alignments:
                        if alignment.hsps:
                            hsp = alignment.hsps[0]  # 取第一个HSP
                            e_values.append(hsp.expect)
                            identity_pct = (hsp.identities / hsp.align_length * 100) if hsp.align_length > 0 else 0
                            identities.append(identity_pct)
                    
                    if e_values:
                        f.write(f"最小E值: {min(e_values):.2e}\n")
                        f.write(f"最大E值: {max(e_values):.2e}\n")
                        f.write(f"平均E值: {sum(e_values)/len(e_values):.2e}\n")
                    
                    if identities:
                        f.write(f"最小相似度: {min(identities):.2f}%\n")
                        f.write(f"最大相似度: {max(identities):.2f}%\n")
                        f.write(f"平均相似度: {sum(identities)/len(identities):.2f}%\n")
                
                f.write("\n生成时间: 当前时间\n")
                
            print(f"成功生成描述文件: {desc_file}")
                
        except Exception as e:
            print(f"生成描述文件时出错: {e}")

    def _extract_and_save_terms(self, csv_file_path: str):
        """
        提取并保存术语到预定义术语文件
        
        Args:
            csv_file_path (str): CSV文件路径
        """
        try:
            from src.utils.translation.term_extractor import TermExtractor
            term_extractor = TermExtractor()
            term_extractor.extract_blast_result_terms(csv_file_path)
        except Exception as e:
            print(f"提取术语时出错: {e}")
            import traceback
            traceback.print_exc()



def get_blast_result_converter() -> BlastResultConverter:
    """
    获取BLAST结果转换器实例
    
    Returns:
        BlastResultConverter: 结果转换器实例
    """
    return BlastResultConverter()