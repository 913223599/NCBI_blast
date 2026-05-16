
import logging
import os
from pathlib import Path
from ..core.base import BaseAssemblyStep

logger = logging.getLogger("Assembly.ConsensusCorrectionStep")

class ConsensusCorrectionStep(BaseAssemblyStep):
    """
    一致性校正步骤 (Consensus Correction / Polishing)
    利用原始 Reads 对组装产物进行碱基纠错 (SNP/Indel 修正)
    目前使用 Polypolish 算法 (针对 Illumina 短读长)
    """
    
    def is_completed(self) -> bool:
        # 如果已经有了 polished 产物，则视为完成
        out_dir = self.get_working_dir()
        polished_fasta = out_dir / "polished_assembly.fasta"
        if polished_fasta.exists() and polished_fasta.stat().st_size > 500:
            # 检查内容是否合法 (非帮助文档)
            try:
                with open(polished_fasta, "r") as f:
                    if f.read(1) == ">":
                        self.context.update("assembly_fasta", polished_fasta)
                        return True
            except:
                pass
        return False

    async def execute(self) -> bool:
        self.status = "running"
        assembly_fasta = self.context.get("assembly_fasta")
        # 1. 严格隔离优先级：未合并纯净双端 > 去宿主双端 > 原始数据
        r1 = self.context.get("unmerged_r1") or self.context.get("clean_r1") or self.context.get("r1")
        r2 = self.context.get("unmerged_r2") or self.context.get("clean_r2") or self.context.get("r2")
        
        is_phage = self.context.config.get("sample_type", "").upper() == "PHAGE"
        if is_phage and r1 == self.context.get("r1") and not self.context.get("clean_r1"):
            self.logger.warning("🚨 [隔离审计预警] 未检测到去宿主环节的 Clean Reads！")
            self.logger.warning("🚨 Polypolish 将使用包含宿主背景的原始数据进行一致性校正。")
            self.logger.warning("🚨 这极可能导致噬菌体高同源区域发生宿主碱基反向突变漂移，请核查后续 SNP！")
        
        if not assembly_fasta or not Path(assembly_fasta).exists():
            logger.warning("未发现原始组装序列，跳过校正步骤")
            return True
            
        tech = (self.context.config.get("tech") or "ILLUMINA").upper()
        # 🔗 默认不对纯二代数据进行额外打磨，除非配置中明确要求或属于混合/三代测序场景
        if tech not in ["NANOPORE", "PACBIO_HIFI"]:
            if not self.context.config.get("params", {}).get("do_polishing", False):
                self.logger.info("✅ 纯二代模式：使用 SPAdes/Unicycler 标准产物。如需 Q50 级精度，请在配置中开启 do_polishing。")
                self.status = "completed"
                return True
            self.logger.info("⚡ 正在通过 Polypolish 对纯二代组装进行超精细校正 (Q50 模式)...")
        from ..env.wsl_manager import WSLManager
        safe_fasta = WSLManager.to_wsl_path(str(assembly_fasta))
        safe_r1 = WSLManager.to_wsl_path(str(r1)) if r1 else None
        safe_r2 = WSLManager.to_wsl_path(str(r2)) if r2 else None
        
        # 🚨 我们明确这是一个纯二代 (Illumina) 短读长平台
        # 故彻底移除与 Nanopore/PacBio 相关的三代 Medaka 分支
        has_short_reads = safe_r1 and safe_r2
        
        polished_result = None
        if has_short_reads:
            self.logger.info("🔬 精修模式：使用 Polypolish (全量短读长进行组装打磨)")
            polished_result = await self._run_polypolish(safe_fasta, safe_r1, safe_r2)
        else:
            self.logger.warning("未检测到有效短读长，无法执行 Polypolish 打磨。")
        
        if polished_result:
            import json
            engine = "Polypolish"
            summary = {
                "status": "ok",
                "tool": engine,
                "description": f"{engine} consensus polishing for short-read assembly",
                "output_file": polished_result.name
            }
            with open(Path(self.get_working_dir()) / "correction_summary.json", "w") as f:
                json.dump(summary, f)

            self.context.update("assembly_fasta", polished_result)
            self.status = "completed"
            return True
        
        logger.warning("一致性校正未成功完成，保留原始组装序列继续后续流程")
        self.status = "completed"
        return True



    async def _run_polypolish(self, safe_fasta: str, safe_r1: str, safe_r2: str):
        """
        Polypolish 短读长精修：将原始 Clean Reads 比对回组装序列
        """
        from ..env.wsl_manager import WSLManager
        
        # 🔗 极速飞升：申请 10GB 左右的内存空间进行密集比对计算
        wsl_tmp_outdir = await self.get_best_wsl_tmp_dir(required_gb=10.0)
        
        # 本地化路径：在内存盘内执行所有密集 IO
        local_fasta = f"{wsl_tmp_outdir}/ref.fasta"
        sam_r1 = f"{wsl_tmp_outdir}/aligned_r1.sam"
        sam_r2 = f"{wsl_tmp_outdir}/aligned_r2.sam"
        filtered_r1 = f"{wsl_tmp_outdir}/filtered_r1.sam"
        filtered_r2 = f"{wsl_tmp_outdir}/filtered_r2.sam"
        local_polished = f"{wsl_tmp_outdir}/polished_assembly.fasta"
        
        win_polished_fasta = Path(self.get_working_dir()) / "polished_assembly.fasta"

        try:
            # 1. 检查工具可用性
            ret_bwa = await self.runner.run_command(["which", "bwa"])
            ret_poly = await self.runner.run_command(["which", "polypolish"])
            if ret_bwa != 0 or ret_poly != 0:
                logger.info("[Polypolish] 未安装配套工具 (bwa/polypolish)，降级跳过精修")
                return None

            if not safe_r1 or not safe_r2:
                return None

            # 准备内存空间
            await self.runner.run_command(["rm", "-rf", wsl_tmp_outdir])
            await self.runner.run_command(["mkdir", "-p", wsl_tmp_outdir])
            
            cpu_count = os.cpu_count() or 8
            threads = str(max(1, cpu_count - 1))
            
            # 🚨 移除了原有的 seqtk 随机抽样！
            # 原因是对于极高同源或长读长的打磨，我们依赖所有的短序列进行全面压制纠错，
            # 随机采样不仅不适合打磨，而且会将靶标覆盖度人为拉低。
            # 直接让 bwa mem 全量跑，抛弃的比对结果也只是计算成本而已。

            # 将参考序列拷贝入内存盘进行本地化索引
            await self.runner.run_command(["cp", safe_fasta, local_fasta])
            
            # Step 1: 建立 BWA 索引
            if self.on_progress: self.on_progress(10, "正在建立内存级靶向序列比对索引...")
            await self.runner.run_command(["bwa", "index", local_fasta])

            # --- 🚀 新增：双路并行比对调度 ---
            if self.on_progress: self.on_progress(30, "正在全核并发执行双向回比对 (R1+R2)...")
            
            # 平分线程数
            total_threads = int(threads)
            p_threads = max(1, total_threads // 2)
            
            from ..engine.runner import CommandRunner
            runner_r1 = CommandRunner(f"{self.__class__.__name__}.R1", is_wsl=True)
            runner_r2 = CommandRunner(f"{self.__class__.__name__}.R2", is_wsl=True)

            cmd1 = ["bash", "-c", f'bwa mem -t {p_threads} -a "{local_fasta}" "{safe_r1}" > "{sam_r1}"']
            cmd2 = ["bash", "-c", f'bwa mem -t {p_threads} -a "{local_fasta}" "{safe_r2}" > "{sam_r2}"']

            import asyncio
            # 同时拉起两个比对进程
            retcodes = await asyncio.gather(
                runner_r1.run_command(cmd1, silence_errors=True),
                runner_r2.run_command(cmd2, silence_errors=True)
            )

            if any(r != 0 for r in retcodes):
                logger.error("并行回比对过程中发生错误")
                return None

            # Step 3: Polypolish 过滤
            if self.on_progress: self.on_progress(70, "正在执行内存级结果过滤...")
            await self.runner.run_command(["polypolish", "filter", "--in1", sam_r1, "--in2", sam_r2, "--out1", filtered_r1, "--out2", filtered_r2])

            # 🔗 关键释放 1：过滤完成后，原始巨型 SAM 已无用，立刻删除释放几十 GB 内存
            self.logger.info("🗑️ 释放中间比对文件 (aligned_r*.sam)...")
            await self.runner.run_command(["rm", "-f", sam_r1, sam_r2])

            # Step 4: 执行精修
            if self.on_progress: self.on_progress(85, "正在合成纠错序列 (Polypolish)...")
            ret_polish = await self.runner.run_command(["bash", "-c", f'polypolish polish "{local_fasta}" "{filtered_r1}" "{filtered_r2}" > "{local_polished}"'])
            
            # 🔗 关键释放 2：精修完成后，过滤后的 SAM 也已无用，立刻删除
            await self.runner.run_command(["rm", "-f", filtered_r1, filtered_r2])

            if ret_polish == 0:
                # 提取唯一产物
                await self.runner.run_command(["cp", "-f", local_polished, WSLManager.to_wsl_path(str(win_polished_fasta))])
                if win_polished_fasta.exists() and win_polished_fasta.stat().st_size > 500:
                    logger.info(f"[Polypolish] 内存级精修成功: {win_polished_fasta.name}")
                    return win_polished_fasta
            
            return None

        except Exception as e:
            logger.warning(f"[Polypolish] 内存精修发生异常: {e}")
            return None
        finally:
            # 🔗 终态回收：确保 wsl_tmp_outdir 文件夹被彻底移除
            self.logger.info(f"♻️ 正在销毁精修临时目录: {wsl_tmp_outdir}")
            if self.context.shm:
                await self.context.shm.release(self.__class__.__name__.lower())
            else:
                await self.runner.run_command(["rm", "-rf", wsl_tmp_outdir])

