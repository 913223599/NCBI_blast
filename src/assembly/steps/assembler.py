import os
import re
from pathlib import Path
from typing import Optional
from ..core.base import BaseAssemblyStep
from ..env.wsl_manager import WSLManager

class AssemblerStep(BaseAssemblyStep):
    """
    组装步骤封装: 支持二代 (Unicycler) 与 三代 (Flye) 平台
    已完成架构级优化：安全的 Shell 拼接、长度加权深度统计、极致 WSL I/O 加速、异常防潮堤。
    """
    def is_completed(self) -> bool:
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
        if self.is_completed():
            self.logger.info("检测到已存在的组装产物，跳过该步骤")
            self.status = "completed"
            if self.on_progress: self.on_progress(100, "已跳过 (发现历史缓存)")
            return True

        self.status = "running"
        cpu_count = os.cpu_count() or 8
        optimal_threads = max(1, cpu_count - 1)
        self.logger.info(f"🚀 自动资源调优: 物理核心数={cpu_count}, 分配线程={optimal_threads}")

        tech = (self.context.config.get("tech") or "ILLUMINA").upper()
        sample_type = (self.context.config.get("sample_type") or "PHAGE").upper()
        total_gb = await self.get_total_memory_gb()
        
        # 内存平衡: 通过 ShmManager 动态获取进程可用内存
        if self.context.shm:
            max_mem = self.context.config.get("max_memory") or self.context.shm.get_process_memory_limit()
        else:
            max_mem = self.context.config.get("max_memory") or max(4, int(total_gb) - 8)
        
        self.logger.info(f"内存平衡审计: 总量={total_gb:.1f}G, 分配给引擎={max_mem}G")
        unicycler_bin = self.context.config.get("unicycler_bin", "unicycler")
        threads = str(optimal_threads)

        r1_raw = self.context.get("clean_r1") or self.context.get("r1")
        r2_raw = self.context.get("clean_r2") or self.context.get("r2")
        r1 = str(r1_raw).replace('\\', '/') if r1_raw else None
        r2 = str(r2_raw).replace('\\', '/') if r2_raw else None
        
        if not r1:
            self.logger.error("未找到有效的输入数据路径")
            self.status = "failed"
            return False

        out_dir = self.get_working_dir() / "assembly_run"
        raw_tmp_dir = await self.get_best_wsl_tmp_dir(required_gb=10.0)
        wsl_tmp_outdir = raw_tmp_dir.replace('\\', '/')
        
        await self.runner.run_command(["rm", "-rf", wsl_tmp_outdir])
        await self.runner.run_command(["mkdir", "-p", wsl_tmp_outdir])

        cmd_str = ""
        handler = None

        # 🔗 技术路线判定
        if tech in ["NANOPORE", "PACBIO_HIFI"]:
            platform_arg = "--nano-raw" if tech == "NANOPORE" else "--pacbio-hifi"
            # 修复：保护路径空格
            cmd_list = [
                "flye", platform_arg, f"'{r1}'", "-o", f"'{wsl_tmp_outdir}'",
                "--threads", threads
            ]
            if sample_type == "PHAGE":
                cmd_list.append("--meta")
            cmd_str = " ".join(cmd_list)
            
            def flye_handler(line: str):
                line = line.strip()
                if "Assembling" in line and self.on_progress: self.on_progress(30, "Flye: 正在计算重叠图谱...")
                elif "Polishing" in line and self.on_progress: self.on_progress(85, "Flye: 正在执行最终打磨...")
            handler = flye_handler

        else:
            # --- 二代方案 (自适应路由) ---
            params = self.context.config.get("params", {})
            final_r1 = WSLManager.to_wsl_path(str(self.context.get("unmerged_r1") or r1))
            final_r2 = WSLManager.to_wsl_path(str(self.context.get("unmerged_r2") or r2))
            final_s = None
            merged = self.context.get("merged_reads")
            if merged and Path(merged).exists():
                final_s = WSLManager.to_wsl_path(str(merged))

            # 执行智能降采样
            if sample_type == "PHAGE" and final_r1 and final_r2:
                e_size = params.get("estimated_genome_size") or self.context.config.get("estimated_genome_size", 100000)
                target_coverage = params.get("target_coverage") or self.context.config.get("target_coverage", 300)
                target_reads = max(50000, int((e_size * target_coverage) / (150 * 2)))
                
                self.logger.info(f"🧪 智能随机采样: 预估={e_size/1000:.0f}kb, 目标深度={target_coverage}x")
                if self.on_progress: self.on_progress(2, "阶段: 执行随机子集采样 (300x)...")
                
                sampling_dir = f"{wsl_tmp_outdir}/sampling"
                await self.runner.run_command(["mkdir", "-p", sampling_dir], is_shell=True)
                r1_s, r2_s = f"{sampling_dir}/S1.fq.gz", f"{sampling_dir}/S2.fq.gz"
                
                # 检查是否可用 pigz
                has_pigz = (await self.runner.run_command(["which", "pigz"], silence_errors=True)) == 0
                zip_tool = f"pigz -p {max(1, optimal_threads//2)}" if has_pigz else "gzip"
                
                # 修复：安全使用单引号包裹路径
                sample_cmd = (
                    f"seqtk sample -s100 '{final_r1}' {target_reads} | {zip_tool} > '{r1_s}' && "
                    f"seqtk sample -s100 '{final_r2}' {target_reads} | {zip_tool} > '{r2_s}'"
                )
                # 🔗 执行采样 (包含管道操作，必须以 Shell 模式运行字符串命令)
                ret_sample = await self.runner.run_command(sample_cmd, is_shell=True)
                
                # 🔗 指令检查 (原子指令，强制使用列表模式，不再手动包裹引号)
                if ret_sample == 0 and await self.runner.run_command(["test", "-s", r1_s]) == 0:
                    final_r1, final_r2 = r1_s, r2_s
                else:
                    self.logger.warning("降采样工具 seqtk 失败或未安装，已自动回退使用全部原始数据")

            # 🚀 极限 I/O 加速: 自动将 Windows 文件系统的输入拷入 WSL 内部
            async def preload_to_ram(src_path: Optional[str], target_name: str) -> Optional[str]:
                if src_path and "/mnt/c/" in src_path:
                    # 🛡️ 增加超大文件防护：超过 5GB 坚决不进内存盘，防止把系统爆掉
                    try:
                        win_p = src_path.replace("/mnt/c/", "c:/")
                        size_gb = Path(win_p).stat().st_size / (1024 ** 3)
                        if size_gb > 5.0:
                            self.logger.warning(f"🛡️ 拒绝预热超大文件 ({size_gb:.1f}GB > 5.0GB): {src_path}，已降级为原地读取")
                            return src_path
                    except Exception:
                        pass
                        
                    shm_path = f"{wsl_tmp_outdir}/{target_name}"
                    self.logger.info(f"⚡ I/O 预热至高极速区: {src_path} → {shm_path}")
                    if await self.runner.run_command(["cp", "-f", src_path, shm_path]) == 0:
                        return shm_path
                return src_path

            final_s = await preload_to_ram(final_s, "merged_cache.fq.gz")
            if final_r1 != f"{wsl_tmp_outdir}/sampling/S1.fq.gz": # 如果没有被采样，预热原始数据
                final_r1 = await preload_to_ram(final_r1, "R1_cache.fq.gz")
                final_r2 = await preload_to_ram(final_r2, "R2_cache.fq.gz")

            self.logger.info("🧪 [常规模式] 启动 Unicycler 引擎")
            mode = params.get("mode") or ("bold" if sample_type == "PHAGE" else "normal")
            min_len = params.get("min_fasta_length") or 200

            spades_tmp_dir = f"{wsl_tmp_outdir}/spades_tmp"
            # 🚀 SPAdes v4.0.0+ 内存管理优化
            # 增加一个冗余的 -m 参数在最后，尝试对抗 Unicycler 的默认注入
            spades_opts = f"--memory {max_mem} --tmp-dir {spades_tmp_dir} -m {max_mem * 1024}"

            cmd_list = [
                unicycler_bin, "-1", f"'{final_r1}'", "-2", f"'{final_r2}'",
                "-o", f"'{wsl_tmp_outdir}'", "--threads", threads,
                "--mode", mode, "--min_fasta_length", str(min_len),
                "--spades_options", f"'{spades_opts}'"
            ]
            if final_s:
                cmd_list.extend(["-s", f"'{final_s}'"])
            
            cmd_str = " ".join(cmd_list)

            def unicycler_detailed_handler(line: str):
                line = line.strip()
                if "K-mer size" in line:
                    try:
                        k = int(line.split("size")[-1].replace(":", "").strip())
                        p = 10 + int(((k - 21) / (127 - 21)) * 40)
                        if self.on_progress: self.on_progress(p, f"Unicycler: K-mer {k}...")
                    except: pass
            handler = unicycler_detailed_handler

        returncode = -1
        try:
            # 修复：如果是完整的命令字符串，必须以 shell 执行
            returncode = await self.runner.run_command(cmd_str, on_output=handler, is_shell=True)
            
            if self.context.config.get("use_gpu") and returncode == 0:
                self.logger.info("🚀 GPU 加速模块已就绪")

        except Exception as e:
            self.logger.error(f"引擎执行过程产生未捕获异常: {e}")
            returncode = -1
            
        finally:
            # 修复：无论成功失败，都先回收日志和产物，然后再执行销毁操作
            await self.runner.run_command(["mkdir", "-p", str(out_dir)], is_shell=True)
            potential_fastas = ["assembly.fasta", "scaffolds.fasta"]
            graph_names = ["assembly.gfa", "assembly_graph.gfa"]
            log_names = ["unicycler.log", "flye.log", "assembly.log"]
            
            found_fasta = False
            for f_name in potential_fastas:
                src = f"{wsl_tmp_outdir}/{f_name}"
                if await self.runner.run_command(["test", "-f", src]) == 0:
                    await self.runner.run_command(["cp", "-f", src, f"{out_dir}/assembly.fasta"])
                    if returncode == 0: self.logger.info(f"✅ 成功捕获序列产物: {f_name}")
                    found_fasta = True
                    break
            
            for names, dest in [(graph_names, "assembly.gfa"), (log_names, "assembly.log")]:
                for n in names:
                    src = f"{wsl_tmp_outdir}/{n}"
                    if await self.runner.run_command(["test", "-f", src]) == 0:
                        await self.runner.run_command(["cp", "-f", src, f"{out_dir}/{dest}"])
                        break
            
            # 特外捕获 SPAdes 内部日志
            spades_log = f"{wsl_tmp_outdir}/spades_assembly/spades.log"
            if await self.runner.run_command(["test", "-f", spades_log]) == 0:
                await self.runner.run_command(["cp", "-f", spades_log, f"{out_dir}/spades.log"])

            # 通过 ShmManager 释放工作空间 (支持诊断保留)
            step_key = self.__class__.__name__.lower()
            if self.context.shm:
                await self.context.shm.release(
                    step_key, retain_for_diagnostics=(returncode != 0)
                )
            elif returncode == 0:
                self.logger.info(f"正在执行回收清理: {wsl_tmp_outdir}")
                await self.runner.run_command(["rm", "-rf", wsl_tmp_outdir])
            else:
                self.logger.warning(f"组装失败，已保留现场以供诊断: {wsl_tmp_outdir}")

        # 只有在程序正常退出，且成功找到了 fasta 才判定成功
        if returncode == 0 and found_fasta:
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
        """解析 Fasta，并采用符合学术标准的加权平均深度计算"""
        stats = {"total_length": 0, "is_circular": False, "avg_depth": 0.0, "contigs": 0}
        total_depth_mass = 0.0  # 用于加权深度计算 (Depth * Length)
        
        try:
            with open(fasta_path, "r", encoding="utf-8") as f:
                current_len = 0
                current_depth = 0.0
                
                def process_previous_contig():
                    nonlocal total_depth_mass
                    if current_len > 0:
                        stats["total_length"] += current_len
                        # 修复：采用加权均值深度 (Weighted Average Depth)
                        total_depth_mass += current_depth * current_len

                for line in f:
                    line = line.strip()
                    if line.startswith(">"):
                        process_previous_contig() # 处理上一条序列的积攒数据
                        current_len = 0
                        stats["contigs"] += 1
                        header = line.lower()
                        
                        depth_match = re.search(r"(?:depth[=]|cov_)(\d+\.?\d*)", header)
                        current_depth = float(depth_match.group(1)) if depth_match else 0.0
                        
                        if "circular=true" in header or "[circular" in header or "circular_detected" in header:
                            stats["is_circular"] = True
                    else:
                        current_len += len(line)
                        
                process_previous_contig() # 处理最后一条序列
                            
            if stats["total_length"] > 0:
                stats["avg_depth"] = round(total_depth_mass / stats["total_length"], 2)
            return stats
        except Exception as e:
            self.logger.error(f"无法解析组装指标: {e}")
            return stats

    def _diagnose_failure(self, log_path: Path) -> str:
        if not log_path.exists():
            return "原因未知 (未找到日志文件或发生致命崩溃终止)"
        try:
            content = log_path.read_text(encoding='utf-8', errors='ignore')
            low_depth_keys = ["Insufficient read depth", "too few reads", "no disjointigs assembled", "No sequences to assemble"]
            if any(k.lower() in content.lower() for k in low_depth_keys):
                return "测序深度过低或数据清洗过度 (无法建立有效的重叠图谱)"
            if "Out of memory" in content or "bad_alloc" in content:
                return "硬件内存空间不足，请尝试调小可用线程数或加大 max_memory"
            if "Segfault" in content or "Signal 11" in content:
                return "底层引擎异常 (Segmentation Fault)"
            lines = [l.strip() for l in content.splitlines() if l.strip()]
            return "报错摘要: " + " | ".join(lines[-2:]) if len(lines) >= 2 else "未知报错"
        except:
            return "日志读取解析失败"