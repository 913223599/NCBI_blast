
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
        r1 = self.context.get("clean_r1") or self.context.get("r1")
        r2 = self.context.get("clean_r2") or self.context.get("r2")
        
        if not assembly_fasta or not Path(assembly_fasta).exists():
            logger.warning("未发现原始组装序列，跳过校正步骤")
            return True

        # 🔗 利用标准 WSLManager 进行路径转换 (自动处理软链接映射)
        from ..env.wsl_manager import WSLManager
        safe_fasta = WSLManager.to_wsl_path(str(assembly_fasta))
        safe_r1 = WSLManager.to_wsl_path(str(r1)) if r1 else None
        safe_r2 = WSLManager.to_wsl_path(str(r2)) if r2 else None
        
        # 🔬 执行 Polypolish 精修 (内部已优化为内存盘模式)
        polished_result = await self._run_polypolish(safe_fasta, safe_r1, safe_r2)
        
        if polished_result:
            # 持久化汇总数据供报告导出
            import json
            summary = {
                "status": "ok",
                "tool": "Polypolish",
                "description": "Short-read consensus polishing (Illumina)",
                "output_file": polished_result.name
            }
            with open(Path(self.get_working_dir()) / "correction_summary.json", "w") as f:
                json.dump(summary, f)

            self.context.update("assembly_fasta", polished_result)
            self.status = "completed"
            return True
        
        # 如果精修失败，我们保留原始组装，不中断流水线
        logger.warning("一致性校正未成功完成，保留原始组装序列继续后续流程")
        self.status = "completed"
        return True

    async def _run_polypolish(self, safe_fasta: str, safe_r1: str, safe_r2: str):
        """
        Polypolish 短读长精修：将原始 Clean Reads 比对回组装序列
        """
        # 🔗 极速飞升：申请 10GB 左右的内存空间进行密集比对计算
        wsl_tmp_outdir = await self.get_best_wsl_tmp_dir(required_gb=10.0)
        
        # 本地化路径：在内存盘内执行所有密集 IO，彻底摆脱 Windows NTFS 瓶颈
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
            await self.runner.run_command(["rm", "-rf", wsl_tmp_outdir], is_shell=True)
            await self.runner.run_command(["mkdir", "-p", wsl_tmp_outdir], is_shell=True)
            
            # 将参考序列拷贝入内存盘进行本地化索引 (防止在慢速盘上建立索引)
            await self.runner.run_command(["cp", safe_fasta, local_fasta], is_shell=True)

            threads = str(self.context.config.get("threads", 8))
            
            # Step 1: 建立 BWA 索引
            if self.on_progress: self.on_progress(10, "正在建立内存级比对索引...")
            await self.runner.run_command(["bwa", "index", local_fasta])

            # Step 2: 独立比对 R1 和 R2
            if self.on_progress: self.on_progress(30, "正在执行内存级超导比对 R1...")
            await self.runner.run_command(["bash", "-c", f'bwa mem -t {threads} -a "{local_fasta}" "{safe_r1}" > "{sam_r1}"'])
            
            if self.on_progress: self.on_progress(50, "正在执行内存级超导比对 R2...")
            await self.runner.run_command(["bash", "-c", f'bwa mem -t {threads} -a "{local_fasta}" "{safe_r2}" > "{sam_r2}"'])
            
            # Step 3: Polypolish 过滤
            if self.on_progress: self.on_progress(70, "正在执行内存级结果过滤...")
            await self.runner.run_command(["polypolish", "filter", "--in1", sam_r1, "--in2", sam_r2, "--out1", filtered_r1, "--out2", filtered_r2])

            # Step 4: 执行精修
            if self.on_progress: self.on_progress(85, "正在合成纠错序列 (Polypolish)...")
            ret_polish = await self.runner.run_command(["bash", "-c", f'polypolish polish "{local_fasta}" "{filtered_r1}" "{filtered_r2}" > "{local_polished}"'])
            
            if ret_polish == 0:
                # 提取唯一产物
                await self.runner.run_command(["cp", "-f", local_polished, str(win_polished_fasta)], is_shell=True)
                if win_polished_fasta.exists() and win_polished_fasta.stat().st_size > 500:
                    logger.info(f"[Polypolish] 内存级精修成功: {win_polished_fasta.name}")
                    return win_polished_fasta
            
            return None

        except Exception as e:
            logger.warning(f"[Polypolish] 内存精修发生异常: {e}")
            return None
        finally:
            # 🔗 强效回收：不论成败，立即销毁内存中的所有临时 SAM/索引文件，释放系统 RAM
            self.logger.info(f"♻️ 正在销毁精修临时数据，释放空间: {wsl_tmp_outdir}")
            await self.runner.run_command(["rm", "-rf", wsl_tmp_outdir], is_shell=True)

