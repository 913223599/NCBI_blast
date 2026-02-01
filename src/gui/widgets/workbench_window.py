from PyQt6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QTabWidget, 
                             QPushButton, QLabel, QHBoxLayout, QFileDialog, 
                             QMessageBox, QTextEdit)
from PyQt6.QtCore import Qt, QThread, pyqtSignal

from src.workbench.pipelines.data_pipeline import DataPipeline
from src.workbench.pipelines.analysis_pipeline import AnalysisPipeline
from src.workbench.models.tool_config import ToolConfig

class WorkbenchWindow(QMainWindow):
    """
    Main Window for the NCBI Workbench.
    Integrates all tool modules via Tabs.
    """
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("NCBI Workbench v12.0")
        self.resize(1000, 700)
        
        # Pipelines
        self.data_pipe = DataPipeline()
        self.analysis_pipe = AnalysisPipeline()
        
        # Main Layout
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        
        # Header
        header = QLabel("NCBI Bioinformatics Workbench")
        header.setStyleSheet("font-size: 18px; font-weight: bold; padding: 10px;")
        main_layout.addWidget(header)
        
        # Tabs
        self.tabs = QTabWidget()
        main_layout.addWidget(self.tabs)
        
        self.init_sra_tab()
        self.init_seq_tab()
        self.init_tree_tab()
        self.init_log_tab()
        
        # Status Bar
        self.statusBar().showMessage("Ready (153 Tools Loaded)")

    def init_sra_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        layout.addWidget(QLabel("SRA Data Acquisition"))
        
        # Accession Input
        input_layout = QHBoxLayout()
        self.acc_input = QTextEdit()
        self.acc_input.setMaximumHeight(30)
        self.acc_input.setPlaceholderText("Enter Accession (e.g., SRR123456)")
        input_layout.addWidget(self.acc_input)
        
        btn_fetch = QPushButton("Run Pipeline (Prefetch -> Validate -> Dump)")
        btn_fetch.clicked.connect(self.run_sra_pipeline)
        input_layout.addWidget(btn_fetch)
        
        layout.addLayout(input_layout)
        layout.addStretch()
        self.tabs.addTab(tab, "1. SRA Hub")

    def init_seq_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.addWidget(QLabel("Sequence Factory (Under Construction)"))
        self.tabs.addTab(tab, "2. Sequence Lab")

    def init_tree_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.addWidget(QLabel("Phylogenetic Analysis (Under Construction)"))
        self.tabs.addTab(tab, "3. Tree Studio")

    def init_log_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        self.log_area = QTextEdit()
        self.log_area.setReadOnly(True)
        layout.addWidget(self.log_area)
        self.tabs.addTab(tab, "Logs")

    def log(self, message: str):
        self.log_area.append(message)

    def run_sra_pipeline(self):
        acc = self.acc_input.toPlainText().strip()
        if not acc:
            QMessageBox.warning(self, "Error", "Please enter an accession.")
            return
            
        self.log(f"Starting SRA Pipeline for {acc}...")
        # Note: In production, run this in QThread
        results = self.data_pipe.run_acquisition_workflow(acc, ToolConfig.RESULTS_DIR)
        self.log(f"Pipeline Result: {results}")

