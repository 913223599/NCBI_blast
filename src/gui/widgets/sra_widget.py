from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
                             QLineEdit, QPushButton, QTextEdit, QProgressBar, QMessageBox)
from PyQt6.QtCore import QThread, pyqtSignal

from src.workbench.pipelines.data_pipeline import DataPipeline
from src.workbench.models.tool_config import ToolConfig

class SraWorker(QThread):
    finished = pyqtSignal(dict)
    
    def __init__(self, accession):
        super().__init__()
        self.accession = accession
        self.pipeline = DataPipeline()
        
    def run(self):
        # Run pipeline in background
        result = self.pipeline.run_acquisition_workflow(self.accession, ToolConfig.RESULTS_DIR)
        self.finished.emit(result)

class SraWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setup_ui()
        
    def setup_ui(self):
        layout = QVBoxLayout(self)
        
        # Head
        layout.addWidget(QLabel("<h2>SRA Data Acquisition Hub</h2>"))
        layout.addWidget(QLabel("Fetch, Validate and Convert SRA data locally."))
        
        # Input
        form = QHBoxLayout()
        self.acc_input = QLineEdit()
        self.acc_input.setPlaceholderText("Enter Accession (e.g., SRR000001)")
        form.addWidget(QLabel("Accession:"))
        form.addWidget(self.acc_input)
        
        self.btn_run = QPushButton("Start Pipeline")
        self.btn_run.clicked.connect(self.start_pipeline)
        form.addWidget(self.btn_run)
        
        layout.addLayout(form)
        
        # Progress
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setRange(0, 0) # Indeterminate
        self.progress.hide()
        layout.addWidget(self.progress)
        
        # Log
        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        layout.addWidget(self.log_view)
        
    def start_pipeline(self):
        acc = self.acc_input.text().strip()
        if not acc:
            return
            
        self.log(f"Starting pipeline for {acc}...")
        self.progress.show()
        self.btn_run.setEnabled(False)
        
        self.worker = SraWorker(acc)
        self.worker.finished.connect(self.on_finished)
        self.worker.start()
        
    def on_finished(self, result):
        self.progress.hide()
        self.btn_run.setEnabled(True)
        self.log(f"Pipeline Result:\n{result}")
        if result.get("files"):
            self.log(f"Generated Files: {result['files']}")
            
    def log(self, msg):
        self.log_view.append(msg)
