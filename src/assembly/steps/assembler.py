
from pathlib import Path
from ..core.base import BaseAssemblyStep

class AssemblerStep(BaseAssemblyStep):
    """
    组装步骤封装: 支持二代 (Unicycler) 与 三代 (Flye) 平台
    """
    def is_completed(self) -> bool:
        # 🔗 兼容性检查：同时支持新旧目录名
        for dir_name in ["assembly_run", "unicycler_run"]:
            out_dir = self.get_working_dir() / dir_name
            assembly_fasta = out_dir / "assembly.fasta"
            if assembly_fasta.exists() and assembly_fasta.stat().st_size > 0:
                self.context.update("assembly_fasta", assembly_fasta)
                stats = self._parse_assembly_stats(assembly_fasta)
                self.context.update("assembly_stats", stats)
                return True
        return False

    async def execute(self) -> bool:
        # ... (断点检查保持不变)
        if self.is_completed():
            self.logger.info("检测到已存在的组装产物，跳过该步骤")
            self.status = "completed"
            if self.on_progress: self.on_progress(100, "已跳过 (发现历史缓存)")
            return True

        self.status = "running"
        
        # 🔗 1. 初始化
        tech = (self.context.config.get("tech") or "ILLUMINA").upper()
        sample_type = (self.context.config.get("sample_type") or "PHAGE").upper()
        threads = str(self.context.config.get("threads", 8))
        max_mem = self.context.config.get("max_memory", 16)
        unicycler_bin = self.context.config.get("unicycler_bin", "unicycler")

        # 💡 路径修复：确保输入路径是 POSIX 格式 (正斜杠)
        r1_raw = self.context.get("clean_r1") or self.context.get("r1")
        r2_raw = self.context.get("clean_r2") or self.context.get("r2")
        r1 = str(r1_raw).replace('\\', '/') if r1_raw else None
        r2 = str(r2_raw).replace('\\', '/') if r2_raw else None
        
        if not r1:
            self.logger.error("未找到有效的输入数据路径")
            self.status = "failed"
            return False

        out_dir = self.get_working_dir() / "assembly_run"
        
        # 💡 路径修复：确保临时目录是 POSIX 格式
        raw_tmp_dir = await self.get_best_wsl_tmp_dir(required_gb=10.0)
        wsl_tmp_outdir = str(raw_tmp_dir).replace('\\', '/')
        
        await self.runner.run_command(["rm", "-rf", wsl_tmp_outdir], is_shell=True)
        await self.runner.run_command(["mkdir", "-p", wsl_tmp_outdir], is_shell=True)

        cmd = []
        handler = None

        # 🔗 2. 技术路线判定
        if tech in ["NANOPORE", "PACBIO_HIFI"]:
            # --- 三代方案 (Flye) ---
            platform_arg = "--nano-raw" if tech == "NANOPORE" else "--pacbio-hifi"
            cmd = [
                "flye", platform_arg, r1, "-o", wsl_tmp_outdir,
                "--threads", threads, "--meta" if sample_type == "PHAGE" else ""
            ]
            def flye_handler(line: str):
                line = line.strip()
                if "Assembling" in line: self.on_progress(30, "Flye: 正在计算重叠图谱...")
                elif "Polishing" in line: self.on_progress(85, "Flye: 正在执行最终打磨...")
            handler = flye_handler

        else:
            # --- 二代方案 (Unicycler) ---
            self.logger.info(f"🧪 [二代链路] 启动 Unicycler 引擎")
            if sample_type == "PHAGE" and r1 and r2:
                # 🧪 300x 智能下采样逻辑 (全面还原)
                e_size = self.context.config.get("estimated_genome_size", 50000)
                target_coverage = self.context.config.get("target_coverage", 300)
                target_reads = max(50000, int((e_size * target_coverage) / (150 * 2)))
                
                self.logger.info(f"🧪 智能采样: 预估基因组={e_size/1000:.0f}kb, 目标覆盖度={target_coverage}x")
                if self.on_progress: self.on_progress(2, "阶段: 执行智能深度采样 (300x)...")
                
                # 🔗 核心修复：手动拼接 Linux 路径，避免 Windows Path 产生反斜杠
                sampling_dir = f"{wsl_tmp_outdir}/sampling"
                await self.runner.run_command(["mkdir", "-p", sampling_dir], is_shell=True)
                r1_s, r2_s = f"{sampling_dir}/S1.fq.gz", f"{sampling_dir}/S2.fq.gz"
                
                await self.runner.run_command([
                    "fastp", "-i", r1, "-I", r2, "-o", r1_s, "-O", r2_s,
                    "--reads_to_process", str(target_reads), "--thread", str(threads)
                ])
                r1, r2 = r1_s, r2_s

            cmd = [
                unicycler_bin, "-1", r1, "-2", r2,
                "-o", wsl_tmp_outdir, "--threads", threads,
                "--spades_options", f"'--memory {max_mem}'"
            ]
            
            def unicycler_detailed_handler(line: str):
                line = line.strip()
                if "Reading reads" in line: self.on_progress(2, "阶段: 处理测序输入...")
                elif "K-mer size" in line:
                    try:
                        k = int(line.split("size")[-1].replace(":", "").strip())
                        p = 10 + int(((k - 21) / (127 - 21)) * 40)
                        self.on_progress(p, f"正在进行 K-mer {k} 组装叠加...")
                    except: pass
                elif "Bridging" in line: self.on_progress(70, "阶段: 正在构建组装路径...")
                elif "Polishing" in line: self.on_progress(85, "阶段: 执行序列自校验 (Pilon)...")
            handler = unicycler_detailed_handler

        try:
            # 🔗 3. 统一命令执行 (单次运行)
            returncode = await self.runner.run_command(
                cmd, 
                on_output=handler,
                is_shell=True
            )
            
            # [GPU 加速预案]
            if self.context.config.get("use_gpu") and returncode == 0:
                self.logger.info("🚀 GPU 加速模块已就绪")

            # 🔗 4. 产物提取与兼容性映射
            if self.on_progress: self.on_progress(95, "阶段: 正在回收最终组装产物...")
            await self.runner.run_command(["mkdir", "-p", str(out_dir)], is_shell=True)
            
            # 文件映射表: [源文件名, 目标文件名]
            file_map = [
                ("assembly.fasta", "assembly.fasta"),
                ("assembly.gfa" if tech == "ILLUMINA" else "assembly_graph.gfa", "assembly.gfa"),
                ("unicycler.log" if tech == "ILLUMINA" else "flye.log", "assembly.log")
            ]
            
            for src_name, dest_name in file_map:
                src = f"{wsl_tmp_outdir}/{src_name}"
                await self.runner.run_command(["cp", "-f", src, f"{str(out_dir)}/{dest_name}"], is_shell=True)

        finally:
            # 🔗 5. 回收物理内存空间
            self.logger.info(f"♻️ 正在执行回收清理: {wsl_tmp_outdir}")
            await self.runner.run_command(["rm", "-rf", wsl_tmp_outdir], is_shell=True)

        if returncode == 0:
            assembly_fasta = out_dir / "assembly.fasta"
            if assembly_fasta.exists() and assembly_fasta.stat().st_size > 0:
                self.context.update("assembly_fasta", assembly_fasta)
                stats = self._parse_assembly_stats(assembly_fasta)
                self.context.update("assembly_stats", stats)
                self.status = "completed"
                return True
        else:
            log_file = out_dir / "assembly.log"
            reason = self._diagnose_failure(log_file)
            self.logger.error(f"组装失败: {reason}")
            if self.on_progress: self.on_progress(0, f"Error: {reason}")
        
        self.status = "failed"
        return False

    def _parse_assembly_stats(self, fasta_path: Path) -> dict:
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
        if not log_path.exists():
            return "原因未知 (未找到日志文件)"
        try:
            content = log_path.read_text(encoding='utf-8', errors='ignore')
            low_depth_keys = ["Insufficient read depth", "too few reads", "no disjointigs assembled", "No sequences to assemble"]
            if any(k.lower() in content.lower() for k in low_depth_keys):
                return "测序深度不足 (无法建立有效的重叠群)"
            if "Out of memory" in content or "bad_alloc" in content:
                return "内存空间不足"
            if "Segfault" in content or "Signal 11" in content:
                return "程序崩溃 (引擎异常)"
            lines = [l.strip() for l in content.splitlines() if l.strip()]
            return "报错摘要: " + " | ".join(lines[-2:])
        except:
            return "日志读取失败"
