
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional
import time

from .core.base import PipelineContext
from .steps.quality_control import QualityControlStep
from .steps.host_cleaner import HostCleanerStep
from .steps.assembler import AssemblerStep
from .steps.annotation import AnnotationStep
from .env.dependency_manager import DependencyManager
from .engine.gpu_config import GPUConfigManager
from .utils.file_handler import AssemblyFileHandler

class AssemblyManager:
    """
    重构后的基因组拼接管理器
    集成了环境感知、GPU 加速策略及文件校验
    """
    def __init__(self, project_root: Path):
        self.project_root = project_root
        self.logger = logging.getLogger("Assembly.Manager")
        self.results_base = project_root / "results" / "assembly"
        self.results_base.mkdir(parents=True, exist_ok=True)
        
        # 初始化管理器
        self.env_manager = DependencyManager()
        self.gpu_manager = GPUConfigManager()
        self.file_handler = AssemblyFileHandler()
        
        # 活跃任务追踪 (用于强制停止)
        self.active_steps: Dict[str, Any] = {}
        
        from .utils.ncbi_downloader import NCBIDownloader
        from .utils.path_resolver import HostPathResolver
        self.ncbi_downloader = NCBIDownloader(project_root, self.logger)
        self.host_resolver = HostPathResolver(project_root)
        
        # 🔗 额外步骤：确保 WSL 下存在无空格路径映射
        if self.env_manager.is_wsl:
            from .env.wsl_manager import WSLManager
            WSLManager.ensure_project_link()

    def stop_task(self, task_id: str):
        """外部调用：强制停止指定任务"""
        target_id = task_id
        
        # 🔗 智能识别：支持 "current" 别名，自动匹配当前活跃任务
        if task_id == "current":
            if self.active_steps:
                target_id = list(self.active_steps.keys())[-1]
            else:
                self.logger.warning("⚠️ 尝试停止 'current' 任务，但活跃任务列表为空。")
                return False

        if target_id in self.active_steps:
            step = self.active_steps[target_id]
            self.logger.warning(f"🛑 正在强制停止任务: {target_id}")
            if hasattr(step, 'runner'):
                # 💡 强制终止底层 WSL 进程
                step.runner.terminate()
            
            # 标记数据库状态
            from src.backend.utils.assembly_db import assembly_db
            assembly_db.update_task_progress(target_id, "ABORTED", 0, "aborted")
            
            self.active_steps.pop(target_id, None)
            return True
        return False

    async def run_pipeline(self, 
                           task_id: Optional[str], 
                           sample_type: str,
                           r1_input: str, 
                           r2_input: str, 
                           config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        通用基因组流水线 (支持 BACTERIA, PHAGE, VIRUS 等)
        """
        # 0. 格式与完整性预检
        # ...
        # 0. 格式与完整性预检
        if not self.file_handler.validate_fastq_pair(r1_input, r2_input):
            return {"status": "error", "message": "输入文件格式不正确或双端不匹配 (仅支持 .fastq.gz / .fq.gz)"}
            
        if not self.file_handler.check_file_integrity(r1_input) or not self.file_handler.check_file_integrity(r2_input):
            return {"status": "error", "message": "检测到输入压缩文件已损坏 (.gz integrity check failed)"}

        # 自动生成样本 ID
        sample_id = self.file_handler.get_sample_id(r1_input)
        task_id = task_id or f"{sample_id}_{int(time.time())}"

        # 1. 环境预检
        # 2. 硬件资源评估 (动态线程与 GPU)
        import os
        from src.backend.utils.assembly_db import assembly_db
        
        total_cpus = os.cpu_count() or 4
        # 默认使用 75% 的逻辑处理器，但预留至少 2 个核心给系统
        default_threads = max(2, total_cpus - 4) if total_cpus > 8 else total_cpus
        
        import psutil
        total_mem = psutil.virtual_memory().total
        # 尽可能使用空余内存，保留 1GB 给系统 (单位 GB)
        max_mem_gb = max(2, (total_mem // (1024**3)) - 1)
        
        config = config or {}
        config["sample_type"] = sample_type
        config["max_memory"] = max_mem_gb
        
        threads = config.get("threads") or default_threads
        config["threads"] = threads
        
        # 🔗 2.1 初始化数据库记录 (持久化)
        try:
            if not assembly_db.get_task(task_id):
                assembly_db.create_task(
                    task_id, 
                    config.get("name", "New Task"), 
                    sample_id, 
                    sample_type, 
                    config
                )
        except Exception as e:
            logging.error(f"Failed to record task in DB: {e}")

        gpu_env = self.gpu_manager.get_acceleration_env()
        
        # 3. 初始化上下文与配置 (注入 WSL 标识)
        config["is_wsl"] = self.env_manager.is_wsl
        task_dir = self.results_base / task_id
        
        # 🔗 核心修复：支持任务重置 (Reset)
        if config.get("reset") and task_dir.exists():
            self.logger.warning(f"正在重置任务 {task_id}，清理旧数据...")
            import shutil
            try:
                shutil.rmtree(task_dir)
                task_dir.mkdir(parents=True)
            except Exception as e:
                self.logger.error(f"清理任务目录失败: {e}")
        
        # 🔗 GPU 加速环境准备 (挂载为内部属性，不进入 ctx.data 序列化)
        ctx = PipelineContext(task_id, task_dir, config)
        ctx.gpu_manager = self.gpu_manager
        ctx.gpu_env = self.gpu_manager.get_acceleration_env()
        
        # 注入初始输入与环境
        ctx.update("r1", Path(r1_input))
        ctx.update("r2", Path(r2_input))
        
        # 2. 定义步骤序列 (深度模块化：根据物种类型动态编排)
        pipeline_steps = [QualityControlStep(ctx)]
        
        # 🔗 噬菌体专项：插入宿主剔除步骤
        if sample_type == "PHAGE":
            pipeline_steps.append(HostCleanerStep(ctx))
            
        pipeline_steps.extend([
            AssemblerStep(ctx),
            AnnotationStep(ctx)
        ])
        
        logging.info(f"--- [Pipeline Start] Type: {sample_type} | Tasks: {len(pipeline_steps)} | Task: {task_id} ---")
        
        try:
            for i, step in enumerate(pipeline_steps):
                # 链路注册：支持外部停止
                self.active_steps[task_id] = step
                step_name = step.__class__.__name__
                
                # 🔗 额外逻辑：如果已完成，且未要求重置，则提前恢复上下文并同步进度
                if not config.get("reset") and step.is_completed():
                    self.logger.info(f"⏭️ 步骤 {step_name} 已有结果，跳过计算。")
                    # 同步指标到数据库（针对断点续传后的前端显示）
                    overall_p = ((i + 1) / len(pipeline_steps)) * 100
                    self._report_progress(task_id, step_name, overall_p, "completed")
                    continue
                
                # 🔗 额外逻辑：如果是 HostCleaner，解析物理数据库路径
                if step_name == "HostCleanerStep":
                    host_id = config.get("params", {}).get("host_filter_db", "default_ecoli")
                    
                    if host_id.startswith("ncbi:"):
                        species = host_id.replace("ncbi:", "").strip()
                        if not species:
                            raise ValueError("NCBI 宿主菌名称不能为空，请在设置中输入菌株名称（如 Escherichia coli）。")
                        resolved_path_str = await self.ncbi_downloader.fetch_reference_genome(species)
                        if not resolved_path_str:
                            raise ValueError(f"无法从 NCBI 获取物种 '{species}' 的参考基因组，请检查网络连接或尝试手动上传参考文件。")
                        actual_path = Path(resolved_path_str)
                    else:
                        actual_path = self.host_resolver.resolve(host_id)
                    
                    if actual_path:
                        config["params"]["host_filter_db"] = str(actual_path)
                    else:
                        raise ValueError(f"指定的宿主数据库 '{host_id}' 未能通过物理路径解析。")

                stage_map = {
                    "QualityControlStep": "数据质控",
                    "HostCleanerStep": "宿主剔除",
                    "AssemblerStep": "基因组组装",
                    "AnnotationStep": "功能注释"
                }
                current_stage = stage_map.get(step_name, step_name)
                
                # 初始步骤进度
                overall_progress = (i / len(pipeline_steps)) * 100
                self._report_progress(task_id, current_stage, overall_progress, "running")
                
                # 注入进度感知回调
                def step_progress_callback(p, sub_status=None):
                    # 计算相对于整个流水线的细粒度进度
                    current_step_p = overall_progress + (p / len(pipeline_steps))
                    # 如果有具体子状态，拼接到枚举名称后，方便前端显示
                    display_stage = f"{current_stage} ({sub_status})" if sub_status else current_stage
                    self._report_progress(task_id, display_stage, current_step_p, "running")

                step.on_progress = step_progress_callback
                
                logging.info(f"正在执行步骤: {step_name}")
                success = await step.execute()
                
                if not success:
                    logging.error(f"步骤 {step_name} 失败，流水线终止。")
                    self._report_progress(task_id, "FAILED", overall_progress, "failed")
                    from src.backend.utils.assembly_db import assembly_db
                    assembly_db.finalize_task(task_id, "error", {"failed_step": step_name})
                    return {"status": "failed", "step": step_name, "task_id": task_id}
            
            self._report_progress(task_id, "COMPLETED", 100, "success")
            from src.backend.utils.assembly_db import assembly_db
            
            assembly_db.finalize_task(task_id, "completed", {"results": ctx.data})
            logging.info(f"--- [Pipeline Success] Task: {task_id} ---")
            return {
                "status": "success",
                "task_id": task_id,
                "outputs": ctx.data,
                "working_dir": str(task_dir)
            }
            
        except Exception as e:
            logging.exception(f"流水线运行时发生非预期错误: {str(e)}")
            self._report_progress(task_id, "FAILED", 0, "error")
            from src.backend.utils.assembly_db import assembly_db
            assembly_db.finalize_task(task_id, "error", {"error": str(e)})
            return {"status": "error", "message": str(e)}
        finally:
            self.active_steps.pop(task_id, None)

    def _report_progress(self, task_id: str, step: str, progress: float, status: str):
        """通过 WebSocket 广播进度数据，并持久化到数据库"""
        try:
            from src.backend.broadcaster import broadcaster
            from src.backend.utils.assembly_db import assembly_db
            
            # 1. 广播给前端
            broadcaster.broadcast_sync("assembly_progress", {
                "task_id": task_id,
                "step": step,
                "progress": round(progress, 2),
                "status": status,
                "timestamp": time.time()
            })
            
            # 2. 同步到数据库
            assembly_db.update_task_progress(task_id, step, progress, status)
            
        except Exception as e:
            logging.error(f"进度广播或持久化失败: {e}")

    async def run_bacteria_pipeline(self, *args, **kwargs):
        """兼容性别名：默认运行细菌流水线"""
        return await self.run_pipeline(*args, sample_type="BACTERIA", **kwargs)
