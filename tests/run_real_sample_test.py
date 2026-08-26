# -*- coding: utf-8 -*-
"""
真实样本测试脚本: BC16_contig_4-Aeromonas phage BUCT551.fasta
验证多引擎流式级联互补 (Waterfall Cascading Pipeline) 在真实噬菌体基因组上的注释效果
"""
import sys
import os
import time
import json
import asyncio
import logging
from pathlib import Path

# 设置日志格式
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("test_real_sample")

# 引入项目根目录
project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from src.analysis.annotation.types import AnnotationRunRequest
from src.analysis.annotation.pipeline import AnnotationPipeline


async def main():
    fasta_file = Path(r"E:\测序数据\气单胞\BC16\BC16_contig_4-Aeromonas phage BUCT551.fasta")
    if not fasta_file.exists():
        logger.error(f"输入文件不存在: {fasta_file}")
        return

    logger.info(f"开始测试真实噬菌体样本: {fasta_file.name}")
    task_id = f"TEST_REAL_{int(time.time())}"
    work_dir = project_root / "results" / "annotations" / task_id

    req = AnnotationRunRequest(
        task_name="BC16_Aeromonas_phage_BUCT551_Annotation",
        sample_type="PHAGE",
        engine="auto",
        fasta_path=str(fasta_file.resolve()),
        prefix="BUCT551",
        genetic_code=11,
        min_contig_len=100,
        enable_waterfall=True,
        enable_homology=True,
        enable_phold=True,
        enable_safety_audit=True
    )

    pipeline = AnnotationPipeline(task_id=task_id, work_dir=work_dir)
    
    start_t = time.time()
    logger.info(f"启动多引擎流式级联注释管线 (Task ID: {task_id})...")
    
    result = await pipeline.execute(req)
    
    elapsed = time.time() - start_t
    logger.info(f"注释流水线执行完毕，耗时: {elapsed:.2f} 秒")
    
    summary = result.get("summary", {})
    files = result.get("files", {})
    feature_count = result.get("feature_count", 0)
    safety_audit = result.get("safety_audit", {})
    
    print("\n" + "=" * 60)
    print("【真实样本功能注释与多引擎级联互补测试报告】")
    print("=" * 60)
    print(f"任务标识 (Task ID)     : {task_id}")
    print(f"样本类型 (Sample Type) : {req.sample_type}")
    print(f"总序列长度 (Total bp)  : {summary.get('total_length', 0):,} bp")
    print(f"Contig 数量            : {summary.get('num_contigs', 0)}")
    print(f"GC 含量                : {summary.get('gc_content', 0.0)}%")
    print(f"总特征数 (Total Feats) : {summary.get('total_features', 0)}")
    print(f"CDS 编码基因数         : {summary.get('cds_count', 0)}")
    print(f"已明确功能基因 (Known) : {summary.get('annotated_count', 0)}")
    print(f"假定/未知蛋白 (Hypo)   : {summary.get('hypothetical_count', 0)}")
    
    if summary.get('cds_count'):
        anno_rate = round((summary.get('annotated_count', 0) / summary.get('cds_count', 1)) * 100, 2)
        print(f"功能注释覆盖率         : {anno_rate}%")
    
    print("-" * 60)
    print("【各引擎级联互补贡献统计】:")
    engine_contribs = summary.get("engine_contributions", {})
    for eng, count in engine_contribs.items():
        print(f"  - [{eng}]: 贡献/补充了 {count} 个基因特征")
        
    print("-" * 60)
    print("【功能大类分布统计】:")
    cat_dist = summary.get("category_distribution", {})
    for cat, count in sorted(cat_dist.items(), key=lambda x: x[1], reverse=True):
        print(f"  - {cat}: {count} 个")
        
    print("-" * 60)
    print("【生物安全性审计 (CARD / VFDB / Anti-CRISPR)】:")
    print(f"  - 合规状态 : {'安全通过' if safety_audit.get('safety_passed') else '提示注意'}")
    print(f"  - CARD耐药基因数    : {len(safety_audit.get('amr_genes', []))}")
    print(f"  - VFDB毒力因子数    : {len(safety_audit.get('virulent_factors', []))}")
    print(f"  - Anti-CRISPR状态   : {safety_audit.get('anti_crispr_status')}")
    
    print("-" * 60)
    print("【产物文件路径】:")
    for k, v in files.items():
        print(f"  - {k.upper():<18}: {v}")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    asyncio.run(main())
