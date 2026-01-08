"""
翻译数据管理器模块
负责管理翻译数据的加载、存储和检索 - 优化版
"""

import csv
import os
from pathlib import Path
from typing import Dict, Optional


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
        # 优化路径获取逻辑：使用更稳健的pathlib操作
        # 假设当前文件位于 src/utils/translation/
        # parents[2] -> src/, parents[3] -> 项目根目录
        self.project_root = Path(__file__).resolve().parents[3]

        if not os.path.isabs(csv_file):
            self.csv_file = str(self.project_root / csv_file)
        else:
            self.csv_file = csv_file

        # 初始化数据结构
        self.translations: Dict[str, str] = {}
        self.term_categories: Dict[str, str] = {}

        # 初始化分类字典，确保常用键存在
        self.translations_by_category: Dict[str, Dict[str, str]] = {
            key: {} for key in ['species', 'genus', 'strain', 'gene', 'sequence', 'other']
        }

        # 统一加载数据
        self._load_all_data()

    def _upsert_memory(self, english: str, chinese: str, category: str):
        """
        [内部方法] 统一更新内存中的数据结构
        确保三个字典状态始终保持同步
        """
        # 1. 更新主字典
        self.translations[english] = chinese

        # 2. 规范化分类
        if category not in self.translations_by_category:
            category = 'other'

        # 3. 更新分类字典
        self.translations_by_category[category][english] = chinese

        # 4. 更新反向索引
        self.term_categories[english] = category

    def _parse_row(self, row: dict):
        """[内部方法] 解析单行数据并更新内存"""
        if 'english' in row and 'chinese' in row:
            english = row['english'].strip()
            chinese = row['chinese'].strip()
            category = row.get('category', 'other').strip() or 'other'

            if english and chinese:
                self._upsert_memory(english, chinese, category)

    def _load_all_data(self):
        """加载所有数据（用户数据 + 预定义数据）"""
        # 1. 加载用户自定义数据
        if os.path.exists(self.csv_file) and os.path.getsize(self.csv_file) > 0:
            try:
                with open(self.csv_file, 'r', encoding='utf-8') as f:
                    reader = csv.DictReader(f)
                    # 检查是否为旧格式
                    fieldnames = reader.fieldnames or []
                    if any(h in fieldnames for h in ['序号', '物种英文名']):
                        self._create_empty_csv()
                    else:
                        for row in reader:
                            self._parse_row(row)
            except Exception as e:
                print(f"警告: 加载用户翻译数据时出错: {e}")
                self._create_empty_csv()
        else:
            self._create_empty_csv()

        # 2. 加载预定义数据 (作为补充，不覆盖用户数据)
        predefined_file = self.project_root / "predefined_terms.csv"
        if predefined_file.exists():
            try:
                with open(predefined_file, 'r', encoding='utf-8') as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        english = row.get('english', '').strip()
                        # 仅当该术语尚未存在时才添加 (用户数据优先级 > 预定义数据)
                        if english and english not in self.translations:
                            self._parse_row(row)
            except Exception as e:
                print(f"警告: 加载预定义术语时出错: {e}")

    def _save_translations(self):
        """
        保存翻译数据到CSV文件
        优化：直接转储内存数据，不再重复读取预定义文件
        """
        try:
            # 确保目录存在
            Path(self.csv_file).parent.mkdir(parents=True, exist_ok=True)

            with open(self.csv_file, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(['english', 'chinese', 'category'])

                # 写入所有内存中的数据
                for english, chinese in self.translations.items():
                    category = self.term_categories.get(english, 'other')
                    writer.writerow([english, chinese, category])

        except Exception as e:
            print(f"警告: 保存翻译数据时出错: {e}")

    def _create_empty_csv(self):
        """创建空的CSV文件并写入标题行"""
        try:
            Path(self.csv_file).parent.mkdir(parents=True, exist_ok=True)
            with open(self.csv_file, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(['english', 'chinese', 'category'])
        except Exception as e:
            print(f"警告: 创建空CSV文件时出错: {e}")

    # ================= 公共接口保持不变 =================

    def get_translation(self, english_text: str, category: str = None) -> Optional[str]:
        """获取英文文本的中文翻译"""
        english_text = english_text.strip()

        if category and category in self.translations_by_category:
            return self.translations_by_category[category].get(english_text)

        return self.translations.get(english_text)

    def add_translation(self, english_text: str, chinese_text: str, category: str = 'other'):
        """添加新的翻译条目"""
        english_text = english_text.strip()
        chinese_text = chinese_text.strip()
        category = category.strip() if category else 'other'

        if english_text and chinese_text:
            self._upsert_memory(english_text, chinese_text, category)
            self._save_translations()

    def update_translation(self, english_text: str, chinese_text: str, category: str = 'other'):
        """更新翻译条目"""
        self.add_translation(english_text, chinese_text, category)

    def contains(self, english_text: str, category: str = None) -> bool:
        """检查是否包含指定的英文文本翻译"""
        return self.get_translation(english_text, category) is not None

    def get_all_terms(self) -> Dict[str, str]:
        """获取所有翻译条目"""
        return self.translations.copy()

    def get_terms_by_category(self, category: str) -> Dict[str, str]:
        """根据分类获取翻译条目"""
        if category in self.translations_by_category:
            return self.translations_by_category[category].copy()
        return {}


def get_translation_data_manager(csv_file: str = "translation_data.csv") -> TranslationDataManager:
    """获取翻译数据管理器实例"""
    return TranslationDataManager(csv_file)