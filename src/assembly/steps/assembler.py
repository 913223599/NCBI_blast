
from pathlib import Path
from ..core.base import BaseAssemblyStep

class AssemblerStep(BaseAssemblyStep):
    """
    组装步骤 (Unicycler) 封装
    """
    def is_completed(self) -> bool:
        out_dir = self.get_working_dir() / "unicycler_run"
        assembly_fasta = out_dir / "assembly.fasta"
        
        # 🔗 物理校验
        if assembly_fasta.exists() and assembly_fasta.stat().st_size > 0:
            # 🔗 断点续传时也要保持指标完整性
            self.context.update("assembly_fasta", assembly_fasta)
            stats = self._parse_assembly_stats(assembly_fasta)
            self.context.update("assembly_stats", stats)
            return True
        return False

    async def execute(self) -> bool:
        # 🔗 0. 断点检查
        if self.is_completed():
            self.logger.info("检测到已存在的组装产物，跳过该步骤 (已恢复)")
            self.status = "completed"
            if self.on_progress: self.on_progress(100, "已跳过 (发现历史缓存)")
            return True

        self.status = "running"
        
        # 从 Context 自动获取上一步产出的干净数据
        r1 = self.context.get("clean_r1") or self.context.get("r1")
        r2 = self.context.get("clean_r2") or self.context.get("r2")
        
        if not r1 or not r2:
            self.logger.error("未找到有效的输入 Fastq 数据 (clean_r1/r2)")
            self.status = "failed"
            return False
            
        out_dir = self.get_working_dir() / "unicycler_run"
        unicycler_bin = self.context.config.get("unicycler_bin", "unicycler")
        assembly_fasta = out_dir / "assembly.fasta"

        # 🔗 1. 进度解析逻辑 (细粒度汉化)
        def output_handler(line: str):
            if "K-mer size" in line:
                try:
                    k_size = int(line.split("size")[-1].strip())
                    p = min(60, (k_size / 127) * 60)
                    if self.on_progress: self.on_progress(p, f"正在进行 K-mer {k_size} 迭代组装...")
                except: pass
            elif "Starting SPAdes" in line:
                if self.on_progress: self.on_progress(5, "正在启动底层 SPAdes 引擎...")
            elif "Simplifying graph" in line:
                if self.on_progress: self.on_progress(65, "正在简化与平滑组装图谱...")
            elif "Polishing" in line and "iteration" in line:
                try:
                    iter_num = line.split("iteration")[-1].strip().split()[0]
                    if self.on_progress: self.on_progress(70 + int(iter_num)*2, f"正在进行序列校正 (P{iter_num})...")
                except:
                    if self.on_progress: self.on_progress(70, "正在进行序列校正 (Polishing)...")
            elif "Polishing" in line and "finished" in line:
                if self.on_progress: self.on_progress(95, "正在收尾并生成最终基因组文件...")

        max_mem = self.context.config.get("max_memory", 16)
        
        cmd = [
            unicycler_bin,
            "-1", str(r1), "-2", str(r2),
            "-o", str(out_dir),
            "--threads", str(self.context.config.get("threads", 8))
        ]
        
        # 🔗 动态内存控制：通过 SPAdes 后端限制内存
        cmd.extend(["--spades_options", f"--memory {max_mem}"])
        
        # 🔗 2. 命令执行
        returncode = await self.runner.run_command(
            cmd, 
            cwd=out_dir.parent,
            env=self.context.get("gpu_env"),
            on_output=output_handler
        )
        
        if returncode == 0:
            if assembly_fasta.exists():
                self.context.update("assembly_fasta", assembly_fasta)
                # 🔗 后处理：提取组装指标 (成环、长度、深度)
                stats = self._parse_assembly_stats(assembly_fasta)
                self.context.update("assembly_stats", stats)
                
                self.status = "completed"
                return True
        else:
            reason = self._diagnose_failure(out_dir / "unicycler.log")
            self.logger.error(f"组装失败: {reason}")
            if self.on_progress: self.on_progress(0, f"Error: {reason}")
        
        self.status = "failed"
        return False

    def _parse_assembly_stats(self, fasta_path: Path) -> dict:
        """
        解析 Unicycler 产物 Fasta 头部元数据
        示例: >1 length=48325 depth=1.00x circular=true
        """
        stats = {"total_length": 0, "is_circular": False, "avg_depth": 0.0, "contigs": 0}
        try:
            with open(fasta_path, "r") as f:
                for line in f:
                    if line.startswith(">"):
                        stats["contigs"] += 1
                        if "length=" in line:
                            stats["total_length"] += int(line.split("length=")[1].split()[0])
                        if "circular=true" in line:
                            stats["is_circular"] = True
                        if "depth=" in line:
                            depth_str = line.split("depth=")[1].split("x")[0]
                            stats["avg_depth"] = (stats["avg_depth"] + float(depth_str)) / 2 if stats["avg_depth"] > 0 else float(depth_str)
            return stats
        except Exception as e:
            self.logger.error(f"无法解析组装指标: {e}")
            return stats

    def _diagnose_failure(self, log_path: Path) -> str:
        """通过解析日志给出直观的失败原因"""
        if not log_path.exists():
            return "原因未知 (未找到日志文件)"
        
        try:
            content = log_path.read_text(encoding='utf-8', errors='ignore')
            if "Insufficient read depth" in content or "too few reads" in content.lower():
                return "测序深度不足"
            if "Out of memory" in content or "bad_alloc" in content:
                return "内存空间不足"
            if "Segfault" in content or "Signal 11" in content:
                return "程序崩溃"
            if "not found" in content and "spades" in content:
                return "内部依赖缺失"
            lines = [l.strip() for l in content.splitlines() if l.strip()]
            return "具体错误: " + " | ".join(lines[-3:])
        except:
            return "日志读取失败"
