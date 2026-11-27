"""
生物学翻译器模块
负责生物学专业术语的翻译，结合本地数据库和AI翻译服务
"""

import threading
from typing import Optional

from .qwen_translator import QwenTranslator
from .term_extractor import TermExtractor  # 导入TermExtractor
from ..taxonomy_provider import get_taxonomy_provider
import logging
logger = logging.getLogger(__name__)


class BiologyTranslator:
    """
    生物学翻译器类
    支持本地数据库和AI翻译相结合的翻译模式
    """
    
    def __init__(self, data_file: Optional[str] = None, use_ai: bool = True, ai_api_key: Optional[str] = None, ai_model: str = "deepseek-r1"):
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
        self.ai_translator: Optional['QwenTranslator'] = None
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

    def _translate_consensus_text(
        self,
        text: str,
        category: str,
        use_ai_override: Optional[bool],
    ) -> Optional[str]:
        import re

        if '(' not in text or '%' not in text:
            return None
        matches = list(re.finditer(r'([^,()]+)\s*\(\s*(\d+)%\s*\)', text))
        if not matches:
            return None

        translated_entries = []
        fully_translated = True
        for match in matches:
            pure_name = match.group(1).strip()
            try:
                pct_val = int(match.group(2))
            except Exception:
                pct_val = 100
            translated_name = self.translate_text(pure_name, category=category, use_ai_override=use_ai_override)
            if translated_name == pure_name:
                fully_translated = False
            translated_entries.append((translated_name, pct_val))

        merged_dict: dict[str, int] = {}
        for name, pct in translated_entries:
            merged_dict[name] = merged_dict.get(name, 0) + pct

        sorted_merged = sorted(merged_dict.items(), key=lambda x: x[1], reverse=True)
        if len(sorted_merged) == 1:
            final_text = f"{sorted_merged[0][0]}(100%)"
        else:
            final_text = ", ".join(f"{name}({pct}%)" for name, pct in sorted_merged)

        if final_text == text:
            return None
        if fully_translated:
            with self._lock:
                self._translation_cache[text] = final_text
        return final_text

    def _is_valid_taxonomy_term(self, text: str, category: str) -> bool:
        if category not in ('species', 'genus'):
            return True
        try:
            lineage = get_taxonomy_provider().get_lineage_details(text)
            if not lineage:
                logging.getLogger(__name__).warning(
                    f"[Taxonomy Validation] 拉丁名 '{text}' 未在分类数据库中找到，跳过存入词库。"
                )
                return False
        except Exception as exc:
            logger.debug("物种校验查询失败，跳过该校验步骤 (%s): %s", text, exc)
        return True

    def _persist_ai_translation(self, source_text: str, translated_text: str, category: str, source_tag: str) -> None:
        if not self.translation_data_manager:
            return
        if not self._is_valid_taxonomy_term(source_text, category):
            return
        self.translation_data_manager.add_translation(
            source_text,
            translated_text,
            category=category or 'species',
            source=source_tag,
        )
        try:
            self.term_extractor.extract_and_store_key_terms(source_text, translated_text)
        except Exception as exc:
            logger.debug("术语提取与落库跳过异常 (%s): %s", source_text, exc)

    def _lookup_local_translation(self, text: str, original_text: str, category: str) -> Optional[str]:
        if not self.translation_data_manager:
            return None
        normalized_text = self.term_extractor.normalize_term(text)
        candidates = [normalized_text, text] if normalized_text != text else [text]
        for cand in candidates:
            local_result = self.translation_data_manager.get_translation(cand, category=category)
            if local_result and local_result != cand:
                with self._lock:
                    self._translation_cache[original_text] = str(local_result)
                return str(local_result)
        return None

    def translate_text(self, text: str, category: str = 'other', use_ai_override: Optional[bool] = None) -> str:
        """
        [SMART] 翻译整段文本 - 增加共识字符串拆解逻辑
        """
        if not text:
            return text

        with self._lock:
            if text in self._translation_cache:
                return self._translation_cache[text]

        consensus_res = self._translate_consensus_text(text, category, use_ai_override)
        if consensus_res is not None:
            return consensus_res

        local_hit = self._lookup_local_translation(text, text, category)
        if local_hit is not None:
            return local_hit

        active_use_ai = use_ai_override if use_ai_override is not None else self.use_ai
        if active_use_ai:
            if not self.ai_translator:
                if use_ai_override:
                    logging.getLogger(__name__).warning("请求了 AI 翻译，但尚未配置有效 API Key。")
            else:
                try:
                    logging.getLogger(__name__).info(f"[AI] 正在调用模型 '{self.ai_model}' 翻译: {text}")
                    ai_result = self.ai_translator.translate_text(text)
                    if ai_result and ai_result != text:
                        self._persist_ai_translation(text, ai_result, category, "ai")
                        with self._lock:
                            self._translation_cache[text] = ai_result
                        return ai_result
                except Exception as e:
                    logging.getLogger(__name__).error(f"[AITranslator] AI翻译异常: {e}")

        return text

    @staticmethod
    def _extract_batch_components(texts: list) -> set[str]:
        import re

        consensus_pattern = r'([^,()]+)\s*\(\s*(\d+)%\s*\)'
        pure_components: set[str] = set()
        for text in texts:
            if not text:
                continue
            if "," in text and "(" in text and "%" in text:
                matches = list(re.finditer(consensus_pattern, text))
                if matches:
                    for match in matches:
                        pure_components.add(match.group(1).strip())
                    continue
            pure_components.add(text)
        return pure_components

    def _partition_batch_texts(
        self,
        texts: list,
        to_ai_set: set[str],
        category: str,
        on_result_ready,
    ) -> tuple[dict, list]:
        import re

        consensus_pattern = r'([^,()]+)\s*\(\s*(\d+)%\s*\)'
        results: dict = {}
        pending_texts: list = []
        for text in texts:
            if not text:
                continue
            needs_ai = False
            if "," in text and "(" in text and "%" in text:
                matches = list(re.finditer(consensus_pattern, text))
                if matches:
                    needs_ai = any(m.group(1).strip() in to_ai_set for m in matches)
                elif text in to_ai_set:
                    needs_ai = True
            elif text in to_ai_set:
                needs_ai = True

            if not needs_ai:
                res = self.translate_text(text, category=category, use_ai_override=False)
                results[text] = res
                if on_result_ready:
                    on_result_ready(text, res)
            else:
                pending_texts.append(text)
        return results, pending_texts

    def _run_ai_batch_translation(
        self,
        to_ai_list: list[str],
        category: str,
        on_result_ready,
    ) -> None:
        if not (to_ai_list and self.use_ai and self.ai_translator):
            return
        try:
            chunk_size = 30
            ai_results = []
            for i in range(0, len(to_ai_list), chunk_size):
                ai_results.extend(self.ai_translator.batch_translate(to_ai_list[i : i + chunk_size]))

            for i, pure_text in enumerate(to_ai_list):
                if i >= len(ai_results):
                    break
                ai_res = ai_results[i]
                if not ai_res or ai_res == pure_text:
                    continue
                with self._lock:
                    self._translation_cache[pure_text] = ai_res
                if on_result_ready:
                    on_result_ready(pure_text, ai_res)
                self._persist_ai_translation(pure_text, ai_res, category, "ai_batch")
        except Exception as e:
            logging.getLogger(__name__).error(f"Biology Batch AI Error: {e}")

    def translate_batch(self, texts: list, category: str = "species", on_result_ready=None) -> dict:
        """
        [OPTIMIZED] 整合批量翻译：本地库优先 + AI 批量补偿 (修复复合文本AI乱翻译问题)
        """
        pure_components = self._extract_batch_components(texts)
        to_ai_set: set[str] = set()
        for pure_text in pure_components:
            clean_text = pure_text.strip()
            part_res = self.translate_text(clean_text, category=category, use_ai_override=False)
            if part_res == clean_text:
                to_ai_set.add(clean_text)
            elif on_result_ready:
                on_result_ready(clean_text, part_res)

        results, pending_texts = self._partition_batch_texts(texts, to_ai_set, category, on_result_ready)
        self._run_ai_batch_translation(list(to_ai_set), category, on_result_ready)

        for text in pending_texts:
            res = self.translate_text(text, category=category, use_ai_override=False)
            results[text] = res
            if on_result_ready:
                on_result_ready(text, res)
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


def get_biology_translator(data_file: Optional[str] = None, use_ai: bool = True, ai_api_key: Optional[str] = None, ai_model: str = "deepseek-r1") -> BiologyTranslator:
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


def get_global_biology_translator(data_file: Optional[str] = None, use_ai: bool = True, ai_api_key: Optional[str] = None, ai_model: str = "deepseek-r1") -> BiologyTranslator:
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