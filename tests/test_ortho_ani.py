# -*- coding: utf-8 -*-
"""
test_ortho_ani.py - 国际标准全基因组 OrthoANI 与正交 OrthoAAI 自动化验证测试
遵循 ICTV 噬菌体分类规范与 OrthoANIu (Lee et al., 2016) 算法金标准
"""

import sys
import unittest
import random
from pathlib import Path

# 添加项目根目录到导入路径
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from src.analysis.pan_genomics.ani_calculator import OrthoANICalculator


class TestOrthoANI(unittest.TestCase):
    def setUp(self):
        self.calc = OrthoANICalculator(
            slice_len=1020,
            min_identity=70.0,
            min_coverage=0.5,
            min_rbh_count=3,
            min_af_threshold=5.0
        )
        random.seed(2026)
        self.bases = ['A', 'C', 'G', 'T']

    def test_self_identity(self):
        """测试 1: 自身对照恒为 100.0%，AF 恒为 100.0%"""
        seq = ''.join(random.choices(self.bases, k=5100))
        res = self.calc.compute_matrix(['sample_A'], {'sample_A': seq})
        self.assertEqual(res['ani_matrix']['sample_A']['sample_A'], 100.0)
        self.assertEqual(res['af_matrix']['sample_A']['sample_A'], 100.0)

    def test_subspecies_snp_precision(self):
        """测试 2: 亲缘相近包含微小 SNP 的株系，ANI 输出精细浮点数，杜绝取整抹平变异"""
        s1 = ''.join(random.choices(self.bases, k=5100))
        s2_list = list(s1)
        # 引入约 0.4% 的随机点突变 (20 个碱基替换)
        for _ in range(20):
            pos = random.randint(0, len(s2_list) - 1)
            s2_list[pos] = random.choice([b for b in self.bases if b != s2_list[pos]])
        s2 = ''.join(s2_list)

        res = self.calc.compute_matrix(['s1', 's2'], {'s1': s1, 's2': s2})
        ani_val = res['ani_matrix']['s1']['s2']
        af_val = res['af_matrix']['s1']['s2']

        self.assertIsNotNone(ani_val)
        self.assertGreaterEqual(ani_val, 99.0)
        self.assertLess(ani_val, 100.0)  # 严格验证不是取整的 100.0
        self.assertEqual(af_val, 100.0)
        self.assertIn("Same Species", res['taxonomy_matrix']['s1']['s2'])

    def test_different_lengths_no_dilution(self):
        """测试 3: 基因组长度不同时，ANI 保持核心区同源度，不被长序列分母稀释"""
        # s1: 3060 bp (3 个切片)
        s1 = ''.join(random.choices(self.bases, k=3060))
        # s2: 包含完全相同的 3060 bp，外加 3060 bp 差异序列 (总长 6120 bp)
        s2 = s1 + ''.join(random.choices(self.bases, k=3060))

        res = self.calc.compute_matrix(['s1', 's2'], {'s1': s1, 's2': s2})
        ani_val = res['ani_matrix']['s1']['s2']
        af_val = res['af_matrix']['s1']['s2']

        self.assertIsNotNone(ani_val)
        self.assertEqual(ani_val, 100.0)  # 核心同源区段保持 100.0%
        self.assertAlmostEqual(af_val, 66.7, delta=1.0)  # 覆盖度正确反映 4080 / 9180 比例

    def test_distinct_genus_reporting(self):
        """测试 4: 远缘异属样本，ANI 规范输出 None (前端显示 -/NA)，杜绝 0%/1% 伪低值"""
        s1 = ''.join(random.choices(self.bases, k=5100))
        s2 = ''.join(random.choices(self.bases, k=5100))

        res = self.calc.compute_matrix(['s1', 's2'], {'s1': s1, 's2': s2})
        ani_val = res['ani_matrix']['s1']['s2']
        self.assertIsNone(ani_val)  # 规范输出 None
        self.assertIn("Distinct Genus", res['taxonomy_matrix']['s1']['s2'])

    def test_protein_ortho_aai_mode(self):
        """测试 5: 当缺乏 DNA 仅有蛋白质时，运行严格双向 BBH 的 OrthoAAI"""
        prot1 = [
            ("MKVLWAALLVTFLAGCQAKVEQAVETEPEPELRQQTEWQSGQ", None),
            ("MNIKESLKAISSAVELGIKSVEQIKDAVELGIKSVEQIKDAV", None),
            ("MSKGEELFTGVVPILVELDGDVNGHKFSVSGEGEGDATYGKL", None)
        ]
        # prot2 包含 1 个完全相同，1 个 95% 相似，1 个无关蛋白
        prot2 = [
            ("MKVLWAALLVTFLAGCQAKVEQAVETEPEPELRQQTEWQSGQ", None),
            ("MNIKESLKAISSAVELGIKSVEQIKDAVELGIKSVEQIKDAA", None),  # 1 aa 突变
            ("MWWWRRRTTTKKKLLLPPPQQQAAASSSDDDFFFGGGHHHJJ", None)
        ]

        calc = OrthoANICalculator()
        res = calc.calculate_ortho_aai_pair("p1", "p2", prot1, prot2)
        self.assertIsNotNone(res['ani'])
        self.assertGreater(res['ani'], 95.0)
        self.assertEqual(res['rbh_count'], 2)  # 2 个正交 BBH 命中


if __name__ == '__main__':
    unittest.main()
