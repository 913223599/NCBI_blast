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
            
            # --- 核心改进：聚合胶囊归档 (Encapsulated Capsule Archiving) ---
            # 1. 建立基于 [项目/会话] 的物理层级，确保 Source 与 Result 永不分离
            import shutil, time
            project_id = self.target_path.stem
            timestamp = time.strftime('%Y%m%d_%H%M%S')
            
            # 创建唯一的会话指纹目录
            session_id = f"Session_{timestamp}"
            archive_dir = Path("results/tree_results") / project_id / session_id
            archive_dir.mkdir(parents=True, exist_ok=True)
            
            # 2. 迁移原始序列 (Source) 到归档会话
            archive_fasta = archive_dir / self.target_path.name
            shutil.copy2(self.target_path, archive_fasta)
            
            # 3. 迁移分析结果 (Result) 到归档会话
            final_tree_path = None
            if "tree_file" in final_result:
                raw_nwk_path = Path(final_result["tree_file"])
                if raw_nwk_path.exists():
                    archive_nwk = archive_dir / raw_nwk_path.name
                    shutil.move(str(raw_nwk_path), str(archive_nwk)) # 移动而非拷贝，完成初步清理
                    final_result["tree_file"] = str(archive_nwk) # 更新结果路径为归档路径
                    final_tree_path = archive_nwk
            
            # 4. 暴力清理挥发性中间产物 (Cleanup Staging Area)
            # 扫描 results 根目录下所有与当前项目名相关的临时文件 (.dm, _aligned.fasta 等)
            try:
                staging_results = Path("results")
                # 清理模式：[项目名].dm, [项目名]_aligned.fasta, [项目名].nwk (如果还在)
                patterns = [f"{project_id}.dm", f"{project_id}_aligned.fasta", f"{project_id}.nwk"]
                for p in patterns:
                    target_junk = staging_results / p
                    if target_junk.exists():
                        target_junk.unlink()
                # 针对旧版残留 user_input 的定期自愈清理
                for junk in staging_results.glob("user_input.*"):
                    junk.unlink()
            except Exception as cleanup_err:
                print(f"Post-analysis cleanup failed: {cleanup_err}")

            # 5. 返回复合指纹，供前端精准定位 (Project/Session/Filename)
            final_result["input_file"] = f"{project_id}/{session_id}/{self.target_path.name}"
            
            self.finished.emit(final_result)
        except Exception as e:
            self.error.emit(str(e))

