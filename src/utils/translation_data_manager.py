"""
翻译数据管理模块
用于管理本地翻译数据的存储和更新，支持CSV格式存储
"""

import csv
import os
from typing import Dict, Optional, List, Tuple
import pandas as pd


class TranslationDataManager:
    """
    翻译数据管理器
    负责管理本地翻译数据的存储、检索和更新
    支持术语分类存储以优化查询性能
    """
    
    def __init__(self, data_file: str = "translation_data.csv"):
        """
        初始化翻译数据管理器
        
        Args:
            data_file (str): CSV数据文件路径
        """
        self.data_file = data_file
        # 存储完整的翻译数据记录，包括分类信息
        self.translation_records: List[Dict[str, str]] = []
        # 快速查找字典
        self.translation_data: Dict[str, str] = {}
        # 按类别存储翻译数据，提高查询效率
        self.translation_by_category: Dict[str, Dict[str, str]] = {}
        self._load_data()
    
    def _load_data(self):
        """
        从CSV文件加载翻译数据
        """
        if not os.path.exists(self.data_file):
            # 如果文件不存在，创建一个带有表头的空文件
            with open(self.data_file, 'w', newline='', encoding='utf-8') as csvfile:
                writer = csv.writer(csvfile)
                writer.writerow(['english', 'chinese', 'category', 'subcategory'])
            return
        
        try:
            # 使用pandas读取CSV文件
            df = pd.read_csv(self.data_file, encoding='utf-8')
            
            # 将数据转换为字典格式
            self.translation_data = dict(zip(df['english'], df['chinese']))
            
            # 存储完整的记录
            self.translation_records = df.to_dict('records')
            
            # 按类别组织数据
            self.translation_by_category = {}
            for record in self.translation_records:
                category = record.get('category', 'unknown')
                if category not in self.translation_by_category:
                    self.translation_by_category[category] = {}
                self.translation_by_category[category][record['english']] = record['chinese']
                
        except Exception as e:
            print(f"警告: 加载翻译数据文件时出错: {e}")
            self.translation_data = {}
            self.translation_records = []
    
    def _save_data(self):
        """
        将翻译数据保存到CSV文件
        """
        try:
            # 创建DataFrame
            df = pd.DataFrame(self.translation_records)
            # 确保必要的列存在
            for col in ['english', 'chinese', 'category', 'subcategory']:
                if col not in df.columns:
                    df[col] = ""
            # 保存到CSV文件
            df.to_csv(self.data_file, index=False, encoding='utf-8')
            print(f"数据已保存至 {self.data_file}")  # 添加提示信息
        except Exception as e:
            print(f"警告: 保存翻译数据时出错: {e}")

    def get_translation(self, english: str) -> Optional[str]:
        """
        获取指定英文术语的中文翻译
        
        Args:
            english (str): 英文术语
            
        Returns:
            str or None: 中文翻译，如果找不到则返回None
        """
        return self.translation_data.get(english)
    
    def get_translation_with_context(self, english: str, category: str = None) -> Optional[str]:
        """
        根据类别获取指定英文术语的中文翻译
        
        Args:
            english (str): 英文术语
            category (str): 术语类别
            
        Returns:
            str or None: 中文翻译，如果找不到则返回None
        """
        if category and category in self.translation_by_category:
            return self.translation_by_category[category].get(english)
        return self.translation_data.get(english)
    
    def add_translation(self, english: str, chinese: str, category: str = "unknown", subcategory: str = ""):
        """
        添加新的翻译条目
        优化：避免存储过长的摘要信息，只存储关键术语
        
        Args:
            english (str): 英文术语
            chinese (str): 中文翻译
            category (str): 术语类别（如菌种、基因等）
            subcategory (str): 子类别
        """
        # 检查是否为摘要信息（包含多个">"字符或长度过长）
        if english.count('>') > 1 or len(english) > 200:
            print(f"跳过摘要信息存储: {english[:50]}...")
            return
            
        # 只有当翻译内容不为空且与原文字不同时才添加
        if english and chinese and english.strip() and chinese.strip() and english != chinese:
            # 额外检查：确保中文翻译不是英文原文的简单变体
            if english.strip().lower() != chinese.strip().lower():
                # 更新快速查找字典
                self.translation_data[english] = chinese
                
                # 检查是否已存在该条目
                existing_index = None
                for i, record in enumerate(self.translation_records):
                    if record['english'] == english:
                        existing_index = i
                        break
                
                # 创建新记录
                new_record = {
                    'english': english,
                    'chinese': chinese,
                    'category': category,
                    'subcategory': subcategory
                }
                
                # 更新或添加记录
                if existing_index is not None:
                    self.translation_records[existing_index] = new_record
                else:
                    self.translation_records.append(new_record)
                
                # 更新分类存储
                if category not in self.translation_by_category:
                    self.translation_by_category[category] = {}
                self.translation_by_category[category][english] = chinese
                
                # 确保数据被保存
                self._save_data()

    def update_translation(self, english: str, chinese: str, category: str = None, subcategory: str = None):
        """
        更新现有翻译条目
        
        Args:
            english (str): 英文术语
            chinese (str): 新的中文翻译
            category (str, optional): 新的术语类别
            subcategory (str, optional): 新的子类别
        """
        # 查找现有记录
        existing_index = None
        existing_record = None
        for i, record in enumerate(self.translation_records):
            if record['english'] == english:
                existing_index = i
                existing_record = record
                break
        
        if existing_record:
            # 更新翻译
            self.translation_data[english] = chinese
            
            # 更新记录
            updated_record = existing_record.copy()
            updated_record['chinese'] = chinese
            if category is not None:
                updated_record['category'] = category
            if subcategory is not None:
                updated_record['subcategory'] = subcategory
                
            self.translation_records[existing_index] = updated_record
            
            # 更新分类存储
            record_category = updated_record['category']
            if record_category not in self.translation_by_category:
                self.translation_by_category[record_category] = {}
            self.translation_by_category[record_category][english] = chinese
            
            self._save_data()
    
    def remove_translation(self, english: str):
        """
        删除翻译条目
        
        Args:
            english (str): 英文术语
        """
        # 从快速查找字典中删除
        if english in self.translation_data:
            del self.translation_data[english]
        
        # 从记录列表中删除
        self.translation_records = [record for record in self.translation_records if record['english'] != english]
        
        # 从分类存储中删除
        for category_dict in self.translation_by_category.values():
            if english in category_dict:
                del category_dict[english]
        
        # 保存数据
        self._save_data()
    
    def get_statistics(self):
        """
        获取翻译数据统计信息
        
        Returns:
            dict: 包含各类翻译条目数量的字典
        """
        # 按类别统计
        category_stats = {}
        for record in self.translation_records:
            category = record.get('category', 'unknown')
            category_stats[category] = category_stats.get(category, 0) + 1
        
        # 添加总计
        category_stats['total_entries'] = len(self.translation_records)
        
        return category_stats
    
    def search_translations(self, query: str) -> List[Dict[str, str]]:
        """
        搜索翻译条目
        
        Args:
            query (str): 搜索查询
            
        Returns:
            list: 匹配的翻译条目列表
        """
        results = []
        query_lower = query.lower()
        
        for record in self.translation_records:
            if (query_lower in record['english'].lower() or 
                query_lower in record['chinese'].lower() or
                query_lower in record.get('category', '').lower() or
                query_lower in record.get('subcategory', '').lower()):
                results.append(record)
        
        return results


def get_translation_data_manager(data_file: str = "translation_data.csv") -> TranslationDataManager:
    """
    获取翻译数据管理器实例
    
    Args:
        data_file (str): CSV数据文件路径
        
    Returns:
        TranslationDataManager: 数据管理器实例
    """
    return TranslationDataManager(data_file)