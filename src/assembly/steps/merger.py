import os
import logging
from pathlib import Path
from ..core.base import BaseAssemblyStep
from ..env.wsl_manager import WSLManager

logger = logging.getLogger("Assembly.ReadMergerStep")

class ReadMergerStep(BaseAssemblyStep):
    """
    读长合并步骤: 使用 FLASH / fastp 工具将 R1/R2 有重叠的部分合并
    合并后的长 Reads 有助于跨越更长的重复序列区域
    """
    
    def is_completed(self) -> bool:
        # 如果已经有了 merged 产物，则视为完成
        out_dir = self.get_working_dir()
        merged_file = out_dir / "merged.extendedFrags.fastq.gz"
        unmerged_r1 = out_dir / "merged.notCombined_1.fastq.gz"
        unmerged_r2 = out_dir / "merged.notCombined_2.fastq.gz"

        if merged_file.exists() and merged_file.stat().st_size > 0:
            #  断点续传核心修复：必须同步更新所有中间产物变量
            self.context.update("merged_reads", merged_file)
            if unmerged_r1.exists() and unmerged_r1.stat().st_size > 0: 
                self.context.update("unmerged_r1", unmerged_r1)
            if unmerged_r2.exists() and unmerged_r2.stat().st_size > 0: 
                self.context.update("unmerged_r2", unmerged_r2)
            return True
        return False

    async def execute(self) -> bool:
        self.status = "running"
        r1 = self.context.get("clean_r1") or self.context.get("r1")
        r2 = self.context.get("clean_r2") or self.context.get("r2")
        
        if not r1 or not r2:
            logger.warning("未发现双端测序数据，跳过读长合并")
            return True

        #  架构修复：长读长数据（Nanopore/PacBio）禁止走合并
        tech = (self.context.config.get("tech") or "ILLUMINA").upper()
        if tech in ["NANOPORE", "PACBIO_HIFI"]:
            logger.info(f"️ 检测到长读长平台 ({tech})，合并模块不适用，自动跳过")
            return True

        if not self.context.config.get("params", {}).get("merge_reads"):
            logger.info("未开启读长合并开关，跳过该步骤")
            return True

        # 环境与路径准备
        out_dir = self.get_working_dir()
        out_dir.mkdir(parents=True, exist_ok=True)
        wsl_out_dir = WSLManager.to_wsl_path(str(out_dir))
        
        #  极速飞升：使用内存盘执行合并计算
        wsl_tmp_outdir = await self.get_best_wsl_tmp_dir(required_gb=5.0)
        
        #  安全修复：is_shell=True 时必须传入完整的字符串，并对路径单引号保护
        await self.runner.run_command(f"rm -rf '{wsl_tmp_outdir}'", is_shell=True)
        await self.runner.run_command(f"mkdir -p '{wsl_tmp_outdir}'", is_shell=True)

        wsl_r1 = WSLManager.to_wsl_path(str(r1))
        wsl_r2 = WSLManager.to_wsl_path(str(r2))
        
        shm_merged = f"{wsl_tmp_outdir}/merged.extendedFrags.fastq.gz"
        shm_un1 = f"{wsl_tmp_outdir}/merged.notCombined_1.fastq.gz"
        shm_un2 = f"{wsl_tmp_outdir}/merged.notCombined_2.fastq.gz"
        
        threads = str(self.context.config.get("threads", 8))
        fastp_threads = str(min(16, int(threads)))
        
        if self.on_progress: self.on_progress(10, "正在执行高速内存读长合并 (fastp --merge)...")
        
        # 执行命令 (列表形式，无 is_shell=True，安全)
        cmd = [
            "fastp",
            "-i", wsl_r1,
            "-I", wsl_r2,
            "-m", "--merged_out", shm_merged,
            "--out1", shm_un1,
            "--out2", shm_un2,
            "--thread", fastp_threads,
            "-Q", "-A", "-G", "-L", # 纯净模式：只负责合并，不负责质控
            "-h", f"{wsl_tmp_outdir}/merge_report.html",
            "-j", f"{wsl_tmp_outdir}/merge_report.json"
        ]
        
        try:
            ret_code = await self.runner.run_command(cmd)
            
            if ret_code == 0:
                if self.on_progress: self.on_progress(80, "合并完成，正在持久化数据...")
                
                #  逻辑与安全修复：使用通配符保证拷贝完整，单引号防止路径空格攻击，校验拷贝返回值
                cp_cmd = f"cp -f '{wsl_tmp_outdir}'/*.fastq.gz '{wsl_out_dir}/'"
                cp_ret = await self.runner.run_command(cp_cmd, is_shell=True)
                
                if cp_ret != 0:
                    logger.error(f"严重错误：合并产物无法从内存盘回写至物理盘 {wsl_out_dir}")
                    return False
                
                # 标记新产物
                merged_file = out_dir / "merged.extendedFrags.fastq.gz"
                unmerged_r1 = out_dir / "merged.notCombined_1.fastq.gz"
                unmerged_r2 = out_dir / "merged.notCombined_2.fastq.gz"
                
                if merged_file.exists() and merged_file.stat().st_size > 0:
                    self.context.update("merged_reads", merged_file)
                    if unmerged_r1.exists(): self.context.update("unmerged_r1", unmerged_r1)
                    if unmerged_r2.exists(): self.context.update("unmerged_r2", unmerged_r2)
                    
                    if self.on_progress: self.on_progress(100, "读长合并阶段圆满结束")
                    return True
                else:
                    logger.error("未能找到有效的合并结果文件 (文件不存在或体积为 0)")
                    return False
            
            logger.error("fastp 读长合并过程发生异常退出")
            return False
            
        except Exception as e:
            logger.error(f"ReadMergerStep 执行崩溃: {e}")
            return False
            
        finally:
            # ️ 资源回收：确保无论成功失败，内存盘资源一定被释放
            self.logger.info("️ 清理合并阶段内存盘缓存...")
            if self.context.shm:
                await self.context.shm.release(self.__class__.__name__.lower())
            else:
                await self.runner.run_command(f"rm -rf '{wsl_tmp_outdir}'", is_shell=True)