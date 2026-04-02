from PyQt6.QtCore import QThread, pyqtSignal
from pathlib import Path
import json
from src.workbench.pipelines.analysis_pipeline import AnalysisPipeline
from src.workbench.models.tool_config import ToolConfig

class TreeWorker(QThread):
    finished = pyqtSignal(dict)
    progress = pyqtSignal(dict)
    error = pyqtSignal(str)
    
    def __init__(self, target_path, params=None):
        super().__init__()
        self.target_path = Path(target_path)
        self.params = params or {"mode": "standard"}
        self.pipeline = AnalysisPipeline()
        
    def run(self):
        try:
            mode = self.params.get("mode", "standard")
            k_size = self.params.get("kmerSize", 21)
            
            # Run pipeline with dynamic params
            workflow = self.pipeline.run_full_pipeline(
                self.target_path, 
                ToolConfig.RESULTS_DIR, 
                method=mode,
                params={"k": k_size} if mode == "rapid" else {}
            )
            
            final_result = {}
            for step_data in workflow:
                self.progress.emit(step_data)
                if "result" in step_data:
                    final_result = step_data["result"]
            
            self.finished.emit(final_result)
        except Exception as e:
            self.error.emit(str(e))

