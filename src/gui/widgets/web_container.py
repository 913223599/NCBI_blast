# Modules
import os
import json
import logging
import tempfile
import datetime
from pathlib import Path
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QMessageBox
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebChannel import QWebChannel
from PyQt6.QtCore import QUrl, QObject, pyqtSlot, pyqtSignal

# BLAST Logic
from src.blast.manager import get_blast_manager

class WebBridge(QObject):
    """Bridge for JS to python communication"""
    
    # Signals
    page_ready = pyqtSignal()
    help_requested = pyqtSignal()
    blast_event = pyqtSignal(str, str) # type, json_data
    
    def __init__(self, container):
        super().__init__()
        self.container = container
        self.logger = logging.getLogger(__name__)
        
        # Initialize BlastManager
        self.blast_manager = get_blast_manager()
        
        # Setup Arrearage Callback for QwenTranslator
        try:
            from src.utils.translation.qwen_translator import QwenTranslator
            QwenTranslator._on_arrearage_callback = self.notify_arrearage
        except ImportError:
            pass

    def notify_arrearage(self):
        """Notify JS about AI account arrearage"""
        self.logger.warning("AI Translation Arrearage detected, notifying UI")
        # Run on main thread or via signal is safer, but WebEngine is usually okay with cross-thread JS
        js_code = "if(window.app && window.app.showNotification) window.app.showNotification('AI 翻译账户欠费或访问受限，已自动切换为本地翻译模式。', 'error', 10000);"
        self.container.web_view.page().runJavaScript(js_code)

    @pyqtSlot()
    def request_help(self):
        """Handle help request from JS (Legacy or Toggle)"""
        self.logger.info("JS requested help dialog")
        # If we use embedded help, we might just want to switch view in JS, 
        # but if we want to support the external dialog, we emit.
        # For now, let's keep the signal but ALSO expose data methods.
        self.help_requested.emit()

    @pyqtSlot(result=list)
    def get_help_structure(self):
        """Return the help category structure to JS"""
        from src.utils.help_manager import get_help_manager
        return get_help_manager().get_help_structure()

    @pyqtSlot(str, result=str)
    def get_help_content(self, topic_id):
        """Return markdown content for a topic"""
        from src.utils.help_manager import get_help_manager
        return get_help_manager().get_help_content(topic_id)

    @pyqtSlot(str)
    def on_js_error(self, message):
        self.logger.error(f"[JS Error] {message}")

    @pyqtSlot(str)
    def on_js_log(self, message):
        self.logger.info(f"[JS Log] {message}")
        
    @pyqtSlot()
    def on_page_ready(self):
        self.logger.info("Web Container Report: Ready")
        self.page_ready.emit()
    
    @pyqtSlot(str)
    def request_file_load(self, file_type):
        """Handle file load request from JS"""
        self.logger.info(f"JS requested file load for type: {file_type}")
        self.container.open_file_dialog(file_type)

    @pyqtSlot(str, result=str)
    def run_blast_job(self, params_json):
        """Run BLAST job via BlastManager"""
        self.logger.info(f"BLAST Job Requested via Manager: {params_json}")
        try:
            params = json.loads(params_json)
            
            # Basic validation
            if not params.get('query') and not params.get('files'):
                return json.dumps({'status': 'error', 'error': 'No query or files provided'})
            
            # Create task in manager
            task_id = self.blast_manager.create_task(params)
            
            return json.dumps({
                'status': 'started', 
                'message': 'BLAST job launched in background', 
                'task_id': task_id
            })
                
        except Exception as e:
            self.logger.error(f"BLAST Launch Error: {e}")
            return json.dumps({'status': 'error', 'error': str(e)})

    @pyqtSlot(str)
    def stop_blast_job(self, task_id):
        """Cancel a running job"""
        self.blast_manager.stop_task(task_id)

    @pyqtSlot(str)
    def pause_blast_job(self, task_id):
        """Pause a running job"""
        self.blast_manager.pause_task(task_id)

    @pyqtSlot(str)
    def resume_blast_job(self, task_id):
        """Resume a paused job"""
        self.blast_manager.resume_task(task_id)

    @pyqtSlot(str, result=str)
    def get_task_status(self, task_id):
        """Query task status from manager"""
        status = self.blast_manager.get_task_status(task_id)
        return json.dumps(status) if status else "{}"

    # --- AI Translation & Settings Slots ---

    @pyqtSlot(str, result=str)
    def get_api_key(self, service):
        """Get API key from config"""
        from src.utils.config_manager import get_config_manager
        return get_config_manager().get_api_key(service)

    # --- UI Translation Slots ---
    @pyqtSlot(result=str)
    def get_ui_translations(self):
        """Return full translation dictionary for current language"""
        from src.utils.ui_translation_manager import get_ui_translator
        tr = get_ui_translator()
        data = tr.get_all_translations_for_current_lang()
        return json.dumps(data, ensure_ascii=False)

    @pyqtSlot(result=str)
    def get_ui_language(self):
        """Get current UI language code"""
        from src.utils.ui_translation_manager import get_ui_translator
        return get_ui_translator().get_language()

    @pyqtSlot(str, result=bool)
    def save_ui_language(self, lang_code):
        """Save UI language and return True if successful"""
        try:
            from src.utils.ui_translation_manager import get_ui_translator
            get_ui_translator().set_language(lang_code)
            self.logger.info(f"UI Language switched to: {lang_code}")
            return True
        except Exception as e:
            self.logger.error(f"Failed to save UI language: {e}")
            return False

    @pyqtSlot(str, str, result=bool)
    def update_dictionary_entry(self, english, chinese):
        """Update a translation entry manually."""
        try:
            success = self.translator.data_manager.update_entry(english, chinese)
            return success
        except Exception as e:
            logging.error(f"Bridge update_dictionary_entry error: {e}")
            return False

    @pyqtSlot(str, result=str)
    def search_dictionary(self, query):
        """Search dictionary entries."""
        try:
            results = self.translator.data_manager.search_entries(query)
            return json.dumps(results, ensure_ascii=False)
        except Exception as e:
            logging.error(f"Bridge search_dictionary error: {e}")
            return "[]"

    @pyqtSlot(str, str, result=bool)
    def save_api_key(self, service, key):
        """Save API key to config"""
        try:
            from src.utils.config_manager import get_config_manager
            get_config_manager().set_api_key(service, key)
            self.logger.info(f"API key for {service} saved via bridge")
            return True
        except Exception as e:
            self.logger.error(f"Failed to save API key for {service}: {e}")
            return False

    @pyqtSlot(str, str, result=str)
    def translate_text(self, text, category='species'):
        """Translate text using BiologyTranslator"""
        from src.utils.translation.biology_translator import get_global_biology_translator
        try:
            # Normalize input
            text = text.strip()
            if not text: return ""
            
            self.logger.info(f"Bridge translating: [{text}] (cat={category})")
            
            translator = get_global_biology_translator()
            result = translator.translate_text(text, category=category)
            
            self.logger.info(f"Bridge result: [{text}] -> [{result}]")
            return result if result else text
        except Exception as e:
            self.logger.error(f"Translation bridge error: {e}")
            return text

    @pyqtSlot(str, result=str)
    def search_dictionary(self, query):
        """Search translation dictionary"""
        from src.utils.translation.biology_translator import get_global_biology_translator
        try:
            translator = get_global_biology_translator()
            results = translator.search_translations(query)
            return json.dumps(results)
        except Exception as e:
            self.logger.error(f"Dictionary search error: {e}")
            return "[]"

    @pyqtSlot(str, result=bool)
    def update_dictionary_entry(self, english, chinese):
        """Update a dictionary entry"""
        from src.utils.translation.biology_translator import get_global_biology_translator
        try:
            translator = get_global_biology_translator()
            success = translator.update_translation(english, chinese)
            if success:
                self.logger.info(f"Dictionary updated: {english} -> {chinese}")
            return success
        except Exception as e:
            self.logger.error(f"Dictionary update error: {e}")
            return False

    # --- AI Model Config ---
    @pyqtSlot(result=str)
    def get_supported_ai_models(self):
        """Get list of supported AI models from config"""
        try:
            from src.utils.config_manager import get_config_manager
            # Returns dict {key: name}
            models = get_config_manager().get_supported_models() 
            return json.dumps(models)
        except Exception as e:
            self.logger.error(f"Failed to get supported models: {e}")
            return "{}"

    @pyqtSlot(result=str)
    def get_current_ai_model(self):
        """Get currently selected AI model"""
        try:
            from src.utils.config_manager import get_config_manager
            settings = get_config_manager().get_advanced_settings()
            current = settings.get("ai_model", "deepseek-r1")
            self.logger.debug(f"Bridge: get_current_ai_model returning '{current}'")
            return current
        except Exception as e:
            self.logger.error(f"Failed to get current model: {e}")
            return "deepseek-r1"

    @pyqtSlot(str, result=bool)
    def save_ai_model(self, model_key):
        """Save selected AI model"""
        try:
            from src.utils.config_manager import get_config_manager
            cm = get_config_manager()
            settings = cm.get_advanced_settings()
            settings["ai_model"] = model_key
            cm.set_advanced_settings(settings)
            self.logger.info(f"AI Model switched to: {model_key}")
            return True
        except Exception as e:
            self.logger.error(f"Failed to save AI model: {e}")
            return False

    @pyqtSlot(str, result=str)
    def test_ai_model(self, model_key):
        """
        测试新增模型是否可用
        Returns: JSON string {"success": bool, "message": str}
        """
        try:
            from src.utils.translation.qwen_translator import QwenTranslator
            import json
            
            # 使用临时实例进行测试
            self.logger.info(f"Bridge testing model: {model_key}")
            translator = QwenTranslator(model=model_key)
            success, message = translator.validate_model()
            self.logger.info(f"Model test result: {success}, {message}")
            
            return json.dumps({"success": success, "message": message})
        except Exception as e:
            self.logger.error(f"Bridge testing model exception: {e}")
            return json.dumps({"success": False, "message": str(e)})
            
    @pyqtSlot(str, str, result=bool)
    def add_ai_model(self, model_key, model_name):
        """Add a new AI model to the supported list"""
        try:
            from src.utils.config_manager import get_config_manager
            get_config_manager().add_supported_model(model_key, model_name)
            self.logger.info(f"AI Model added: {model_key} ({model_name})")
            return True
        except Exception as e:
            self.logger.error(f"Failed to add AI model: {e}")
            return False

    @pyqtSlot(str, result=bool)
    def delete_ai_model(self, model_key):
        """Remove an AI model from the supported list"""
        try:
            from src.utils.config_manager import get_config_manager
            get_config_manager().remove_supported_model(model_key)
            self.logger.info(f"AI Model removed: {model_key}")
            return True
        except Exception as e:
            self.logger.error(f"Failed to remove AI model: {e}")
            return False

    @pyqtSlot(str, result=str)
    def get_task_results(self, task_id):
        """Fetch results for a task"""
        results = self.blast_manager.get_task_results(task_id)
        for res in results:
            if 'csv_file' in res and os.path.exists(res['csv_file']):
                res['data'] = self._parse_blast_csv(res['csv_file'], limit=1) # Matrix only needs top hit
        return json.dumps(results)

    @pyqtSlot(str, result=str)
    def get_detailed_blast_results(self, csv_file):
        """Fetch ALL hits from a specific CSV file for detail view"""
        if not os.path.exists(csv_file):
            return "[]"
        data = self._parse_blast_csv(csv_file, limit=None) # Get all
        return json.dumps(data)

    @pyqtSlot(str)
    def open_alignment_visualizer(self, xml_file):
        """Trigger pop-up matplotlib-based visualizer"""
        from src.gui.widgets.alignment_visualizer import AlignmentVisualizerDialog
        if os.path.exists(xml_file):
            # We use parent.parent because bridge's container is WebContainer, 
            # and we want the main window as parent usually, but container is fine.
            dial = AlignmentVisualizerDialog(xml_file, self.container)
            dial.exec()
        else:
            self.logger.error(f"XML file not found for visualizer: {xml_file}")


    @pyqtSlot(result=str)
    def get_all_tasks(self):
        """Return list of all current and past tasks"""
        tasks = self.blast_manager.list_tasks()
        return json.dumps(tasks)

    @pyqtSlot()
    def clear_all_history(self):
        """Clear all tasks via manager"""
        self.logger.info("JS requested clear history")
        self.blast_manager.clear_history()

    @pyqtSlot(str)
    def delete_single_task(self, task_id):
        """Delete specific task"""
        self.logger.info(f"JS requested delete task: {task_id}")
        self.blast_manager.delete_task(task_id)

    def _parse_blast_csv(self, csv_path, limit=None):
        """Parse BLAST CSV output to list of dicts for Web UI"""
        import csv
        data = []
        try:
            with open(csv_path, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                count = 0
                for row in reader:
                    # Simplify keys for Web
                    data.append({
                        'title': row.get('标题', 'Unknown'),
                        'len': row.get('长度', '0'),
                        'acc': row.get('登录号', 'N/A'),
                        'species': row.get('物种', 'N/A'),
                        'genus': row.get('属名', ''),
                        'strain': row.get('菌株', ''),
                        'gene_type': row.get('基因类型', ''),
                        'seq_type': row.get('序列类型', ''),
                        'host': row.get('宿主信息', ''),
                        'hsp_count': row.get('高得分片段对(HSPs)', '0'),
                        'evalue': row.get('E值', 'N/A'),
                        'align_len': row.get('比对长度', '0'),
                        'ident_count': row.get('相同碱基数', '0'),
                        'similarity': row.get('相似度', '0%'),
                        'gaps': row.get('缺口数', '0'),
                        'query_range': row.get('查询起始-结束', ''),
                        'hit_range': row.get('命中起始-结束', '')
                    })
                    count += 1
                    if limit and count >= limit:
                        break
        except Exception as e:
            self.logger.error(f"CSV Parse Error: {e}")
        return data

    def _generate_summary(self, result):
        import os
        return f"Processed {os.path.basename(str(result.get('file','')))} in {result.get('elapsed_time',0):.2f}s"



class DnDWebEngineView(QWebEngineView):
    """
    Subclass to intercept Drag and Drop events.
    Prevents the browser from navigating to the file and instead
    feeds the path back to the application logic.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.accept()
        else:
            super().dragEnterEvent(event)

    def dropEvent(self, event):
        if event.mimeData().hasUrls():
            urls = event.mimeData().urls()
            paths = []
            for url in urls:
                if url.isLocalFile():
                    paths.append(str(url.toLocalFile()))
            
            if paths:
                event.accept()
                print(f"Intercepted Drop: {paths}")
                # Inject into JS
                # access parent (WebContainer) -> bridge? 
                # Or run JS directly.
                import json
                safe_paths = json.dumps(paths)
                
                # Check which view is active via JS or assume active app handles it
                # We call a generic handleFilesDropped on window.app
                js_code = f"if(window.app && window.app.handleFilesDropped) window.app.handleFilesDropped({safe_paths});"
                self.page().runJavaScript(js_code)
                return
        
        super().dropEvent(event)


class WebContainer(QWidget):
    """
    Main Web Container Widget.
    Hosts the Single Page Application (SPA).
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.logger = logging.getLogger(__name__)
        self.bridge = WebBridge(self) # Pass self to bridge
        self.setup_ui()
        
    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # Subclassing QWebEngineView to capture drops might be needed if standard view consumes them
        # But installing event filter or overriding parent events works too.
        # However, WebEngineView has its own drop handling (loading file).
        # We need to strictly intercept it.
        self.web_view = DnDWebEngineView(self) # Use custom class
        
        # ... (rest of setup)
        
        # Enable JS features like popups (required for iCn3D menus)
        settings = self.web_view.settings()
        settings.setAttribute(settings.WebAttribute.JavascriptCanOpenWindows, True)
        settings.setAttribute(settings.WebAttribute.JavascriptCanAccessClipboard, True)
        settings.setAttribute(settings.WebAttribute.LocalStorageEnabled, True)
        
        # Setup WebChannel
        self.channel = QWebChannel()
        self.channel.registerObject("py_bridge", self.bridge)
        self.web_view.page().setWebChannel(self.channel)
        
        # Handle "window.open" - simplified for now: load in main view or just allow it.
        # Custom page class or signal connection might be needed for full multi-window support.
        
        # Load the local index.html
        base_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../web"))
        index_path = os.path.join(base_path, "index.html")
        
        if not os.path.exists(index_path):
            self.logger.error(f"Web Container index not found at: {index_path}")
            QMessageBox.critical(self, "Error", f"Web App not found at {index_path}")
        else:
            url = QUrl.fromLocalFile(index_path)
            self.logger.info(f"Loading Web Container from: {url.toString()}")
            self.web_view.load(url)
            
        layout.addWidget(self.web_view)

    def reload(self):
        self.web_view.reload()

    def open_file_dialog(self, file_type):
        """Open QFileDialog and inject content back to JS"""
        from PyQt6.QtWidgets import QFileDialog, QMessageBox
        
        filter_str = "All Files (*.*)"
        if file_type == 'tree':
            filter_str = "Tree Files (*.nwk *.newick *.txt);;All Files (*.*)"
        elif file_type == 'structure':
            filter_str = "Protein Structure (*.pdb *.ent);;All Files (*.*)"
        elif file_type == 'fasta':
            filter_str = "Sequence Files (*.fasta *.fas *.fa *.seq *.ab1 *.abi);;All Files (*.*)"
            
        file_path, _ = QFileDialog.getOpenFileName(self, f"Open {file_type}", "", filter_str)
        
        if file_path:
            try:
                ext = Path(file_path).suffix.lower()
                content = ""
                
                # 特殊处理：如果是二进制测序文件，通过 FileHandler 提取序列文本
                if ext in ['.ab1', '.abi']:
                    from src.utils.file_handler import FileHandler
                    handler = FileHandler()
                    for seq_info in handler.read_fasta_file_iter(file_path):
                        content = seq_info['sequence']
                        break # 目前仅支持单序列预览/注入
                else:
                    # 普通文本文件处理
                    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                        content = f.read()
                
                if not content:
                    raise ValueError("无法从文件中提取有效序列或内容为空")

                # Escape content for JS string
                import json
                safe_content = json.dumps(content)
                safe_path = json.dumps(file_path)
                
                # Call JS: window.app.handleFileLoaded(content, file_type, path)
                js_code = f"window.app.handleFileLoaded({safe_content}, '{file_type}', {safe_path});"
                self.web_view.page().runJavaScript(js_code)
                self.logger.info(f"Injected {file_type} file content to JS (Size: {len(content)})")
                
            except Exception as e:
                self.logger.error(f"Failed to read file {file_path}: {e}")
                QMessageBox.warning(self, "读取错误", f"无法读取文件 {Path(file_path).name}:\n{str(e)}")
