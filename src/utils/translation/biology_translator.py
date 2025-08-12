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


class BiologyTranslator:
    """
    生物学专业术语翻译器
    专门用于生物学领域专业术语的翻译
    使用高效的数据结构支持大量数据的存储和检索
    """
    
    def __init__(self, data_file: Optional[str] = None, use_ai: bool = True, 
                 ai_api_key: Optional[str] = None):
        """
        初始化翻译器
        
        Args:
            data_file (str, optional): 包含翻译数据的CSV文件路径
            use_ai (bool): 是否使用AI翻译器
            ai_api_key (str, optional): AI翻译器API密钥
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
        
        # 添加缓存来存储已翻译的内容，避免重复翻译
        self._translation_cache = {}
        
        # 初始化AI翻译器（如果启用）
        if self.use_ai and QWEN_AVAILABLE:
            try:
                self.ai_translator = get_qwen_translator(self.ai_api_key)
                # 添加健康检查
                if self.ai_translator and hasattr(self.ai_translator, 'health_check'):
                    if not self.ai_translator.health_check():
                        raise Exception("AI翻译器健康检查失败")
            except Exception as e:
                print(f"警告: 无法初始化或验证AI翻译器: {e}")
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
            str: 翻译后的文本，带有翻译类型标识（[AI]表示AI翻译，[本地]表示本地翻译）
        """
        if not text:
            return text
            
        # 检查缓存中是否已有翻译结果
        if text in self._translation_cache:
            print(f"[翻译调试] 使用缓存翻译: {text} -> {self._translation_cache[text]}")
            return self._translation_cache[text]
            
        original_text = text  # 保存原始文本
        
        # 如果启用了AI翻译且AI翻译器可用，则根据翻译质量决定是否使用AI翻译
        if self.use_ai and self.ai_translator:
            # 首先尝试从本地数据中翻译
            local_result = self._translate_with_local_data(text)
            # 检查本地翻译质量
            if local_result != text:
                print(f"[翻译调试] 使用本地翻译: {text} -> {local_result}")
                # 返回本地翻译结果，并添加标识
                translated = f"[本地]{local_result}"
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
                    
                    # 更新缓存
                    self._translation_cache[text] = result
                    
                    # 返回AI翻译结果，并添加标识
                    translated = f"[AI]{result}"
                except Exception as e:
                    print(f"AI翻译失败: {e}")
                    
                    # 新增逻辑：AI翻译失败时，如果已有本地翻译则使用本地翻译
                    if self.translation_data_manager:
                        local_result = self._translate_with_local_data(text)
                        if local_result != text:
                            print(f"[翻译调试] AI翻译失败，使用本地翻译: {text} -> {local_result}")
                            translated = f"[本地]{local_result}"
                        else:
                            translated = text  # 返回原文
                    else:
                        translated = text  # 返回原文
        else:
            # 如果有本地数据管理器，尝试使用本地数据翻译
            if self.translation_data_manager:
                local_result = self._translate_with_local_data(text)
                if local_result != text:  # 如果本地翻译成功
                    print(f"[翻译调试] 使用本地翻译: {text} -> {local_result}")
                    # 返回本地翻译结果，并添加标识
                    translated = f"[本地]{local_result}"
                else:
                    translated = text  # 返回原文
            else:
                translated = text  # 返回原文
        
        # 存储翻译结果到缓存 - 此处已移至各个返回点
        # self._translation_cache[original_text] = translated
        
        return translated

    def translate_components(self, species: str, genus: str, strain: str, gene_type: str, sequence_type: str) -> str:
        """
        翻译已分离的组件并拼接成完整文本
        
        Args:
            species (str): 物种名称
            genus (str): 属名
            strain (str): 菌株名称
            gene_type (str): 基因类型
            sequence_type (str): 序列类型
            
        Returns:
            str: 翻译并拼接后的完整文本
        """
        translated_parts = []
        
        # 翻译物种
        if species:
            translated_species = self._translate_component(species, "species")
            if translated_species:
                translated_parts.append(translated_species)
        
        # 翻译属名（如果与物种不同）
        if genus and genus != species:
            translated_genus = self._translate_component(genus, "genus")
            if translated_genus:
                translated_parts.append(translated_genus)
        
        # 翻译菌株
        if strain:
            translated_strain = self._translate_component(strain, "strain")
            if translated_strain:
                translated_parts.append(translated_strain)
        
        # 翻译基因类型
        if gene_type:
            translated_gene = self._translate_component(gene_type, "gene")
            if translated_gene:
                translated_parts.append(translated_gene)
        
        # 翻译序列类型
        if sequence_type:
            translated_sequence = self._translate_component(sequence_type, "sequence")
            if translated_sequence:
                translated_parts.append(translated_sequence)
        
        # 如果翻译后的部分为空，尝试使用AI翻译整个文本
        if not translated_parts and self.use_ai and self.ai_translator:
            try:
                # 将所有组件组合成一个文本进行AI翻译
                combined_text = " ".join(filter(None, [species, genus, strain, gene_type, sequence_type]))
                if combined_text:
                    print(f"[翻译调试] 组件翻译失败，使用AI翻译组合文本: {combined_text}")
                    ai_result = self.ai_translator.translate_text(combined_text)
                    return f"[AI]{ai_result}"
            except Exception as e:
                print(f"AI翻译组合文本失败: {e}")
        
        # 拼接翻译后的部分
        return " ".join(translated_parts) if translated_parts else ""
    
    def _translate_component(self, component: str, component_type: str) -> str:
        """
        翻译单个组件
        
        Args:
            component (str): 组件内容
            component_type (str): 组件类型 (species, genus, strain, gene, sequence)
            
        Returns:
            str: 翻译后的组件内容
        """
        if not component:
            return ""
            
        # 检查缓存
        cache_key = f"{component}_{component_type}"
        if cache_key in self._translation_cache:
            return self._translation_cache[cache_key]
            
        # 使用AI翻译器翻译
        if self.use_ai and self.ai_translator:
            try:
                ai_translation = self.ai_translator.translate_text(component)
                if ai_translation and ai_translation != component:
                    # 存储到本地数据库
                    if self.translation_data_manager:
                        try:
                            self.translation_data_manager.add_translation(component, ai_translation, component_type)
                            print(f"[翻译调试] 已将'{component}'的AI翻译结果存储到本地数据库")
                        except Exception as e:
                            print(f"[翻译调试] 存储AI翻译结果到本地数据库失败: {e}")
                    # 缓存结果
                    self._translation_cache[cache_key] = ai_translation
                    return ai_translation
            except Exception as e:
                print(f"AI翻译组件'{component}'失败: {e}")
        
        # 如果找不到翻译，返回原文
        self._translation_cache[cache_key] = component
        return component
    
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
        
        # 检查缓存
        if text in self._translation_cache:
            cached_result = self._translation_cache[text]
            # 如果缓存结果包含标识符，则去掉标识符返回纯翻译文本
            if cached_result.startswith('[AI]'):
                return cached_result[4:]
            elif cached_result.startswith('[本地]'):
                return cached_result[4:]
            return cached_result
        
        # 优先尝试直接匹配整个文本
        if self.translation_data_manager:
            direct_translation = self.translation_data_manager.get_translation(text)
            if direct_translation:
                self._translation_cache[text] = direct_translation
                return direct_translation
            
        # 如果找不到翻译，返回原文
        self._translation_cache[text] = original_text
        return original_text

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
        term_extractor = TermExtractor(self.translation_data_manager)
        term_extractor.extract_and_store_key_terms(original, translated)

def get_biology_translator(data_file: Optional[str] = None, use_ai: bool = True, 
                           ai_api_key: Optional[str] = None) -> BiologyTranslator:
    """
    获取生物学翻译器实例
    
    Args:
        data_file (str, optional): 包含翻译数据的CSV文件路径
        use_ai (bool): 是否使用AI翻译器
        ai_api_key (str, optional): AI翻译器API密钥
        
    Returns:
        BiologyTranslator: 生物学翻译器实例
    """
    return BiologyTranslator(data_file, use_ai, ai_api_key)