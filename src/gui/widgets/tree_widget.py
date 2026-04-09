from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QPushButton, QLabel, 
                             QFileDialog, QTextEdit, QSplitter)
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebChannel import QWebChannel
from PyQt6.QtCore import QThread, pyqtSignal, QUrl, QTimer, QObject, pyqtSlot
from pathlib import Path
import json
import logging


from src.workbench.pipelines.analysis_pipeline import AnalysisPipeline
from src.workbench.models.tool_config import ToolConfig
from src.workbench.wrappers.tree_archive_manager import ArchiveManager

class TreeWorker(QThread):
    finished = pyqtSignal(dict)
    progress = pyqtSignal(dict)
    error = pyqtSignal(str)
    
    def __init__(self, fasta_path, mode="standard"):
        super().__init__()
        self.fasta_path = Path(fasta_path)
        self.mode = mode
        self.pipeline = AnalysisPipeline()
        self.archiver = ArchiveManager()
        
    def run(self):
        try:
            workflow = None
            if self.mode == "fast":
                workflow = self.pipeline.run_fast_tree_workflow(self.fasta_path, ToolConfig.RESULTS_DIR)
            else:
                workflow = self.pipeline.run_standard_tree_workflow(self.fasta_path, ToolConfig.RESULTS_DIR)
            
            final_result = {}
            for step_data in workflow:
                self.progress.emit(step_data)
                if "result" in step_data:
                    final_result = step_data["result"]
            
            # --- 核心改进：使用ArchiveManager进行聚合胶囊归档 ---
            project_id = self.fasta_path.stem
            
            try:
                # 准备需要归档的文件列表
                result_files = {}
                if "tree_file" in final_result:
                    result_files["tree_file"] = final_result["tree_file"]
                if "manifest_file" in final_result:
                    result_files["manifest_file"] = final_result["manifest_file"]
                
                # 执行归档
                archive_dir = self.archiver.create_session_archive(
                    source_fasta=self.fasta_path,
                    result_files=result_files,
                    project_id=project_id
                )
                
                # 更新结果中的文件路径为归档后的路径
                if "tree_file" in result_files:
                    final_result["tree_file"] = str(result_files["tree_file"])
                if "manifest_file" in result_files:
                    final_result["manifest_file"] = str(result_files["manifest_file"])
                
                # 清理临时工作区
                self.archiver.cleanup_staging_area(project_id)
                
            except Exception as archive_err:
                print(f"Archive execution failed (non-critical): {archive_err}")
                # 归档失败不影响主流程，继续返回结果
            
            self.finished.emit(final_result)
        except Exception as e:
            self.error.emit(str(e))

class WebBridge(QObject):
    """Bridge for JS to python communication"""
    def __init__(self, log_callback):
        super().__init__()
        self.log_callback = log_callback

    @pyqtSlot(str)
    def on_js_error(self, message):
        self.log_callback(f"[JS Error] {message}")
    
    @pyqtSlot(str)
    def on_js_log(self, message):
        # 过滤掉一些 verbose 的日志 if needed
        self.log_callback(f"[JS] {message}")

    @pyqtSlot()
    def on_page_ready(self):
        self.log_callback("[JS] Page reports ready.")

class TreeWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.logger = logging.getLogger(__name__)
        self.current_newick = None
        self.setup_ui()
        self.setup_bridge()

        
    def setup_bridge(self):
        self.channel = QWebChannel()
        self.bridge = WebBridge(self.handle_bridge_log)
        self.channel.registerObject("py_bridge", self.bridge)
        self.web_view.page().setWebChannel(self.channel)
        
    def handle_bridge_log(self, msg):
        self.log_view.append(msg)
        if "[JS Error]" in msg or "CRITICAL" in msg:
             self.logger.error(msg)
        else:
             self.logger.info(msg)

    def setup_ui(self):
        from PyQt6.QtWidgets import QComboBox, QProgressBar, QGroupBox, QFrame

        layout = QVBoxLayout(self)
        
        # Header
        header = QFrame()
        header.setStyleSheet("background: white; border-bottom: 1px solid #ddd;")
        header_layout = QHBoxLayout(header)
        title = QLabel("<h2>Phylogenetic Tree Studio</h2>")
        title.setStyleSheet("border: none;")
        header_layout.addWidget(title)
        layout.addWidget(header)
        
        # Splitter for Log vs Viz
        splitter = QSplitter()
        
        # Left: Controls & Log
        control_widget = QWidget()
        control_layout = QVBoxLayout(control_widget)
        
        # Config Group
        cfg_group = QGroupBox("Analysis Settings")
        cfg_layout = QVBoxLayout(cfg_group)
        
        self.method_select = QComboBox()
        self.method_select.addItem("Standard (Alignment-based)", "standard")
        self.method_select.addItem("Fast (MinHash-based)", "fast")
        cfg_layout.addWidget(QLabel("Workflow Method:"))
        cfg_layout.addWidget(self.method_select)
        
        self.btn_load = QPushButton("Select FASTA & Build Tree")
        self.btn_load.setStyleSheet("background-color: #007bff; color: white; padding: 6px; font-weight: bold;")
        self.btn_load.clicked.connect(self.run_tree)
        cfg_layout.addWidget(self.btn_load)
        
        control_layout.addWidget(cfg_group)
        
        # Progress
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.hide()
        control_layout.addWidget(self.progress_bar)
        
        self.status_label = QLabel("Ready")
        self.status_label.setStyleSheet("color: #666; font-style: italic;")
        control_layout.addWidget(self.status_label)
        
        # Actions
        action_layout = QHBoxLayout()
        self.btn_reload_viz = QPushButton("Reload Viz")
        self.btn_reload_viz.clicked.connect(self.reload_visualization)
        self.btn_reload_viz.setEnabled(False)
        action_layout.addWidget(self.btn_reload_viz)
        
        control_layout.addLayout(action_layout)
        
        # Log
        control_layout.addWidget(QLabel("Activity Log:"))
        self.log_view = QTextEdit()
        self.log_view.setStyleSheet("font-family: Consolas; font-size: 9pt;")
        control_layout.addWidget(self.log_view)
        
        splitter.addWidget(control_widget)
        
        # Right: Web View
        self.web_view = QWebEngineView()
        # Initialize with blank or loading
        self.web_view.setHtml("<div style='text-align:center; padding:50px; color:#aaa;'><h1>Tree Visualization Area</h1><p>Load sequences to begin</p></div>")
        splitter.addWidget(self.web_view)
        splitter.setStretchFactor(1, 4) # Give more space to Web View
        
        layout.addWidget(splitter)
        
        # Connect load finished signal
        self.web_view.loadFinished.connect(self.on_load_finished)
        
    def run_tree(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select FASTA", "", "FASTA (*.fasta *.fa)")
        if not path:
            return
            
        mode = self.method_select.currentData()
        self.log_view.append(f"Starting {mode} workflow for {path}...")
        
        self.btn_load.setEnabled(False)
        self.method_select.setEnabled(False)
        self.progress_bar.setValue(0)
        self.progress_bar.show()
        
        self.worker = TreeWorker(path, mode)
        self.worker.progress.connect(self.on_progress)
        self.worker.finished.connect(self.on_finished)
        self.worker.error.connect(self.on_error)
        self.worker.start()
        
    def on_progress(self, data):
        pct = data.get("progress", 0)
        msg = data.get("message", "")
        self.progress_bar.setValue(pct)
        self.status_label.setText(msg)
        if msg:
            self.log_view.append(f"[{data.get('step')}] {msg}")
            
    def on_error(self, err_msg):
        self.log_view.append(f"ERROR: {err_msg}")
        self.status_label.setText("Error occurred")
        self.reset_ui_state()

    def on_finished(self, result):
        self.reset_ui_state()
        self.log_view.append(f"Workflow completed. Result keys: {list(result.keys())}")
        
        if "tree_file" in result:
             self.current_tree_path = result["tree_file"]
             self.visualize_tree(self.current_tree_path)
             self.btn_reload_viz.setEnabled(True)
             self.status_label.setText("Tree built successfully.")
        else:
             self.log_view.append("Warning: No tree file generated.")

    def reset_ui_state(self):
        self.btn_load.setEnabled(True)
        self.method_select.setEnabled(True)
        self.progress_bar.hide()

    def visualize_tree(self, tree_path):
        """
        Load the template first.
        """
        project_root = ToolConfig.PROJECT_ROOT
        template_path = project_root / "src" / "web" / "templates" / "tree_explorer.html"
        
        if not template_path.exists():
            self.log_view.append(f"Error: Template not found at {template_path}")
            return
            
        self.log_view.append(f"Loading template: {template_path}")
        self.web_view.setUrl(QUrl.fromLocalFile(str(template_path)))
        
        # Store newick content for injection after load
        try:
            with open(tree_path, 'r') as f:
                self.current_newick = f.read().strip()
        except Exception as e:
            self.log_view.append(f"Error reading tree file: {e}")

    def on_load_finished(self, ok):
        if not ok:
            self.log_view.append("Error loading visualization template.")
            return
            
        if self.current_newick:
            # Escape newick string for JS
            safe_newick = json.dumps(self.current_newick)
            js_code = f"loadTree({safe_newick});"
            self.web_view.page().runJavaScript(js_code)
            self.log_view.append("Tree data injected into visualization.")

    def reload_visualization(self):
        if hasattr(self, 'current_tree_path') and self.current_tree_path:
            self.visualize_tree(self.current_tree_path)

