
from PyQt6.QtCore import QThread, pyqtSignal
from src.analysis.workflow_engine import WorkflowEngine

class WorkflowWorker(QThread):
    # Signal structure: { "node_id": str, "status": "running"|"completed"|"error", "message": str }
    progress = pyqtSignal(dict) 
    finished = pyqtSignal(dict) # Returns the final context (output paths)
    error = pyqtSignal(str)
    
    def __init__(self, topology_json):
        super().__init__()
        self.topology = topology_json
        self.engine = WorkflowEngine()
        
    def run(self):
        try:
            context = self.engine.run_topology(
                self.topology, 
                progress_callback=self._on_progress
            )
            self.finished.emit(context)
        except Exception as e:
            self.error.emit(str(e))
            
    def _on_progress(self, node_id, status, msg):
        self.progress.emit({
            "node_id": node_id,
            "status": status,
            "message": msg
        })
