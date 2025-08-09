"""
生物学专业术语翻译模块
提供生物学专业术语的英译中功能
使用更高效的数据结构支持大量数据的存储和检索
"""

import json
import re
import os
from typing import Dict, List, Tuple, Optional

# 导入通义千问翻译器
try:
    from .qwen_translator import get_qwen_translator, QwenTranslator
    QWEN_AVAILABLE = True
except ImportError:
    QWEN_AVAILABLE = False
    QwenTranslator = object  # 占位符

# 导入模拟翻译器（用于测试）
try:
    from .mock_qwen_translator import get_mock_qwen_translator, MockQwenTranslator
    MOCK_AVAILABLE = True
except ImportError:
    MOCK_AVAILABLE = False
    MockQwenTranslator = object  # 占位符

# 导入翻译数据管理器
try:
    from .translation_data_manager import get_translation_data_manager, TranslationDataManager
    TRANSLATION_DATA_MANAGER_AVAILABLE = True
except ImportError:
    TRANSLATION_DATA_MANAGER_AVAILABLE = False
    TranslationDataManager = object  # 占位符


class BiologyTranslator:
    """
    生物学专业术语翻译器
    专门用于生物学领域专业术语的翻译
    使用高效的数据结构支持大量数据的存储和检索
    """
    
    def __init__(self, data_file: Optional[str] = None, use_ai: bool = False, 
                 ai_api_key: Optional[str] = None, use_mock: bool = False):
        """
        初始化翻译器
        
        Args:
            data_file (str, optional): 包含翻译数据的CSV文件路径
            use_ai (bool): 是否使用AI翻译器
            ai_api_key (str, optional): AI翻译器API密钥
            use_mock (bool): 是否使用模拟AI翻译器（用于测试）
        """
        # 初始化翻译数据管理器
        self.translation_data_manager = None
        if TRANSLATION_DATA_MANAGER_AVAILABLE:
            csv_file = data_file or "translation_data.csv"
            self.translation_data_manager = get_translation_data_manager(csv_file)
        
        # AI翻译器相关属性
        self.use_ai = use_ai
        self.use_mock = use_mock
        self.ai_translator = None
        self.ai_api_key = ai_api_key
        
        # 初始化AI翻译器（如果启用）
        if self.use_mock and MOCK_AVAILABLE:
            try:
                self.ai_translator = get_mock_qwen_translator(self.ai_api_key)
            except Exception as e:
                print(f"警告: 无法初始化模拟AI翻译器: {e}")
                self.ai_translator = None
                self.use_mock = False
        elif self.use_ai and QWEN_AVAILABLE:
            try:
                self.ai_translator = get_qwen_translator(self.ai_api_key)
            except Exception as e:
                print(f"警告: 无法初始化AI翻译器: {e}")
                self.ai_translator = None
                self.use_ai = False
        elif self.use_ai and not QWEN_AVAILABLE:
            print("警告: 请求使用AI翻译器，但未安装dashscope库")
            self.use_ai = False
    
    def translate_text(self, text: str) -> str:
        """
        翻译整段文本中的生物学专业术语
        使用本地翻译数据优先，失败时使用AI翻译并回收数据
        
        Args:
            text (str): 英文文本
            
        Returns:
            str: 翻译后的文本
        """
        if not text:
            return text
            
        # 如果启用了模拟AI翻译且模拟翻译器可用，则使用模拟AI翻译
        if self.use_mock and self.ai_translator:
            try:
                result = self.ai_translator.translate_text(text)
                # 回收翻译数据
                if self.translation_data_manager:
                    self._collect_translations(text, result)
                return result
            except Exception as e:
                print(f"模拟AI翻译失败: {e}")
        
        # 如果启用了AI翻译且AI翻译器可用，则优先使用AI翻译
        elif self.use_ai and self.ai_translator:
            # 首先尝试从本地数据中翻译
            if self.translation_data_manager:
                local_result = self._translate_with_local_data(text)
                if local_result != text:  # 如果本地翻译成功
                    return local_result
            
            # 如果本地翻译失败或未启用，使用AI翻译
            try:
                result = self.ai_translator.translate_text(text)
                # 回收翻译数据
                if self.translation_data_manager:
                    self._collect_translations(text, result)
                return result
            except Exception as e:
                print(f"AI翻译失败: {e}")
                # 新增逻辑：AI翻译失败时，将原文存储到本地词典中
                if self.translation_data_manager:
                    self.translation_data_manager.add_translation(text, text)
        
        # 如果有本地数据管理器，尝试使用本地数据翻译
        if self.translation_data_manager:
            local_result = self._translate_with_local_data(text)
            if local_result != text:  # 如果本地翻译成功
                return local_result
        
        # 所有方法都失败，返回原文
        return text
    
    def _translate_with_local_data(self, text: str) -> str:
        """
        使用本地翻译数据翻译文本
        
        Args:
            text (str): 英文文本
            
        Returns:
            str: 翻译后的文本，如果无法翻译则返回原文
        """
        if not self.translation_data_manager:
            return text
            
        # 尝试直接匹配整个文本
        direct_translation = self.translation_data_manager.get_translation(text)
        if direct_translation:
            return direct_translation
            
        # 如果直接匹配失败，尝试逐词翻译
        words = text.split()
        translated_words = []
        all_translated = True
        
        for word in words:
            translation = self.translation_data_manager.get_translation(word)
            if translation:
                translated_words.append(translation)
            else:
                # 如果有任何词无法翻译，则整个翻译失败
                all_translated = False
                break
        
        # 只有当所有词都被翻译时才返回翻译结果
        if all_translated and translated_words:
            return " ".join(translated_words)
            
        # 否则返回原文
        return text
    
    def _collect_translations(self, original: str, translated: str):
        """
        收集并存储翻译数据，优化存储方式，拆分关键内容存储
        
        Args:
            original (str): 原文
            translated (str): 译文
        """
        if not self.translation_data_manager:
            return
            
        # 存储整句翻译
        self.translation_data_manager.add_translation(original, translated)
        
        # 拆分并存储关键内容翻译
        # 提取关键部分进行存储，如菌种名、基因名、序列类型等
        self._extract_and_store_key_terms(original, translated)
    
    def _extract_and_store_key_terms(self, original: str, translated: str):
        """
        提取并存储关键术语翻译
        
        Args:
            original (str): 原文
            translated (str): 译文
        """
        if not self.translation_data_manager:
            return
        
        # 定义常见术语模式
        patterns = [
            # 菌种名模式 (如: Rothia marina)
            (r'([A-Z][a-z]+(?:\s+[a-z]+)?)\s+strain', '菌种'),
            # 基因名称模式 (如: 16S ribosomal RNA gene)
            (r'(16S\s+ribosomal\s+RNA(?:\s+gene)?)', '基因'),
            # 序列类型模式 (如: partial sequence)
            (r'(partial\s+sequence)', '序列'),
            (r'(complete\s+genome)', '基因组'),
            (r'(plasmid\s+vector)', '载体'),
            # 菌株编号模式 (如: strain JSM 078151)
            (r'strain\s+([A-Z0-9\s]+?)(?:\s+16S|\s+partial|,\s+partial|$)', '菌株'),
        ]
        
        # 提取英文关键术语
        for pattern, category in patterns:
            matches = re.findall(pattern, original, re.IGNORECASE)
            for match in matches:
                # 处理分组匹配结果
                term = match if isinstance(match, str) else match[0] if match else ""
                if term and term.strip() and len(term.strip()) > 2:  # 过滤过短的术语
                    # 对于每个提取的英文术语，尝试在中文翻译中找到对应部分
                    # 这里使用简化的处理方法，实际应用中可以使用更复杂的NLP技术
                    chi_term = self._find_chinese_equivalent(term, translated)
                    if chi_term:
                        # 存储术语翻译
                        self.translation_data_manager.add_translation(term.strip(), chi_term.strip())
    
    def _find_chinese_equivalent(self, english_term: str, chinese_text: str) -> str:
        """
        在中文文本中查找英文术语的对应翻译
        
        Args:
            english_term (str): 英文术语
            chinese_text (str): 中文文本
            
        Returns:
            str: 对应的中文术语，如果找不到则返回空字符串
        """
        # 这是一个简化的实现，实际应用中可以使用更复杂的NLP技术
        # 根据术语类型使用不同的查找策略
        
        # 通用查找方法：基于术语词典
        term_dictionary = {
            '16S ribosomal RNA': '16S核糖体RNA',
            '16S ribosomal RNA gene': '16S核糖体RNA基因',
            'partial sequence': '部分序列',
            'complete genome': '完整基因组',
            'plasmid vector': '质粒载体',
        }
        
        # 直接查找
        if english_term in term_dictionary:
            return term_dictionary[english_term]
        
        # 忽略大小写查找
        for eng, chi in term_dictionary.items():
            if eng.lower() == english_term.lower():
                return chi
        
        # 包含关系查找
        for eng, chi in term_dictionary.items():
            if eng.lower() in english_term.lower():
                return chi
        
        # 如果是菌种名称，使用通用翻译规则
        if 'strain' in english_term:
            # 提取菌种名
            parts = english_term.split()
            if len(parts) >= 2:
                genus = parts[0]  # 属名
                # 简单的翻译规则：属名 + "菌"
                if genus.istitle() and len(genus) > 1:
                    return f"{genus}菌"
        
        return ""  # 未找到对应翻译
    
    def get_statistics(self) -> Dict[str, int]:
        """
        获取翻译数据统计信息
        
        Returns:
            dict: 包含各类翻译条目数量的字典
        """
        if self.translation_data_manager:
            return self.translation_data_manager.get_statistics()
        return {"total_entries": 0}


def get_biology_translator(data_file: Optional[str] = None, use_ai: bool = False, 
                          ai_api_key: Optional[str] = None, use_mock: bool = False) -> BiologyTranslator:
    """
    获取生物学翻译器实例
    
    Args:
        data_file (str, optional): 包含翻译数据的CSV文件路径
        use_ai (bool): 是否使用AI翻译器
        ai_api_key (str, optional): AI翻译器API密钥
        use_mock (bool): 是否使用模拟AI翻译器（用于测试）
        
    Returns:
        BiologyTranslator: 翻译器实例
    """
    return BiologyTranslator(data_file, use_ai, ai_api_key, use_mock)


def get_biology_translator_from_api(api_key: Optional[str] = None) -> BiologyTranslator:
    """
    获取基于API的生物学翻译器实例
    
    Args:
        api_key (str, optional): API密钥
        
    Returns:
        BiologyTranslator: 翻译器实例
    """
    return BiologyTranslator(use_ai=True, ai_api_key=api_key)