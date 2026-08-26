# -*- coding: utf-8 -*-
"""
外部文件导入与比对集成测试
"""
import sys
import unittest
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from src.analysis.protein_compare.engine import ProteinComparer


class TestExternalFileCompare(unittest.TestCase):
    """测试外部 GenBank / FASTA 文件的载入与跨样本比对"""

    def setUp(self):
        self.comparer = ProteinComparer()

    def test_load_external_gbk(self):
        """测试直接从外部生成的 BUCT551.gbk 载入蛋白质"""
        gbk_candidates = list(Path("results/annotations").glob("**/BUCT551.gbk"))
        if gbk_candidates:
            gbk_file = gbk_candidates[0]
            proteins, meta = self.comparer.load_proteins_from_file(gbk_file)
            self.assertGreater(len(proteins), 50)
            self.assertEqual(meta["cds_count"], len(proteins))
            self.assertGreater(meta["total_length"], 50000)

            # 测试与其他样本比对
            res = self.comparer.compare_two_samples(
                sample_a_name="External_BUCT551",
                sample_a_proteins=proteins,
                sample_b_name="External_BUCT551_Self",
                sample_b_proteins=proteins,
                target_category="tail_fiber"
            )
            self.assertGreater(res.identical_count, 0)


if __name__ == "__main__":
    unittest.main()
