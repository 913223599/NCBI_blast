
from pathlib import Path
from ..core.base import BaseAssemblyStep

class AnnotationStep(BaseAssemblyStep):
    """
    注释步骤 (Prokka) 封装
    """
    async def execute(self) -> bool:
        self.status = "running"
        
        fasta = self.context.get("assembly_fasta")
        if not fasta:
             self.status = "failed"
             return False
             
        out_dir = self.get_working_dir() / "prokka_res"
        prokka_bin = self.context.config.get("prokka_bin", "prokka")
        prefix = self.context.config.get("prefix", "ASSEMBLY")
        
        # 🔗 0. 断点检查
        gbk_file = out_dir / f"{prefix}.gbk"
        if gbk_file.exists() and gbk_file.stat().st_size > 0:
            self.logger.info("检测到已存在的注释结果，跳过该步骤 (已恢复)")
            self.context.update("annotation_dir", out_dir)
            self.context.update("gbk_file", gbk_file)
            if self.on_progress: self.on_progress(100, "已跳过 (发现历史缓存)")
            self.status = "completed"
            return True

        sample_type = self.context.config.get("sample_type", "BACTERIA")
        
        # 🔗 0.5. 预处理：简化 Fasta 头部 (Prokka 对带空格的 Header 兼容性较差)
        out_dir.mkdir(parents=True, exist_ok=True)
        simple_fasta = out_dir / "simple_assembly.fasta"
        try:
            with open(fasta, "r") as fin, open(simple_fasta, "w") as fout:
                for line in fin:
                    if line.startswith(">"):
                        # 只保留 ID，去掉 length/depth 等元数据
                        header = line.split()[0]
                        fout.write(f"{header}\n")
                    else:
                        fout.write(line)
            fasta_to_use = str(simple_fasta)
        except Exception as e:
            self.logger.warning(f"无法简化 Fasta 头部: {e}，将尝试使用原始文件")
            fasta_to_use = str(fasta)

        cmd = [
            prokka_bin,
            "--outdir", str(out_dir),
            "--prefix", prefix,
            "--cpus", str(self.context.config.get("threads", 8)),
            "--mincontiglen", "0",
            "--force"
        ]

        # 🔗 逻辑增强：针对噬菌体/病毒进行参数优化
        if sample_type in ["PHAGE", "VIRUS"]:
            cmd.extend(["--kingdom", "Viruses"])
        
        cmd.append(fasta_to_use)
        
        if self.on_progress: self.on_progress(10, "正在进行基因组特征预测 (Prokka)...")

        # 🔗 细粒度进度解析
        def prokka_handler(line: str):
            if "Running: " in line:
                tool = line.split("Running: ")[-1].split()[0]
                tool_map = {
                    "prodigal": (30, "正在预测蛋白质编码基因..."),
                    "aragorn": (50, "正在识别 tRNA/tmRNA..."),
                    "barrnap": (60, "正在搜索核糖体 RNA..."),
                    "minced": (65, "正在检测 CRISPR 阵列..."),
                    "blastp": (75, "正在进行相似性比对..."),
                    "hmmer": (85, "正在检索蛋白质家族 HMM 库..."),
                    "tbl2asn": (95, "正在生成 GenBank 提交文件...")
                }
                if tool in tool_map:
                    p, msg = tool_map[tool]
                    if self.on_progress: self.on_progress(p, msg)

        returncode = await self.runner.run_command(
            cmd, 
            cwd=out_dir.parent,
            env=self.context.get("gpu_env"),
            on_output=prokka_handler
        )
        
        # 🔗 2. 策略：如果是 Code 2 (Prokka 常见启动失败)，尝试自愈并重试一次
        if returncode == 2:
            self.logger.warning("检测到 Prokka 启动失败 (Code 2)，正在尝试执行环境自愈 (--setupdb)...")
            if self.on_progress: self.on_progress(15, "正在初始化数据库并自愈环境...")
            setup_cmd = [prokka_bin, "--setupdb"]
            await self.runner.run_command(setup_cmd, cwd=out_dir.parent)
            
            self.logger.info("自愈完成，正在进行第二次重试...")
            if self.on_progress: self.on_progress(20, "自愈成功，正在重试注释...")
            returncode = await self.runner.run_command(cmd, cwd=out_dir.parent, env=self.context.get("gpu_env"))

        if returncode == 0:
            if gbk_file.exists():
                self.context.update("annotation_dir", out_dir)
                self.context.update("gbk_file", gbk_file)
                self.status = "completed"
                if self.on_progress: self.on_progress(100, "功能注释已完成")
                return True
        else:
            # 🔗 3. 深度诊断
            reason = self._diagnose_failure(out_dir.parent / "annotation.log")
            self.logger.error(f"注释失败: {reason}")
            if self.on_progress: self.on_progress(0, f"失败提示: {reason}")

        self.status = "failed"
        return False

    def _diagnose_failure(self, log_path: Path) -> str:
        """解析 Prokka 失败原因"""
        msg = "逻辑错误或依赖冲突 (Code 2)"
        
        try:
            # 💡 增加常见错误检测
            if "/mnt/" in str(log_path):
                return "WSL 文件权限或 Perl 环境异常，建议切换到系统原生路径"
            return "可能是 tbl2asn 组件过期或输入序列格式不规范，请检查结果文件夹中的 err 文件"
        except:
            return msg
