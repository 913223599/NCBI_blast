# -*- coding: utf-8 -*-
"""
脚本：heal_assembly_metrics.py
功能：扫描所有历史组装产物，自动校准并自愈数据库中的 N50、GC 含量、片段数与深度指标。
"""

import os
import sys
import json
import logging
from pathlib import Path

# 确保导入路径包含项目根目录
project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from src.backend.utils.assembly_db import assembly_db
from src.backend.utils.assembly_storage import AssemblyStorage
from src.backend.routes.assembly import find_assembly_fasta, parse_assembly_fasta_metrics

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("HealAssemblyMetrics")


def heal_all_assembly_metrics():
    logger.info("开始扫描并自愈历史基因组拼接任务指标...")
    tasks = assembly_db.get_history(limit=500)
    logger.info(f"获取到 {len(tasks)} 条历史任务记录")

    healed_count = 0
    skipped_count = 0

    for t in tasks:
        task_id = t["id"]
        task_name = t.get("name", task_id)
        status = t.get("status")
        task_dir = AssemblyStorage.get_task_dir(task_id)

        if status not in ["completed", "success"]:
            skipped_count += 1
            continue

        asm_fasta = find_assembly_fasta(task_id, task_dir)
        if not asm_fasta or not asm_fasta.exists() or asm_fasta.stat().st_size == 0:
            logger.warning(f"任务 [{task_name}] ({task_id}) 未找到有效 assembly.fasta，跳过")
            skipped_count += 1
            continue

        # 解析真实指标
        stats, contigs = parse_assembly_fasta_metrics(asm_fasta, task_dir)
        if not stats or stats.get("total_length", 0) <= 0:
            logger.warning(f"任务 [{task_name}] ({task_id}) FASTA 解析失败，跳过")
            skipped_count += 1
            continue

        # 写入数据库
        assembly_db.update_task_metrics(
            task_id,
            total_length=int(stats["total_length"]),
            contig_count=int(stats.get("contigs", len(contigs))),
            n50=int(stats.get("n50", 0)),
            gc_content=float(stats.get("gc_percent", 0.0)),
            is_circular=bool(stats.get("is_circular", False)),
            avg_depth=float(stats.get("avg_depth", 0.0)),
            max_contig_length=int(stats.get("max_contig_length", 0))
        )

        logger.info(
            f"已成功校准任务 [{task_name}]: 片段数={stats['contigs']}, "
            f"总长={stats['total_length']} bp, N50={stats['n50']} bp, "
            f"GC={stats['gc_percent']}%, 深度={stats['avg_depth']}x, 环状={stats['is_circular']}"
        )
        healed_count += 1

    logger.info(f"历史数据自愈完成! 成功校准: {healed_count} 个任务，跳过: {skipped_count} 个任务。")


if __name__ == "__main__":
    heal_all_assembly_metrics()
