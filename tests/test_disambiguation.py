# -*- coding: utf-8 -*-
"""
消歧与抗模糊碰撞测试套件
验证重构后的分类器能否抵御短词子串碰撞、复杂结构域重叠与假阳性误判
"""
import sys
import unittest
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from src.analysis.protein_compare.engine import ProteinComparer


class TestDisambiguationAndAntiCollision(unittest.TestCase):
    """消歧与抗子串碰撞测试"""

    def setUp(self):
        self.comparer = ProteinComparer()

    def test_substring_anti_collision(self):
        """测试防止子串碰撞（如 rz, pac, coat, ci 等短词误匹配）"""
        # oxidoreductase / crystallize 中含有 "rz" 字母序列，绝不能误判为 lysis
        self.assertEqual(self.comparer.classify_protein("NADH oxidoreductase"), "other")
        self.assertEqual(self.comparer.classify_protein("crystallization chaperone"), "other")

        # capacity / compaction 中含有 "pac"，绝不能误判为 packaging
        self.assertEqual(self.comparer.classify_protein("DNA compaction protein"), "other")
        self.assertEqual(self.comparer.classify_protein("heat capacity regulator"), "other")

        # coactivator 中含有 "coat"，绝不能误判为 capsid_head
        self.assertEqual(self.comparer.classify_protein("transcriptional coactivator"), "replication")

        # dehydrogenase / detail 绝不能误判
        self.assertEqual(self.comparer.classify_protein("glucose dehydrogenase"), "other")

    def test_domain_disambiguation_priority(self):
        """测试复杂结构域消歧与优先级仲裁"""
        # tail-associated lysozyme (尾部穿刺溶菌酶): 虽含 lysozyme，但属于尾丝宿主穿刺系统，优先归入 tail_fiber
        self.assertEqual(self.comparer.classify_protein("tail-associated lysozyme"), "tail_fiber")
        self.assertEqual(self.comparer.classify_protein("gp5 tailspike with lysozyme domain"), "tail_fiber")

        # maturation protease (衣壳成熟蛋白酶): 虽含 protease，但属于衣壳成熟系统，优先归入 capsid_head
        self.assertEqual(self.comparer.classify_protein("head maturation protease"), "capsid_head")
        self.assertEqual(self.comparer.classify_protein("prohead protease"), "capsid_head")

        # portal protein (门控蛋白): 明确归入 capsid_head
        self.assertEqual(self.comparer.classify_protein("capsid portal protein"), "capsid_head")

        # terminase: 最高优先级包装末端酶
        self.assertEqual(self.comparer.classify_protein("terminase large subunit"), "packaging")
        self.assertEqual(self.comparer.classify_protein("terminase small subunit"), "packaging")

    def test_hypothetical_exclusion(self):
        """测试未知与假定蛋白安全防护"""
        self.assertEqual(self.comparer.classify_protein("hypothetical protein"), "other")
        self.assertEqual(self.comparer.classify_protein("unknown"), "other")
        self.assertEqual(self.comparer.classify_protein("uncharacterized protein"), "other")
        self.assertEqual(self.comparer.classify_protein("putative protein"), "other")


if __name__ == "__main__":
    unittest.main()
