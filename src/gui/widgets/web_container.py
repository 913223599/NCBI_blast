# -*- coding: utf-8 -*-
"""
web_container.py — 主入口
WebBridge 通过 Mixin 组合了 6 个职责域模块，保持 QWebChannel 注册接口不变。
WebContainer / DnDWebEngineView / WebPage 保留原位。
"""
import os
import json
import logging
import datetime
from pathlib import Path
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QMessageBox, QFileDialog
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebChannel import QWebChannel
from PyQt6.QtCore import QUrl, QObject, pyqtSlot, pyqtSignal
from PyQt6.QtWebEngineCore import QWebEngineProfile, QWebEnginePage

from src.blast.manager import get_blast_manager
from src.gui.workers.tree_worker_thread import TreeWorker

# --- Mixin 模块导入 ---
from src.gui.widgets.bridge_core import CoreBridgeMixin
from src.gui.widgets.bridge_strain_db import StrainDBMixin
from src.gui.widgets.bridge_blast import BlastBridgeMixin
from src.gui.widgets.bridge_tree import TreeBridgeMixin
from src.gui.widgets.bridge_translation import TranslationBridgeMixin
from src.gui.widgets.bridge_settings import SettingsBridgeMixin


class WebBridge(
    CoreBridgeMixin,
    StrainDBMixin,
    BlastBridgeMixin,
    TreeBridgeMixin,
    TranslationBridgeMixin,
    SettingsBridgeMixin,
    QObject
):
    """Bridge for JS to Python communication (Mixin-Composition Architecture)"""

    # Signals
    page_ready = pyqtSignal()
    help_requested = pyqtSignal()
    blast_event = pyqtSignal(str, str)  # type, json_data
    recall_event = pyqtSignal(bool, str)  # success, message

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

        # Initialize Translation Thread Pool (from TranslationBridgeMixin)
        self._init_translation_pool()

    def _on_bridge_event_emitted(self, event_type, json_data):
        """Relay signals from Python to JS global handler in the WebView"""
        try:
            safe_type = json.dumps(event_type)
            js_code = f"if(window.handleBridgeEvent) window.handleBridgeEvent({safe_type}, {json_data});"
            self.container.web_view.page().runJavaScript(js_code)
        except Exception as exc:
            self.logger.error(f"Failed to relay bridge event: {exc}")


# ──────────────────────────────────────────────
# DnD-Aware WebEngineView
# ──────────────────────────────────────────────
class DnDWebEngineView(QWebEngineView):
    """Subclass to intercept Drag and Drop events."""

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
                        extracted = self._extract_sequences_from_zip(local_path)
                        if extracted:
                            final_paths.extend(extracted)
                    else:
                        final_paths.append(local_path)

            if final_paths:
                event.accept()
                safe_paths = json.dumps(final_paths)
                js_code = f"if(window.app && window.app.handleFilesDropped) window.app.handleFilesDropped({safe_paths});"
                self.page().runJavaScript(js_code)
                return

        super().dropEvent(event)

    def _extract_sequences_from_zip(self, zip_path):
        """Shared logic for ZIP sorting on drag-and-drop"""
        import zipfile
        import os
        from PyQt6.QtWidgets import QInputDialog, QLineEdit

        extracted_results = []
        try:
            with zipfile.ZipFile(zip_path) as zf:
                valid_exts = ['.seq', '.fasta', '.fas', '.fa']
                seq_files = [n for n in zf.namelist() if any(n.lower().endswith(e) for e in valid_exts)]

                if not seq_files:
                    return []

                test_file = seq_files[0]
                password = None
                try:
                    zf.read(test_file)
                except Exception as exc:
                    if 'encrypted' in str(exc).lower() or 'password' in str(exc).lower():
                        pwd, ok = QInputDialog.getText(
                            self, "拖入加密压缩包",
                            f"文件 '{Path(zip_path).name}' 已加密。\n请输入解压密码:",
                            QLineEdit.EchoMode.Password
                        )
                        if not ok:
                            return []
                        password = pwd

                project_root = Path(__file__).resolve().parent.parent.parent.parent
                staging_id = f"staged_{datetime.datetime.now().strftime('%H%M%S')}_{os.getpid()}"
                temp_root = project_root / "results" / "extracted" / staging_id
                temp_root.mkdir(parents=True, exist_ok=True)

                pwd_bytes = password.encode() if password else None
                for f_name in seq_files:
                    try:
                        out_path = zf.extract(f_name, path=str(temp_root), pwd=pwd_bytes)
                        extracted_results.append(out_path)
                    except Exception:
                        pass

        except Exception as exc:
            print(f"Error extracting ZIP drop: {exc}")

        return extracted_results


