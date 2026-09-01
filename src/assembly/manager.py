
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional
import time as _time

from .core.base import PipelineContext
from .steps.quality_control import QualityControlStep
from .steps.host_cleaner import HostCleanerStep
from .steps.assembler import AssemblerStep
from .steps.prophage_separator import ProphageSeparatorStep
from .steps.merger import ReadMergerStep
from .steps.gap_filler import GapFillerStep
from .steps.scaffolder import ScaffoldingStep
from .steps.correction import ConsensusCorrectionStep
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
        
        #  内存探测缓存：避免频繁调用 systeminfo.exe
        self._cached_total_mem_gb: Optional[float] = None
        
        from .utils.ncbi_downloader import NCBIDownloader
        from .utils.path_resolver import HostPathResolver
        self.ncbi_downloader = NCBIDownloader(project_root, self.logger)
        self.host_resolver = HostPathResolver(project_root)
        
        #  额外步骤：确保 WSL 下存在无空格路径映射
        if self.env_manager.is_wsl:
            from .env.wsl_manager import WSLManager
            WSLManager.ensure_project_link()

    def stop_task(self, task_id: str) -> Optional[str]:
        """外部调用：强制停止指定任务 (支持多 Worker 跨进程斩断)"""
        target_id = task_id
        
        #  智能识别：支持 "current" 别名，自动匹配当前活跃任务
        if task_id == "current":
            from src.backend.utils.assembly_db import assembly_db
            running_tasks = [t for t in assembly_db.get_incomplete_tasks() if t.get('status') == 'running']
            if running_tasks:
                target_id = running_tasks[-1]['id']
            elif self.active_steps:
                target_id = list(self.active_steps.keys())[-1]
            else:
                self.logger.warning("️ 尝试停止 'current' 任务，但活跃任务列表为空且无运行中的任务。")
                return None

        # 1. 标记数据库状态为 ABORTED
        from src.backend.utils.assembly_db import assembly_db
        assembly_db.update_task_progress(target_id, "ABORTED", 0, "aborted")
        
        # 2. 尝试在本地内存中终止 (如果是当前 Worker 启动的任务)
        terminated_locally = False
        if target_id in self.active_steps:
            step = self.active_steps[target_id]
            self.logger.warning(f" 正在强制停止本地任务: {target_id}")
            
            if hasattr(step, 'context'):
                step.context.is_aborted = True
            if hasattr(step, 'runner'):
                step.runner.terminate()
            
            self.active_steps.pop(target_id, None)
            terminated_locally = True
        
        # 3. 跨 Worker 进程斩断：利用 WSL pkill 根据 task_id 路径特征杀进程
        self.logger.warning(f" 正在跨 Worker/WSL 全局清理任务进程: {target_id}")
        try:
            import subprocess
            from .env.wsl_manager import WSLManager
            distro = WSLManager.get_best_distro()
            # pkill -9 -f 会杀死命令行中包含 task_id 的所有进程
            cmd = f"pkill -9 -f {target_id}"
            subprocess.run(["wsl", "-d", distro, "-u", "root", "bash", "-c", cmd], capture_output=True, timeout=5)
        except Exception as e:
            self.logger.error(f"跨进程终止失败: {e}")
            if not terminated_locally:
                return None

        return target_id

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
        if not self.file_handler.validate_fastq_pair(r1_input, r2_input):
            return {"status": "error", "message": "输入文件格式不正确或双端不匹配 (仅支持 .fastq.gz / .fq.gz)"}
            
        if not self.file_handler.check_file_integrity(r1_input) or not self.file_handler.check_file_integrity(r2_input):
            return {"status": "error", "message": "检测到输入压缩文件已损坏 (.gz integrity check failed)"}

        # 自动生成样本 ID
        sample_id = self.file_handler.get_sample_id(r1_input)
        task_id = task_id or f"{sample_id}_{int(_time.time())}"

        # 1. 环境预检
        # 2. 硬件资源评估 (动态线程与 GPU)
        import os
        from src.backend.utils.assembly_db import assembly_db
        
        total_cpus = os.cpu_count() or 4
        default_threads = max(2, total_cpus - 4) if total_cpus > 8 else total_cpus
        
        #  内存探测优化：只执行一次并缓存结果
        if self._cached_total_mem_gb is None:
            import psutil
            total_mem = psutil.virtual_memory().total
            self._cached_total_mem_gb = total_mem / (1024**3)
        total_mem_gb = self._cached_total_mem_gb
        # 如果用户没有显式指定 max_memory，则交由底层步骤基于 ShmManager 动态获取
        # 不再在此处强制设死 max_memory_gb，避免挤占内存盘空间
        
        config = config or {}
        config["sample_type"] = sample_type
        
        threads = config.get("threads") or default_threads
        config["threads"] = threads
        
        #  2.1 初始化数据库记录 (持久化)
        try:
            if not assembly_db.get_task(task_id):
                assembly_db.create_task(
                    task_id, 
                    config.get("name", "New Task"), 
                    sample_id, 
                    sample_type, 
                    config.get("tech", "NGS"),
                    config
                )
        except Exception as e:
            logging.error(f"Failed to record task in DB: {e}")

        gpu_env = self.gpu_manager.get_acceleration_env()
        
        # 3. 初始化上下文与配置 (注入 WSL 标识)
        config["is_wsl"] = self.env_manager.is_wsl
        task_dir = self.results_base / task_id
        
        #  核心修复：支持任务重置 (Reset)，加入 Windows 鲁棒性清理逻辑
        if config.get("reset") and task_dir.exists():
            self.logger.warning(f"正在重置任务 {task_id}，清理旧数据...")
            import shutil
            import time
            from .env.wsl_manager import WSLManager
            
            # 采用 3 次重试 + WSL 强力清理模式
            cleanup_success = False
            for i in range(3):
                try:
                    # 尝试 1: 标准递归删除
                    shutil.rmtree(task_dir)
                    cleanup_success = True
                    break
                except Exception:
                    # 尝试 2: 如果是 Windows 文件锁，尝试利用 WSL 暴力铲除 (通常比 Windows API 更有效)
                    try:
                        import subprocess
                        wsl_path = WSLManager.to_wsl_path(str(task_dir))
                        distro = WSLManager.get_best_distro()
                        subprocess.run(["wsl", "-d", distro, "-u", "root", "rm", "-rf", wsl_path], capture_output=True, timeout=5)
                        if not task_dir.exists():
                            cleanup_success = True
                            break
                    except Exception:
                        pass
                    
                    self.logger.warning(f"文件夹可能被占用，正在进行第 {i+1}/3 次重试...")
                    time.sleep(1.5)
            
            if not cleanup_success:
                self.logger.error(f" 无法清理旧任务目录，请手动关闭打开该目录的文件夹或程序后再重试")
            else:
                task_dir.mkdir(parents=True, exist_ok=True)
                self.logger.info(f" 任务目录 {task_id} 重置成功")
        
        # GPU 加速环境准备 (挂载为内部属性，不进入 ctx.data 序列化)
        ctx = PipelineContext(task_id, task_dir, config)
        ctx.gpu_manager = self.gpu_manager
        ctx.gpu_env = self.gpu_manager.get_acceleration_env()
        
        # 注入 ShmManager (内存盘统一资源管理器)
        if self.env_manager.is_wsl:
            from .core.shm_manager import ShmManager
            from .engine.runner import CommandRunner
            shm_runner = CommandRunner("ShmManager", is_wsl=True)
            ctx.shm = ShmManager(task_id, shm_runner, total_mem_gb)
        
        # 注入初始输入与环境
        ctx.update("r1", Path(r1_input))
        ctx.update("r2", Path(r2_input))
        
        from .steps.phage_annotation import PhageAnnotationStep
        
        # 2. 定义步骤序列 (深度模块化：根据物种类型动态编排)
        from .core.base import BaseAssemblyStep
        pipeline_steps: List[BaseAssemblyStep] = [QualityControlStep(ctx)]
        
        #  获取是否需要提前停止
        stop_early = config.get("params", {}).get("stop_after_assembly", False)

        #  噬菌体专项：插入宿主剔除步骤与专项注释
        if sample_type == "PHAGE":
            pipeline_steps.append(HostCleanerStep(ctx))
            pipeline_steps.append(ReadMergerStep(ctx))
            pipeline_steps.append(AssemblerStep(ctx))
            #  纯化与前噬菌体分离：无论是裂解态（需过滤宿主污染）还是溶源态（需切割找靶），
            # ProphageSeparatorStep 内部的 VIBRANT/VirSorter2 都是必经的过滤漏斗！
            self.logger.info(" 激活噬菌体纯化与分离模块 (PhiSpy/VIBRANT 双路寻靶过滤)")
            pipeline_steps.append(ProphageSeparatorStep(ctx))
            pipeline_steps.append(GapFillerStep(ctx))
            pipeline_steps.append(ScaffoldingStep(ctx))
            if not stop_early:
                pipeline_steps.append(ConsensusCorrectionStep(ctx))
                pipeline_steps.append(PhageAnnotationStep(ctx))
        else:
            pipeline_steps.append(ReadMergerStep(ctx))
            pipeline_steps.append(AssemblerStep(ctx))
            pipeline_steps.append(GapFillerStep(ctx))
            pipeline_steps.append(ScaffoldingStep(ctx))
            if not stop_early:
                pipeline_steps.extend([
                    ConsensusCorrectionStep(ctx),
                    AnnotationStep(ctx)
                ])
        
        logging.info(f"--- [Pipeline Start] Type: {sample_type} | Tasks: {len(pipeline_steps)} | Task: {task_id} ---")
        
        #  1.5 环境自愈预检：确保所有步骤所需的工具和数据库已就绪
        try:
            self._report_progress(task_id, "环境自愈", 0, "running")
            await self._prepare_environment(sample_type, pipeline_steps, config.get("tech", "ILLUMINA"))
        except Exception as e:
            self.logger.warning(f"️ 环境预检/自愈过程中发生异常 (非致命): {e}")

        try:
            for step_index, step in enumerate(pipeline_steps):
                if getattr(ctx, "is_aborted", False):
                    self.logger.warning(" 流水线中止，任务已经被用户打断")
                    break
                    
                # 链路注册：支持外部停止
                self.active_steps[task_id] = step
                step_name = step.__class__.__name__
                
                #  如果已完成，跳过
                if not config.get("reset") and step.is_completed():
                    self.logger.info(f"️ 步骤 {step_name} 已有结果，跳过计算。")
                    overall_p = ((step_index + 1) / len(pipeline_steps)) * 100
                    self._report_progress(task_id, step_name, overall_p, "completed")
                    continue
                
                # 针对 HostCleaner 的参数解析 (保持原有逻辑)
                if step_name == "HostCleanerStep":
                    host_id = config.get("params", {}).get("host_filter_db", "default_ecoli")
                    if host_id and host_id.startswith("ncbi:"):
                        species = host_id.replace("ncbi:", "").strip()
                        resolved_path_str = await self.ncbi_downloader.fetch_reference_genome(species)
                        config["params"]["host_filter_db"] = resolved_path_str if resolved_path_str else None
                    elif host_id:
                        actual_path = self.host_resolver.resolve(host_id)
                        config["params"]["host_filter_db"] = str(actual_path) if actual_path else None

                stage_map = {
                    "QualityControlStep": "数据质控",
                    "HostCleanerStep": "宿主剔除",
                    "ReadMergerStep": "读长合并",
                    "AssemblerStep": "基因组组装",
                    "ProphageSeparatorStep": "前噬菌体分离",
                    "ScaffoldingStep": "支架构建",
                    "GapFillerStep": "局部补洞",
                    "ConsensusCorrectionStep": "一致性校正",
                    "AnnotationStep": "功能注释",
                    "PhageAnnotationStep": "功能注释",
                }
                current_stage = stage_map.get(step_name, step_name)
                
                # 初始步骤进度
                overall_progress = (step_index / len(pipeline_steps)) * 100
                self._report_progress(task_id, current_stage, overall_progress, "running")
                
                # 注入进度感知回调
                def step_progress_callback(p, sub_status=None):
                    current_step_p = overall_progress + (p / len(pipeline_steps))
                    display_stage = f"{current_stage} ({sub_status})" if sub_status else current_stage
                    self._report_progress(task_id, display_stage, current_step_p, "running")

                step.on_progress = step_progress_callback
                
                self.logger.info(f" 正在执行步骤 [{step_index+1}/{len(pipeline_steps)}]: {step_name}")
                start_time = _time.time()
                success = await step.execute()
                duration = _time.time() - start_time
                
                # 遥测记录
                if "telemetry" not in ctx.data: ctx.data["telemetry"] = {"steps": {}}
                ctx.data["telemetry"]["steps"][step_name] = {
                    "duration": round(duration, 2),
                    "status": "success" if success else "failed"
                }

                if not success:
                    self.logger.error(f" 步骤 {step_name} 失败，流水线终止。")
                    self._report_progress(task_id, "FAILED", overall_progress, "failed")
                    assembly_db.finalize_task(task_id, "error", {"failed_step": step_name})
                    return {"status": "failed", "step": step_name, "task_id": task_id}
            
            #  终态垃圾清理 (Global Task Garbage Collection)
            if config.get("auto_clean_intermediates", True):
                self._report_progress(task_id, "资源回收", 99, "running")
                self.logger.info("️ 流水线完结，正在清理测序中段缓存数据以保护物理磁盘空间...")
                try:
                    # 1. 销毁 Fastp 或 HostCleaner 或 ReadMerger 留下的未过滤大块 FASTQ
                    for k in ["clean_r1", "clean_r2", "merged_reads", "unmerged_r1", "unmerged_r2"]:
                        fpath = ctx.get(k)
                        if fpath and Path(fpath).exists():
                            #  严格审计：只删除巨大的测序文件 (.fastq.gz / .fq.gz)
                            # 必须保留小文件（如 .report / .log / .json 等以便回溯分析）
                            p = Path(fpath)
                            if p.suffix in [".gz", ".fastq", ".fq"]:
                                #  保护机制：确保只清理当前任务目录内部产生的临时大文件，且绝不能与原始输入路径冲突
                                if task_dir in p.parents and p.resolve() != Path(r1_input).resolve() and p.resolve() != Path(r2_input).resolve():
                                    p.unlink(missing_ok=True)
                            
                    # 2. 销毁临时深度采样副本
                    sampling_dir = task_dir / "assembly_run" / "sampling"
                    if sampling_dir.exists():
                        import shutil
                        shutil.rmtree(sampling_dir, ignore_errors=True)
                        
                    # 3. 销毁 Fastp 原始过滤产物
                    fastp_dir = task_dir / "fastp_filtered"
                    if fastp_dir.exists():
                        for f in fastp_dir.glob("*.fastq.gz"):
                            f.unlink(missing_ok=True)
                            
                except Exception as gc_e:
                    self.logger.warning(f"全局垃圾回收执行异常 (跳过): {gc_e}")

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
            # 全局资源回收: 通过 ShmManager 清理所有内存盘和临时目录残留
            try:
                if ctx.shm:
                    await ctx.shm.cleanup_all()
                elif self.env_manager.is_wsl:
                    from .engine.runner import CommandRunner
                    cleanup_runner = CommandRunner("ShmCleanup", is_wsl=True)
                    await cleanup_runner.run_command([
                        "bash", "-c",
                        f"find /dev/shm /tmp -maxdepth 1 -name 'asm_{task_id}_*' "
                        f"-exec rm -rf {{}} + 2>/dev/null || true"
                    ], silence_errors=True)
            except Exception as e:
                self.logger.warning(f"️ 资源回收异常: {e}")

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
                "timestamp": _time.time()
            })
            
            # 2. 同步到数据库
            assembly_db.update_task_progress(task_id, step, progress, status)
            
        except Exception as e:
            logging.error(f"进度广播或持久化失败: {e}")

    async def run_bacteria_pipeline(self, *args, **kwargs):
        """兼容性别名：默认运行细菌流水线"""
        return await self.run_pipeline(*args, sample_type="BACTERIA", **kwargs)

    async def _prepare_environment(self, sample_type: str, steps: List[Any], tech: str = "ILLUMINA"):
        """
        深度自愈：检查流水线各步骤的依赖，缺失时自动触发部署脚本
        """
        # 1. 确定测序流水线必须具备的基础工具
        critical_tools = ["fastp", "bwa", "samtools", "minimap2"]

        if sample_type == "PHAGE":
            critical_tools.extend(["polypolish", "checkv"])
            # 前噬菌体分离模式：当提供宿主基因组时追加工具检查
            host_genome = self._get_config_value(steps, "host_genome")
            if host_genome:
                critical_tools.extend(["phispy", "prokka"])
            
        # 2. 差量检查
        missing = [t for t in critical_tools if not self.env_manager.check_tool_installed(t)]
        
        # 3. 检查 NGCS 引擎环境
        ngcs_cli_candidate = Path(r"E:\NGCS\ngcs\cli.py")
        if not ngcs_cli_candidate.exists():
            self.logger.warning(f"注意: 默认 NGCS CLI 路径 ({ngcs_cli_candidate}) 不存在，请确保配置了正确的 ngcs_cli_path。")

        # 4. 检查 Pharokka 数据库 (噬菌体模式独有)
        pharokka_db_ready = (self.project_root / "database" / "pharokka_db").exists()
        
        if missing or (sample_type == "PHAGE" and not pharokka_db_ready):
            self.logger.info(f"发现环境不完整! 缺失工具: {missing}, 准备执行自动化部署自愈程序...")
            
            from .engine.runner import CommandRunner
            runner = CommandRunner("EnvRepair", is_wsl=True)
            
            # 使用项目内置的万能部署脚本
            setup_script = self.project_root / "scripts" / "setup_assembly_env.sh"
            if setup_script.exists():
                # 转换 Windows 路径为 WSL 路径
                from .env.wsl_manager import WSLManager
                wsl_script = WSLManager.to_wsl_path(str(setup_script))
                
                # 提示用户，因为这可能需要几分钟
                self.logger.info("正在运行 scripts/setup_assembly_env.sh，这可能需要约 1-5 分钟，请耐心等待...")
                await runner.run_command(["bash", wsl_script])
                self.logger.info("自动化部署自愈程序执行完毕")
            else:
                self.logger.error("找不到部署脚本 scripts/setup_assembly_env.sh，请检查项目完整性。")
        else:
            self.logger.info("环境工具预检通过")

    def _get_config_value(self, steps: List[Any], key: str) -> Optional[str]:
        """从步骤上下文或全局配置中安全提取参数值"""
        for step in steps:
            if hasattr(step, 'context') and hasattr(step.context, 'config'):
                val = step.context.config.get("params", {}).get(key)
                if val:
                    return val
        return None
