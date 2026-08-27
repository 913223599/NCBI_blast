# -*- coding: utf-8 -*-
"""
泛基因组分析引擎单元测试 (test_pan_genomics_engine.py)
"""
import unittest
from pathlib import Path
from src.analysis.pan_genomics.types import (
    SampleInputItem,
    PanGenomicsRunRequest,
    PanGenomicsResult
)
from src.analysis.pan_genomics.engine import PanGenomicsEngine


class TestPanGenomicsEngine(unittest.TestCase):
    """测试多样本泛基因组与多维交叉对比引擎"""

    def setUp(self):
        self.engine = PanGenomicsEngine()

    def test_pan_genomics_mock_analysis(self):
        """测试 3 个样本的泛基因组正交聚类、生活史判定与尾丝对比"""
        # 构造 3 个模拟样本
        s1 = SampleInputItem(sample_id="SAMPLE_A", sample_name="Phage_Alpha", source_type="task")
        s2 = SampleInputItem(sample_id="SAMPLE_B", sample_name="Phage_Beta", source_type="task")
        s3 = SampleInputItem(sample_id="SAMPLE_C", sample_name="Phage_Gamma", source_type="task")

        req = PanGenomicsRunRequest(
            samples=[s1, s2, s3],
            identity_threshold=0.5,
            coverage_threshold=0.5
        )

        # 注入 mock 数据给 engine._load_sample_features
        def mock_load(s):
            if s.sample_id == "SAMPLE_A":
                return {
                    "sample_id": "SAMPLE_A",
                    "sample_name": "Phage_Alpha",
                    "features": [
                        {"id": "A1", "locus_tag": "A_001", "feature_type": "CDS", "product": "major capsid protein", "category": "Structural", "translation": "MKLLVAGSTAL", "start": 1, "end": 300, "strand": "+"},
                        {"id": "A2", "locus_tag": "A_002", "feature_type": "CDS", "product": "tail fiber protein", "category": "Structural", "translation": "MAASTTFIBERAAAA", "start": 301, "end": 900, "strand": "+"},
                        {"id": "A3", "locus_tag": "A_003", "feature_type": "CDS", "product": "endolysin", "category": "Lysis", "translation": "MKKLYSISENAAAA", "start": 901, "end": 1500, "strand": "+"},
                        {"id": "A4", "locus_tag": "A_004", "feature_type": "CDS", "product": "anti-CRISPR protein AcrIF1", "category": "Defense & Host Interaction", "translation": "MACRIFAAA", "start": 1501, "end": 1800, "strand": "+"},
                        {"id": "A5", "locus_tag": "A_005", "feature_type": "tRNA", "product": "tRNA-Arg(AGA)", "category": "Other Functional", "start": 1801, "end": 1875, "strand": "+"}
                    ],
                    "safety_audit": {
                        "anti_crispr_genes": [{"cds_id": "A_004", "source": "AcrIF1", "identity": 95.0}],
                        "amr_genes": [],
                        "virulent_factors": []
                    }
                }
            elif s.sample_id == "SAMPLE_B":
                return {
                    "sample_id": "SAMPLE_B",
                    "sample_name": "Phage_Beta",
                    "features": [
                        {"id": "B1", "locus_tag": "B_001", "feature_type": "CDS", "product": "major capsid protein", "category": "Structural", "translation": "MKLLVAGSTAL", "start": 1, "end": 300, "strand": "+"},
                        {"id": "B2", "locus_tag": "B_002", "feature_type": "CDS", "product": "tail fiber protein", "category": "Structural", "translation": "MAASTTFIBERBBBB", "start": 301, "end": 900, "strand": "+"},
                        {"id": "B3", "locus_tag": "B_003", "feature_type": "CDS", "product": "endolysin", "category": "Lysis", "translation": "MKKLYSISENBBBB", "start": 901, "end": 1500, "strand": "+"},
                        {"id": "B4", "locus_tag": "B_004", "feature_type": "CDS", "product": "tyrosine integrase", "category": "Replication & Repair", "translation": "MINTEGRASEBBB", "start": 1501, "end": 2200, "strand": "+"}
                    ],
                    "safety_audit": None
                }
            else:
                return {
                    "sample_id": "SAMPLE_C",
                    "sample_name": "Phage_Gamma",
                    "features": [
                        {"id": "C1", "locus_tag": "C_001", "feature_type": "CDS", "product": "major capsid protein", "category": "Structural", "translation": "MKLLVAGSTAL", "start": 1, "end": 300, "strand": "+"},
                        {"id": "C2", "locus_tag": "C_002", "feature_type": "CDS", "product": "tail spike protein", "category": "Structural", "translation": "MSPIKECCCC", "start": 301, "end": 900, "strand": "+"},
                        {"id": "C3", "locus_tag": "C_003", "feature_type": "CDS", "product": "ribonucleotide reductase", "category": "Metabolism & AMG", "translation": "MNRDAACCCC", "start": 901, "end": 1800, "strand": "+"}
                    ],
                    "safety_audit": None
                }

        self.engine._load_sample_features = mock_load

        res = self.engine.run_analysis(req)

        # 1. 验证宏观统计
        self.assertEqual(res.summary.total_samples, 3)
        self.assertGreater(res.summary.total_clusters, 0)
        
        # Major capsid 在 3 个样本全共有 -> 应归类为 Core
        capsid_cluster = next((c for c in res.clusters if "capsid" in c.representative_product.lower()), None)
        self.assertIsNotNone(capsid_cluster)
        self.assertEqual(capsid_cluster.cluster_type, "Core")
        self.assertEqual(capsid_cluster.sample_count, 3)

        # 2. 验证生活史分型
        alpha_life = next(l for l in res.lifestyles if l.sample_id == "SAMPLE_A")
        beta_life = next(l for l in res.lifestyles if l.sample_id == "SAMPLE_B")

        self.assertEqual(alpha_life.lifestyle, "Lytic")
        self.assertTrue(alpha_life.is_safe_for_therapy)
        self.assertEqual(beta_life.lifestyle, "Temperate")
        self.assertFalse(beta_life.is_safe_for_therapy)
        self.assertGreater(beta_life.integrase_count, 0)

        # 3. 验证尾部受体识别模块与 Identity 矩阵
        self.assertGreater(len(res.tail_proteins), 0)
        self.assertIn("SAMPLE_A", res.tail_identity_matrix)
        self.assertEqual(res.tail_identity_matrix["SAMPLE_A"]["SAMPLE_A"], 100.0)

        # 4. 验证裂解系统
        self.assertGreater(len(res.lysis_proteins), 0)

        # 5. 验证 AMG 代谢酶与 tRNA
        self.assertGreater(len(res.amg_genes), 0)
        self.assertIn("SAMPLE_A", res.trna_profiles)
        self.assertEqual(len(res.trna_profiles["SAMPLE_A"]), 1)


if __name__ == "__main__":
    unittest.main()
