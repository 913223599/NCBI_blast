"""
生物学专业术语翻译模块
用于翻译生物学领域的专业术语，支持本地数据和AI翻译
"""

import csv
import re
from typing import Optional, Dict, List
import logging


# 导入通义千问翻译器
try:
    from .qwen_translator import get_qwen_translator, QwenTranslator
    QWEN_AVAILABLE = True
except ImportError:
    QWEN_AVAILABLE = False
    QwenTranslator = object  # 占位符

# 导入翻译数据管理器
try:
    from .translation_data_manager import get_translation_data_manager, TranslationDataManager
    TRANSLATION_DATA_MANAGER_AVAILABLE = True
except ImportError:
    TRANSLATION_DATA_MANAGER_AVAILABLE = False
    TranslationDataManager = object  # 占位符

# 导入翻译质量检查器
try:
    from .translation_quality_checker import get_translation_quality_checker, TranslationQualityChecker
    TRANSLATION_QUALITY_CHECKER_AVAILABLE = True
except ImportError:
    TRANSLATION_QUALITY_CHECKER_AVAILABLE = False
    TranslationQualityChecker = object  # 占位符


class BiologyTranslator:
    """
    生物学专业术语翻译器
    专门用于生物学领域专业术语的翻译
    使用高效的数据结构支持大量数据的存储和检索
    """
    
    def __init__(self, data_file: Optional[str] = None, use_ai: bool = False, 
                 ai_api_key: Optional[str] = None, quality_checker: Optional[TranslationQualityChecker] = None):
        """
        初始化翻译器
        
        Args:
            data_file (str, optional): 包含翻译数据的CSV文件路径
            use_ai (bool): 是否使用AI翻译器
            ai_api_key (str, optional): AI翻译器API密钥
            quality_checker (TranslationQualityChecker, optional): 翻译质量检查器实例
        """
        # 初始化翻译数据管理器
        self.translation_data_manager = None
        if TRANSLATION_DATA_MANAGER_AVAILABLE:
            csv_file = data_file or "translation_data.csv"
            self.translation_data_manager = get_translation_data_manager(csv_file)
        
        # AI翻译器相关属性
        self.use_ai = use_ai
        self.ai_translator = None
        self.ai_api_key = ai_api_key
        
        # 初始化AI翻译器（如果启用）
        if self.use_ai and QWEN_AVAILABLE:
            try:
                self.ai_translator = get_qwen_translator(self.ai_api_key)
            except Exception as e:
                print(f"警告: 无法初始化AI翻译器: {e}")
                self.ai_translator = None
                self.use_ai = False
        elif self.use_ai and not QWEN_AVAILABLE:
            print("警告: 请求使用AI翻译器，但未安装dashscope库")
            self.use_ai = False
            
        # 初始化翻译质量检查器
        self.quality_checker = quality_checker
        if not self.quality_checker and TRANSLATION_QUALITY_CHECKER_AVAILABLE:
            self.quality_checker = get_translation_quality_checker()
    
    def translate_text(self, text: str) -> str:
        """
        翻译整段文本中的生物学专业术语
        使用本地翻译数据优先，失败时使用AI翻译并回收数据
        
        Args:
            text (str): 英文文本
            
        Returns:
            str: 翻译后的文本，带有翻译类型标识（[AI]表示AI翻译，[本地]表示本地翻译）
        """
        if not text:
            return text
            
        # 如果启用了AI翻译且AI翻译器可用，则根据翻译质量决定是否使用AI翻译
        if self.use_ai and self.ai_translator:
            # 初始化翻译质量检查器
            quality_checker = None
            if TRANSLATION_QUALITY_CHECKER_AVAILABLE:
                quality_checker = get_translation_quality_checker()
            
            # 首先尝试从本地数据中翻译
            if self.translation_data_manager:
                local_result = self._translate_with_local_data(text)
                # 检查本地翻译质量 - 如果包含"菌"字但不是完整翻译，则认为质量不高
                if local_result != text and "菌" in local_result and self.quality_checker and not self.quality_checker.is_poor_translation(local_result):
                    print(f"[翻译调试] 使用本地翻译: {text} -> {local_result}")
                    # 返回本地翻译结果，并添加标识
                    return f"[本地]{local_result}"
                elif local_result != text:
                    # 本地翻译质量不高，尝试使用AI翻译
                    print(f"[翻译调试] 本地翻译质量不高，尝试AI翻译: {text}")
                else:
                    # 本地翻译失败，使用AI翻译
                    print(f"[翻译调试] 本地翻译失败，尝试AI翻译: {text}")
            
            # 使用AI翻译
            print(f"[翻译调试] 使用AI翻译: {text}")
            try:
                result = self.ai_translator.translate_text(text)
                print(f"[翻译调试] AI翻译结果: {result}")
                # 回收翻译数据
                if self.translation_data_manager:
                    self._collect_translations(text, result)
                # 返回AI翻译结果，并添加标识
                return f"[AI]{result}"
            except Exception as e:
                print(f"AI翻译失败: {e}")
                # 新增逻辑：AI翻译失败时，如果已有本地翻译则使用本地翻译，否则将原文存储到本地词典中
                if self.translation_data_manager:
                    local_result = self._translate_with_local_data(text)
                    if local_result != text:
                        print(f"[翻译调试] AI翻译失败，使用本地翻译: {text} -> {local_result}")
                        return f"[本地]{local_result}"
                    else:
                        self.translation_data_manager.add_translation(text, text)
        
        # 如果有本地数据管理器，尝试使用本地数据翻译
        if self.translation_data_manager:
            local_result = self._translate_with_local_data(text)
            if local_result != text:  # 如果本地翻译成功
                print(f"[翻译调试] 使用本地翻译: {text} -> {local_result}")
                # 返回本地翻译结果，并添加标识
                quality_indicator = "[本地-低质]" if self.quality_checker and self.quality_checker.is_poor_translation(local_result) else "[本地]"
                return f"{quality_indicator}{local_result}"
        
        # 所有方法都失败，返回原文
        print(f"[翻译调试] 未翻译，返回原文: {text}")
        return text
    
    def _translate_with_local_data(self, text: str) -> str:
        """
        翻译单个序列文本
        
        Args:
            text (str): 单个序列的英文文本
            
        Returns:
            str: 翻译后的文本，如果无法翻译则返回原文
        """
        # 缓存原始文本，避免重复参数传递
        original_text = text
        
        # 优先尝试直接匹配整个文本
        direct_translation = self.translation_data_manager.get_translation(text)
        if direct_translation:
            return direct_translation
            
        # 尝试匹配特殊模式（最具体的模式优先）
        special_result = self._translate_special_patterns(text)
        if special_result != original_text:  # 如果特殊模式处理成功
            return special_result
            
        # 尝试匹配常见模式（按优先级排序）
        common_result = self._translate_common_patterns(text)
        if common_result != original_text:  # 如果常用模式处理成功
            return common_result
            
        # 最后尝试逐词翻译
        word_result = self._translate_word_by_word(text)
        if word_result != original_text:  # 如果逐词翻译成功
            return word_result
            
        # 否则返回原文
        return original_text

    def _translate_special_patterns(self, text: str) -> str:
        """
        处理特殊模式的翻译
        
        Args:
            text (str): 待翻译的文本
            
        Returns:
            str: 翻译后的文本，如果无法翻译则返回原文
        """
        # 导入特殊模式翻译器并使用
        try:
            from .special_pattern_translator import get_special_pattern_translator
            special_pattern_translator = get_special_pattern_translator(self.translation_data_manager)
            return special_pattern_translator.translate_special_patterns(text)
        except ImportError:
            # 如果无法导入新模块，则返回原文
            return text

    def _translate_common_patterns(self, text: str) -> str:
        """
        处理常见生物学术语模式的翻译
        
        Args:
            text (str): 待翻译的文本
            
        Returns:
            str: 翻译后的文本，如果无法翻译则返回原文
        """
        # 缓存原始文本
        original_text = text
        
        # 优化模式匹配顺序：最常见的模式放在前面
        patterns = [
            # 完整模式匹配（最常见的模式）
            r'([A-Z][a-z]+(?:\s+[a-z]+)?)\s+(strain\s+[A-Za-z0-9\-._]+)\s+(16S\s+ribosomal\s+RNA(?:\s+gene)?)\s*,\s*(partial\s+sequence|complete\s+genome)',
            # 菌种 + 基因 + 序列类型
            r'([A-Z][a-z]+(?:\s+[a-z]+)?)\s+(16S\s+ribosomal\s+RNA(?:\s+gene)?)\s*,\s*(partial\s+sequence|complete\s+genome)',
            # 菌种 + 分离株 + 基因
            r'([A-Z][a-z]+(?:\s+[a-z]+)?)\s+(partial\s+16S\s+rRNA\s+gene)\s*,\s*(isolate\s+[A-Za-z0-9\-._]+)',
            # 菌种 + 菌株 + 基因
            r'([A-Z][a-z]+(?:\s+[a-z]+)?)\s+(strain\s+[A-Za-z0-9\-._]+)\s+(16S\s+ribosomal\s+RNA(?:\s+gene)?)',
        ]
        
        # 缓存翻译数据管理器
        tdm = self.translation_data_manager
        
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                translated_parts = []
                all_parts_translated = True
                
                # 优化翻译过程：使用缓存
                for i in range(1, len(match.groups()) + 1):
                    part = match.group(i)
                    # 优先尝试直接匹配整个部分
                    part_translation = tdm.get_translation(part)
                    if part_translation:
                        translated_parts.append(part_translation)
                        continue
                        
                    # 拆分部分进行翻译
                    sub_parts = re.split(r'[,\s]+', part)
                    translated_sub_parts = []
                    all_sub_translated = True
                    
                    for sub_part in sub_parts:
                        sub_translation = tdm.get_translation(sub_part)
                        if sub_translation:
                            translated_sub_parts.append(sub_translation)
                        else:
                            all_sub_translated = False
                            break
                    
                    if all_sub_translated and translated_sub_parts:
                        translated_parts.append(" ".join(translated_sub_parts))
                    else:
                        all_parts_translated = False
                        break
                
                if all_parts_translated and translated_parts:
                    return " ".join(translated_parts)
        
        # 没有匹配到常用模式，返回原文
        return original_text

    def _translate_word_by_word(self, text: str) -> str:
        """
        逐词翻译文本
        先尝试按词翻译，再尝试按短语翻译
        
        Args:
            text (str): 待翻译的文本
            
        Returns:
            str: 翻译后的文本，如果无法翻译则返回原文
        """
        # 缓存原始文本
        original_text = text
        
        # 缓存翻译数据管理器
        tdm = self.translation_data_manager
        
        # 尝试逐词翻译
        words = text.split()
        translated_words = []
        
        # 优化翻译过程：使用缓存
        for word in words:
            translation = tdm.get_translation(word)
            if not translation:
                # 如果有任何词无法翻译，则整个翻译失败
                return original_text
            translated_words.append(translation)
        
        # 只有当所有词都被翻译时才返回翻译结果
        if translated_words:
            return " ".join(translated_words)
            
        # 新增逻辑：尝试对文本进行更细粒度的拆分
        phrases = re.split(r'[,\s]+', text)
        translated_phrases = []
        
        for phrase in phrases:
            phrase_translation = tdm.get_translation(phrase)
            if not phrase_translation:
                # 如果有任何短语无法翻译，则整个翻译失败
                return original_text
            translated_phrases.append(phrase_translation)
        
        if translated_phrases:
            return " ".join(translated_phrases)
            
        # 无法翻译，返回原文
        return original_text

    # 已移至special_pattern_translator.py模块
    # def _translate_remaining_text(self, text: str) -> str:
    #     ...

    # 已移至special_pattern_translator.py模块
    # def _translate_strain_name(self, strain_name: str) -> str:
    #     ...

    # 已移至special_pattern_translator.py模块
    # def _translate_isolate_name(self, isolate_name: str) -> str:
    #     ...

    # 已移至special_pattern_translator.py模块
    # def _translate_clone_name(self, clone_name: str) -> str:
    #     ...

    def _collect_translations(self, original: str, translated: str):
        """
        收集并存储翻译数据，优化存储方式，只存储关键术语
        
        Args:
            original (str): 原文
            translated (str): 译文
        """
        if not self.translation_data_manager:
            return
            
        # 使用独立的术语提取器处理术语提取和存储
        from .term_extractor import TermExtractor
        term_extractor = TermExtractor(self.translation_data_manager, self.quality_checker)
        term_extractor.extract_and_store_key_terms(original, translated)

def get_biology_translator(data_file: Optional[str] = None, use_ai: bool = False, 
                           ai_api_key: Optional[str] = None, quality_checker: Optional[TranslationQualityChecker] = None) -> BiologyTranslator:
    """
    获取生物学翻译器实例
    
    Args:
        data_file (str, optional): 包含翻译数据的CSV文件路径
        use_ai (bool): 是否使用AI翻译器
        ai_api_key (str, optional): AI翻译器API密钥
        quality_checker (TranslationQualityChecker, optional): 翻译质量检查器实例
        
    Returns:
        BiologyTranslator: 生物学翻译器实例
    """
    return BiologyTranslator(data_file, use_ai, ai_api_key, quality_checker)