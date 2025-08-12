"""
BLAST结果翻译模块
用于处理和翻译BLAST结果中的物种、属名和菌株信息
"""

import csv
import os
from typing import Dict
from pathlib import Path
import pandas as pd


class BlastResultTranslator:
    """
    BLAST结果翻译器
    专门用于处理BLAST结果中物种、属名和菌株的翻译
    """
    
    def __init__(self, data_file: str = "translation_data.csv"):
        """
        初始化BLAST结果翻译器
        
        Args:
            data_file (str): CSV数据文件路径
        """
        # 确保使用项目根目录下的翻译数据文件
        if not os.path.isabs(data_file):
            # 获取项目根目录
            project_root = Path(__file__).parent.parent.parent.parent
            data_file = os.path.join(project_root, data_file)
        
        self.data_file = data_file
        self.translations: Dict[str, str] = {}
        self._load_data()
    
    def _load_data(self):
        """
        从CSV文件加载翻译数据
        """
        if not os.path.exists(self.data_file):
            # 如果文件不存在，创建一个带有表头的空文件
            with open(self.data_file, 'w', newline='', encoding='utf-8') as csvfile:
                writer = csv.writer(csvfile)
                # 使用新的表头格式
                writer.writerow(['english', 'chinese', 'category'])
            return
        
        try:
            # 使用pandas读取CSV文件
            df = pd.read_csv(self.data_file, encoding='utf-8')
            # 将数据转换为字典格式，英文为键，中文为值
            self.translations = dict(zip(df['english'], df['chinese']))
        except Exception as e:
            print(f"警告: 加载翻译数据文件时出错: {e}")
            self.translations = {}
    
    def translate_species(self, species_english: str) -> str:
        """
        翻译物种名称
        
        Args:
            species_english (str): 英文物种名称
            
        Returns:
            str: 中文物种名称，如果找不到则返回原文
        """
        # 确保输入是字符串类型
        if not isinstance(species_english, str):
            return str(species_english) if species_english is not None else ""
        
        # 直接在翻译字典中查找
        return self.translations.get(species_english, species_english)
    
    def translate_genus(self, genus_english: str) -> str:
        """
        翻译属名
        
        Args:
            genus_english (str): 英文属名
            
        Returns:
            str: 中文属名，如果找不到则返回原文
        """
        # 确保输入是字符串类型
        if not isinstance(genus_english, str):
            return str(genus_english) if genus_english is not None else ""
        
        # 直接在翻译字典中查找
        return self.translations.get(genus_english, genus_english)
    
    def translate_strain(self, strain_english: str) -> str:
        """
        翻译菌株名称
        
        Args:
            strain_english (str): 英文菌株名称
            
        Returns:
            str: 中文菌株名称，如果找不到则返回原文
        """
        # 确保输入是字符串类型
        if not isinstance(strain_english, str):
            return str(strain_english) if strain_english is not None else ""
        
        # 直接在翻译字典中查找
        return self.translations.get(strain_english, strain_english)


def get_blast_result_translator(data_file: str = "translation_data.csv") -> BlastResultTranslator:
    """
    获取BLAST结果翻译器实例
    
    Args:
        data_file (str): CSV数据文件路径
        
    Returns:
        BlastResultTranslator: BLAST结果翻译器实例
    """
    return BlastResultTranslator(data_file)