import os
import logging
from pathlib import Path
from ..core.base import BaseAssemblyStep
from ..env.wsl_manager import WSLManager

logger = logging.getLogger("Assembly.QualityControl")

class QualityControlStep(BaseAssemblyStep):
    """
    质控步骤 (Fastp) 封装
    已优化：WSL 路径兼容、单/双端自适应、三代长读长自动放行、异常防潮堤。
    """
    def is_completed(self) -> bool:
        out_dir = self.get_working_dir()
        clean_r1 = out_dir / f"{self.context.task_id}_R1.clean.fq.gz"
        clean_r2 = out_dir / f"{self.context.task_id}_R2.clean.fq.gz"
        
        r2 = self.context.get("r2")
        
        #  物理校验：根据单/双端差异化验证文件存在且体积大于 10KB
        if r2:
            if clean_r1.exists() and clean_r2.exists():
                if clean_r1.stat().st_size > 10240 and clean_r2.stat().st_size > 10240:
                    self.context.update("clean_r1", clean_r1)
                    self.context.update("clean_r2", clean_r2)
                    return True
        else:
            if clean_r1.exists() and clean_r1.stat().st_size > 10240:
                self.context.update("clean_r1", clean_r1)
                return True
                
        return False

    async def execute(self) -> bool:
        #  0. 如果已完成，则直接跳过
        if self.is_completed():
            self.status = "completed"
            if self.on_progress: self.on_progress(100.0, "已跳过 (发现历史缓存)")
            return True

        self.status = "running"
        
        # 1. 获取输入输出
        r1 = self.context.get("r1")
        r2 = self.context.get("r2")
        
        if not r1:
            self.logger.error("未发现有效的测序数据 (r1)，质控中止")
            self.status = "failed"
            return False

        #  架构与学术修复: 长读长兼容性 (Nanopore/PacBio 禁走 Fastp)
        tech = (self.context.config.get("tech") or "ILLUMINA").upper()
        if tech in ["NANOPORE", "PACBIO_HIFI"]:
            self.logger.info(f"️ 检测到长读长平台 ({tech})，默认 Fastp 短读长质控不适用，自动放行原始数据")
            self.context.update("clean_r1", r1)
            if r2: self.context.update("clean_r2", r2)
            self.status = "completed"
            if self.on_progress: self.on_progress(100.0, "长读长数据自动放行")
            return True

        out_dir = self.get_working_dir()
        out_dir.mkdir(parents=True, exist_ok=True)
        
        clean_r1 = out_dir / f"{self.context.task_id}_R1.clean.fq.gz"
        clean_r2 = out_dir / f"{self.context.task_id}_R2.clean.fq.gz"
        fastp_json = out_dir / "fastp_report.json"
        fastp_html = out_dir / "fastp_report.html"
        
        fastp_bin = self.context.config.get("fastp_bin", "fastp")
        
        #  进度解析 (fastp 实时反馈)
        def output_handler(line: str):
            if "processed" in line and ":" in line:
                try:
                    processed_str = line.split(":")[-1].replace(",", "").strip()
                    processed = int(processed_str)
                    p = min(99, (processed / 5000000) * 100)
                    m_reads = round(processed / 1000000, 1)
                    if self.on_progress: self.on_progress(p, f"已处理: {m_reads}M 条序列")
                except: pass

        #  核心计算资源分配优化
        cpu_count = os.cpu_count() or 8
        optimal_threads = max(1, cpu_count - 1)
        fastp_threads = str(min(optimal_threads, 16))
        self.logger.info(f" 自动资源调优: 物理核心数={cpu_count}, 分配 Fastp 线程={fastp_threads}")

        #  核心修复：WSL 跨系统路径兼容
        wsl_r1 = WSLManager.to_wsl_path(str(r1))
        wsl_out_r1 = WSLManager.to_wsl_path(str(clean_r1))
        wsl_json = WSLManager.to_wsl_path(str(fastp_json))
        wsl_html = WSLManager.to_wsl_path(str(fastp_html))

        #  核心修复：动态适配单端/双端测序数据
        cmd = [
            fastp_bin,
            "-i", wsl_r1,
            "-o", wsl_out_r1,
            "--json", wsl_json,
            "--html", wsl_html,
            "--thread", fastp_threads
        ]

        if r2:
            self.logger.info("检测为双端测序 (Paired-End) 数据")
            wsl_r2 = WSLManager.to_wsl_path(str(r2))
            wsl_out_r2 = WSLManager.to_wsl_path(str(clean_r2))
            cmd.extend([
                "-I", wsl_r2,
                "-O", wsl_out_r2,
                "--detect_adapter_for_pe", 
                "--correction"
            ])
        else:
            self.logger.info("检测为单端测序 (Single-End) 数据")

        if self.on_progress: self.on_progress(5, "正在启动过滤引擎...")
        
        try:
            # 安全获取环境变量
            gpu_env = getattr(self.context, "gpu_env", None) or self.context.get("gpu_env")
            
            # 3. 使用 Runner 执行，并使用正确的 WSL 工作目录
            returncode = await self.runner.run_command(
                cmd, 
                cwd=WSLManager.to_wsl_path(str(out_dir)), 
                env=gpu_env,
                on_output=output_handler
            )
            
            if returncode == 0:
                self.context.update("clean_r1", clean_r1)
                if r2: self.context.update("clean_r2", clean_r2)
                self.status = "completed"
                if self.on_progress: self.on_progress(100, "质控完成")
                return True
            else:
                self.logger.error(f"Fastp 执行失败，进程退出码: {returncode}")
                
        except Exception as e:
            self.logger.error(f"质控过程发生未捕获异常: {e}")

        self.status = "failed"
        return False