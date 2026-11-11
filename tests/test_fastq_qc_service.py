# -*- coding: utf-8 -*-
"""
FASTQ 测序质量控制与长度过滤服务单元测试
验证：
1. 读长窗口过滤 (Length QC: min_len, max_len)
2. Phred 平均质量值过滤 (Q-Score QC: min_avg_qscore)
3. 异常 N 碱基比例过滤 (N-ratio QC: max_n_ratio)
4. 质控统计指标 (QC Metrics) 计算与断点兼容
"""
import unittest
import io
from pathlib import Path
import sys

# 相对模块路径引用
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.backend.services.fastq_qc_service import FastqQCFilter, FastqQCReport


class TestFastqQCService(unittest.TestCase):
    """测序质量控制测试用例"""

    def setUp(self):
        self.filter = FastqQCFilter(
            min_len=1200,
            max_len=1800,
            min_avg_qscore=10.0,
            max_n_ratio=0.05
        )

    def test_phred_qscore_calculation(self):
        """测试 Phred 质量值 ASCII 换算与平均值计算"""
        # ASCII '?' 是 63, 63 - 33 = Q30
        q_str = "?" * 10
        avg_q = FastqQCFilter.calc_mean_qscore(q_str)
        self.assertAlmostEqual(avg_q, 30.0, places=2)

        # ASCII '+' 是 43, 43 - 33 = Q10
        q_str_10 = "+" * 10
        avg_q_10 = FastqQCFilter.calc_mean_qscore(q_str_10)
        self.assertAlmostEqual(avg_q_10, 10.0, places=2)

    def test_filter_reads(self):
        """测试综合过滤不同缺陷的 Reads"""
        # 构造测试 Reads:
        # Read 1: 合格 16S 全长序列 (1500 bp, Q20, 0% N)
        seq_good = "A" * 1500
        qual_good = "5" * 1500  # '5' = 53 - 33 = Q20
        
        # Read 2: 超短序列 (800 bp)
        seq_short = "C" * 800
        qual_short = "5" * 800

        # Read 3: 超长嵌合序列 (2500 bp)
        seq_long = "G" * 2500
        qual_long = "5" * 2500

        # Read 4: 低质量序列 (1500 bp, Q7)
        seq_low_q = "T" * 1500
        qual_low_q = "(" * 1500  # '(' = 40 - 33 = Q7

        # Read 5: 高 N 比例序列 (1500 bp, 20% N)
        seq_high_n = "N" * 300 + "A" * 1200
        qual_high_n = "5" * 1500

        raw_reads = [
            ("read_good", seq_good, qual_good),
            ("read_short", seq_short, qual_short),
            ("read_long", seq_long, qual_long),
            ("read_low_q", seq_low_q, qual_low_q),
            ("read_high_n", seq_high_n, qual_high_n),
        ]

        clean_reads, report = self.filter.filter_reads(raw_reads)

        # 仅有 read_good 通过质控
        self.assertEqual(len(clean_reads), 1)
        self.assertEqual(clean_reads[0][0], "read_good")

        # 检查质控统计报表
        self.assertEqual(report.total_raw_reads, 5)
        self.assertEqual(report.passed_clean_reads, 1)
        self.assertEqual(report.dropped_len_short, 1)
        self.assertEqual(report.dropped_len_long, 1)
        self.assertEqual(report.dropped_low_quality, 1)
        self.assertEqual(report.dropped_excessive_n, 1)
        self.assertAlmostEqual(report.pass_rate_pct, 20.0, places=1)


if __name__ == "__main__":
    unittest.main()
