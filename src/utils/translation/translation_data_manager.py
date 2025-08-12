"""
翻译数据管理器模块
负责管理翻译数据的加载、存储和检索
"""

import csv
import os
from typing import Dict, Optional, Tuple, List
from pathlib import Path


class TranslationDataManager:
    """
    翻译数据管理器
    负责管理翻译数据的加载、存储和检索
    """
    
    def __init__(self, csv_file: str = "translation_data.csv"):
        """
        初始化翻译数据管理器
        
        Args:
            csv_file (str): 包含翻译数据的CSV文件路径
        """
        # 确保使用项目根目录下的translation_data.csv文件
        if not os.path.isabs(csv_file):
            # 获取项目根目录下的translation_data.csv文件路径
            current_dir = Path(__file__).parent
            project_root = current_dir.parent.parent
            csv_file = str(project_root / csv_file)
        
        self.csv_file = csv_file
        self.translations: Dict[str, str] = {}
        # 按分类存储的翻译数据，提高查询效率
        self.translations_by_category: Dict[str, Dict[str, str]] = {
            'species': {},    # 物种
            'genus': {},      # 属名
            'strain': {},     # 菌株
            'gene': {},       # 基因类型
            'sequence': {},   # 序列类型
            'other': {}       # 其他
        }
        # 保存每个术语的分类信息
        self.term_categories: Dict[str, str] = {}
        self._load_translations()
        self._load_predefined_terms()  # 添加预定义术语加载
    
    def _load_translations(self):
        """加载翻译数据"""
        try:
            # 检查文件是否存在且不为空
            if os.path.exists(self.csv_file) and os.path.getsize(self.csv_file) > 0:
                with open(self.csv_file, 'r', encoding='utf-8') as f:
                    reader = csv.DictReader(f)
                    # 检查是否是旧格式（包含已弃用的表头）
                    if any(header in reader.fieldnames for header in ['序号', '物种英文名', '属名英文名', '菌株英文名']):
                        # 旧格式文件，需要重新创建
                        self.translations = {}
                        self.term_categories = {}
                        # 初始化分类字典
                        for category in self.translations_by_category:
                            self.translations_by_category[category] = {}
                        # 创建带有正确标题行的空文件
                        self._create_empty_csv()
                    else:
                        # 新格式文件，正常加载
                        for row in reader:
                            # 确保行中有英文和中文字段
                            if 'english' in row and 'chinese' in row:
                                english = row['english'].strip()
                                chinese = row['chinese'].strip()
                                # 获取分类信息，如果没有则默认为'other'
                                category = row.get('category', 'other').strip()
                                if not category:
                                    category = 'other'
                                
                                if english and chinese:
                                    self.translations[english] = chinese
                                    self.term_categories[english] = category
                                    # 按分类存储
                                    if category in self.translations_by_category:
                                        self.translations_by_category[category][english] = chinese
                                    else:
                                        self.translations_by_category['other'][english] = chinese
                                        self.term_categories[english] = 'other'
            else:
                # 如果文件不存在或为空，初始化空的翻译字典
                self.translations = {}
                self.term_categories = {}
                # 初始化分类字典
                for category in self.translations_by_category:
                    self.translations_by_category[category] = {}
                # 创建带有标题行的空文件
                self._create_empty_csv()
        except Exception as e:
            print(f"警告: 加载翻译数据文件时出错: {e}")
            self.translations = {}
            self.term_categories = {}
            # 初始化分类字典
            for category in self.translations_by_category:
                self.translations_by_category[category] = {}
    
    def _create_empty_csv(self):
        """创建空的CSV文件并写入标题行"""
        try:
            with open(self.csv_file, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(['english', 'chinese', 'category'])  # 添加分类列
        except Exception as e:
            print(f"警告: 创建空CSV文件时出错: {e}")
    
    def get_translation(self, english_text: str, category: str = None) -> Optional[str]:
        """
        获取英文文本的中文翻译
        
        Args:
            english_text (str): 英文文本
            category (str, optional): 分类，如果提供则只在该分类中查找
            
        Returns:
            str: 中文翻译，如果未找到则返回None
        """
        english_text = english_text.strip()
        
        # 如果提供了分类，则只在该分类中查找
        if category and category in self.translations_by_category:
            return self.translations_by_category[category].get(english_text)
        
        # 否则在所有翻译中查找
        return self.translations.get(english_text)
    
    def add_translation(self, english_text: str, chinese_text: str, category: str = 'other'):
        """
        添加新的翻译条目
        
        Args:
            english_text (str): 英文文本
            chinese_text (str): 中文翻译
            category (str): 分类 (species, genus, strain, gene, sequence, other)
        """
        english_text = english_text.strip()
        chinese_text = chinese_text.strip()
        category = category.strip() if category else 'other'
        
        # 验证分类
        if category not in self.translations_by_category:
            category = 'other'
        
        if english_text and chinese_text:
            # 更新内存中的字典
            self.translations[english_text] = chinese_text
            self.term_categories[english_text] = category
            self.translations_by_category[category][english_text] = chinese_text
            # 保存到文件
            self._save_translations()
    
    def update_translation(self, english_text: str, chinese_text: str, category: str = 'other'):
        """
        更新翻译条目
        
        Args:
            english_text (str): 英文文本
            chinese_text (str): 中文翻译
            category (str): 分类
        """
        self.add_translation(english_text, chinese_text, category)
    
    def contains(self, english_text: str, category: str = None) -> bool:
        """
        检查是否包含指定的英文文本翻译
        
        Args:
            english_text (str): 英文文本
            category (str, optional): 分类，如果提供则只在该分类中查找
            
        Returns:
            bool: 如果包含返回True，否则返回False
        """
        return self.get_translation(english_text, category) is not None
    
    def get_all_terms(self) -> Dict[str, str]:
        """
        获取所有翻译条目
        
        Returns:
            Dict[str, str]: 所有翻译条目
        """
        return self.translations.copy()
    
    def get_terms_by_category(self, category: str) -> Dict[str, str]:
        """
        根据分类获取翻译条目
        
        Args:
            category (str): 分类
            
        Returns:
            Dict[str, str]: 指定分类的翻译条目
        """
        if category in self.translations_by_category:
            return self.translations_by_category[category].copy()
        return {}
    
    def _save_translations(self):
        """保存翻译数据到CSV文件"""
        try:
            # 确保目录存在
            Path(self.csv_file).parent.mkdir(parents=True, exist_ok=True)
            
            # 写入所有翻译条目
            with open(self.csv_file, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(['english', 'chinese', 'category'])  # 写入标题行，包含分类列
                # 先写入预定义术语，确保它们不会被覆盖
                predefined_terms_written = set()
                predefined_terms_file = Path(__file__).parent.parent.parent.parent / "predefined_terms.csv"
                if predefined_terms_file.exists():
                    with open(predefined_terms_file, 'r', encoding='utf-8') as pf:
                        preader = csv.DictReader(pf)
                        for row in preader:
                            if 'english' in row and 'chinese' in row:
                                english = row['english'].strip()
                                chinese = row['chinese'].strip()
                                category = row.get('category', 'other').strip()
                                if not category:
                                    category = 'other'
                                
                                if english and chinese:
                                    writer.writerow([english, chinese, category])
                                    predefined_terms_written.add(english)
                
                # 再写入用户添加的术语，避免重复写入预定义术语
                for english, chinese in self.translations.items():
                    if english not in predefined_terms_written:
                        # 获取该条目的分类
                        category = self.term_categories.get(english, 'other')
                        writer.writerow([english, chinese, category])
        except Exception as e:
            print(f"警告: 保存翻译数据时出错: {e}")
    
    def _load_predefined_terms(self):
        """加载预定义术语文件中的翻译数据"""
        try:
            predefined_terms_file = Path(__file__).parent.parent.parent.parent / "predefined_terms.csv"
            if predefined_terms_file.exists():
                with open(predefined_terms_file, 'r', encoding='utf-8') as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        # 确保行中有英文和中文字段
                        if 'english' in row and 'chinese' in row:
                            english = row['english'].strip()
                            chinese = row['chinese'].strip()
                            category = row.get('category', 'other').strip()
                            if not category:
                                category = 'other'
                            
                            if english and chinese:
                                # 只有当翻译不存在时才添加预定义术语
                                if english not in self.translations:
                                    self.translations[english] = chinese
                                    self.term_categories[english] = category
                                    # 按分类存储
                                    if category in self.translations_by_category:
                                        self.translations_by_category[category][english] = chinese
                                    else:
                                        self.translations_by_category['other'][english] = chinese
                                        self.term_categories[english] = 'other'
        except Exception as e:
            print(f"警告: 加载预定义术语文件时出错: {e}")


def get_translation_data_manager(csv_file: str = "translation_data.csv") -> TranslationDataManager:
    """
    获取翻译数据管理器实例
    
    Args:
        csv_file (str): 包含翻译数据的CSV文件路径
        
    Returns:
        TranslationDataManager: 翻译数据管理器实例
    """
    return TranslationDataManager(csv_file)