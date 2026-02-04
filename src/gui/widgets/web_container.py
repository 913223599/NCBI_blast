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
from src.gui.workers.tree_worker_thread import TreeWorker
from PyQt6.QtWidgets import QFileDialog

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

        # Connect to BlastManager real-time result stream
        self.blast_manager.result_listeners.append(self._broadcast_result)

    def _broadcast_result(self, task_id, data):
        """Internal callback to push single result to JS"""
        # Ensure we have the parsed data for the matrix row 
        # (similar to what get_task_results does)
        if 'csv_file' in data and os.path.exists(data['csv_file']):
            parsed = self._parse_blast_csv(data['csv_file'], limit=1)
            data['data'] = parsed
        
        self.blast_event.emit("single_result_update", json.dumps({
            "task_id": task_id,
            "result": data
        }))

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
        self.logger.info(f"BRIDGE: JS requested file load for type: {file_type}")
        try:
            self.container.open_file_dialog(file_type)
        except Exception as e:
            self.logger.error(f"BRIDGE ERROR in open_file_dialog: {e}")

    @pyqtSlot(str, str, result=bool)
    def save_file(self, content, filename_hint="export.txt"):
        """Save text content to valid local file via Dialog"""
        from PyQt6.QtWidgets import QFileDialog, QMessageBox
        try:
            # Determine filter based on extension
            file_filter = "All Files (*.*)"
            if filename_hint.endswith("svg"):
                file_filter = "SVG Files (*.svg);;All Files (*.*)"
            elif filename_hint.endswith("png"):
                file_filter = "PNG Files (*.png);;All Files (*.*)"
            elif filename_hint.endswith("nwk"):
                file_filter = "Newick Files (*.nwk *.tree);;All Files (*.*)"
                
            path, _ = QFileDialog.getSaveFileName(self.container, "Save File", filename_hint, file_filter)
            
            if path:
                with open(path, 'w', encoding='utf-8') as f:
                    f.write(content)
                self.logger.info(f"File saved successfully to: {path}")
                return True
            return False # Cancelled
        except Exception as e:
            self.logger.error(f"Save File Error: {e}")
            return False

    @pyqtSlot()
    def request_tree_analysis(self):
        """Handle request to run tree analysis from iTOL page"""
        self.logger.info("JS requested tree analysis")
        self.container.run_tree_analysis()

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
        """Clear all tasks and notify if some folders were locked"""
        self.logger.info("JS requested clear all history")
        failed_paths = self.blast_manager.clear_history()
        
        if failed_paths:
            self.logger.warning(f"Batch clear partially failed. {len(failed_paths)} folders locked.")
            self.blast_event.emit("batch_deletion_failed", json.dumps({
                "failed_list": failed_paths
            }))
        
        # We still emit status_update to refresh the list for items that WERE deleted
        self.blast_event.emit("status_update", json.dumps({"status": "cleared"}))

    @pyqtSlot(str)
    def delete_single_task(self, task_id):
        """Delete specific task and notify on failure"""
        self.logger.info(f"JS requested delete task: {task_id}")
        success, failed_path = self.blast_manager.delete_task(task_id)
        if not success:
            self.logger.warning(f"Deletion failed for {task_id}, path blocked: {failed_path}")
            # Notify JS via blast_event signal
            self.blast_event.emit("deletion_failed", json.dumps({
                "task_id": task_id,
                "path": failed_path
            }))

    @pyqtSlot(str)
    def resume_task(self, task_id):
        """Resume a failed/cancelled task"""
        self.logger.info(f"JS requested resume task: {task_id}")
        if self.blast_manager.resume_task(task_id):
            # Notify JS to refresh UI immediately
            self.blast_event.emit("status_update", json.dumps({"status": "resumed", "task_id": task_id}))

    @pyqtSlot(str)
    def open_results_dir(self, path):
        """Open results directory in explorer"""
        self.logger.info(f"JS requested open folder: {path}")
        self.blast_manager.open_directory(path)

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
                        'acc': row.get('访问号', 'N/A'),
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

    def run_tree_analysis(self):
        """
        Open file dialog (supports multi-select), merge if needed, run TreeWorker.
        """
        # 1. Allow multi-select and .seq/.txt files
        paths, _ = QFileDialog.getOpenFileNames(self, "Select Sequences for Tree", "", "Sequence Files (*.fasta *.fa *.fna *.seq *.txt);;All Files (*.*)")
        
        if not paths:
            return

        final_path = paths[0]
        
        # 2. If multiple files OR single non-fasta file, we merge/convert
        if len(paths) > 1 or (len(paths) == 1 and not paths[0].lower().endswith(('.fasta', '.fa', '.fna'))):
            try:
                # Create a named temp file that persists so worker can read it
                # We put it in result dir or temp dir
                import tempfile
                
                # Use a specific prefix to identify merged files
                with tempfile.NamedTemporaryFile(mode='w', suffix='_merged.fasta', delete=False, encoding='utf-8') as tmp:
                    final_path = tmp.name
                    self.logger.info(f"Merging {len(paths)} files into temporary FASTA: {final_path}")
                    
                    for p in paths:
                        p_obj = Path(p)
                        with open(p, 'r', encoding='utf-8', errors='ignore') as src:
                            content = src.read().strip()
                            if not content: continue
                            
                            # Heuristic: If content starts with >, assume it's already FASTA fragment
                            # Otherwise, assume raw sequence
                            header = p_obj.stem
                            
                            if content.startswith('>'):
                                # Write as is, ensure newline
                                tmp.write(f"{content}\n")
                            else:
                                # Raw sequence, wrap it
                                # Remove all whitespace/newlines from sequence
                                clean_seq = "".join(content.split())
                                tmp.write(f">{header}\n{clean_seq}\n")
                                
            except Exception as e:
                QMessageBox.critical(self, "Merge Error", f"Failed to merge sequence files:\n{str(e)}")
                return
            
        self.logger.info(f"Starting tree analysis for {final_path}")
        # Notify JS that we started with VISIBLE loading state
        self.web_view.page().runJavaScript("if(window.showLoading) window.showLoading('正在构建进化树...');")
        self.web_view.page().runJavaScript("console.log('[Py] Starting tree analysis...');")
        
        # Create worker
        # Store worker in self to prevent garbage collection
        self.tree_worker = TreeWorker(final_path)
        self.tree_worker.finished.connect(self.on_tree_finished)
        self.tree_worker.error.connect(self.on_tree_error)
        self.tree_worker.progress.connect(self.on_tree_progress)
        self.tree_worker.start()

    def on_tree_progress(self, data):
        """Handle progress updates from TreeWorker"""
        try:
            percent = data.get("progress", 0)
            msg = data.get("message", "")
            # Call JS update
            # We use a try-catch block in JS to be safe
            js_code = f"if(window.updateLoading) window.updateLoading({percent}, '{msg}');"
            self.web_view.page().runJavaScript(js_code)
        except Exception as e:
            self.logger.error(f"Error updating progress: {e}")
        
    def on_tree_finished(self, result):
        # Hide loading first
        self.web_view.page().runJavaScript("if(window.hideLoading) window.hideLoading();")
        
        self.logger.info("Tree analysis finished")
        if "tree_file" in result:
            tree_path = result["tree_file"]
            try:
                with open(tree_path, 'r') as f:
                    newick_content = f.read().strip()
                
                # Escape JSON
                safe_newick = json.dumps(newick_content)
                
                # CRITICAL FIX: Target the iframe, not the main window
                js_code = f"""
                (function() {{
                    var iframe = document.querySelector("#tree-view iframe");
                    // If we are INSIDE the iframe (which matches tree_explorer structure), window.loadTree exists directly
                    if (window.loadTree) {{
                        console.log("[Py->JS] Loading tree directly in current view...");
                        window.loadTree({safe_newick});
                    }} 
                    else if (iframe && iframe.contentWindow && iframe.contentWindow.loadTree) {{
                        console.log("[Py->JS] Injecting tree data into child iframe...");
                        iframe.contentWindow.loadTree({safe_newick});
                    }} else {{
                        console.error("[Py->JS] Failed to find target window for loadTree.");
                    }}
                }})();
                """
                self.web_view.page().runJavaScript(js_code)
                self.logger.info(f"Injected tree data ({len(newick_content)} bytes)")
            except Exception as e:
                self.logger.error(f"Failed to read tree file: {e}")
                self.web_view.page().runJavaScript(f"console.error('Failed to read tree file: {str(e)}'); alert('读取树文件失败: {str(e)}');")
        else:
             self.logger.warning("No tree file in result")
             self.web_view.page().runJavaScript("console.warn('No tree file generated.'); alert('建树失败：未生成结果文件');")

    def on_tree_error(self, err_msg):
        self.web_view.page().runJavaScript("if(window.hideLoading) window.hideLoading();")
        self.logger.error(f"Tree analysis error: {err_msg}")
        self.web_view.page().runJavaScript(f"console.error('Tree analysis failed: {err_msg}'); alert('建树过程出错: {err_msg}');")
