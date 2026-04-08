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
                    shutil.move(str(raw_nwk_path), str(archive_nwk)) # 移动而非拷贝
                    final_result["tree_file"] = str(archive_nwk)
                    final_tree_path = archive_nwk
            
            # 3.5 核心改进：迁移指纹清单 (Manifest) 到归档会话
            try:
                manifest_src = Path("results/sequence_manifest.json")
                if manifest_src.exists():
                    archive_manifest = archive_dir / "sequence_manifest.json"
                    shutil.move(str(manifest_src), str(archive_manifest))
                    final_result["manifest_file"] = str(archive_manifest)
            except: pass
            
            # 4. 强力自动清理冗余产物 (Cleanup Engine V2)
            try:
                staging_results = Path("results")
                # 模糊匹配模式：扫描 results 根目录下所有以当前项目名为前缀的文件碎片 (不进入目录)
                # 覆盖：.dm, _aligned.fasta, .nwk, .log, .mldist, .iqtree, .ckp.gz 等
                for junk in staging_results.glob(f"{project_id}*"):
                    if junk.is_file(): # 严禁误删目录
                        junk.unlink()
                
                # 针对旧版残留 user_input 的定期自愈清理
                for junk in staging_results.glob("user_input.*"):
                    if junk.is_file(): junk.unlink()
            except Exception as cleanup_err:
                print(f"Cleanup V2 execution failed: {cleanup_err}")

            # 5. 返回复合指纹，供前端精准定位 (Project/Session/Filename)
            final_result["input_file"] = f"{project_id}/{session_id}/{self.target_path.name}"
            
            self.finished.emit(final_result)
        except Exception as e:
            self.error.emit(str(e))

