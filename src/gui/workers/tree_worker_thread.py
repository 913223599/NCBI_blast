from PyQt6.QtCore import QThread, pyqtSignal
from pathlib import Path
import json
from src.workbench.pipelines.analysis_pipeline import AnalysisPipeline
from src.workbench.models.tool_config import ToolConfig

class TreeWorker(QThread):
    finished = pyqtSignal(dict)
    progress = pyqtSignal(dict)
    error = pyqtSignal(str)
    
    def __init__(self, target_path, mode="standard", stage=None, params=None):
        super().__init__()
        self.target_path = Path(target_path)
        self.mode = mode
        self.stage = stage # New: optional stage name for modular calls
        self.params = params or {} # New: parameters for the stage
        self.pipeline = AnalysisPipeline()
        
    def run(self):
        try:
            # Modular Circuit Mode
            if self.stage:
                result = {}
                if self.stage == "fasta":
                    result = self.pipeline.stage_fasta_process(self.target_path, ToolConfig.RESULTS_DIR)
                elif self.stage == "dist":
                    output_dm = ToolConfig.RESULTS_DIR / f"{self.target_path.stem}.dm"
                    result = self.pipeline.stage_dist_compute(
                        self.target_path, output_dm, 
                        method=self.params.get("method", "rapid"),
                        k=int(self.params.get("k", 20)),
                        threads=self.params.get("threads", None)
                    )
                elif self.stage == "nwk":
                    output_nwk = ToolConfig.RESULTS_DIR / f"{self.target_path.stem}.nwk"
                    result = self.pipeline.stage_nwk_inference(self.target_path, output_nwk)
                elif self.stage == "group":
                    result = self.pipeline.stage_group_analysis(
                        self.target_path, ToolConfig.RESULTS_DIR,
                        dist_threshold=float(self.params.get("threshold", 0.05))
                    )
                
                self.finished.emit(result)
                return

            # Legacy / Monolithic Mode
            workflow = None
            if self.mode == "rapid":
                workflow = self.pipeline.run_full_pipeline(self.target_path, ToolConfig.RESULTS_DIR, params={"k": 20})
            else:
                workflow = self.pipeline.run_full_pipeline(self.target_path, ToolConfig.RESULTS_DIR)
            
            final_result = {}
            for step_data in workflow:
                self.progress.emit(step_data)
                if "result" in step_data:
                    final_result = step_data["result"]
            
            self.finished.emit(final_result)
        except Exception as e:
            self.error.emit(str(e))

