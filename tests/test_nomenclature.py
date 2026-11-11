# -*- coding: utf-8 -*-
"""
验证跨注释引擎命名兼容性测试
"""
import sys
import unittest
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from src.analysis.protein_compare.engine import ProteinComparer


class TestNomenclatureCompatibility(unittest.TestCase):
    """测试各大注释程序多样化命名的归类兼容性"""

    def setUp(self):
        self.comparer = ProteinComparer()

    def test_pharokka_phrogs_naming(self):
        """测试 Pharokka & PHROGs 命名风格"""
        self.assertEqual(self.comparer.classify_protein("tail length tape measure protein"), "tail_fiber")
        self.assertEqual(self.comparer.classify_protein("major capsid protein"), "capsid_head")
        self.assertEqual(self.comparer.classify_protein("terminase large subunit"), "packaging")
        self.assertEqual(self.comparer.classify_protein("endolysin"), "lysis")
        self.assertEqual(self.comparer.classify_protein("DNA polymerase"), "replication")
        self.assertEqual(self.comparer.classify_protein("spanin"), "lysis")
        self.assertEqual(self.comparer.classify_protein("HNH endonuclease"), "replication")

    def test_phold_ai_naming(self):
        """测试 Phold AI (Foldseek / ESMFold) 命名风格"""
        self.assertEqual(self.comparer.classify_protein("Phold: putative tail fiber protein"), "tail_fiber")
        self.assertEqual(self.comparer.classify_protein("Phold: capsid portal protein"), "capsid_head")
        self.assertEqual(self.comparer.classify_protein("Phold: holin-like protein"), "lysis")
        self.assertEqual(self.comparer.classify_protein("putative tail length tape measure"), "tail_fiber")

    def test_prokka_ncbi_refseq_naming(self):
        """测试 Prokka / NCBI RefSeq / GenBank 命名风格"""
        self.assertEqual(self.comparer.classify_protein("N-acetylmuramoyl-L-alanine amidase"), "lysis")
        self.assertEqual(self.comparer.classify_protein("phage baseplate wedge subunit"), "tail_fiber")
        self.assertEqual(self.comparer.classify_protein("ATP-dependent DNA helicase"), "replication")
        self.assertEqual(self.comparer.classify_protein("single-stranded DNA-binding protein"), "replication")
        self.assertEqual(self.comparer.classify_protein("portal protein"), "capsid_head")
        self.assertEqual(self.comparer.classify_protein("head maturation protease"), "capsid_head")
        self.assertEqual(self.comparer.classify_protein("tailspike protein"), "tail_fiber")
        self.assertEqual(self.comparer.classify_protein("receptor-binding protein"), "tail_fiber")
        self.assertEqual(self.comparer.classify_protein("site-specific integrase"), "replication")
        self.assertEqual(self.comparer.classify_protein("small subunit terminase"), "packaging")


if __name__ == "__main__":
    unittest.main()
