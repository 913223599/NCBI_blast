"""
术语提取和存储模块
用于从生物学术语中提取关键术语并存储到翻译数据库中
"""

import re
import csv
import os
from typing import List, Tuple, Optional
from pathlib import Path


class TermExtractor:
    """
    术语提取器
    专门用于从生物学术语中提取关键术语并存储到翻译数据库中
    """

    def __init__(self, translation_data_manager=None):
        """
        初始化术语提取器
        
        Args:
            translation_data_manager: 翻译数据管理器实例
        """
        self.translation_data_manager = translation_data_manager

    def extract_and_store_key_terms(self, original: str, translated: str):
        """
        提取并存储关键术语翻译
        根据NCBI官方的物种分类模式进行结构化存储
        
        Args:
            original (str): 原文
            translated (str): 译文
        """
        # 如果没有翻译数据管理器，则直接返回
        if not self.translation_data_manager:
            return
            
        # 从翻译结果中提取纯文本（去除[AI]或[本地]前缀）
        clean_translated = translated
        if translated.startswith('[AI]'):
            clean_translated = translated[4:]  # 去掉前缀[AI]
        elif translated.startswith('[本地]'):
            clean_translated = translated[4:]  # 去掉前缀[本地]
            
        # 将翻译结果添加到翻译数据管理器中
        # 先尝试确定术语的分类
        category = 'other'  # 默认分类
        
        # 根据术语特征判断分类
        if ' ' in original:  # 包含空格的可能是完整描述
            if 'gene' in original.lower() or 'rna' in original.lower():
                category = 'gene'
            elif 'sequence' in original.lower() or 'genome' in original.lower():
                category = 'sequence'
            elif 'strain' in original.lower() or 'isolate' in original.lower():
                category = 'strain'
            elif any(bac in original.lower() for bac in ['bacillus', 'staphylococcus', 'escherichia']):
                category = 'species'
        else:  # 单个词更可能是分类名称
            if any(suffix in original.lower() for suffix in ['s', 'us', 'a', 'um', 'er']):
                category = 'genus'  # 属名通常以这些字母结尾
            elif any(bac in original.lower() for bac in ['bacillus', 'staphylococcus', 'escherichia']):
                category = 'species'
                
        # 不再存储到本地数据库，而是直接使用术语数据库
        # 添加到翻译数据库
        try:
            self.translation_data_manager.add_translation(original, clean_translated, category)
            print(f"[翻译调试] 已将'{original}'的翻译结果存储到术语数据库，分类为'{category}'")
        except Exception as e:
            print(f"[翻译调试] 存储翻译结果到术语数据库失败: {e}")

    def extract_blast_result_terms(self, csv_file_path: str):
        """
        从BLAST结果CSV文件中提取术语并保存到预定义术语文件中
        
        Args:
            csv_file_path (str): BLAST结果CSV文件路径
        """
        # 确定预定义术语文件路径
        predefined_terms_file = Path(__file__).parent.parent.parent.parent / "predefined_terms.csv"
        
        # 读取现有的预定义术语
        existing_terms = set()
        existing_terms_dict = {}  # 用于快速查找
        if predefined_terms_file.exists():
            with open(predefined_terms_file, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    term_key = (row['english'], row['category'])
                    existing_terms.add(term_key)
                    existing_terms_dict[term_key] = row['chinese']
        
        # 从CSV文件中提取术语
        new_terms = {}
        try:
            with open(csv_file_path, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    # 提取基因类型
                    gene_type = row.get('基因类型', '').strip()
                    if gene_type:
                        translated_gene = self._translate_term_from_db(gene_type, 'gene')
                        new_terms[(gene_type, 'gene')] = translated_gene
                    
                    # 提取序列类型
                    sequence_type = row.get('序列类型', '').strip()
                    if sequence_type:
                        translated_sequence = self._translate_term_from_db(sequence_type, 'sequence')
                        new_terms[(sequence_type, 'sequence')] = translated_sequence
                    
                    # 提取菌株信息（可能包含术语和编码）
                    strain = row.get('菌株', '').strip()
                    if strain:
                        # 分离术语部分和编码部分
                        strain_term, strain_code = self._parse_strain_info(strain)
                        if strain_term:
                            translated_strain = self._translate_term_from_db(strain_term, 'strain')
                            new_terms[(strain_term, 'strain')] = translated_strain
        except Exception as e:
            print(f"读取CSV文件时出错: {e}")
            return
        
        # 合并现有术语和新术语
        all_terms = []
        # 先添加现有术语
        for term_key, chinese in existing_terms_dict.items():
            all_terms.append((term_key[0], chinese, term_key[1]))
        
        # 再添加新术语（避免重复）
        for term_key, chinese in new_terms.items():
            if term_key not in existing_terms:
                all_terms.append((term_key[0], chinese, term_key[1]))
        
        # 将所有术语写入预定义术语文件，分类使用英文
        try:
            with open(predefined_terms_file, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(['english', 'chinese', 'category'])
                for term in all_terms:
                    writer.writerow(term)
            print(f"成功更新预定义术语文件: {predefined_terms_file}")
        except Exception as e:
            print(f"写入预定义术语文件时出错: {e}")

    def _translate_term_from_db(self, term: str, category: str = None) -> str:
        """
        从预定义术语数据库中获取术语翻译
        
        Args:
            term (str): 英文术语
            category (str): 术语类别（可选）
            
        Returns:
            str: 中文翻译
        """
        # 确定预定义术语文件路径
        predefined_terms_file = Path(__file__).parent.parent.parent.parent / "predefined_terms.csv"
        
        # 如果文件不存在，返回原术语
        if not predefined_terms_file.exists():
            return term
            
        try:
            # 读取预定义术语文件
            with open(predefined_terms_file, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    # 精确匹配术语
                    if row['english'].strip() == term.strip():
                        return row['chinese'].strip()
                    
                    # 如果指定了类别，也检查类别是否匹配
                    if category and row['category'].strip() == category.strip() and row['english'].strip() == term.strip():
                        return row['chinese'].strip()
        except Exception as e:
            print(f"读取预定义术语文件时出错: {e}")
            
        # 如果没有找到匹配的翻译，返回原术语
        return term

    def _translate_gene_term(self, gene_term: str) -> str:
        """
        翻译基因术语
        
        Args:
            gene_term (str): 英文基因术语
            
        Returns:
            str: 中文翻译
        """
        return self._translate_term_from_db(gene_term, 'gene')

    def _translate_sequence_term(self, sequence_term: str) -> str:
        """
        翻译序列术语
        
        Args:
            sequence_term (str): 英文序列术语
            
        Returns:
            str: 中文翻译
        """
        return self._translate_term_from_db(sequence_term, 'sequence')

    def _translate_strain_term(self, strain_term: str) -> str:
        """
        翻译菌株术语
        
        Args:
            strain_term (str): 英文菌株术语
            
        Returns:
            str: 中文翻译
        """
        return self._translate_term_from_db(strain_term, 'strain')

    def _parse_strain_info(self, strain_info: str) -> Tuple[str, str]:
        """
        解析菌株信息，分离术语部分和编码部分
        
        Args:
            strain_info (str): 完整的菌株信息
            
        Returns:
            tuple: (术语部分, 编码部分)
        """
        if not strain_info:
            return "", ""
        
        # 分离术语和编码部分
        parts = strain_info.split(' ', 1)
        if len(parts) == 2:
            return parts[0], parts[1]
        else:
            return strain_info, ""