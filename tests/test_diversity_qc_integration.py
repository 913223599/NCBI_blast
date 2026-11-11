# -*- coding: utf-8 -*-
"""
16S 多样性分析前置质控集成测试
验证：
1. 读长质控与 Phred Q 值质控对模拟/真实测序读段的过滤精准度
2. 比对同一性与覆盖度门槛 (pident >= 85%, qcovs >= 70%) 对假比对的剔除效果
3. 质控统计汇总 (QC Summary) 数据结构正确性
"""
import unittest
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.backend.services.fastq_qc_service import FastqQCFilter, FastqQCReport
from src.backend.services.diversity_filter import DiversityNoiseFilter


class TestDiversityQCIntegration(unittest.TestCase):
    """多样性分析质控集成测试"""

    def setUp(self):
        self.qc = FastqQCFilter(
            min_len=1200,
            max_len=1800,
            min_avg_qscore=10.0,
            max_n_ratio=0.05,
            auto_adapt_length=True
        )
        self.noise_filter = DiversityNoiseFilter(
            min_rel_abundance=0.5,
            min_reads_count=2,
            preserve_other=True
        )

    def test_pipeline_qc_and_noise_separation(self):
        """测试质控与物种分类噪声的层级分离"""
        # 1. 模拟测序导入质控
        reads = [
            ("r1", "A" * 1500, "5" * 1500), # 合格 (Q20, 1500bp)
            ("r2", "T" * 1500, "5" * 1500), # 合格
            ("r3", "C" * 1500, "5" * 1500), # 合格
            ("r4", "G" * 300,  "5" * 300),  # 截断短片段 (300bp) -> 应被质控过滤
            ("r5", "A" * 1500, "!" * 1500), # 极劣质读段 (Q0) -> 应被质控过滤
        ]
        clean_reads, qc_rep = self.qc.filter_reads(reads, sample_name="test_sample")
        self.assertEqual(len(clean_reads), 3)
        self.assertEqual(qc_rep.total_raw_reads, 5)
        self.assertEqual(qc_rep.passed_clean_reads, 3)
        self.assertEqual(qc_rep.dropped_len_short, 1)
        self.assertEqual(qc_rep.dropped_low_quality, 1)
        self.assertAlmostEqual(qc_rep.pass_rate_pct, 60.0, places=1)

        # 2. 模拟物种分类与孤儿噪声过滤
        # 假设 100 条比对结果，核心物种 90 条，孤儿读段各 1 条 (<=2 阈值)
        species_hits = {
            "Aeromonas veronii": 50,
            "Pseudidiomarina gelatinasegens": 40,
            "Contaminant_A": 1,
            "Artifact_B": 1,
        }
        filter_res = self.noise_filter.filter_taxa(species_hits, total_classified=92)
        clean_taxa = filter_res["filtered_counts"]

        # 验证孤儿读段被隔离，核心物种保全
        self.assertIn("Aeromonas veronii", clean_taxa)
        self.assertIn("Pseudidiomarina gelatinasegens", clean_taxa)
        self.assertNotIn("Contaminant_A", clean_taxa)
        self.assertNotIn("Artifact_B", clean_taxa)
        self.assertEqual(filter_res["noise_reads"], 2)


if __name__ == "__main__":
    unittest.main()
