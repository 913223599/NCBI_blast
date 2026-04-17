
import logging
from pathlib import Path
from typing import Optional
from ..core.base import BaseAssemblyStep

class HostCleanerStep(BaseAssemblyStep):
    """
    宿主数据剔除步骤 (SRP: 只负责从测序回传中剔除非病毒序列)
    使用算法: Minimap2 比对 + Samtools 提取未比对 Read
    """
    def is_completed(self) -> bool:
        out_dir = self.get_working_dir()
        filtered_r1 = out_dir / "unmapped_R1.fastq.gz"
        filtered_r2 = out_dir / "unmapped_R2.fastq.gz"
        
        # 🔗 物理校验
        if filtered_r1.exists() and filtered_r2.exists():
            if filtered_r1.stat().st_size > 10240:
                self.context.update("clean_r1", filtered_r1)
                self.context.update("clean_r2", filtered_r2)
                return True
        return False

    async def execute(self) -> bool:
        # 🔗 0. 断点检查
        if self.is_completed():
            self.logger.info("检测到已存在的宿主过滤结果，跳过计算")
            self.status = "completed"
            if self.on_progress: self.on_progress(100, "已跳过 (发现缓存)")
            return True

        # 1. 检查配置是否开启了宿主过滤
        host_db = self.context.config.get("params", {}).get("host_filter_db")
        if not host_db:
            self.logger.info("未配置宿主过滤数据库，跳过该步骤")
            # 确保下游步骤能拿到数据
            self.context.update("clean_r1", self.context.get("r1"))
            self.context.update("clean_r2", self.context.get("r2"))
            return True

        self.status = "running"
        # 优先获取 QualityControl 产出的干净数据
        r1 = self.context.get("clean_r1") or self.context.get("r1")
        r2 = self.context.get("clean_r2") or self.context.get("r2")
        
        if not r1 or not r2:
            self.status = "failed"
            return False
            
        out_dir = self.get_working_dir()
        filtered_r1 = out_dir / "unmapped_R1.fastq.gz"
        filtered_r2 = out_dir / "unmapped_R2.fastq.gz"
        bam_file = out_dir / "mapped_to_host.bam"

        if self.on_progress: self.on_progress(5, "正在映射测序数据到宿主基因组...")
        
        # 命令 1：比对并直接输出到 BAM (支持多线程压缩)
        threads = str(self.context.config.get("threads", 8))
        minimap_cmd = [
            "minimap2", "-ax", "sr", "-t", threads,
            str(host_db), str(r1), str(r2), "|",
            "samtools", "view", "-@", threads, "-b", "-f", "12", "-o", str(bam_file)
        ]
        
        ret = await self.runner.run_command(minimap_cmd, is_shell=True)
        if ret != 0: return False

        if self.on_progress: self.on_progress(60, "正在提取未比对序列 (宿主剔除)...")
        
        # 命令 2：将 BAM 还原为双端 FASTQ (增加多线程支持)
        if self.on_progress: self.on_progress(80, "正在生成清洗后的 Fastq 文件...")
        restore_cmd = [
            "samtools", "fastq", "-@", threads, 
            "-1", str(filtered_r1), "-2", str(filtered_r2),
            "-0", "/dev/null", "-s", "/dev/null", "-n", str(bam_file)
        ]
        ret = await self.runner.run_command(restore_cmd)
        
        if ret == 0 and filtered_r1.exists():
            if self.on_progress: self.on_progress(100, "宿主剔除已完成")
            self.context.update("clean_r1", filtered_r1)
            self.context.update("clean_r2", filtered_r2)
            self.status = "completed"
            return True

        self.status = "failed"
        return False
