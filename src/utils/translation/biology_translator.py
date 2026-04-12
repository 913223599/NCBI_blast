"""
生物学翻译器模块
负责生物学专业术语的翻译，结合本地数据库和AI翻译服务
"""

import threading
from typing import Optional

from .qwen_translator import QwenTranslator
from .term_extractor import TermExtractor  # 导入TermExtractor
from ..taxonomy_provider import get_taxonomy_provider


class BiologyTranslator:
    """
    生物学翻译器类
    支持本地数据库和AI翻译相结合的翻译模式
    """
    
    def __init__(self, data_file: str = None, use_ai: bool = True, ai_api_key: str = None, ai_model: str = "deepseek-r1"):
        """
        初始化生物学翻译器
        
        Args:
            data_file (str): 本地翻译数据库文件路径
            use_ai (bool): 是否启用AI翻译
            ai_api_key (str): AI服务API密钥
            ai_model (str): AI模型名称
        """
        # 确保数据文件路径存在
        # 默认使用项目根目录下的translation_data.csv，由get_translation_data_manager内部处理
        
        from .translation_data_manager import get_translation_data_manager
        self.translation_data_manager = get_translation_data_manager()
        self.use_ai = use_ai
        self.ai_model = ai_model
        
        # 初始化术语提取器用于规范化术语
        self.term_extractor = TermExtractor(self.translation_data_manager)
        
        # 初始化AI翻译器（如果启用）
        if use_ai and ai_api_key:
            try:
                self.ai_translator = QwenTranslator(api_key=ai_api_key, model=ai_model)
            except Exception as e:
                print(f"AI翻译器初始化失败: {e}")
                self.ai_translator = None
                self.use_ai = False
        else:
            self.ai_translator = None
            self.use_ai = False
        
        # 内存缓存（用于提高频繁查询的性能）
        self._translation_cache = {}
        self._lock = threading.Lock()  # 线程安全锁

    def translate_text(self, text: str, category: str = 'other', use_ai_override: Optional[bool] = None) -> str:
        """
        [SMART] 翻译整段文本 - 增加共识字符串拆解逻辑
        """
        if not text:
            return text
        
        # 0. [核心优化] 识别并处理共识概率字符串 (例如: "Species A(90%), Species B(10%)")
        import re
        # 匹配模式: 文本(百分比%)
        consensus_pattern = r'([^,()]+)\s*\(\s*\d+%\s*\)'
        if ',' in text and '(' in text and '%' in text:
            # 找到所有的匹配项及其对应的位置
            matches = list(re.finditer(consensus_pattern, text))
            if matches:
                # 这是一个共识字符串，我们需要逐个拆解翻译
                result_parts = []
                last_end = 0
                for match in matches:
                    full_match = match.group(0) 
                    pure_name = match.group(1).strip()
                    start, end = match.span()
                    result_parts.append(text[last_end:start])
                    
                    # 翻译这个纯名称
                    # 如果当前允许使用 AI，我们允许在此处尝试翻译单个物种
                    translated_name = self.translate_text(pure_name, category=category, use_ai_override=use_ai_override)
                    
                    reassembled = full_match.replace(pure_name, translated_name)
                    result_parts.append(reassembled)
                    last_end = end
                
                result_parts.append(text[last_end:])
                final_text = "".join(result_parts)
                
                # 如果有任何一部分发生了变化（不管是本地还是 AI），都认为成功
                if final_text != text:
                    # 存入缓存以加速下次整体匹配
                    with self._lock:
                        self._translation_cache[text] = final_text
                    return final_text

        # 使用覆盖配置或默认配置
        active_use_ai = use_ai_override if use_ai_override is not None else self.use_ai
            
        # 线程安全的缓存访问
        with self._lock:
            if text in self._translation_cache:
                # print(f"[Debug] Cache hit: {text}")
                return self._translation_cache[text]
        
        original_text = text
        
        # 1. 对输入文本进行规范化
        normalized_text = self.term_extractor.normalize_term(text)
        
        # 2. 如果文本被规范化了，先尝试从数据库中查找规范化后的版本
        if normalized_text != text and self.translation_data_manager:
            # 传递 category 以优化查询
            local_result = self.translation_data_manager.get_translation(normalized_text, category=category)
            if local_result and local_result != normalized_text:
                result = f"{local_result}"
                with self._lock:
                    self._translation_cache[original_text] = result
                return result
        
        # 3. 尝试本地数据库匹配原始文本
        if self.translation_data_manager:
            local_result = self.translation_data_manager.get_translation(text, category=category)
            if local_result and local_result != text:
                result = f"{local_result}"
                with self._lock:
                    self._translation_cache[original_text] = result
                return result

        # 4. 尝试 AI 翻译 (如果启用且可用)
        if active_use_ai:
            if not self.ai_translator:
                # 如果明确要求了 AI 翻译，但未配置，给予提示
                if use_ai_override:
                    import logging
                    logging.getLogger(__name__).warning("请求了 AI 翻译，但尚未配置有效 API Key。")
            else:
                try:
                    ai_result = self.ai_translator.translate_text(text)
                    if ai_result and ai_result != text:
                        # 恢复并加强自动保存机制：AI 翻译成功后应记录，下次可从本地库秒级返回
                        if self.translation_data_manager:
                            # [VALIDATION] 如果分类目录为物种或属，强制从离线分类数据库校验其拉丁名合法性
                            is_valid = True
                            if category in ('species', 'genus'):
                                try:
                                    tax_provider = get_taxonomy_provider()
                                    lineage = tax_provider.get_lineage_details(text)
                                    if not lineage:
                                        import logging
                                        logging.getLogger(__name__).warning(f"[Taxonomy Validation] 拉丁名 '{text}' 未在分类数据库中找到，跳过存入词库。")
                                        is_valid = False
                                except:
                                    pass # 容错处理
                            
                            if is_valid:
                                # 1. 使用专用的保存方法，标记来源为 AI
                                self.translation_data_manager.add_translation(
                                    text, 
                                    ai_result, 
                                    category=category if category else 'species', 
                                    source="ai"
                                )
                                # 2. 调用术语提取深度学习分析（如有）
                                try:
                                    self.term_extractor.extract_and_store_key_terms(text, ai_result)
                                except:
                                    pass
                        
                        # 移除原先带有的 [AI] 前缀，保证界面的清洁度和词库的标准性
                        result = ai_result
                        with self._lock:
                            self._translation_cache[original_text] = result
                        return result
                except Exception as e:
                    import logging
                    logging.getLogger(__name__).error(f"[AITranslator] AI翻译异常: {e}")
                    # AI 失败降级为原文，无需特殊处理，继续向下执行

        # 5. 默认返回原文
        # 注意：如果是只查询本地 (use_ai_override == False)，不要把英文原文存入缓存，
        # 否则后续真正的 AI 后台线程调用时，会在第 0 步直接命中这个原文缓存，导致 AI 彻底失效！
        if active_use_ai:
            with self._lock:
                self._translation_cache[original_text] = original_text
        return original_text

    def translate_batch(self, texts: list, category: str = 'species') -> dict:
        """
        [OPTIMIZED] 整合批量翻译：本地库优先 + AI 批量补偿 (修复复合文本AI乱翻译问题)
        """
        import re
        # 匹配模式: 文本(百分比%)
        consensus_pattern = r'([^,()]+)\s*\(\s*\d+%\s*\)'
        
        pure_components = set()
        
        # 1. 扁平化：解析出所有的子结构，收集所有需要翻译的最基础词汇
        for text in texts:
            if not text:
                continue
            
            if ',' in text and '(' in text and '%' in text:
                matches = list(re.finditer(consensus_pattern, text))
                if matches:
                    for match in matches:
                        pure_name = match.group(1).strip()
                        pure_components.add(pure_name)
                else:
                    pure_components.add(text)
            else:
                pure_components.add(text)
                    
        # 2. 差集计算：对收集到的基础词汇检查本地缓存，选出未命中的移交 AI
        to_ai_set = set()
        for pure_text in pure_components:
            clean_text = pure_text.strip()
            # 基础词本身不再分割，如果在本地没找到直接返回原文说明必须走AI
            part_res = self.translate_text(clean_text, category=category, use_ai_override=False)
            if part_res == clean_text:
                to_ai_set.add(clean_text)

        # 3. 对未命中的最细粒度纯词条进行 AI 批量翻译
        to_ai_list = list(to_ai_set)
        if to_ai_list and self.use_ai and self.ai_translator:
            try:
                ai_results = self.ai_translator.batch_translate(to_ai_list)
                for i, pure_text in enumerate(to_ai_list):
                    if i < len(ai_results):
                        ai_res = ai_results[i]
                        # 自动存入本地库，以便下一阶段重新组装时可以直接命中
                        if ai_res and ai_res != pure_text:
                            with self._lock:
                                self._translation_cache[pure_text] = ai_res
                            if self.translation_data_manager:
                                # [VALIDATION] 批量处理也增加校验逻辑
                                is_valid = True
                                if category in ('species', 'genus'):
                                    try:
                                        tax_provider = get_taxonomy_provider()
                                        lineage = tax_provider.get_lineage_details(pure_text)
                                        if not lineage:
                                            is_valid = False
                                    except: pass
                                
                                if is_valid:
                                    self.translation_data_manager.add_translation(
                                        pure_text, ai_res, category=category, source="ai_batch"
                                    )
                                    try:
                                        self.term_extractor.extract_and_store_key_terms(pure_text, ai_res)
                                    except:
                                        pass
            except Exception as e:
                import logging
                logging.getLogger(__name__).error(f"Biology Batch AI Error: {e}")

        # 4. 再一次完成全量组装
        # 现在所有必需的短词均已存在于本地/缓存中（部分从 DB/内置，部分借由刚才的 AI 动态翻译而来）
        # 我们对原始传入的混合 texts 直接调用 translate_text 即可完成最终切割替换。
        results = {}
        for text in texts:
            if not text:
                results[text] = text
                continue
            res = self.translate_text(text, category=category, use_ai_override=False)
            results[text] = res

        return results

    def search_translations(self, query: str, limit: int = 50) -> list:
        """透传搜索请求"""
        if self.translation_data_manager:
            return self.translation_data_manager.search_translations(query, limit)
        return []

    def update_translation(self, english: str, chinese: str, category: str = 'species') -> bool:
        """透传更新请求"""
        if self.translation_data_manager:
            return self.translation_data_manager.update_translation_entry(english, chinese, category=category)
        return False

    def add_translation(self, original: str, translation: str, source: str = "manual"):
        """
        添加新的翻译对
        
        Args:
            original (str): 原文
            translation (str): 翻译文本
            source (str): 来源标记
        """
        if self.translation_data_manager:
            # 使用术语提取器进行规范化处理
            try:
                self.term_extractor.extract_and_store_key_terms(original, translation)
            except Exception as e:
                print(f"术语提取和存储过程中出错: {e}")
                import traceback
                traceback.print_exc()
            # 同时更新内存缓存
            with self._lock:
                self._translation_cache[original] = f"{translation}"


