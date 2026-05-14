
import os
import logging
from pathlib import Path
from ..core.base import BaseAssemblyStep
from ..env.wsl_manager import WSLManager

logger = logging.getLogger("Assembly.GapFillerStep")

class GapFillerStep(BaseAssemblyStep):
    """
    局部补洞步骤: 使用 GapFiller 工具填补组装后的 N 碱基和窄缺口
    利用原始 Reads 的配对信息进行末端延伸
    """
    
    def is_completed(self) -> bool:
        out_dir = self.get_working_dir()
        filled_fasta = out_dir / "assembly.filled.fasta"
        return filled_fasta.exists() and filled_fasta.stat().st_size > 0

    async def execute(self) -> bool:
        self.status = "running"
        assembly_fasta = self.context.get("assembly_fasta")
        r1 = self.context.get("clean_r1") or self.context.get("r1")
        r2 = self.context.get("clean_r2") or self.context.get("r2")
        
        if not assembly_fasta or not Path(assembly_fasta).exists():
            return True

        if not self.context.config.get("params", {}).get("fill_gaps"):
            logger.info("未开启局部补洞开关，跳过该步骤")
            return True

        # 检查工具 (GapFiller 通常是 perl 脚本)
        ret = await self.runner.run_command(["which", "GapFiller"])
        if ret != 0:
            logger.info("未找到 GapFiller 工具，跳过该步骤")
            return True

        out_dir = self.get_working_dir()
        out_dir.mkdir(parents=True, exist_ok=True)
        
        # 通过 ShmManager 申请工作空间 (优先内存盘加速)
        if self.context.shm:
            ws = await self.context.shm.acquire_manual("gapfiller", required_gb=2.0)
            shm_dir = ws.path
        else:
            shm_id = f"gapfill_{self.context.task_id}_{os.urandom(4).hex()}"
            shm_dir = f"/dev/shm/{shm_id}"
            await self.runner.run_command(["mkdir", "-p", shm_dir])
        
        try:
            # 1. 准备配置文件 (GapFiller 需要一个 lib 配置文件)
            # 在 WSL 环境中构建文件，但路径指向内存盘
            lib_file_wsl = f"{shm_dir}/libraries.txt"
            lib_content = f"lib1 bwa {WSLManager.to_wsl_path(str(r1))} {WSLManager.to_wsl_path(str(r2))} 300 0.25 FR"
            await self.runner.run_command(["bash", "-c", f"echo '{lib_content}' > {lib_file_wsl}"])
            
            wsl_fasta = WSLManager.to_wsl_path(str(assembly_fasta))
            
            if self.on_progress: self.on_progress(20, "正在执行 GapFiller 填补缺口 (RAM Disk 加速)...")
            
            # 运行 GapFiller
            cmd = [
                "GapFiller",
                "-l", lib_file_wsl,
                "-s", wsl_fasta,
                "-b", "gapfill_res",
                "-T", str(self.context.config.get("threads", 8))
            ]
            
            ret_code = await self.runner.run_command(cmd, cwd=shm_dir)
            
            if ret_code == 0:
                # 产物在 shm_dir/gapfill_res/gapfill_res.gapfilled.final.fa
                wsl_result_src = f"{shm_dir}/gapfill_res/gapfill_res.gapfilled.final.fa"
                if await self.runner.run_command(["test", "-f", wsl_result_src]) != 0:
                    wsl_result_src = f"{shm_dir}/gapfill_res.gapfilled.final.fa"
                
                if await self.runner.run_command(["test", "-f", wsl_result_src]) == 0:
                    final_dest = out_dir / "assembly.filled.fasta"
                    await self.runner.run_command(["cp", wsl_result_src, WSLManager.to_wsl_path(str(final_dest))])
                    
                    self.context.update("assembly_fasta", final_dest)
                    if self.on_progress: self.on_progress(100, "局部补洞完成")
                    return True
            
            logger.warning("GapFiller 未能成功填补任何缺口")
            return True # 补洞失败不影响主流程
        finally:
            if self.context.shm:
                await self.context.shm.release("gapfiller")
            else:
                await self.runner.run_command(["rm", "-rf", shm_dir])
