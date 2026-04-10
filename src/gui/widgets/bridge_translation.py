# -*- coding: utf-8 -*-
"""
WebBridge Mixin: AI 翻译 + 生物词典管理
职责：翻译桥接、异步 AI 翻译队列、词典 CRUD、校对修复
"""
import json
import re
import threading

from PyQt6.QtCore import pyqtSlot

class TranslationBridgeMixin:
    """翻译引擎桥接 Mixin"""

    def _init_translation_pool(self):
        """初始化翻译辅助设施"""
        import threading
        self._ai_trans_lock = threading.Lock()
        self._ai_trans_in_flight = set()

    @pyqtSlot(str, str, result=str)
    def translate_text(self, text, category='species'):
        """单个文本翻译（保留单步逻辑，但任务投递至全局池）"""
        from src.utils.translation.biology_translator import get_global_biology_translator
        from PyQt6.QtCore import QThreadPool, QRunnable
        
        try:
            text = text.strip()
            if not text: return ""

            translator = get_global_biology_translator()

            def process_term(name):
                local_res = translator.translate_text(name, category=category, use_ai_override=False)
                if local_res and local_res != name:
                    return local_res
                if translator.use_ai:
                    with self._ai_trans_lock:
                        if name not in self._ai_trans_in_flight:
                            self._ai_trans_in_flight.add(name)
                            # 使用全局线程池分发任务
                            class TransTask(QRunnable):
                                def __init__(self, target, n, c):
                                    super().__init__()
                                    self.target = target
                                    self.n = n
                                    self.c = c
                                def run(self):
                                    self.target(self.n, self.c)
                            QThreadPool.globalInstance().start(TransTask(self._async_ai_worker, name, category))
                    return f"{name} (AI翻译中...)"
                return name

            # 处理带有百分比的复合名称
            pattern = r"([^,(]+)\s*\((?:\d{1,3}%)\)"
            if re.findall(pattern, text) and "(" in text and "%" in text:
                return re.sub(pattern, lambda m: m.group(0).replace(m.group(1), process_term(m.group(1).strip())), text)

            return process_term(text)
        except Exception as exc:
            self.logger.error(f"Translation bridge error: {exc}")
            return text

    @pyqtSlot(str, str)
    def translate_batch(self, texts_json, category='species'):
        """[ULTRA-OPTIMIZED] 整合批处理：将词条分组并使用 AI 批量接口，提速 10 倍以上"""
        from PyQt6.QtCore import QThreadPool, QRunnable
        try:
            names = json.loads(texts_json)
            if not isinstance(names, list) or not names: return

            # 分组大小（建议 15-20，平衡性能与准确度）
            CHUNK_SIZE = 20
            chunks = [names[i:i + CHUNK_SIZE] for i in range(0, len(names), CHUNK_SIZE)]

            for chunk in chunks:
                class BatchAITask(QRunnable):
                    def __init__(self, mixin, targets, cat):
                        super().__init__()
                        self.mixin = mixin
                        self.targets = targets
                        self.cat = cat
                    def run(self):
                        from src.utils.translation.biology_translator import get_global_biology_translator
                        try:
                            translator = get_global_biology_translator()
                            # 1. 尝试从本地库批量获取（这一步很快）
                            # 2. 对库里没有的，调用 AI 批量翻译
                            results = translator.translate_batch(self.targets, category=self.cat)
                            
                            # 陆续发射结果，让前端实时更新
                            for orig, tran in results.items():
                                if tran and tran != orig:
                                    self.mixin.blast_event.emit("translation_done", json.dumps({
                                        "original": orig, "translated": tran
                                    }))
                        except Exception as e:
                            print(f"[BatchAITask] Error: {e}")
                
                QThreadPool.globalInstance().start(BatchAITask(self, chunk, category))
        except Exception as e:
            self.logger.error(f"Batch translation dispatch error: {e}")

    def _async_ai_worker(self, name, category):
        """后台单体 AI 翻译 worker"""
        from src.utils.translation.biology_translator import get_global_biology_translator
        try:
            translator = get_global_biology_translator()
            ai_res = translator.translate_text(name, category=category, use_ai_override=True)
            self.blast_event.emit("translation_done", json.dumps({"original": name, "translated": ai_res}))
        except Exception as exc:
            self.logger.error(f"[AI] 异步翻译失败 {name}: {exc}")
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
                results = [r for r in results if r.get('source') in ('ai', 'ai_batch')]
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
                    cursor.execute("SELECT english, chinese, category, source FROM translations WHERE source IN ('ai', 'ai_batch') ORDER BY created_at DESC")
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
