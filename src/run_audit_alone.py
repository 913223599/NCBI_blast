import asyncio
import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(r"F:\NCBI blast\src").resolve()))

from assembly.context import PipelineContext
from assembly.steps.phage_annotation import PhageAnnotationStep
from assembly.env.wsl_manager import WSLManager

async def run_audit_independently():
    task_id = "AS_1777212562068"
    print(f"🚀 开始为任务 {task_id} 单独执行独立深度安全审计...")
    
    context = PipelineContext(task_id, {})
    # Initialize basic context variables that the step expects
    step = PhageAnnotationStep(context)
    
    win_work_path = step.get_working_dir()
    integrated_tsv = win_work_path / "Integrated_Final_Annotations.tsv"
    fasta = step.context.get("scaffold_path")
    if not fasta:
        fasta = Path(r"F:\NCBI blast\results\assembly\AS_1777212562068\prophageseparatorstep\separated_phage.fasta")
    win_final_gbk = win_work_path / "phold_res" / "phold.gbk"
    if not win_final_gbk.exists():
        win_final_gbk = win_work_path / "pharokka_res" / "PHAGE.gbk"

    print("📊 运行指标: 检查基础文件存在性...")
    print(f"TSV 存在: {integrated_tsv.exists()}")
    print(f"FASTA 存在: {fasta.exists()}")
    print(f"GBK 存在: {win_final_gbk.exists()}")
    
    threads = 28
    
    print("\n🔍 1. 执行血缘深度挖掘与预测 (Deep Host Prediction)...")
    host_results = await step._deep_host_prediction(fasta, threads)
    print("血缘挖掘状态:", host_results.get("status"))
    print(f"找到 Top hits: {len(host_results.get('top_hits', []))} 个")
    
    mash_hit_tsv = win_work_path / "pharokka_res" / "PHAGE_top_hits_mash_inphared.tsv"
    print("\n🔍 2. 从 Mash 回溯 PhageScope 顶级元数据 (Mine Metadata)...")
    ref_audit = await asyncio.to_thread(step._mine_phagescope_metadata, mash_hit_tsv)
    print("环境来源:", ref_audit.get("environment"))
    print("生活史:", ref_audit.get("lifestyle"))
    
    print("\n🔍 3. 运行 Bacphlip 生活史预测与氨基酸验证...")
    lifecycle_results = await step._run_bacphlip_prediction(win_final_gbk)
    print("独立生活史预测:", lifecycle_results)
    
    print("\n🔍 4. 生成系统发育树型圈图...")
    tree_path = win_work_path / "Phylogeny_tree.png"
    step._generate_phylogeny_image(ref_audit, tree_path)
    if tree_path.exists():
        print(f"✅ 系统血缘进化树已独立生成保存至: {tree_path.name}")
        
    print("\n✅ 所有安全审计模块独立修复运行彻底完成！")

if __name__ == "__main__":
    asyncio.run(run_audit_independently())