def get_biology_translator(data_file: str = None, use_ai: bool = True, ai_api_key: str = None, ai_model: str = "deepseek-r1") -> BiologyTranslator:
    """
    获取生物学翻译器实例
    
    Args:
        data_file (str): 本地翻译数据库文件路径
        use_ai (bool): 是否启用AI翻译
        ai_api_key (str): AI服务API密钥
        ai_model (str): AI模型名称
        
    Returns:
        BiologyTranslator: 生物学翻译器实例
    """
    return BiologyTranslator(data_file=data_file, use_ai=use_ai, ai_api_key=ai_api_key, ai_model=ai_model)


# 全局翻译器实例（可选，用于需要单例的场景）
_global_translator = None
_global_lock = threading.Lock()


def get_global_biology_translator(data_file: str = None, use_ai: bool = True, ai_api_key: str = None, ai_model: str = "deepseek-r1") -> BiologyTranslator:
    """
    获取全局生物学翻译器实例（线程安全的单例模式）
    
    Args:
        data_file (str): 本地翻译数据库文件路径
        use_ai (bool): 是否启用AI翻译
        ai_api_key (str): AI服务API密钥
        ai_model (str): AI模型名称
        
    Returns:
        BiologyTranslator: 生物学翻译器实例
    """
    global _global_translator
    
    with _global_lock:
        if _global_translator is None:
            # Auto-fetch API key from config if not provided
            if ai_api_key is None:
                try:
                    from ..config_manager import get_config_manager
                    config = get_config_manager()
                    ai_api_key = config.get_api_key("dashscope")
                    
                    # Also try to sync model from settings if available
                    advanced = config.get_advanced_settings()
                    if "ai_model" in advanced:
                        ai_model = advanced["ai_model"]
                except Exception as e:
                    print(f"Warning: Failed to auto-fetch API key from config: {e}")

            _global_translator = BiologyTranslator(
                data_file=data_file, 
                use_ai=use_ai, 
                ai_api_key=ai_api_key, 
                ai_model=ai_model
            )
    
    return _global_translator