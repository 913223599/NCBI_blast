# -*- coding: utf-8 -*-
"""
test_ngcs_assembler_step.py - NGCS 组装步骤单元与集成测试
验证 AssemblerStep 全面接入 NGCS 引擎后的短读长双端与长读长单分子组装功能。
"""

import os
import sys
import gzip
import random
import asyncio
import tempfile
import unittest
from pathlib import Path

# 添加项目根路径到 sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.assembly.core.base import PipelineContext
from src.assembly.steps.assembler import AssemblerStep


class TestNGCSAssemblerStep(unittest.IsolatedAsyncioTestCase):
    """测试 NGCS 组装器步骤的执行、指标解析与断点机制"""

    def setUp(self):
        random.seed(42)

    def _generate_synthetic_pe_reads(self, r1_path: Path, r2_path: Path, genome_len: int = 5000):
        """生成合成二代双端测序数据 (带一定覆盖深度)"""
        bases = ["A", "C", "G", "T"]
        genome = "".join(random.choices(bases, k=genome_len))
        read_len = 150
        step = 2

        with gzip.open(r1_path, "wt", encoding="utf-8") as f1, gzip.open(r2_path, "wt", encoding="utf-8") as f2:
            for i in range(0, genome_len - 300, step):
                fwd = genome[i:i + read_len]
                rev_fwd = genome[i + read_len:i + 300]
                rev = rev_fwd.translate(str.maketrans("ACGT", "TGCA"))[::-1]

                f1.write(f"@read_{i}/1\n{fwd}\n+\n{chr(70) * len(fwd)}\n")
                f2.write(f"@read_{i}/2\n{rev}\n+\n{chr(70) * len(rev)}\n")
        return genome

    def _generate_synthetic_ont_reads(self, ont_path: Path, genome_len: int = 8000, num_reads: int = 80):
        """生成合成三代长读长测序数据"""
        bases = ["A", "C", "G", "T"]
        genome = "".join(random.choices(bases, k=genome_len))

        with gzip.open(ont_path, "wt", encoding="utf-8") as f:
            for idx in range(num_reads):
                start = random.randint(0, max(0, genome_len - 1500))
                length = random.randint(800, 1400)
                read_seq = genome[start:start + length]
                f.write(f"@ont_read_{idx}\n{read_seq}\n+\n{chr(70) * len(read_seq)}\n")
        return genome

    async def test_short_read_pe_assembly(self):
        """测试二代短读长双端测序数据组装 (NGCS C++20 / Python 欧拉残差流)"""
        with tempfile.TemporaryDirectory() as td:
            work_dir = Path(td)
            r1 = work_dir / "sample_R1.fq.gz"
            r2 = work_dir / "sample_R2.fq.gz"
            ref_genome = self._generate_synthetic_pe_reads(r1, r2, genome_len=4000)

            config = {
                "tech": "ILLUMINA",
                "sample_type": "PHAGE",
                "params": {
                    "threads": 4,
                    "mode": "metagenome"
                }
            }
            ctx = PipelineContext("test_task_sr", work_dir, config)
            ctx.update("clean_r1", r1)
            ctx.update("clean_r2", r2)

            step = AssemblerStep(ctx)
            progress_records = []
            def on_p(p, desc):
                progress_records.append((p, desc))
            step.on_progress = on_p

            success = await step.execute()
            self.assertTrue(success, "短读长组装步骤应执行成功")
            self.assertEqual(step.status, "completed")

            # 校验产物
            asm_fasta = ctx.get("assembly_fasta")
            self.assertIsNotNone(asm_fasta)
            self.assertTrue(Path(asm_fasta).exists())
            self.assertGreater(Path(asm_fasta).stat().st_size, 0)

            # 校验指标统计
            stats = ctx.get("assembly_stats")
            self.assertIsNotNone(stats)
            self.assertGreater(stats.get("total_length", 0), 3000)
            self.assertGreater(stats.get("contigs", 0), 0)
            self.assertGreater(stats.get("gc_percent", 0.0), 0.0)

            # 校验进度广播
            self.assertGreater(len(progress_records), 0)

            # 校验断点检测 (缓存命中)
            self.assertTrue(step.is_completed())

    async def test_long_read_nanopore_assembly(self):
        """测试三代长读长单分子数据组装 (NGCS 连续谱流形与 SIMD-POA)"""
        with tempfile.TemporaryDirectory() as td:
            work_dir = Path(td)
            ont_fq = work_dir / "sample_ont.fq.gz"
            self._generate_synthetic_ont_reads(ont_fq, genome_len=6000, num_reads=70)

            config = {
                "tech": "NANOPORE",
                "sample_type": "BACTERIA",
                "params": {
                    "threads": 4,
                    "min_read_length": 400,
                    "mode": "isolate"
                }
            }
            ctx = PipelineContext("test_task_ont", work_dir, config)
            ctx.update("clean_r1", ont_fq)

            step = AssemblerStep(ctx)
            success = await step.execute()
            self.assertTrue(success, "长读长组装步骤应执行成功")
            self.assertEqual(step.status, "completed")

            asm_fasta = ctx.get("assembly_fasta")
            self.assertIsNotNone(asm_fasta)
            self.assertTrue(Path(asm_fasta).exists())
            self.assertGreater(Path(asm_fasta).stat().st_size, 0)

            stats = ctx.get("assembly_stats")
            self.assertIsNotNone(stats)
            self.assertGreater(stats.get("total_length", 0), 0)
            self.assertGreater(stats.get("contigs", 0), 0)


if __name__ == "__main__":
    unittest.main()