# ──────────────────────────────────────────────
# Custom WebPage for JS Console
# ──────────────────────────────────────────────
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


# ──────────────────────────────────────────────
# Main Web Container Widget
# ──────────────────────────────────────────────
class WebContainer(QWidget):
    """Main Web Container Widget. Hosts the Single Page Application (SPA)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.logger = logging.getLogger(__name__)
        self.bridge = WebBridge(self)
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.web_view = DnDWebEngineView(self)

        # Persistent Storage
        storage_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../storage/web"))
        os.makedirs(storage_path, exist_ok=True)

        # Cleanup potentially corrupted cache
        import shutil
        corrupted_dirs = ["Shared Dictionary", "Cache", "Code Cache", "Service Worker"]
        for d_name in corrupted_dirs:
            d_path = os.path.join(storage_path, d_name)
            if os.path.exists(d_path):
                try:
                    if not hasattr(WebContainer, "_cache_cleaned"):
                        self.logger.info(f"Checking storage health: {d_name}")
                        if d_name == "Shared Dictionary":
                            shutil.rmtree(d_path, ignore_errors=True)
                except Exception as exc:
                    self.logger.warning(f"Could not clean cache dir {d_name}: {exc}")
        WebContainer._cache_cleaned = True

        # Named Profile
        profile = QWebEngineProfile("BioStationProfile", self.web_view)
        profile.setPersistentStoragePath(storage_path)
        profile.setPersistentCookiesPolicy(QWebEngineProfile.PersistentCookiesPolicy.AllowPersistentCookies)
        profile.downloadRequested.connect(self.on_download_requested)

        # Custom page
        page = WebPage(profile, self.web_view)
        from PyQt6.QtGui import QColor
        page.setBackgroundColor(QColor("#0f172a"))
        self.web_view.setPage(page)

        # JS settings
        settings = self.web_view.settings()
        settings.setAttribute(settings.WebAttribute.JavascriptCanOpenWindows, True)
        settings.setAttribute(settings.WebAttribute.JavascriptCanAccessClipboard, True)
        settings.setAttribute(settings.WebAttribute.LocalStorageEnabled, True)

        # WebChannel
        self.channel = QWebChannel()
        self.channel.registerObject("py_bridge", self.bridge)
        self.web_view.page().setWebChannel(self.channel)

        # Load URL
        dev_url = os.environ.get("WEB_URL")
        if dev_url:
            url = QUrl(dev_url)
            self.logger.info(f"Loading Dev Web Container from: {url.toString()}")
            self.web_view.load(url)
        else:
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
            self.web_view.update()
            from PyQt6.QtCore import QTimer
            QTimer.singleShot(100, self._force_redraw_cycle)
            QTimer.singleShot(300, self._force_redraw_cycle)

    def _force_redraw_cycle(self):
        """强制重绘周期"""
        if hasattr(self, 'web_view'):
            js_code = """
            (function(){
                window.dispatchEvent(new Event('resize'));
                if (window.app && window.app.syncViewLayouts) {
                    window.app.syncViewLayouts();
                }
                document.body.style.opacity = '0.999';
                setTimeout(() => { document.body.style.opacity = '1'; }, 0);
            })();
            """
            self.web_view.page().runJavaScript(js_code)
            self.web_view.update()
            if self.web_view.focusProxy():
                self.web_view.focusProxy().repaint()
            if self.window():
                self.window().update()

    def open_file_dialog(self, file_type):
        """Open QFileDialog and handle file injection, including compressed archive support"""
        from PyQt6.QtWidgets import QInputDialog, QLineEdit
        import zipfile

        filter_str = "All Files (*.*)"
        if file_type == 'tree':
            filter_str = "Tree Files (*.nwk *.newick *.txt);;All Files (*.*)"
        elif file_type == 'structure':
            filter_str = "Protein Structure (*.pdb *.ent);;All Files (*.*)"
        elif file_type == 'fasta':
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
                        valid_exts = ['.seq', '.fasta', '.fas', '.fa']
                        seq_files = [n for n in zf.namelist() if any(n.lower().endswith(e) for e in valid_exts)]

                        if not seq_files:
                            QMessageBox.information(self, "压缩包解析", "该压缩包内未提取到有效的序列文件 (.seq, .fasta等)")
                            return

                        password = None
                        test_file = seq_files[0]
                        try:
                            zf.read(test_file)
                        except RuntimeError as runtime_exc:
                            if 'encrypted' in str(runtime_exc).lower() or 'password' in str(runtime_exc).lower():
                                while True:
                                    pwd, ok = QInputDialog.getText(
                                        self, "识别到加密压缩包",
                                        f"压缩文件 '{Path(file_path).name}' 已加密。\n请输入密码以继续导入序列:",
                                        QLineEdit.EchoMode.Password
                                    )
                                    if not ok:
                                        return
                                    try:
                                        zf.read(test_file, pwd=pwd.encode())
                                        password = pwd
                                        break
                                    except Exception:
                                        QMessageBox.warning(self, "密码错误", "输入的密码不正确，请重新输入。")

                        project_root = Path(__file__).resolve().parent.parent.parent.parent
                        staging_id = f"staged_{datetime.datetime.now().strftime('%H%M%S')}_{os.getpid()}"
                        temp_root = project_root / "results" / "extracted" / staging_id
                        temp_root.mkdir(parents=True, exist_ok=True)

                        pwd_bytes = password.encode() if password else None
                        injected_count = 0

                        for f_name in seq_files:
                            try:
                                out_path = zf.extract(f_name, path=str(temp_root), pwd=pwd_bytes)
                                inner_ext = Path(out_path).suffix.lower()
                                content = ""
                                if inner_ext in ['.ab1', '.abi']:
                                    from src.utils.file_handler import FileHandler
                                    handler = FileHandler()
                                    for seq_info in handler.read_fasta_file_iter(out_path):
                                        content = seq_info['sequence']
                                        break
                                else:
                                    with open(out_path, 'r', encoding='utf-8', errors='ignore') as fobj:
                                        content = fobj.read()

                                if content:
                                    safe_content = json.dumps(content)
                                    safe_path = json.dumps(out_path)
                                    js_code = f"if(window.app) window.app.handleFileLoaded({safe_content}, 'fasta', {safe_path});"
                                    self.web_view.page().runJavaScript(js_code)
                                    injected_count += 1
                            except Exception as inner_exc:
                                self.logger.error(f"Extraction error for {f_name}: {inner_exc}")

                        if injected_count > 0:
                            QMessageBox.information(self, "导入完成", f"已成功从压缩包中分拣并导入了 {injected_count} 条序列。")
                        return
                except Exception as zip_exc:
                    raise ValueError(f"压缩包解析失败: {zip_exc}")

            # --- 常规处理：单文件 ---
            content = ""
            if ext in ['.ab1', '.abi']:
                from src.utils.file_handler import FileHandler
                handler = FileHandler()
                for seq_info in handler.read_fasta_file_iter(file_path):
                    content = seq_info['sequence']
                    break
            else:
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as fobj:
                    content = fobj.read()

            if not content:
                raise ValueError("无法从文件中提取有效序列或内容为空")

            safe_content = json.dumps(content)
            safe_path = json.dumps(file_path)
            js_code = f"if(window.app) window.app.handleFileLoaded({safe_content}, '{file_type}', {safe_path});"
            self.web_view.page().runJavaScript(js_code)
            self.logger.info(f"Injected {file_type} file content to JS (Size: {len(content)})")

        except Exception as exc:
            self.logger.error(f"Failed to read file {file_path}: {exc}")
            QMessageBox.warning(self, "操作错误", f"无法处理所选文件:\n{str(exc)}")

    def run_tree_analysis(self, params=None):
        """Run tree analysis with optional parameters and sequence source logic."""
        params = params or {"mode": "standard"}
        mode = params.get("mode", "standard")

        paths = []
        workspace = Path("results/tree_workspace")
        if workspace.exists():
            for ext in ("*.fasta", "*.seq", "*.fa", "*.fna"):
                paths.extend([str(f) for f in workspace.glob(ext)])
            self.logger.info(f"Auto-detected {len(paths)} sequences in tree workspace.")

        if not paths:
            self.logger.info("Workspace empty, showing file dialog...")
            paths, _ = QFileDialog.getOpenFileNames(
                self, "Select Sequences for Tree", "",
                "Sequence Files (*.fasta *.fa *.fna *.seq *.txt);;All Files (*.*)"
            )

        if not paths:
            return

        final_path = paths[0]

        if len(paths) > 1 or (len(paths) == 1 and not paths[0].lower().endswith(('.fasta', '.fa', '.fna'))):
            try:
                timestamp = datetime.datetime.now().strftime("%m%d_%H%M")
                merge_name = f"Merged_{len(paths)}_Seqs_{timestamp}.fasta"
                final_path = workspace / merge_name

                self.logger.info(f"Merging {len(paths)} files into workspace FASTA: {final_path}")

                with open(final_path, 'w', encoding='utf-8') as tmp:
                    for p_str in paths:
                        p_obj = Path(p_str)
                        with open(p_str, 'r', encoding='utf-8', errors='ignore') as src:
                            content = src.read().strip()
                            if not content:
                                continue
                            header = p_obj.stem
                            if content.startswith('>'):
                                tmp.write(f"{content}\n")
                            else:
                                clean_seq = "".join(content.split())
                                tmp.write(f">{header}\n{clean_seq}\n")
            except Exception as exc:
                QMessageBox.critical(self, "Merge Error", f"Failed to merge sequence files:\n{str(exc)}")
                return

        self.logger.info(f"Starting tree analysis ({mode}) for {final_path}")
        self.web_view.page().runJavaScript("if(window.showLoading) window.showLoading('正在构建进化树...');")

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
            js_code = f"if(window.updateLoading) window.updateLoading({percent}, {safe_msg});"
            self.web_view.page().runJavaScript(js_code)
        except Exception as exc:
            self.logger.error(f"Error updating progress: {exc}")

    def on_tree_finished(self, result):
        self.web_view.page().runJavaScript("if(window.hideLoading) window.hideLoading();")
        self.logger.info("Tree analysis finished")

        if "tree_file" in result:
            tree_path = result["tree_file"]
            self.bridge.current_tree_path = tree_path
            try:
                with open(tree_path, 'r') as fobj:
                    newick_content = fobj.read().strip()

                safe_newick = json.dumps(newick_content)
                source_file = os.path.basename(result.get("input_file", "Unknown"))
                safe_source = json.dumps(source_file)
                safe_path = json.dumps(tree_path)

                id_to_hash = result.get("id_to_hash", {})
                self.bridge.last_manifest = id_to_hash
                safe_manifest = json.dumps(id_to_hash)

                js_code = f"if(window.treeView) window.treeView.loadNewick({safe_newick}, null, {safe_source}, {safe_path}, {safe_manifest});"
                self.web_view.page().runJavaScript(js_code)
                self.logger.info(f"Injected tree data with manifest size: {len(id_to_hash)}")
            except Exception as exc:
                self.logger.error(f"Failed to read tree file: {exc}")
                safe_err = json.dumps(str(exc))
                self.web_view.page().runJavaScript(
                    f"console.error('Failed to read tree file: ' + {safe_err}); alert('读取树文件失败: ' + {safe_err});"
                )
        else:
            self.logger.warning("No tree file in result")
            self.web_view.page().runJavaScript(
                "console.warn('No tree file generated.'); alert('建树失败：未生成结果文件');"
            )

    def run_tree_reroot(self, node_id):
        """Execute reroot operation and reload tree"""
        if not hasattr(self.bridge, 'current_tree_path') or not self.bridge.current_tree_path:
            self.web_view.page().runJavaScript(
                "if(window.app) window.app.showNotification('未找到当前活动的树文件。', 'error');"
            )
            return

        try:
            self.web_view.page().runJavaScript("if(window.showLoading) window.showLoading('正在重定根...');")

            old_path = Path(self.bridge.current_tree_path)
            new_path = old_path.parent / f"{old_path.stem}_rerooted.nwk"

            from src.gui.workers.tree_worker_thread import TreeFactory
            self.bridge.tree_tools = getattr(self.bridge, 'tree_tools', TreeFactory())
            self.bridge.tree_tools.tree_reroot(old_path, node_id, new_path)

            with open(new_path, 'r') as fobj:
                content = fobj.read()

            source_file = old_path.name.replace('_rerooted.nwk', '').replace('.nwk', '') + '.fasta'
            safe_source = json.dumps(source_file)
            safe_newick = json.dumps(content)

            manifest = getattr(self.bridge, 'last_manifest', {})
            safe_manifest = json.dumps(manifest)

            js_code = f"if(window.treeView) window.treeView.loadNewick({safe_newick}, 'Rerooted', {safe_source}, null, {safe_manifest});"
            self.web_view.page().runJavaScript(js_code)
        except Exception as exc:
            self.logger.error(f"Reroot failed: {exc}")
            safe_err = json.dumps(str(exc))
            self.web_view.page().runJavaScript(
                f"if(window.app) window.app.showNotification('重定根失败: ' + {safe_err}, 'error');"
            )

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
        js_code = (
            f"if(window.treeView) window.treeView.setLoading(false); "
            f"if(window.app) window.app.showNotification('建树失败: ' + {safe_err}, 'error');"
        )
        self.web_view.page().runJavaScript(js_code)
