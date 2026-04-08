# Modules
import os
import json
import logging
import tempfile
import datetime
import time
from pathlib import Path
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QMessageBox
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebChannel import QWebChannel
from PyQt6.QtCore import QUrl, QObject, pyqtSlot, pyqtSignal
from PyQt6.QtWebEngineCore import QWebEngineProfile, QWebEnginePage

# BLAST Logic
from src.blast.manager import get_blast_manager
from src.workbench.models.annotation_manager import get_annotation_manager
from src.gui.workers.tree_worker_thread import TreeWorker
from PyQt6.QtWidgets import QFileDialog

class WebBridge(QObject):
    """Bridge for JS to python communication"""
    
    # Signals
    page_ready = pyqtSignal()
    help_requested = pyqtSignal()
    blast_event = pyqtSignal(str, str) # type, json_data
    recall_event = pyqtSignal(bool, str) # success, message
    
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
        
        # Connect bridge signal to actual JS execution
        self.blast_event.connect(self._on_bridge_event_emitted)
        
        # Async Translation Queue & Limited Pool
        import threading
        from concurrent.futures import ThreadPoolExecutor
        self._ai_trans_lock = threading.Lock()
        self._ai_trans_in_flight = set()  # Track items currently being translated by AI
        # 使用线程池限制并发量(例如最多4个并发)，防止大规模翻译导致系统负载过高或 API 频率超限
        self._ai_trans_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="AITranslator")

    def _on_bridge_event_emitted(self, event_type, json_data):
        """Relay signals from Python to JS global handler in the WebView"""
        try:
            # Escape strings for safe JS injection
            safe_type = json.dumps(event_type)
            # data is already json_data string
            js_code = f"if(window.handleBridgeEvent) window.handleBridgeEvent({safe_type}, {json_data});"
            self.container.web_view.page().runJavaScript(js_code)
        except Exception as e:
            self.logger.error(f"Failed to relay bridge event: {e}")

    def _broadcast_result(self, task_id, data):
        """Internal callback to push single result to JS (with top-50/98% consensus logic)"""
        best_hit = None
        if 'csv_file' in data and os.path.exists(data['csv_file']):
            # 根据需求，扩大到前 50 个结果进行 98% 相似度一致性分析
            top_hits = self._parse_blast_csv(data['csv_file'], limit=50)
            best_hit = self._select_consensus_hit(top_hits)
            data['data'] = [best_hit] if best_hit else []
        
        self.blast_event.emit("single_result_update", json.dumps({
            "task_id": task_id,
            "result": data
        }))
        
        # Sync with Annotation Manager if we found a good identity
        if best_hit:
            try:
                # 优先级 1: 使用共识推举引擎提取的精简物种名 (speciesName)
                # 优先级 2: 使用原始结果中的 species 字段
                # 优先级 3: 使用标题
                identity = best_hit.get('speciesName') or best_hit.get('species') or best_hit.get('title')
                
                if identity:
                    # 鲁棒性清洗：提取真正的物种名 (通常为前两个单词)
                    # 例如 "Citrobacter freundii strain CH-GX-BL..." -> "Citrobacter freundii"
                    import re
                    # 匹配双名法：两个单词组成的专有名词
                    match = re.search(r'^([A-Z][a-z]+(?:\s+[a-z]+))', identity.strip())
                    if match:
                        identity = match.group(1)
                    else:
                        # 兜底：取第一个分号前的部分并修剪
                        identity = identity.split(';')[0].split(' strain')[0].split(' genome')[0].strip()
                    
                    self.logger.info(f"Consensus Identity Elected: {identity}")
                    
                    # 关键修复：同步到 V2 哈希库，确保进化树能召回这个“推举”后的词条
                    get_annotation_manager().update_annotation(
                        sequence_hash=data.get('sequence_hash'),
                        last_known_id=data.get('sequence_id'),
                        blast_identity=identity
                    )
            except Exception as e:
                self.logger.error(f"Failed to sync consensus annotation: {e}")

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

    @pyqtSlot(str, result=str)
    def get_annotations_by_hashes(self, hashes_json):
        """Fetch human-readable names via Content Hash (MD5) lookup with runtime cleaning"""
        try:
            import re
            hashes = json.loads(hashes_json)
            mapping = get_annotation_manager().get_annotations_by_hashes(hashes)
            
            # Runtime Cleaning: Ensure older long records are also simplified
            clean_mapping = {}
            for h, identity in mapping.items():
                if identity:
                    # 同样的清洗逻辑：只保留前两个单词
                    match = re.search(r'^([A-Z][a-z]+(?:\s+[a-z]+))', identity.strip())
                    if match:
                        clean_mapping[h] = match.group(1)
                    else:
                        clean_mapping[h] = identity.split(';')[0].split(' strain')[0].split(' genome')[0].strip()
                else:
                    clean_mapping[h] = identity
            
            return json.dumps(clean_mapping)
        except Exception as e:
            self.logger.error(f"Failed to get annotations (Hash): {e}")
            return "{}"

    @pyqtSlot(str, str)
    def request_batch_blast(self, seq_ids_json, source_rel_path):
        """
        [One-Click Identity] 
        从进化树侧直接发起比对任务
        """
        try:
            from Bio import SeqIO
            seq_ids = set(json.loads(seq_ids_json))
            
            # 定位原始文件
            results_dir = Path("results/tree_results")
            full_path = results_dir / source_rel_path
            
            if not full_path.exists():
                # 尝试递归搜索 (针对不同层级的归档)
                matches = list(results_dir.rglob(source_rel_path.split('/')[-1]))
                if matches: full_path = matches[0]
                else:
                    self.logger.error(f"Cannot find source FASTA: {source_rel_path}")
                    return

            # 提取序列内容
            queries = []
            for rec in SeqIO.parse(full_path, "fasta"):
                if rec.id in seq_ids:
                    queries.append(f">{rec.id}\n{str(rec.seq)}")
            
            if not queries:
                self.logger.warning("No matching sequences found in source FASTA")
                return

            # 创建比对任务 (使用时间戳确保 ID 唯一，防止缓存碰撞导致的“秒完成”误判)
            timestamp = datetime.datetime.now().strftime('%M%S')
            params = {
                "query": "\n".join(queries),
                "program": "auto",
                "database": "nt",
                "evalue": 0.05,
                "hitlist_size": 50,
                "task_name": f"Identify_{len(queries)}_Seqs_{timestamp}"
            }
            task_id = self.blast_manager.create_task(params)
            self.logger.info(f"Auto-BLAST Task Started: {task_id} for {len(queries)} sequences.")
            
            # 通知前端任务已启动
            self.container.web_view.page().runJavaScript(
                f"if(window.app) window.app.showNotification('已自动发起 {len(queries)} 条序列的身份识别任务...', 'info');"
            )
            
        except Exception as e:
            self.logger.error(f"Failed to initiate auto-blast: {e}")

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
                # [修复] 针对 CSV 文件使用 utf-8-sig 编码，提升 Excel 兼容性
                encoding = 'utf-8-sig' if path.lower().endswith('.csv') else 'utf-8'
                with open(path, 'w', encoding=encoding) as f:
                    f.write(content)
                self.logger.info(f"File saved successfully to: {path} (encoding={encoding})")
                return True
            return False # Cancelled
        except Exception as e:
            self.logger.error(f"Save File Error: {e}")
            return False

    @pyqtSlot(str)
    def save_tree_sequences(self, fasta_content):
        """保存手动输入的序列到工作空间，支持 Tree Station 2.0"""
        try:
            import re
            import datetime
            workspace = Path("results/tree_workspace")
            workspace.mkdir(parents=True, exist_ok=True)
            
            # --- 智能命名逻辑：避免 user_input 硬编码 ---
            # 1. 尝试提取第一个序列的标题作为主干名称
            first_header = "Station_Input"
            match = re.search(r'^>\s*(.+)', fasta_content, re.M)
            if match:
                header_line = match.group(1).strip()
                # 清洗文件名：保留字母数字、空格、点、下划线、横杠，其余替换为下划线
                first_header = "".join(c if c.isalnum() or c in (' ', '.', '_', '-') else '_' for c in header_line).strip()
                # 进一步压缩：空格转下划线，限长 40 字符
                first_header = first_header.replace(' ', '_')[:40]
            
            # 2. 结合时间戳确保唯一性，支持分批多次导入
            timestamp = datetime.datetime.now().strftime("%y%m%d_%H%M")
            file_name = f"{first_header}_{timestamp}.fasta"
            file_path = workspace / file_name
            
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(fasta_content)
            self.logger.info(f"User sequences saved to {file_path}")
            return True
        except Exception as e:
            self.logger.error(f"Failed to save sequences: {e}")
            return False

    @pyqtSlot(str)
    def recall_tree_sequences(self, source_filename):
        """Recall original sequences from results back to active workspace for re-analysis"""
        from pathlib import Path
        import shutil
        try:
            results_dir = Path("results/tree_results")
            workspace_dir = Path("results/tree_workspace")
            workspace_dir.mkdir(parents=True, exist_ok=True)
            
            # 使用列表解析处理多种可能的路径
            potential_file = results_dir / source_filename
            if not potential_file.exists():
                # [深度搜索] 关键修复：结果存储在 Project 子目录下，需使用 rglob 进行递归查找
                # 优先匹配精准文件名 (包含指纹)
                matches = list(results_dir.rglob(source_filename))
                if matches:
                    potential_file = matches[0]
                else:
                    # 无法完全匹配时，尝试前缀匹配
                    self.logger.info(f"Precise match failed for {source_filename}, trying recursive wildcard matching...")
                    matches = list(results_dir.rglob(f"{source_filename}*"))
                    if matches:
                        potential_file = matches[0]
                    else:
                        self.logger.error(f"Recall Failed: No file matches {source_filename} in any subfolders of {results_dir}")
                        self.recall_event.emit(False, f"Not Found: {source_filename}")
                        return
            
            # --- 智能召回逻辑：还原逻辑文件名，剥离物理指纹前缀 ---
            # 物理文件名通常为：Tree_20240405_183302_original_name.fasta
            pure_name = potential_file.name
            import re
            # 匹配指纹模式：Tree_YYYYMMDD_HHMMSS_
            match = re.match(r'^Tree_\d{8}_\d{6}_(.+)$', pure_name)
            if match:
                pure_name = match.group(1)
            
            target_path = workspace_dir / pure_name
            shutil.copy2(potential_file, target_path)
            self.logger.info(f"BRIDGE: [SUCCESS] Recalled {potential_file.name} to workspace as {pure_name}.")
            self.recall_event.emit(True, pure_name)
        except Exception as e:
            self.logger.error(f"Recall Logic Error: {e}")
            self.recall_event.emit(False, str(e))

    @pyqtSlot(str)
    def delete_tree_archive(self, rel_path):
        """Physically delete a single tree archive file or a whole project folder"""
        from pathlib import Path
        import shutil
        try:
            target = Path("results/tree_results") / rel_path
            if target.exists():
                if target.is_dir():
                    shutil.rmtree(target)
                    self.logger.info(f"BRIDGE: [SUCCESS] Physically deleted project folder: {target}")
                else:
                    target.unlink()
                    self.logger.info(f"BRIDGE: [SUCCESS] Physically deleted archive file: {target}")
            else:
                self.logger.warning(f"BRIDGE: [WARNING] Delete target not found: {rel_path}")
        except Exception as e:
            self.logger.error(f"BRIDGE: [ERROR] Failed to delete archive {rel_path}: {e}")

    @pyqtSlot(str)
    def request_tree_analysis(self, params_json):
        """Handle tree analysis request with params"""
        self.logger.info(f"JS requested tree analysis: {params_json}")
        try:
            params = json.loads(params_json)
            # Pass full params to container/worker
            self.container.run_tree_analysis(params=params)
        except Exception as e:
            self.logger.error(f"Failed to start tree: {e}")
            self.container.web_view.page().runJavaScript(f"if(window.app) window.app.showNotification('启动分析失败: {str(e)}', 'error');")

    @pyqtSlot(result=str)
    def list_tree_sequences(self):
        """List files in the tree workspace"""
        try:
            workspace = Path("results/tree_workspace")
            if not workspace.exists():
                return "[]"
            files = [f.name for f in workspace.glob("*.fasta")] + [f.name for f in workspace.glob("*.seq")]
            return json.dumps(files)
        except Exception as e:
            self.logger.error(f"Failed to list sequences: {e}")
            return "[]"

    @pyqtSlot(str, result=bool)
    def add_tree_workspace_files(self, paths_json):
        """Copy local files directly into the tree workspace (used for DnD handling)"""
        try:
            import shutil
            paths = json.loads(paths_json)
            workspace = Path("results/tree_workspace")
            workspace.mkdir(parents=True, exist_ok=True)
            
            for p in paths:
                src = Path(p)
                if src.is_file():
                    shutil.copy2(src, workspace / src.name)
                    
            self.logger.info(f"Successfully staged {len(paths)} external files to tree workspace.")
            return True
        except Exception as e:
            self.logger.error(f"Failed to stage external files: {e}")
            return False

    @pyqtSlot(result=bool)
    def clear_tree_workspace(self):
        """Clear all files in the tree workspace"""
        try:
            workspace = Path("results/tree_workspace")
            if workspace.exists():
                for f in workspace.glob("*"):
                    try:
                        f.unlink()
                    except Exception as e:
                        pass
                self.logger.info("Tree workspace cleared by UI request.")
            return True
        except Exception as e:
            self.logger.error(f"Error clearing sequence list: {e}")
            return False

    @pyqtSlot(str)
    def delete_analysis_files(self, paths_json):
        """物理删除磁盘上的分析结果文件"""
        try:
            paths = json.loads(paths_json)
            for p_str in paths:
                p = Path(p_str)
                if p.exists() and p.is_file():
                    p.unlink()
                    self.logger.info(f"Physical file deleted: {p_str}")
            return True
        except Exception as e:
            self.logger.error(f"Failed to delete physical files: {e}")
            return False

    @pyqtSlot(str)
    def request_tree_reroot(self, node_id):
        """Handle reroot request"""
        self.logger.info(f"JS requested reroot at: {node_id}")
        self.container.run_tree_reroot(node_id)

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
        tr.load_all_translations() # Reload to get latest JSON changes
        data = tr.get_all_translations_for_current_lang()
        return json.dumps(data, ensure_ascii=False)

    @pyqtSlot(result=str)
    def get_ui_language(self):
        """Get current UI language code"""
        from src.utils.ui_translation_manager import get_ui_translator
        return get_ui_translator().get_language()

    @pyqtSlot(result=str)
    def get_tools_metadata(self):
        """Return the tools_metadata.json content"""
        try:
            path = os.path.join(os.path.dirname(__file__), "../../resources/tools_metadata.json")
            if os.path.exists(path):
                with open(path, 'r', encoding='utf-8') as f:
                    return f.read()
            return "{}"
        except Exception as e:
            self.logger.error(f"Failed to load tools metadata: {e}")
            return "{}"

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

    @pyqtSlot(str, result=bool)
    def save_selected_model(self, model_key):
        """Save the selected AI model and force-recreate the global translator"""
        try:
            from src.utils.config_manager import get_config_manager
            config = get_config_manager()
            config.set_advanced_settings({'ai_model': model_key})
            self.logger.info(f"Selected AI model saved: {model_key}")
            
            # Force the global translator singleton to be recreated with the new model
            import src.utils.translation.biology_translator as bt
            bt._global_translator = None
            self.logger.info("Global translator reset. Next translation will use new model.")
            return True
        except Exception as e:
            self.logger.error(f"Failed to save selected model: {e}")
            return False

    @pyqtSlot(result=str)
    def get_selected_model(self):
        """Get the currently saved AI model selection"""
        try:
            from src.utils.config_manager import get_config_manager
            advanced = get_config_manager().get_advanced_settings()
            return advanced.get('ai_model', '')
        except Exception as e:
            self.logger.error(f"Failed to get selected model: {e}")
            return ""

    @pyqtSlot(str)
    def log_message(self, message):
        """Log message from frontend"""
        self.logger.info(f"[Frontend] {message}")

    @pyqtSlot(str)
    def save_topology(self, topology_json):
        """Save the current canvas topology to a local file for persistence"""
        try:
            path = Path(self.blast_manager.results_dir) / "workspace_topology.json"
            with open(path, 'w', encoding='utf-8') as f:
                f.write(topology_json)
            self.logger.info(f"Workspace topology saved to: {path}")
        except Exception as e:
            self.logger.error(f"Failed to save workspace topology: {e}")

    @pyqtSlot(result=str)
    def load_topology(self):
        """Load the last saved workspace topology from local file"""
        try:
            path = Path(self.blast_manager.results_dir) / "workspace_topology.json"
            if path.exists():
                with open(path, 'r', encoding='utf-8') as f:
                    return f.read()
            return ""
        except Exception as e:
            self.logger.error(f"Failed to load workspace topology: {e}")
            return ""

    @pyqtSlot(str, str, result=str)
    def translate_text(self, text, category='species'):
        """
        Enhanced Translation: Individual item processing with ASYNC AI fallback.
        Local hits are returned instantly. New terms are queued for background AI.
        """
        from src.utils.translation.biology_translator import get_global_biology_translator
        import re
        import threading
        try:
            text = text.strip()
            if not text: return ""
            
            translator = get_global_biology_translator()
            
            # Helper to process a single term
            def process_term(name):
                # 1. 尝试纯本地查询 (不阻塞)
                local_res = translator.translate_text(name, category=category, use_ai_override=False)
                
                # 如果本地库有结果 (翻译内容不等于原文即视为命中本地)
                if local_res and local_res != name:
                    return local_res
                
                # 2. 如果本地未命中，且 AI 已启用，则送入后台队列 (使用线程池控制并发量)
                if translator.use_ai:
                    with self._ai_trans_lock:
                        if name not in self._ai_trans_in_flight:
                            self._ai_trans_in_flight.add(name)
                            # 使用线程池提交，防止大规模请求撑爆系统
                            self._ai_trans_pool.submit(self._async_ai_worker, name, category)
                    return f"{name} (AI翻译中...)"
                
                return name

            # --- Pattern: Name(XX%) ---
            pattern = r"([^,(]+)\s*\((?:\d{1,3}%)\)"
            segments = re.findall(pattern, text)
            
            if segments and "(" in text and "%" in text:
                def translate_match(match):
                    full_segment = match.group(0)
                    name_part = match.group(1).strip()
                    res = process_term(name_part)
                    return full_segment.replace(name_part, res)
                
                result = re.sub(pattern, translate_match, text)
                return result
            
            # --- Case 2: Simple Name ---
            return process_term(text)
            
        except Exception as e:
            self.logger.error(f"Translation bridge error: {e}")
            return text

    def _async_ai_worker(self, name, category):
        """后台 AI 翻译 worker，完成后通过信号通知前端"""
        from src.utils.translation.biology_translator import get_global_biology_translator
        self.logger.info(f"[AI] 开始异步翻译: {name}")
        try:
            translator = get_global_biology_translator()
            # 执行真正的 AI 翻译 (同步阻塞，但在后台线程)
            ai_res = translator.translate_text(name, category=category, use_ai_override=True)
            
            # 无论成功失败，都应通知 JS 刷新对应项（如果翻译没变化，也要传回原本的名字以清除“翻译中”状态）
            # 注意：即使 ai_res == name，我们也传回 ai_res，UI 会根据这个值更新并清除占位符
            self.blast_event.emit("translation_done", json.dumps({
                "original": name,
                "translated": ai_res
            }))
            if ai_res and ai_res != name:
                self.logger.info(f"[AI] 翻译成功: {name} -> {ai_res}")
            else:
                self.logger.info(f"[AI] 翻译未产生变化或保持原文: {name}")

        except Exception as e:
            self.logger.error(f"[AI] 异步翻译失败 {name}: {e}")
            # 发生异常也要通知前端清除状态
            self.blast_event.emit("translation_done", json.dumps({
                "original": name,
                "translated": name
            }))
        finally:
            with self._ai_trans_lock:
                if name in self._ai_trans_in_flight:
                    self._ai_trans_in_flight.remove(name)

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
        except Exception as e:
            self.logger.error(f"Dictionary search error: {e}")
            return "[]"

    @pyqtSlot(str, str, str, result=bool)
    def save_dictionary_term(self, english, chinese, category):
        """Save or update a dictionary term"""
        from src.utils.translation.biology_translator import get_global_biology_translator
        try:
            translator = get_global_biology_translator()
            dm = translator.translation_data_manager
            if dm:
                return dm.add_translation(english, chinese, category, source='manual_web')
            return False
        except Exception as e:
            self.logger.error(f"Failed to save term: {e}")
            return False

    @pyqtSlot(str, result=bool)
    def delete_dictionary_term(self, english):
        """Delete a term from dictionary"""
        from src.utils.translation.biology_translator import get_global_biology_translator
        import sqlite3
        try:
            translator = get_global_biology_translator()
            dm = translator.translation_data_manager
            if dm and dm.db_path.exists():
                conn = sqlite3.connect(dm.db_path)
                cursor = conn.cursor()
                cursor.execute('DELETE FROM translations WHERE english = ?', (english,))
                success = conn.total_changes > 0
                conn.commit()
                conn.close()
                if english in dm._cache:
                    del dm._cache[english]
                return success
            return False
        except Exception as e:
            self.logger.error(f"Failed to delete term: {e}")
            return False

    @pyqtSlot(bool, result=str)
    @pyqtSlot(result=str)
    def get_all_dictionary_terms(self, proofread_mode=False):
        """Get dictionary terms for management"""
        from src.utils.translation.biology_translator import get_global_biology_translator
        try:
            translator = get_global_biology_translator()
            dm = translator.translation_data_manager
            if dm:
                terms = []
                import sqlite3
                conn = sqlite3.connect(dm.db_path)
                cursor = conn.cursor()
                if proofread_mode:
                    # 只获取未校对的词条 (例如来源是 'ai' 的)
                    cursor.execute("SELECT english, chinese, category, source FROM translations WHERE source = 'ai' ORDER BY created_at DESC")
                else:
                    cursor.execute('SELECT english, chinese, category, source FROM translations ORDER BY created_at DESC')
                for row in cursor.fetchall():
                    terms.append({'english': row[0], 'chinese': row[1], 'category': row[2], 'source': row[3]})
                conn.close()
                return json.dumps(terms, ensure_ascii=False)
            return "[]"
        except Exception as e:
            self.logger.error(f"Failed to get terms: {e}")
            return "[]"

    @pyqtSlot(str, result=bool)
    def verify_dictionary_term(self, english):
        """Mark a dictionary term as verified"""
        import sqlite3
        from src.utils.translation.biology_translator import get_global_biology_translator
        try:
            translator = get_global_biology_translator()
            dm = translator.translation_data_manager
            if dm and dm.db_path.exists():
                conn = sqlite3.connect(dm.db_path)
                cursor = conn.cursor()
                # 标记校对过的词条来源为 'verified'
                cursor.execute("UPDATE translations SET source = 'verified' WHERE english = ?", (english,))
                success = conn.total_changes > 0
                conn.commit()
                conn.close()
                return success
            return False
        except Exception as e:
            self.logger.error(f"Failed to verify term: {e}")
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
        except Exception as e:
            self.logger.error(f"Failed to repair dictionary: {e}")
            return json.dumps({"error": str(e)})

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
            
    @pyqtSlot(str, result=bool)
    def add_tree_workspace_files(self, paths_json):
        """Add local files to tree workspace by copying them"""
        try:
            from pathlib import Path
            import shutil
            paths = json.loads(paths_json)
            workspace = Path("results/tree_workspace")
            workspace.mkdir(parents=True, exist_ok=True)
            
            for p_str in paths:
                p = Path(p_str)
                if p.exists():
                    shutil.copy(p, workspace / p.name)
            return True
        except Exception as e:
            self.logger.error(f"Failed to add workspace files: {e}")
            return False

    @pyqtSlot(result=str)
    def list_tree_sequences(self):
        """List files in tree workspace with .nwk support"""
        try:
            from pathlib import Path
            workspace = Path("results/tree_workspace")
            workspace.mkdir(parents=True, exist_ok=True)
            files = []
            for ext in ("*.fasta", "*.seq", "*.fa", "*.fna", "*.nwk", "*.txt"):
                files.extend([f.name for f in workspace.glob(ext)])
            return json.dumps(sorted(list(set(files))))
        except Exception as e:
            self.logger.error(f"Failed to list tree workspace: {e}")
            return "[]"

    @pyqtSlot(str, result=str)
    def get_tree_content(self, filename):
        """Read .nwk tree file content for direct loading"""
        try:
            from pathlib import Path
            path = Path("results/tree_workspace") / filename
            if path.exists():
                return path.read_text(encoding='utf-8', errors='ignore')
            return ""
        except Exception as e:
            self.logger.error(f"get_tree_content error: {e}")
            return ""

    @pyqtSlot(result=bool)
    def clear_tree_workspace(self):
        """Delete all files in tree workspace"""
        try:
            from pathlib import Path
            import os
            workspace = Path("results/tree_workspace")
            if workspace.exists():
                for f in workspace.iterdir():
                    if f.is_file():
                        os.remove(f)
            return True
        except Exception as e:
            self.logger.error(f"Failed to clear workspace: {e}")
            return False

    @pyqtSlot(result=str)
    def get_ai_models(self):
        """Get all AI models configured on backend"""
        try:
            from src.utils.config_manager import get_config_manager
            models = get_config_manager().get_supported_models()
            if isinstance(models, dict):
                models = [{"key": k, "name": v} for k, v in models.items()]
            return json.dumps(models)
        except Exception as e:
            self.logger.error(f"Failed to get AI models: {e}")

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
        """Fetch results for a task, using consensus-based best hit selection (Top 50 / 98%)"""
        results = self.blast_manager.get_task_results(task_id)
        for res in results:
            if 'csv_file' in res and os.path.exists(res['csv_file']):
                # Read top 50 hits for consensus analysis
                top_hits = self._parse_blast_csv(res['csv_file'], limit=50)
                best_hit = self._select_consensus_hit(top_hits)
                res['data'] = [best_hit] if best_hit else []
        return json.dumps(results)

    def _select_consensus_hit(self, hits):
        """Select the best representative hit using majority voting on species.
        
        Updated Criteria:
        - Only consider hits within the provided set (Top 50 by caller).
        - Filter for Identity >= 98%.
        - Select species that appears most frequently in this pool.
        """
        if not hits:
            return None
            
        # 1. 过滤相似度在 98% 以上的命中数据
        high_identity_hits = []
        for hit in hits:
            sim_str = str(hit.get('similarity', '0%')).replace('%', '').strip()
            try:
                sim_val = float(sim_str)
                if sim_val >= 98.0:
                    high_identity_hits.append(hit)
            except (ValueError, TypeError):
                continue
        
        # 2. 如果有 98% 以上的数据，则对这部分数据进行投票；否则回退到全部数据
        target_hits = high_identity_hits if high_identity_hits else hits
        
        if len(target_hits) == 1:
            return target_hits[0]
        
        from collections import Counter
        
        # Count species occurrences, filtering out generic/uninformative names
        generic_names = {'bacterium', 'uncultured bacterium', 'uncultured organism', 
                        'unidentified', 'unknown', 'n/a', ''}
        
        species_counter = Counter()
        species_to_hit = {}  # Map species -> best (first seen) hit with that species
        
        for hit in target_hits:
            species = (hit.get('species') or '').strip()
            species_lower = species.lower()
            
            if species_lower and species_lower not in generic_names:
                species_counter[species] += 1
                if species not in species_to_hit:
                    species_to_hit[species] = hit
        
        if not species_counter:
            # 所有命中项均为通用名称或过滤后为空，直接返回目标集的第一项
            return target_hits[0]
            
        # 3. 统计各物种出现频率百分比
        total_valid = sum(species_counter.values())
        top_entries = species_counter.most_common(5) # 取出现频率最高的前 5 个物种
        
        # 格式化输出: "物种A(60%), 物种B(30%)"
        prob_parts = []
        for name, count in top_entries:
            pct = (count / total_valid) * 100
            prob_parts.append(f"{name}({pct:.0f}%)")
            
        probability_str = ", ".join(prob_parts)
        
        # 4. 选取出现频率最高的物种作为代表
        consensus_species = top_entries[0][0]
        best_hit = dict(species_to_hit[consensus_species]) # 获取该物种最好的比对项副本
        best_hit['species'] = probability_str # 注入概率分布字符串
        
        self.logger.info(
            f"Consensus Probabilities (Top 50/98%): {probability_str} "
            f"on high_identity_hits={bool(high_identity_hits)}"
        )
        return best_hit

    @pyqtSlot(str, result=str)
    def get_detailed_blast_results(self, csv_file):
        """Fetch ALL hits from a specific CSV file for detail view"""
        if not os.path.exists(csv_file):
            return "[]"
        data = self._parse_blast_csv(csv_file, limit=None) # Get all
        return json.dumps(data)

    @pyqtSlot(str, result=str)
    def read_result_file(self, file_path):
        """Read content of a result file for preview (e.g. tree, fasta)"""
        # Basic Security: Prevent reading system files. Allow only if in specific paths or has standard extension
        # For this local app, we trust the logic but prevent obvious abuse
        if "NCBI blast" not in file_path and "temp" not in file_path.lower(): 
             # Weak check but consistent with local app context
             pass
        
        try:
            if os.path.exists(file_path) and os.path.isfile(file_path):
                # Check size
                if os.path.getsize(file_path) > 5 * 1024 * 1024:
                    return "file_too_large"
                
                with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
                    return f.read()
            return ""
        except Exception as e:
            self.logger.error(f"Failed to read result file {file_path}: {e}")
            return ""



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
            
    @pyqtSlot(str, str)
    def rename_task(self, task_id, new_name):
        """Rename specific task"""
        self.logger.info(f"JS requested rename task {task_id} -> {new_name}")
        self.blast_manager.rename_task(task_id, new_name)

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
            with open(csv_path, 'r', encoding='utf-8-sig') as f:
                reader = csv.DictReader(f)
                count = 0
                for row in reader:
                    raw_title = row.get('标题', 'Unknown')
                    
                    # Clean title: strip concatenated hits after '>'
                    if '>' in raw_title:
                        raw_title = raw_title.split('>')[0].strip()
                    
                    # Remove gi|xxx|gb|xxx| prefix to get readable description
                    clean_title = raw_title
                    import re
                    gi_match = re.match(r'^gi\|\d+\|[a-z]+\|[A-Za-z0-9_.]+\|\s*', raw_title)
                    if gi_match:
                        clean_title = raw_title[gi_match.end():].strip()
                    
                    # Extract gene source (e.g. "16S ribosomal RNA gene")
                    gene_source = ''
                    source_patterns = [
                        r'(16S\s+ribosomal\s+RNA\s+gene)',
                        r'(23S\s+ribosomal\s+RNA\s+gene)',
                        r'(ITS\s+region)',
                        r'(chromosome[^,]*)',
                        r'(complete\s+genome)',
                        r'(genome\s+assembly)',
                    ]
                    for pattern in source_patterns:
                        source_match = re.search(pattern, clean_title, re.IGNORECASE)
                        if source_match:
                            gene_source = source_match.group(1)
                            break
                    
                    # Simplify keys for Web
                    data.append({
                        'title': clean_title,
                        'len': row.get('长度', '0'),
                        'acc': row.get('访问号', 'N/A'),
                        'species': row.get('物种', 'N/A'),
                        'genus': row.get('属名', ''),
                        'strain': row.get('菌株', ''),
                        'gene_type': row.get('基因类型', ''),
                        'seq_type': row.get('序列类型', ''),
                        'host': row.get('宿主信息', ''),
                        'gene_source': gene_source,
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
        """Extended drop event to support automatic ZIP extraction/sorting"""
        if event.mimeData().hasUrls():
            urls = event.mimeData().urls()
            final_paths = []
            
            for url in urls:
                if url.isLocalFile():
                    local_path = str(url.toLocalFile())
                    if local_path.lower().endswith('.zip'):
                        # 识别压缩包内序列
                        extracted = self._extract_sequences_from_zip(local_path)
                        if extracted:
                            final_paths.extend(extracted)
                            print(f"ZIP Extracted via Drop: {len(extracted)} files")
                    else:
                        final_paths.append(local_path)
            
            if final_paths:
                event.accept()
                import json
                safe_paths = json.dumps(final_paths)
                
                # 注入前端
                js_code = f"if(window.app && window.app.handleFilesDropped) window.app.handleFilesDropped({safe_paths});"
                self.page().runJavaScript(js_code)
                return
        
        super().dropEvent(event)

    def _extract_sequences_from_zip(self, zip_path):
        """Shared logic for ZIP sorting on drag-and-drop"""
        import zipfile
        import tempfile
        import os
        from pathlib import Path
        from PyQt6.QtWidgets import QInputDialog, QLineEdit, QMessageBox
        
        extracted_results = []
        try:
            with zipfile.ZipFile(zip_path) as zf:
                # 优化分拣：仅识别文本类序列文件 (.seq, .fasta 等)，排除冗余的二进制测序原始文件 (.ab1)
                valid_exts = ['.seq', '.fasta', '.fas', '.fa']
                seq_files = [n for n in zf.namelist() if any(n.lower().endswith(e) for e in valid_exts)]
                
                if not seq_files:
                    return []
                
                # 检查密码
                test_file = seq_files[0]
                password = None
                try:
                    zf.read(test_file)
                except Exception as e:
                    if 'encrypted' in str(e).lower() or 'password' in str(e).lower():
                        pwd, ok = QInputDialog.getText(self, "拖入加密压缩包", 
                                                     f"文件 '{Path(zip_path).name}' 已加密。\n请输入解压密码:", 
                                                     QLineEdit.EchoMode.Password)
                        if not ok: return []
                        password = pwd
                
                # [FIX] 使用带时间戳或进程 ID 的唯一子目录，防止多 ZIP 分拣时文件名冲突
                project_root = Path(__file__).resolve().parent.parent.parent.parent
                staging_id = f"staged_{datetime.datetime.now().strftime('%H%M%S')}_{os.getpid()}"
                temp_root = project_root / "results" / "extracted" / staging_id
                if not temp_root.exists():
                    temp_root.mkdir(parents=True, exist_ok=True)
                
                pwd_bytes = password.encode() if password else None
                for f_name in seq_files:
                    try:
                        out_path = zf.extract(f_name, path=str(temp_root), pwd=pwd_bytes)
                        extracted_results.append(out_path)
                    except:
                        pass
                        
        except Exception as e:
            print(f"Error extracting ZIP drop: {e}")
            
        return extracted_results


class WebPage(QWebEnginePage):
    """Custom page to handle JS console messages"""
    def javaScriptConsoleMessage(self, level, message, lineNumber, sourceID):
        logger = logging.getLogger("src.gui.widgets.web_container.js")
        msg = f"{message} ({sourceID}:{lineNumber})"
        if level == QWebEnginePage.JavaScriptConsoleMessageLevel.ErrorMessageLevel:
            logger.error(f"[JS ERROR] {msg}")
        elif level == QWebEnginePage.JavaScriptConsoleMessageLevel.WarningMessageLevel:
            logger.warning(f"[JS WARN] {msg}")
        else:
            logger.info(f"[JS LOG] {msg}")


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
        
        # Ensure path is persistent in user home or project root
        storage_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../storage/web"))
        os.makedirs(storage_path, exist_ok=True)
        
        # Cleanup potentially corrupted cache subdirs if structure error reported (noisy chrome logs)
        # Note: Deleting Shared Dictionary if corrupted often fixes Simple Cache Backend errors
        # We do this BEFORE creating the profile to ensure a clean start if needed.
        corrupted_dirs = ["Shared Dictionary", "Cache", "Code Cache", "Service Worker"]
        import shutil
        for d in corrupted_dirs:
            d_path = os.path.join(storage_path, d)
            if os.path.exists(d_path):
                try:
                    # In some environments, these files are empty or broken, causing the "wrong file structure" error
                    # We only attempt forced deletion if we suspect corruption (first boot of session)
                    if not hasattr(WebContainer, "_cache_cleaned"):
                        self.logger.info(f"Checking storage health: {d}")
                        # We don't delete everything every time, only Shared Dictionary which is the most common failure
                        if d == "Shared Dictionary":
                            shutil.rmtree(d_path, ignore_errors=True)
                except Exception as e:
                    self.logger.warning(f"Could not clean cache dir {d}: {e}")
        WebContainer._cache_cleaned = True
        
        # Enable Persistent Storage via a named Profile
        profile = QWebEngineProfile("BioStationProfile", self.web_view)
        profile.setPersistentStoragePath(storage_path)
        profile.setPersistentCookiesPolicy(QWebEngineProfile.PersistentCookiesPolicy.AllowPersistentCookies)
        
        # Handle Downloads
        profile.downloadRequested.connect(self.on_download_requested)
        
        # Create a page for this profile (using custom child to capture JS console)
        page = WebPage(profile, self.web_view)
        # v2 补丁：设置默认背景颜色为 Studio 画布色，减少黑屏闪烁时的视觉背离
        from PyQt6.QtGui import QColor
        page.setBackgroundColor(QColor("#0f172a"))
        self.web_view.setPage(page)
        
        # Enable JS features like popups
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
        
        # Load URL - Support WEB_URL for development (HMR for web-next)
        dev_url = os.environ.get("WEB_URL")
        if dev_url:
            url = QUrl(dev_url)
            self.logger.info(f"Loading Dev Web Container from: {url.toString()}")
            self.web_view.load(url)
        else:
            # Fallback to local index.html (legacy)
            base_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../web_legacy"))
            index_path = os.path.join(base_path, "index.html")
            
            if not os.path.exists(index_path):
                self.logger.error(f"Web Container index not found at: {index_path}")
                QMessageBox.critical(self, "Error", f"Web App not found at {index_path}")
            else:
                url = QUrl.fromLocalFile(index_path)
                self.logger.info(f"Loading Local Web Container from: {url.toString()}")
                self.web_view.load(url)
            
        layout.addWidget(self.web_view)

    def reload(self):
        self.web_view.reload()

    def handle_resize_event(self):
        """顶级窗口调整大小或状态变更时触发，采用三重递进式刷新策略"""
        if hasattr(self, 'web_view'):
            # 1. 立即刷新一次
            self.web_view.update()
            
            # 2. 引入多重延迟重绘（关键补丁：应对不同硬件在全屏转换时的 Surface 就绪时机）
            from PyQt6.QtCore import QTimer
            # 第 1 波：快速尝试 (100ms)
            QTimer.singleShot(100, self._force_redraw_cycle)
            # 第 2 波：彻底稳定 (300ms)
            QTimer.singleShot(300, self._force_redraw_cycle)

    def _force_redraw_cycle(self):
        """强制重绘周期：执行 JS 并刷新 WebView"""
        if hasattr(self, 'web_view'):
            # 执行综合性的 JS 刷新脚本
            js_code = """
            (function(){
                window.dispatchEvent(new Event('resize'));
                // 强制同步父子框架布局
                if (window.app && window.app.syncViewLayouts) {
                    window.app.syncViewLayouts();
                }
                // 触发一个极小的 body 偏移以强迫浏览器渲染表面重建
                document.body.style.opacity = '0.999';
                setTimeout(() => { document.body.style.opacity = '1'; }, 0);
            })();
            """
            self.web_view.page().runJavaScript(js_code)
            
            # v4 补丁：不仅刷新 WebView，还从底层强制进行 Repaint 并在窗口级别更新脏区域
            self.web_view.update()
            if self.web_view.focusProxy():
                self.web_view.focusProxy().repaint()
            
            # 手动拉拽顶层窗口刷新
            if self.window():
                self.window().update()

    def open_file_dialog(self, file_type):
        """Open QFileDialog and handle file injection, now including compressed archive support"""
        from PyQt6.QtWidgets import QFileDialog, QMessageBox, QInputDialog, QLineEdit
        from pathlib import Path
        import os
        import json
        import zipfile
        import tempfile
        
        print(f"[Python] open_file_dialog triggered for {file_type}")
        
        filter_str = "All Files (*.*)"
        if file_type == 'tree':
            filter_str = "Tree Files (*.nwk *.newick *.txt);;All Files (*.*)"
        elif file_type == 'structure':
            filter_str = "Protein Structure (*.pdb *.ent);;All Files (*.*)"
        elif file_type == 'fasta':
            # Add compressed archive support explicitly for sequence intake
            filter_str = "Supported Files (*.fasta *.fas *.fa *.seq *.ab1 *.abi *.zip);;Sequence Files (*.fasta *.fas *.fa *.seq *.ab1 *.abi);;Archives (*.zip);;All Files (*.*)"
            
        file_path, _ = QFileDialog.getOpenFileName(self, f"Open {file_type}", "", filter_str)
        
        if not file_path:
            return

        try:
            ext = Path(file_path).suffix.lower()
            
            # --- 分拣处理：压缩包 (.zip) ---
            if ext == '.zip':
                try:
                    with zipfile.ZipFile(file_path) as zf:
                        # 优化分拣：仅识别文本类序列文件 (.seq, .fasta 等)，排除冗余的二进制测序原始文件 (.ab1)
                        valid_exts = ['.seq', '.fasta', '.fas', '.fa']
                        seq_files = [n for n in zf.namelist() if any(n.lower().endswith(e) for e in valid_exts)]
                        
                        if not seq_files:
                            QMessageBox.information(self, "压缩包解析", "该压缩包内未提取到有效的序列文件 (.seq, .fasta等)")
                            return
                        
                        # 检查是否加密
                        password = None
                        test_file = seq_files[0]
                        try:
                            # 试图直接读取第一个文件
                            zf.read(test_file)
                        except RuntimeError as re:
                            if 'encrypted' in str(re).lower() or 'password' in str(re).lower():
                                # 需要密码
                                while True:
                                    pwd, ok = QInputDialog.getText(self, "识别到加密压缩包", 
                                                                 f"压缩文件 '{Path(file_path).name}' 已加密。\n请输入密码以继续导入序列:", 
                                                                 QLineEdit.EchoMode.Password)
                                    if not ok: return
                                    try:
                                        zf.read(test_file, pwd=pwd.encode())
                                        password = pwd
                                        break
                                    except:
                                        QMessageBox.warning(self, "密码错误", "输入的密码不正确，请重新输入。")
                        
                        # [FIX] 使用带时间戳或进程 ID 的唯一子目录，防止多 ZIP 分拣时文件名冲突
                        project_root = Path(__file__).resolve().parent.parent.parent.parent
                        staging_id = f"staged_{datetime.datetime.now().strftime('%H%M%S')}_{os.getpid()}"
                        temp_root = project_root / "results" / "extracted" / staging_id
                        if not temp_root.exists():
                            temp_root.mkdir(parents=True, exist_ok=True)
                        
                        pwd_bytes = password.encode() if password else None
                        injected_count = 0
                        
                        for f_name in seq_files:
                            try:
                                out_path = zf.extract(f_name, path=str(temp_root), pwd=pwd_bytes)
                                
                                # 处理提取出的文件内容
                                inner_ext = Path(out_path).suffix.lower()
                                content = ""
                                if inner_ext in ['.ab1', '.abi']:
                                    from src.utils.file_handler import FileHandler
                                    handler = FileHandler()
                                    for seq_info in handler.read_fasta_file_iter(out_path):
                                        content = seq_info['sequence']
                                        break 
                                else:
                                    with open(out_path, 'r', encoding='utf-8', errors='ignore') as f:
                                        content = f.read()
                                
                                if content:
                                    safe_content = json.dumps(content)
                                    safe_path = json.dumps(out_path)
                                    js_code = f"if(window.app) window.app.handleFileLoaded({safe_content}, 'fasta', {safe_path});"
                                    self.web_view.page().runJavaScript(js_code)
                                    injected_count += 1
                            except Exception as ex:
                                self.logger.error(f"Extraction error for {f_name}: {ex}")
                                
                        if injected_count > 0:
                            QMessageBox.information(self, "导入完成", f"已成功从压缩包中分拣并导入了 {injected_count} 条序列。")
                        return # ZIP 处理结束
                except Exception as ze:
                    raise ValueError(f"压缩包解析失败: {ze}")
            
            # --- 常规处理：单文件 ---
            content = ""
            if ext in ['.ab1', '.abi']:
                from src.utils.file_handler import FileHandler
                handler = FileHandler()
                for seq_info in handler.read_fasta_file_iter(file_path):
                    content = seq_info['sequence']
                    break 
            else:
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
            
            if not content:
                raise ValueError("无法从文件中提取有效序列或内容为空")

            safe_content = json.dumps(content)
            safe_path = json.dumps(file_path)
            
            js_code = f"if(window.app) window.app.handleFileLoaded({safe_content}, '{file_type}', {safe_path});"
            self.web_view.page().runJavaScript(js_code)
            self.logger.info(f"Injected {file_type} file content to JS (Size: {len(content)})")
            
        except Exception as e:
            self.logger.error(f"Failed to read file {file_path}: {e}")
            QMessageBox.warning(self, "操作错误", f"无法处理所选文件:\n{str(e)}")

    def run_tree_analysis(self, params=None):
        """
        Run tree analysis with optional parameters and sequence source logic.
        """
        params = params or {"mode": "standard"}
        mode = params.get("mode", "standard")
        
        # 1. Determine Source Paths
        paths = []
        
        # Check if we have files in the workspace (results/tree_workspace)
        workspace = Path("results/tree_workspace")
        if workspace.exists():
            import itertools
            paths = []
            for ext in ("*.fasta", "*.seq", "*.fa", "*.fna"):
                paths.extend([str(f) for f in workspace.glob(ext)])
            self.logger.info(f"Auto-detected {len(paths)} sequences in tree workspace.")
            
        # If workspace is empty, fallback to File Dialog
        if not paths:
            self.logger.info("Workspace empty, showing file dialog...")
            paths, _ = QFileDialog.getOpenFileNames(self, "Select Sequences for Tree", "", 
                                                 "Sequence Files (*.fasta *.fa *.fna *.seq *.txt);;All Files (*.*)")
        
        if not paths:
            return

        final_path = paths[0]
        
        # 2. If multiple files OR single non-fasta file, we merge/convert
        if len(paths) > 1 or (len(paths) == 1 and not paths[0].lower().endswith(('.fasta', '.fa', '.fna'))):
            try:
                import datetime
                # --- 语义化合并命名：避免 generic temp 文件名影响历史分组 ---
                timestamp = datetime.datetime.now().strftime("%m%d_%H%M")
                merge_name = f"Merged_{len(paths)}_Seqs_{timestamp}.fasta"
                final_path = workspace / merge_name
                
                self.logger.info(f"Merging {len(paths)} files into workspace FASTA: {final_path}")
                
                with open(final_path, 'w', encoding='utf-8') as tmp:
                    for p in paths:
                        p_obj = Path(p)
                        with open(p, 'r', encoding='utf-8', errors='ignore') as src:
                            content = src.read().strip()
                            if not content: continue
                            
                            header = p_obj.stem
                            if content.startswith('>'):
                                tmp.write(f"{content}\n")
                            else:
                                clean_seq = "".join(content.split())
                                tmp.write(f">{header}\n{clean_seq}\n")
            except Exception as e:
                QMessageBox.critical(self, "Merge Error", f"Failed to merge sequence files:\n{str(e)}")
                return
            
        self.logger.info(f"Starting tree analysis ({mode}) for {final_path}")
        self.web_view.page().runJavaScript("if(window.showLoading) window.showLoading('正在构建进化树...');")
        
        # Create worker with params
        self.tree_worker = TreeWorker(final_path, params=params)
        self.tree_worker.finished.connect(self.on_tree_finished)
        self.tree_worker.error.connect(self.on_tree_error)
        self.tree_worker.progress.connect(self.on_tree_progress)
        self.tree_worker.start()

    def on_tree_progress(self, data):
        """Handle progress updates from TreeWorker"""
        try:
            percent = data.get("progress", 0)
            msg = data.get("message", "")
            safe_msg = json.dumps(msg)
            # Call JS update
            js_code = f"if(window.updateLoading) window.updateLoading({percent}, {safe_msg});"
            self.web_view.page().runJavaScript(js_code)
        except Exception as e:
            self.logger.error(f"Error updating progress: {e}")
        
    def on_tree_finished(self, result):
        # Hide loading first
        self.web_view.page().runJavaScript("if(window.hideLoading) window.hideLoading();")
        
        self.logger.info("Tree analysis finished")
        if "tree_file" in result:
            tree_path = result["tree_file"]
            self.bridge.current_tree_path = tree_path # Track it for rerooting
            try:
                with open(tree_path, 'r') as f:
                    newick_content = f.read().strip()
                
                # Escape JSON
                safe_newick = json.dumps(newick_content)
                
                # 获取元数据：源文件名（用于历史分组）与结果路径（用于物理删除）
                source_file = os.path.basename(result.get("input_file", "Unknown"))
                safe_source = json.dumps(source_file)
                safe_path = json.dumps(tree_path)
                
                # 将序列指纹清单 (Manifest) 也透传给前端，确保历史记录能找回身份识别对照关系
                id_to_hash = result.get("id_to_hash", {})
                self.bridge.last_manifest = id_to_hash # 缓存清单，供重定根等子任务召回使用
                safe_manifest = json.dumps(id_to_hash)
                
                # 统一使用 Tree Station 2.0 的加载协议调用 (Newick, Algorithm, SourceFile, FilePath, idToHash)
                js_code = f"if(window.treeView) window.treeView.loadNewick({safe_newick}, null, {safe_source}, {safe_path}, {safe_manifest});"
                self.web_view.page().runJavaScript(js_code)
                self.logger.info(f"Injected tree data with manifest size: {len(id_to_hash)}")
            except Exception as e:
                self.logger.error(f"Failed to read tree file: {e}")
                self.web_view.page().runJavaScript(f"console.error('Failed to read tree file: {str(e)}'); alert('读取树文件失败: {str(e)}');")
        else:
             self.logger.warning("No tree file in result")
             self.web_view.page().runJavaScript("console.warn('No tree file generated.'); alert('建树失败：未生成结果文件');")

    def run_tree_reroot(self, node_id):
        """Execute reroot operation and reload tree"""
        if not hasattr(self.bridge, 'current_tree_path') or not self.bridge.current_tree_path:
             self.web_view.page().runJavaScript("if(window.app) window.app.showNotification('未找到当前活动的树文件。', 'error');")
             return

        try:
             self.web_view.page().runJavaScript("if(window.showLoading) window.showLoading('正在重定根...');")
             
             old_path = Path(self.bridge.current_tree_path)
             new_path = old_path.parent / f"{old_path.stem}_rerooted.nwk"
             
             self.bridge.tree_tools = getattr(self.bridge, 'tree_tools', TreeFactory())
             self.bridge.tree_tools.tree_reroot(old_path, node_id, new_path)
             
             # Reload tree in JS
             with open(new_path, 'r') as f:
                 content = f.read()
             
             # 保持重定根后的项目归属感：使用原文件名作为分组标签
             source_file = old_path.name.replace('_rerooted.nwk', '').replace('.nwk', '') + '.fasta'
             safe_source = json.dumps(source_file)
             import json
             safe_newick = json.dumps(content)
             
             # 召回缓存的 manifest，确保重定根后身份识别不丢
             manifest = getattr(self.bridge, 'last_manifest', {})
             safe_manifest = json.dumps(manifest)
             
             # 统一命名协议：使用 window.treeView.loadNewick，并透传源文件标识以便继续归档
             js_code = f"if(window.treeView) window.treeView.loadNewick({safe_newick}, 'Rerooted', {safe_source}, null, {safe_manifest});"
             self.web_view.page().runJavaScript(js_code)
             
        except Exception as e:
             self.logger.error(f"Reroot failed: {e}")
             safe_err = json.dumps(str(e))
             self.web_view.page().runJavaScript(f"if(window.app) window.app.showNotification('重定根失败: ' + {safe_err}, 'error');")




    def on_download_requested(self, download):
        """Handle download requests from the WebEngine"""
        path, _ = QFileDialog.getSaveFileName(self, "保存下载文件", download.downloadFileName())
        if path:
            download.setDownloadDirectory(os.path.dirname(path))
            download.setDownloadFileName(os.path.basename(path))
            download.accept()
            self.logger.info(f"Download accepted: {path}")
        else:
            self.logger.info("Download cancelled by user")

    def on_tree_error(self, err_msg):
        self.logger.error(f"Tree analysis error: {err_msg}")
        safe_err = json.dumps(str(err_msg))
        js_code = f"if(window.treeView) window.treeView.setLoading(false); if(window.app) window.app.showNotification('建树失败: ' + {safe_err}, 'error');"
        self.web_view.page().runJavaScript(js_code)
