# -*- coding: utf-8 -*-
"""
test_assembly_postproc_and_depth.py - 基因组组装后处理去冗余与深度校正专项测试

测试目标:
1. 验证大比例局部嵌套/从属 Contig（覆盖度 >= 70% 且高一致性）能被精准识别并剔除，解决残留冗余；
2. 验证非冗余的独立 Contig 不会被误删；
3. 验证 FASTA Header 中的深度信息 (depth=xxx) 能被准确提取并加权计算；
4. 验证在缺乏 fastp.json 的三代长读长场景下，能够通过输入 FASTQ 计算真实测序深度，彻底杜绝 1.0x 硬编码兜底；
5. 验证环状分子拓扑标记 (circular=true) 在后处理与指标解析中被完整继承。
"""

import os
import sys
import gzip
import json
import random
import tempfile
import unittest
from pathlib import Path

# 添加项目根路径
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# 导入 NGCS 后处理器
NGCS_DIR = Path("E:/NGCS").resolve()
if str(NGCS_DIR) not in sys.path:
    sys.path.insert(0, str(NGCS_DIR))

from src.assembly.core.base import PipelineContext
from src.assembly.steps.assembler import AssemblerStep
from ngcs.consensus.post_processor import AssemblyPostProcessor


class TestAssemblyPostprocAndDepth(unittest.TestCase):
    """测试后处理消冗与测序深度计算"""

    def setUp(self):
        random.seed(42)
        self.bases = ["A", "C", "G", "T"]

    def _generate_random_seq(self, length: int) -> str:
        return "".join(random.choices(self.bases, k=length))

    def _mutate_seq(self, seq: str, error_rate: float = 0.002) -> str:
        """引入极低测序/组装误差 (模拟 99.8% 一致性)"""
        seq_list = list(seq)
        for i in range(len(seq_list)):
            if random.random() < error_rate:
                seq_list[i] = random.choice([b for b in self.bases if b != seq_list[i]])
        return "".join(seq_list)

    def test_purge_substantial_nested_contig(self):
        """
        测试大比例局部嵌套的 Contig 剔除 (重现 contig_6 与 contig_7 缺陷):
        Contig_A: 10,000 bp (主染色体)
        Contig_B: 4,000 bp, 其中 3,200 bp (80%) 来源于 Contig_A (99.8% 相似), 另有 800 bp 悬垂
        期望: AssemblyPostProcessor 应识别 Contig_B 为从属嵌套冗余并将其剔除，保留且仅保留 Contig_A
        """
        post_proc = AssemblyPostProcessor(min_containment_identity=0.90, min_length=500, verbose=False)

        contig_a_seq = self._generate_random_seq(10000)
        # 从 Contig A 中提取 3200 bp 作为核心重合段
        core_segment = contig_a_seq[2000:5200]
        mutated_core = self._mutate_seq(core_segment, error_rate=0.002)
        # 拼接 800 bp 悬垂末端
        overhang = self._generate_random_seq(800)
        contig_b_seq = mutated_core + overhang

        records = [
            ("contig_A", contig_a_seq),
            ("contig_B", contig_b_seq)
        ]

        purged = post_proc.purge_contained_subsets(records)
        retained_names = [r[0] for r in purged]

        self.assertIn("contig_A", retained_names, "主染色体 Contig_A 必须保留")
        self.assertNotIn("contig_B", retained_names, "局部嵌套且无独立骨架信息的 Contig_B 应当被消冗剔除")
        self.assertEqual(len(purged), 1, "应仅保留 1 条非冗余 Contig")

    def test_preserve_independent_contig_with_small_overlap(self):
        """
        测试具有轻微端部重叠的真实独立 Contig 不被误杀:
        Contig_C: 6,000 bp
        Contig_D: 4,000 bp，仅重叠 300 bp (占 Contig_D 7.5%)
        期望: 两个 Contig 都应被完整保留
        """
        post_proc = AssemblyPostProcessor(min_containment_identity=0.90, min_length=500, verbose=False)

        contig_c_seq = self._generate_random_seq(6000)
        contig_d_seq = contig_c_seq[-300:] + self._generate_random_seq(3700)

        records = [
            ("contig_C", contig_c_seq),
            ("contig_D", contig_d_seq)
        ]

        purged = post_proc.purge_contained_subsets(records)
        retained_names = [r[0] for r in purged]

        self.assertIn("contig_C", retained_names)
        self.assertIn("contig_D", retained_names)
        self.assertEqual(len(purged), 2, "独立 Contig 绝不应被误删")

    def test_depth_parsing_from_fasta_header(self):
        """
        测试 FASTA 头部含有深度字段时的解析与加权计算:
        >contig_1 length=1000 depth=100.0x
        >contig_2 length=3000 depth=200.0x
        期望加权平均深度: (1000*100 + 3000*200) / 4000 = 175.0x
        """
        with tempfile.TemporaryDirectory() as td:
            fa_path = Path(td) / "assembly.fasta"
            with open(fa_path, "w", encoding="utf-8") as f:
                f.write(">contig_1 length=1000 depth=100.0x\n" + "A" * 1000 + "\n")
                f.write(">contig_2 length=3000 depth=200.0x\n" + "C" * 3000 + "\n")

            ctx = PipelineContext("test_depth_header", Path(td), {})
            step = AssemblerStep(ctx)
            stats = step._parse_assembly_stats(fa_path, Path(td))

            self.assertEqual(stats["contigs"], 2)
            self.assertEqual(stats["total_length"], 4000)
            self.assertAlmostEqual(stats["avg_depth"], 175.0, places=1)
            self.assertNotEqual(stats["avg_depth"], 1.0, "解析出的深度绝不能兜底为 1.0x")

    def test_depth_fallback_to_fastq_bases_when_fastp_missing(self):
        """
        测试在长读长模式下无 fastp.json 且 header 无 depth 时的真实深度估算:
        输入 FASTQ 包含 500,000 bp 碱基数据，组装产物总长为 5,000 bp
        期望估算平均深度约为 100.0x，严禁回退为硬编码 1.0x
        """
        with tempfile.TemporaryDirectory() as td:
            work_dir = Path(td)
            fa_path = work_dir / "assembly.fasta"
            with open(fa_path, "w", encoding="utf-8") as f:
                f.write(">contig_1 length=5000\n" + "A" * 5000 + "\n")

            # 模拟输入测序 FASTQ (5000 条 100bp reads = 500,000 bp)
            fq_path = work_dir / "input_ont.fastq"
            read_seq = "A" * 100
            with open(fq_path, "w", encoding="utf-8") as f:
                for idx in range(5000):
                    f.write(f"@read_{idx}\n{read_seq}\n+\n{'I'*100}\n")

            ctx = PipelineContext("test_depth_fallback", work_dir, {})
            # 在 context 中记录 clean_r1 或 r1
            ctx.update("clean_r1", fq_path)

            step = AssemblerStep(ctx)
            stats = step._parse_assembly_stats(fa_path, work_dir)

            self.assertGreater(stats["avg_depth"], 50.0, "通过 FASTQ 测序量计算的深度应大于 50x")
            self.assertNotEqual(stats["avg_depth"], 1.0, "长读长无质控时严禁返回硬编码 1.0x 深度")

    def test_circular_topology_propagation(self):
        """
        测试环化拓扑标记保留与解析:
        >contig_1 length=5000 circular=true depth=80.0x
        期望 stats['is_circular'] 为 True
        """
        with tempfile.TemporaryDirectory() as td:
            fa_path = Path(td) / "assembly.fasta"
            with open(fa_path, "w", encoding="utf-8") as f:
                f.write(">contig_1 length=5000 circular=true depth=80.0x\n" + "A" * 5000 + "\n")

            ctx = PipelineContext("test_circular", Path(td), {})
            step = AssemblerStep(ctx)
            stats = step._parse_assembly_stats(fa_path, Path(td))

            self.assertTrue(stats["is_circular"], "带有 circular=true 的 contig 应将 stats['is_circular'] 置为 True")


if __name__ == "__main__":
    unittest.main()
