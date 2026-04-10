from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal

from src.workbench.models.tool_config import ToolConfig
from src.workbench.pipelines.analysis_pipeline import AnalysisPipeline
from src.workbench.wrappers.tree_archive_manager import ArchiveManager


class TreeWorker(QThread):
    finished = pyqtSignal(dict)
    progress = pyqtSignal(dict)
    error = pyqtSignal(str)
    
    def __init__(self, target_path, params=None):
        super().__init__()
        self.target_path = Path(target_path)
        self.params = params or {"mode": "standard"}
        self.pipeline = AnalysisPipeline()
        self.archiver = ArchiveManager()  # 委托归档职责
        
    def run(self):
        try:
            # --- 深度参数对接：从 UI 传入的配置包中提取核心指令 ---
            mode = self.params.get("mode", "standard")
            k_size = self.params.get("kmerSize", 21)
            use_gpu = self.params.get("useGpu", False)
            engine = self.params.get("engine", "nj")
            msa = self.params.get("msa", "none")
            model = self.params.get("model", "jc")
            bootstrap = self.params.get("bootstrap", 1000)
            threads = self.params.get("threads") # Explicitly extract threads if provided
            
            # Run pipeline with dynamic params
            workflow = self.pipeline.run_full_pipeline(
                self.target_path, 
                ToolConfig.RESULTS_DIR, 
                method=mode,
                params={
                    "engine": engine,
                    "msa": msa,
                    "model": model,
                    "bootstrap": bootstrap,
                    "threads": threads,
                    "k": k_size,
                    "use_gpu": use_gpu
                }
            )
            
            import time
            last_emit_time = 0
            emit_interval = 0.1  # 至少间隔 100ms 才发送一次进度更新
            
            final_result = {}
            for step_data in workflow:
                curr_time = time.time()
                # 只有涉及到结果或者时间超过间隔才发送信号，防止信号风暴
                if "result" in step_data or (curr_time - last_emit_time > emit_interval):
                    self.progress.emit(step_data)
                    last_emit_time = curr_time
                    
                if "result" in step_data:
                    final_result = step_data["result"]
            
            # --- 核心改进：使用ArchiveManager进行聚合胶囊归档 ---
            project_id = self.target_path.stem
            
            try:
                # 准备需要归档的文件列表
                result_files = {}
                if "tree_file" in final_result:
                    result_files["tree_file"] = final_result["tree_file"]
                if "manifest_file" in final_result:
                    result_files["manifest_file"] = final_result["manifest_file"]
                
                # 执行归档
                archive_dir = self.archiver.create_session_archive(
                    source_fasta=self.target_path,
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

            # 返回复合指纹，供前端精准定位 (Project/Session/Filename)
            final_result["input_file"] = f"{project_id}/{archive_dir.name}/{self.target_path.name}" if 'archive_dir' in locals() else str(self.target_path)
            
            self.finished.emit(final_result)
        except Exception as e:
            self.error.emit(str(e))

