
from pathlib import Path
from ..core.base import BaseAssemblyStep

class QualityControlStep(BaseAssemblyStep):
    """
    质控步骤 (Fastp) 封装
    """
    def is_completed(self) -> bool:
        out_dir = self.get_working_dir()
        clean_r1 = out_dir / f"{self.context.task_id}_R1.clean.fq.gz"
        clean_r2 = out_dir / f"{self.context.task_id}_R2.clean.fq.gz"
        
        # 🔗 物理校验：文件存在且体积大于 10KB
        if clean_r1.exists() and clean_r2.exists():
            if clean_r1.stat().st_size > 10240 and clean_r2.stat().st_size > 10240:
                # 同步更新上下文，确保后续步骤能拿到路径
                self.context.update("clean_r1", clean_r1)
                self.context.update("clean_r2", clean_r2)
                return True
        return False

    async def execute(self) -> bool:
        # 🔗 0. 如果已完成，则直接跳过
        if self.is_completed():
            self.status = "completed"
            if self.on_progress: self.on_progress(100.0, "已跳过 (发现缓存)")
            return True

        self.status = "running"
        
        # 1. 获取输入输出 (从 Context 中获取)
        r1 = self.context.get("r1")
        r2 = self.context.get("r2")
        
        out_dir = self.get_working_dir()
        clean_r1 = out_dir / f"{self.context.task_id}_R1.clean.fq.gz"
        clean_r2 = out_dir / f"{self.context.task_id}_R2.clean.fq.gz"
        
        # 2. 构建命令
        fastp_bin = self.context.config.get("fastp_bin", "fastp")
        
        # 🔗 进度解析 (fastp 实时反馈)
        def output_handler(line: str):
            # fastp 在 stderr 输出类似: "Read1 processed: 1000000"
            if "processed" in line and ":" in line:
                try:
                    # 获取处理的 read 数量
                    processed_str = line.split(":")[-1].replace(",", "").strip()
                    processed = int(processed_str)
                    # 这是一个启发式估算法：假设普通样本 5M reads
                    p = min(99, (processed / 5000000) * 100)
                    
                    # 💡 增加细粒度子状态
                    m_reads = round(processed / 1000000, 1)
                    if self.on_progress: self.on_progress(p, f"已处理: {m_reads}M 条序列")
                except: pass

        cmd = [
            fastp_bin,
            "-i", str(r1), "-I", str(r2),
            "-o", str(clean_r1), "-O", str(clean_r2),
            "--thread", str(self.context.config.get("threads", 4)),
            "--detect_adapter_for_pe", "--correction"
        ]
        
        if self.on_progress: self.on_progress(5, "正在启动过滤引擎...")
        
        # 3. 使用 Runner 执行 (注入 GPU 环境)
        returncode = await self.runner.run_command(
            cmd, 
            cwd=out_dir,
            env=self.context.get("gpu_env"),
            on_output=output_handler
        )
        
        if returncode == 0:
            self.context.update("clean_r1", clean_r1)
            self.context.update("clean_r2", clean_r2)
            self.status = "completed"
            if self.on_progress: self.on_progress(100, "质控完成")
            return True
        
        self.status = "failed"
        return False
