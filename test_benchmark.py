import asyncio
import os
from pathlib import Path
from src.assembly.core.base import PipelineContext, BaseAssemblyStep
from src.assembly.steps.quality_control import QualityControlStep
from src.assembly.steps.merger import ReadMergerStep
from src.assembly.steps.assembler import AssemblerStep
from src.assembly.steps.scaffolder import ScaffoldingStep
from src.assembly.steps.correction import ConsensusCorrectionStep
from src.assembly.steps.gap_filler import GapFillerStep
from src.assembly.steps.prophage_separator import ProphageSeparatorStep
from src.assembly.engine.gpu_config import GPUConfigManager
import time
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

async def run_test(name, r1, r2, is_lysogenic=False):
    print(f"==================================================")
    print(f"🚀 Starting Benchmark Test: {name}")
    print(f"==================================================")
    task_id = f"test_{name}"
    task_dir = Path(f"f:/NCBI blast/results/assembly/{task_id}")
    task_dir.mkdir(parents=True, exist_ok=True)
    config = {
        "is_wsl": True,
        "max_memory": 16,
        "threads": 8,
        "tech": "ILLUMINA",
        "estimated_genome_size": 250000, # Jumbo Phage，约 250kbp
        "params": {
            "fill_gaps": True,
            "is_lysogenic": is_lysogenic,
            "target_coverage": 300,
            "mode": "normal" 
        }
    }
    ctx = PipelineContext(task_id, task_dir, config)
    ctx.gpu_manager = GPUConfigManager()
    ctx.gpu_env = ctx.gpu_manager.get_acceleration_env()
    
    # 注入 ShmManager (内存盘统一资源管理器)
    from src.assembly.core.shm_manager import ShmManager
    from src.assembly.engine.runner import CommandRunner
    shm_runner = CommandRunner("ShmManager", is_wsl=True)
    ctx.shm = ShmManager(task_id, shm_runner, total_memory_gb=48.0)
    
    ctx.update("r1", Path(r1))
    ctx.update("r2", Path(r2))
    
    # 流水线步骤编排：遵循"先缩减目标，再精细加工"原则
    steps: list[BaseAssemblyStep] = [
        QualityControlStep(ctx),
        ReadMergerStep(ctx),
        AssemblerStep(ctx),
    ]
    
    # 溶源噬菌体：组装后立即分离，缩减后续步骤的计算目标
    if is_lysogenic:
        steps.append(ProphageSeparatorStep(ctx))
    
    steps.extend([
        GapFillerStep(ctx),
        ScaffoldingStep(ctx),
        ConsensusCorrectionStep(ctx),
    ])
    
    for step in steps:
        print(f"\n---> Running step: {step.__class__.__name__}")
        
        def on_prog(p, msg=None):
            if msg:
                print(f"     [Progress {p}%] {msg}")
                
        step.on_progress = on_prog
        
        t0 = time.time()
        success = await step.execute()
        duration = time.time() - t0
        
        print(f"<--- Step {step.__class__.__name__} finished in {duration:.2f}s, Success: {success}")
        if not success:
            print("[ERROR] Pipeline failed at this step.")
            break
            
    final_out = ctx.get('separated_phage') or ctx.get('scaffold_path') or ctx.get('assembly_fasta')
    print(f"\n[OK] Test {name} completed!")
    print(f"[FILE] Final Assembly Output: {final_out}")

if __name__ == '__main__':
    # 我们测试 SRR30664648 (Ralstonia Jumbo Phage - 225kb 大型噬菌体)
    r1 = "f:/NCBI blast/test_data/ncbi_samples/SRR30664648_1.fastq.gz"
    r2 = "f:/NCBI blast/test_data/ncbi_samples/SRR30664648_2.fastq.gz"
    
    if os.path.exists(r1) and os.path.exists(r2):
        asyncio.run(run_test("SRR30664648_jumbo", r1, r2, is_lysogenic=False))
    else:
        print(f"Error: Could not find dataset files: {r1} or {r2}")
