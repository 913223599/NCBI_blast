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

class TreeWorker(QThread):
    finished = pyqtSignal(dict)
    
    def __init__(self, fasta_path):
        super().__init__()
        self.fasta_path = Path(fasta_path)
        self.pipeline = AnalysisPipeline()
        
    def run(self):
        result = self.pipeline.run_standard_tree_workflow(self.fasta_path, ToolConfig.RESULTS_DIR)
        self.finished.emit(result)

class WebBridge(QObject):
    """Bridge for JS to python communication"""
    def __init__(self, log_callback):
        super().__init__()
        self.log_callback = log_callback

    @pyqtSlot(str)
    def on_js_error(self, message):
        self.log_callback(f"[JS Error] {message}")

    @pyqtSlot()
    def on_page_ready(self):
        self.log_callback("[JS] Page reports ready.")

class TreeWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.logger = logging.getLogger(__name__)
        self.setup_ui()
        self.current_newick = None
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

        layout = QVBoxLayout(self)
        
        # Header
        layout.addWidget(QLabel("<h2>Phylogenetic Tree Studio</h2>"))
        
        # Splitter for Log vs Viz
        splitter = QSplitter()
        
        # Left: Controls & Log
        control_widget = QWidget()
        control_layout = QVBoxLayout(control_widget)
        
        self.btn_load = QPushButton("Select FASTA & Build Tree")
        self.btn_load.clicked.connect(self.run_tree)
        control_layout.addWidget(self.btn_load)
        
        self.btn_reload_viz = QPushButton("Reload Visualization")
        self.btn_reload_viz.clicked.connect(self.reload_visualization)
        self.btn_reload_viz.setEnabled(False)
        control_layout.addWidget(self.btn_reload_viz)
        
        self.log_view = QTextEdit()
        control_layout.addWidget(self.log_view)
        
        splitter.addWidget(control_widget)
        
        # Right: Web View
        self.web_view = QWebEngineView()
        # Initialize with blank or loading
        self.web_view.setHtml("<h3>Tree Visualization Area</h3>")
        splitter.addWidget(self.web_view)
        splitter.setStretchFactor(1, 2)
        
        layout.addWidget(splitter)
        
        # Connect load finished signal
        self.web_view.loadFinished.connect(self.on_load_finished)
        
    def run_tree(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select FASTA", "", "FASTA (*.fasta *.fa)")
        if not path:
            return
            
        self.log_view.append(f"Building tree for {path}...")
        self.btn_load.setEnabled(False)
        self.btn_reload_viz.setEnabled(False)
        
        self.worker = TreeWorker(path)
        self.worker.finished.connect(self.on_finished)
        self.worker.start()
        
    def on_finished(self, result):
        self.btn_load.setEnabled(True)
        self.log_view.append(f"Result: {result}")
        
        if "tree_file" in result:
             self.current_tree_path = result["tree_file"]
             self.visualize_tree(self.current_tree_path)
             self.btn_reload_viz.setEnabled(True)

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

