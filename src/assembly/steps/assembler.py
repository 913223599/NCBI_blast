
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
        
        # [TODO: Hybrid Assembly] 后续版本需增加对长读长 (Nanopore/PacBio) 的支持
        # if self.context.get("long_reads"): ...
        
        if not r1 or not r2:
            self.logger.error("未找到有效的输入 Fastq 数据 (clean_r1/r2)")
            self.status = "failed"
            return False
            
        out_dir = self.get_working_dir() / "unicycler_run"
        unicycler_bin = self.context.config.get("unicycler_bin", "unicycler")
        assembly_fasta = out_dir / "assembly.fasta"

        # 🔗 1. 进度解析逻辑 (细粒度汉化)
        def output_handler(line: str):
            line = line.strip()
            if not line: return
            
            # --- 阶段解析 ---
            if "Reading reads" in line:
                if self.on_progress: self.on_progress(2, "阶段: 正在读取测序数据...")
            elif "Starting SPAdes" in line:
                if self.on_progress: self.on_progress(5, "阶段: 启动 SPAdes 组装引擎...")
            elif "K-mer size" in line:
                try:
                    # K-mer 迭代通常占组装时间的 60%
                    k_size = int(line.split("size")[-1].replace(":", "").strip())
                    # 映射 K-mer (21~127) 到进度 (10% ~ 50%)
                    p = 10 + int(((k_size - 21) / (127 - 21)) * 40)
                    if self.on_progress: self.on_progress(p, f"正在进行 K-mer {k_size} 迭代组装...")
                except: pass
            elif "Finding overlap" in line:
                if self.on_progress: self.on_progress(55, "阶段: 正在寻找序列重叠...")
            elif "Bridging" in line:
                if self.on_progress: self.on_progress(60, "阶段: 正在构建组装桥接路径...")
            elif "Simplifying graph" in line:
                if self.on_progress: self.on_progress(65, "阶段: 正在优化与简化组装图谱...")
            elif "Polishing" in line and "iteration" in line:
                try:
                    # Unicycler 内部校正通常在 70-80% 之间
                    iter_num = line.split("iteration")[-1].strip().split()[0]
                    p = 70 + int(iter_num)
                    if self.on_progress: self.on_progress(min(79, p), f"正在进行序列自校正 (P{iter_num})...")
                except:
                    if self.on_progress: self.on_progress(70, "正在进行序列自校正 (Polishing)...")
            elif "Polishing" in line and "finished" in line:
                if self.on_progress: self.on_progress(100, "组装完成 (Unicycler)")

        max_mem = self.context.config.get("max_memory", 16)
        
        # 🔗 噬菌体专项优化：智能动态深度采样 (Adaptive Downsampling)
        # 根据预估基因组大小 × 目标覆盖度自动计算最优 Read 数，避免过高/过低覆盖
        if self.context.config.get("sample_type") == "PHAGE":
            sampling_dir = out_dir / "sampling"
            sampling_dir.mkdir(parents=True, exist_ok=True)
            sampled_r1 = sampling_dir / "sampled_R1.fq.gz"
            sampled_r2 = sampling_dir / "sampled_R2.fq.gz"
            
            # 自适应覆盖度计算
            estimated_genome_size = self.context.config.get("estimated_genome_size", 50000)  # 默认 50kb
            target_coverage = self.context.config.get("target_coverage", 300)  # 精度模式: 300x
            avg_read_length = 150  # Illumina 典型长度
            # 公式: target_reads(pairs) = (genome_size × coverage) / (read_length × 2)
            target_reads = max(50000, int((estimated_genome_size * target_coverage) / (avg_read_length * 2)))
            
            self.logger.info(f"🧪 智能采样: 预估基因组={estimated_genome_size/1000:.0f}kb, "
                             f"目标覆盖度={target_coverage}x, 采样={target_reads:,} read-pairs")
            
            if self.on_progress: self.on_progress(1, "正在进行智能深度采样 (Downsampling)...")
            fastp_cmd = [
                "fastp", "-i", str(r1), "-I", str(r2),
                "-o", str(sampled_r1), "-O", str(sampled_r2),
                "--reads_to_process", str(target_reads), "--thread", str(self.context.config.get("threads", 4))
            ]
            
            await self.runner.run_command(fastp_cmd)
            # 切换后续拼接输入为采样后的数据
            r1, r2 = sampled_r1, sampled_r2
            
        # 🔗 极速飞升模式：利用基类智能决策系统 (优先内存盘)
        wsl_tmp_outdir = await self.get_best_wsl_tmp_dir(required_gb=5.0)
        
        # 🔗 动态内存控制：通过 SPAdes 后端参数传递
        spades_opts = [f"--memory {max_mem}"]
        self.logger.info(f"🚀 SPAdes 引擎内存限制已设置为: {max_mem}GB")
        
        # 清除可能残留的旧缓存并建立目标
        await self.runner.run_command(["rm", "-rf", wsl_tmp_outdir], is_shell=True)
        
        cmd = [
            unicycler_bin,
            "-1", str(r1), "-2", str(r2),
            "-o", wsl_tmp_outdir,
            "--threads", str(self.context.config.get("threads", 8)),
            "--spades_options", " ".join(spades_opts)
        ]
        
        try:
            # 🔗 2. 命令执行
            returncode = await self.runner.run_command(
                cmd, 
                cwd=out_dir.parent,
                env=self.context.gpu_env,
                on_output=output_handler,
                is_shell=True
            )
            
            # 无论成功失败，都将关键的结果和诊断日志搬回 F 盘主目录，放弃几十万个无用的中间碎片
            if self.on_progress: self.on_progress(95, "正在提取最终产物与组装日志...")
            # 确保 F 盘目录存在
            await self.runner.run_command(["mkdir", "-p", str(out_dir)], is_shell=True)
            # 挑选核心文件安全跨境
            for extract_file in ["assembly.fasta", "assembly.gfa", "unicycler.log"]:
                src = f"{wsl_tmp_outdir}/{extract_file}"
                await self.runner.run_command(["cp", "-f", src, f"{str(out_dir)}/"], is_shell=True)

        finally:
            # 🔗 终极回收机制：不论代码是否抛出异常，强制物理销毁内存临时空间，释放系统 RAM
            self.logger.info(f"♻️ 正在执行内存回收: 清理 {wsl_tmp_outdir}")
            await self.runner.run_command(["rm", "-rf", wsl_tmp_outdir], is_shell=True)

        if returncode == 0:
            if assembly_fasta.exists() and assembly_fasta.stat().st_size > 0:
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
