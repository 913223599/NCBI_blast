"""
单步测试脚本：仅运行 ProphageSeparatorStep
验证 VIBRANT 数据库路径探测修复
"""
import asyncio
import sys
import os
import shutil
import logging

# 确保项目根目录在搜索路径中
project_root = r"F:\NCBI blast"
sys.path.insert(0, project_root)
os.chdir(project_root)

from pathlib import Path
from src.assembly.core.base import PipelineContext
from src.assembly.steps.prophage_separator import ProphageSeparatorStep

# 配置日志
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S"
)

async def main():
    task_id = "AS_1777142977985"
    task_dir = Path(project_root) / "results" / "assembly" / task_id
    assembly_fasta = task_dir / "assemblerstep" / "assembly_run" / "assembly.fasta"
    prophage_dir = task_dir / "prophageseparatorstep"

    # 0. 校验输入
    if not assembly_fasta.exists():
        print(f"❌ 组装产物不存在: {assembly_fasta}")
        return

    print(f"📂 组装产物: {assembly_fasta} ({assembly_fasta.stat().st_size} bytes)")

    # 1. 清除旧结果 (强制重跑)
    if prophage_dir.exists():
        print(f"🗑️ 正在清除旧结果: {prophage_dir}")
        shutil.rmtree(prophage_dir, ignore_errors=True)

    # 2. 构建最小化上下文
    config = {
        "sample_type": "PHAGE",
        "is_wsl": True,
        "params": {
            "host_genome": str(task_dir / "hostcleanerstep" / "host_genome.fasta")
            if (task_dir / "hostcleanerstep" / "host_genome.fasta").exists()
            else None,
            "is_lysogenic": False,
        }
    }

    ctx = PipelineContext(task_id, task_dir, config)
    ctx.update("assembly_fasta", assembly_fasta)

    host_genome = config["params"].get("host_genome")
    print(f"🔬 宿主基因组: {host_genome if host_genome else '未提供'}")
    print(f"🧪 配置: {config}")
    print("=" * 60)
    print("🚀 开始执行 ProphageSeparatorStep...")
    print("=" * 60)

    # 3. 执行
    step = ProphageSeparatorStep(ctx)
    step.on_progress = lambda p, msg=None: print(f"  [{p:.0f}%] {msg or ''}")

    success = await step.execute()

    print("=" * 60)
    if success:
        final_fasta = prophage_dir / "separated_phage.fasta"
        if final_fasta.exists():
            print(f"✅ 成功! 输出: {final_fasta} ({final_fasta.stat().st_size} bytes)")
        else:
            print(f"⚠️ 步骤返回成功但未生成输出文件")
    else:
        print(f"❌ 步骤执行失败")

    # 4. 显示上下文数据
    print("\n📊 上下文数据:")
    for k, v in ctx.data.items():
        print(f"  {k}: {v}")

if __name__ == "__main__":
    asyncio.run(main())
