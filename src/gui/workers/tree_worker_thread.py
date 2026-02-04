from PyQt6.QtCore import QThread, pyqtSignal
from pathlib import Path
from src.workbench.pipelines.analysis_pipeline import AnalysisPipeline
from src.workbench.models.tool_config import ToolConfig

class TreeWorker(QThread):
    finished = pyqtSignal(dict)
    progress = pyqtSignal(dict)
    error = pyqtSignal(str)
    
    def __init__(self, fasta_path, mode="standard"):
        super().__init__()
        self.fasta_path = Path(fasta_path)
        self.mode = mode
        self.pipeline = AnalysisPipeline()
        
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
            
            self.finished.emit(final_result)
        except Exception as e:
            self.error.emit(str(e))
