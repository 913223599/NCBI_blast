# -*- coding: utf-8 -*-
"""
WebBridge Mixin: AI 翻译 + 生物词典管理
职责：翻译桥接、异步 AI 翻译队列、词典 CRUD、校对修复
"""
import re
import json
import threading
from PyQt6.QtCore import pyqtSlot


class TranslationBridgeMixin:
    """翻译引擎桥接 Mixin"""

    def _init_translation_pool(self):
        """初始化翻译线程池（由 WebBridge.__init__ 调用）"""
        from concurrent.futures import ThreadPoolExecutor
        self._ai_trans_lock = threading.Lock()
        self._ai_trans_in_flight = set()
        self._ai_trans_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="AITranslator")

    @pyqtSlot(str, str, result=str)
    def translate_text(self, text, category='species'):
        """Enhanced Translation: Individual item processing with ASYNC AI fallback."""
        from src.utils.translation.biology_translator import get_global_biology_translator
        try:
            text = text.strip()
            if not text:
                return ""

            translator = get_global_biology_translator()

            def process_term(name):
                local_res = translator.translate_text(name, category=category, use_ai_override=False)
                if local_res and local_res != name:
                    return local_res
                if translator.use_ai:
                    with self._ai_trans_lock:
                        if name not in self._ai_trans_in_flight:
                            self._ai_trans_in_flight.add(name)
                            self._ai_trans_pool.submit(self._async_ai_worker, name, category)
                    return f"{name} (AI翻译中...)"
                return name

            pattern = r"([^,(]+)\s*\((?:\d{1,3}%)\)"
            segments = re.findall(pattern, text)

            if segments and "(" in text and "%" in text:
                def translate_match(match):
                    full_segment = match.group(0)
                    name_part = match.group(1).strip()
                    result = process_term(name_part)
                    return full_segment.replace(name_part, result)

                return re.sub(pattern, translate_match, text)

            return process_term(text)
        except Exception as exc:
            self.logger.error(f"Translation bridge error: {exc}")
            return text

    def _async_ai_worker(self, name, category):
        """后台 AI 翻译 worker，完成后通过信号通知前端"""
        from src.utils.translation.biology_translator import get_global_biology_translator
        self.logger.info(f"[AI] 开始异步翻译: {name}")
        try:
            translator = get_global_biology_translator()
            ai_res = translator.translate_text(name, category=category, use_ai_override=True)

            self.blast_event.emit("translation_done", json.dumps({
                "original": name,
                "translated": ai_res
            }))
            if ai_res and ai_res != name:
                self.logger.info(f"[AI] 翻译成功: {name} -> {ai_res}")
            else:
                self.logger.info(f"[AI] 翻译未产生变化或保持原文: {name}")
        except Exception as exc:
            self.logger.error(f"[AI] 异步翻译失败 {name}: {exc}")
            self.blast_event.emit("translation_done", json.dumps({
                "original": name,
                "translated": name
            }))
        finally:
            with self._ai_trans_lock:
                self._ai_trans_in_flight.discard(name)

    @pyqtSlot(str, bool, result=str)
    @pyqtSlot(str, result=str)
    def search_dictionary(self, query, proofread_mode=False):
        """Search translation dictionary"""
        from src.utils.translation.biology_translator import get_global_biology_translator
        try:
            translator = get_global_biology_translator()
            if translator.translation_data_manager:
                results = translator.translation_data_manager.search_translations(query)
            else:
                results = []
            if proofread_mode:
                results = [r for r in results if r.get('source') == 'ai']
            return json.dumps(results, ensure_ascii=False)
        except Exception as exc:
            self.logger.error(f"Dictionary search error: {exc}")
            return "[]"

    @pyqtSlot(str, str, str, result=bool)
    def save_dictionary_term(self, english, chinese, category):
        """Save or update a dictionary term"""
        from src.utils.translation.biology_translator import get_global_biology_translator
        try:
            translator = get_global_biology_translator()
            data_mgr = translator.translation_data_manager
            if data_mgr:
                return data_mgr.add_translation(english, chinese, category, source='manual_web')
            return False
        except Exception as exc:
            self.logger.error(f"Failed to save term: {exc}")
            return False

    @pyqtSlot(str, result=bool)
    def delete_dictionary_term(self, english):
        """Delete a term from dictionary"""
        from src.utils.translation.biology_translator import get_global_biology_translator
        import sqlite3
        try:
            translator = get_global_biology_translator()
            data_mgr = translator.translation_data_manager
            if data_mgr and data_mgr.db_path.exists():
                conn = sqlite3.connect(data_mgr.db_path)
                cursor = conn.cursor()
                cursor.execute('DELETE FROM translations WHERE english = ?', (english,))
                success = conn.total_changes > 0
                conn.commit()
                conn.close()
                if english in data_mgr._cache:
                    del data_mgr._cache[english]
                return success
            return False
        except Exception as exc:
            self.logger.error(f"Failed to delete term: {exc}")
            return False

    @pyqtSlot(bool, result=str)
    @pyqtSlot(result=str)
    def get_all_dictionary_terms(self, proofread_mode=False):
        """Get dictionary terms for management"""
        from src.utils.translation.biology_translator import get_global_biology_translator
        import sqlite3
        try:
            translator = get_global_biology_translator()
            data_mgr = translator.translation_data_manager
            if data_mgr:
                terms = []
                conn = sqlite3.connect(data_mgr.db_path)
                cursor = conn.cursor()
                if proofread_mode:
                    cursor.execute("SELECT english, chinese, category, source FROM translations WHERE source = 'ai' ORDER BY created_at DESC")
                else:
                    cursor.execute('SELECT english, chinese, category, source FROM translations ORDER BY created_at DESC')
                for row in cursor.fetchall():
                    terms.append({'english': row[0], 'chinese': row[1], 'category': row[2], 'source': row[3]})
                conn.close()
                return json.dumps(terms, ensure_ascii=False)
            return "[]"
        except Exception as exc:
            self.logger.error(f"Failed to get terms: {exc}")
            return "[]"

    @pyqtSlot(str, result=bool)
    def verify_dictionary_term(self, english):
        """Mark a dictionary term as verified"""
        import sqlite3
        from src.utils.translation.biology_translator import get_global_biology_translator
        try:
            translator = get_global_biology_translator()
            data_mgr = translator.translation_data_manager
            if data_mgr and data_mgr.db_path.exists():
                conn = sqlite3.connect(data_mgr.db_path)
                cursor = conn.cursor()
                cursor.execute("UPDATE translations SET source = 'verified' WHERE english = ?", (english,))
                success = conn.total_changes > 0
                conn.commit()
                conn.close()
                return success
            return False
        except Exception as exc:
            self.logger.error(f"Failed to verify term: {exc}")
            return False

    @pyqtSlot(result=str)
    def repair_dictionary_categories(self):
        """Repair dictionary categories using intelligent logic"""
        from src.utils.translation.biology_translator import get_global_biology_translator
        try:
            translator = get_global_biology_translator()
            if translator.translation_data_manager:
                results = translator.translation_data_manager.intelligent_repair_categories()
                return json.dumps(results)
            return json.dumps({"error": "No data manager"})
        except Exception as exc:
            self.logger.error(f"Failed to repair dictionary: {exc}")
            return json.dumps({"error": str(exc)})

    @pyqtSlot(str, str, str, result=bool)
    @pyqtSlot(str, str, result=bool)
    def update_dictionary_entry(self, english, chinese, category='species'):
        """Update a dictionary entry"""
        from src.utils.translation.biology_translator import get_global_biology_translator
        try:
            translator = get_global_biology_translator()
            success = translator.update_translation(english, chinese, category=category)
            if success:
                self.logger.info(f"Dictionary updated: {english} -> {chinese} (cat={category})")
            return success
        except Exception as exc:
            self.logger.error(f"Dictionary update error: {exc}")
            return False
