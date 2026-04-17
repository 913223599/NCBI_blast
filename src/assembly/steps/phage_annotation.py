
import os
import shutil
from pathlib import Path
from ..core.base import BaseAssemblyStep

class PhageAnnotationStep(BaseAssemblyStep):
    """
    噬菌体专项注释步骤 (基于 Pharokka)
    集成 PHROGs 数据库进行深度功能解析
    """
    async def execute(self) -> bool:
        self.status = "running"
        
        fasta = self.context.get("assembly_fasta")
        if not fasta:
             self.status = "failed"
             return False
             
        out_dir = self.get_working_dir() / "pharokka_res"
        pharokka_bin = self.context.config.get("pharokka_bin", "pharokka")
        db_dir = self.context.config.get("pharokka_db", "/opt/pharokka_db") # 默认路径
        prefix = self.context.config.get("prefix", "PHAGE_ANNOTATION")
        threads = str(self.context.config.get("threads", 8))
        
        # 🔗 0. 断点检查
        gbk_file = out_dir / f"{prefix}.gbk"
        if gbk_file.exists() and gbk_file.stat().st_size > 0:
            self.logger.info("检测到已存在的 Pharokka 注释结果，跳过该步骤")
            self.context.update("annotation_dir", out_dir)
            self.context.update("gbk_file", gbk_file)
            if self.on_progress: self.on_progress(100, "已跳过 (发现历史缓存)")
            self.status = "completed"
            return True

        # 🔗 1. 环境自检：检查 pharokka 是否安装及数据库是否存在
        if not await self._check_environment(pharokka_bin, db_dir):
            self.logger.warning("⚠️ 本地 Pharokka 环境不完整，将尝试使用 Prokka (Phage Mode) 兜底")
            return await self._fallback_to_prokka(fasta, out_dir.parent / "prokka_fallback")

        out_dir.mkdir(parents=True, exist_ok=True)
        
        # 🔗 2. 执行 Pharokka 主管线
        # 命令格式: pharokka.py -i <input.fasta> -o <out_dir> -d <db_dir> -t <threads> -p <prefix>
        cmd = [
            pharokka_bin,
            "-i", str(fasta),
            "-o", str(out_dir),
            "-d", str(db_dir),
            "-t", threads,
            "-p", prefix,
            "-f" # 强制覆盖
        ]

        if self.on_progress: self.on_progress(20, "正在进行噬菌体特征预测 (Pharokka)...")

        # 进度解析过滤器
        def pharokka_handler(line: str):
            if "Predicting genes" in line:
                if self.on_progress: self.on_progress(30, "正在预测蛋白质编码基因 (Prodigal-gv)...")
            elif "Functional annotation" in line:
                if self.on_progress: self.on_progress(60, "正在深度检索 PHROGs 功能数据库...")
            elif "tRNA" in line:
                if self.on_progress: self.on_progress(80, "正在解析 tRNA / tmRNA...")
            elif "Finalizing" in line:
                if self.on_progress: self.on_progress(95, "正在生成 GenBank 与功能摘要...")

        returncode = await self.runner.run_command(
            cmd, 
            cwd=out_dir.parent,
            env=self.context.get("gpu_env"),
            on_output=pharokka_handler
        )

        if returncode == 0 and gbk_file.exists():
            self.context.update("annotation_dir", out_dir)
            self.context.update("gbk_file", gbk_file)
            
            # 🔗 3. 结果入库与增强报告解析
            summary_file = out_dir / f"{prefix}_summary.txt"
            if summary_file.exists():
                summary_data = self._parse_summary(summary_file)
                self.context.update("annotation_summary", summary_data)

            self.status = "completed"
            if self.on_progress: self.on_progress(100, "噬菌体深度注释完成")
            return True

        self.status = "failed"
        return False

    async def _check_environment(self, bin_name: str, db_path: str) -> bool:
        """检查工具和数据库是否就绪"""
        # 1. 检查二进制文件 (支持 WSL 映射)
        check_cmd = ["which", bin_name]
        ret = await self.runner.run_command(check_cmd)
        if ret != 0: 
            return False
            
        # 2. 检查数据库目录是否存在
        # 注意：这里需要考虑 WSL 路径映射，如果 db_path 在 WSL 内部，外部访问可能受阻
        # 我们假设数据库安装在 WSL 系统内部路径
        check_db_cmd = ["test", "-d", db_path]
        ret_db = await self.runner.run_command(check_db_cmd)
        return ret_db == 0

    async def _fallback_to_prokka(self, fasta: Path, out_dir: Path) -> bool:
        """兜底逻辑：调用 Prokka 并启用病毒模式"""
        from .annotation import AnnotationStep
        self.logger.info("执行 Prokka 兜底注释流程...")
        fallback_step = AnnotationStep(self.context)
        # 修改上下文让 fallback 步骤输出到指定目录
        self.context.config["prokka_out_override"] = str(out_dir) 
        return await fallback_step.execute()

    def _parse_summary(self, path: Path) -> dict:
        """解析 Pharokka 摘要文件"""
        res = {"total_cds": 0, "functional_assigned": 0}
        try:
            with open(path, "r") as f:
                for line in f:
                    if "Total CDS" in line:
                        res["total_cds"] = int(line.split(":")[-1].strip())
                    elif "Assigned function" in line:
                        res["functional_assigned"] = int(line.split(":")[-1].strip())
        except:
            pass
        return res
