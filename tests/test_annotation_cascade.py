# -*- coding: utf-8 -*-
"""
多引擎流式级联互补注释流水线单元与集成测试 (TestAnnotationCascade)
"""
import sys
import os
import asyncio
import unittest
from pathlib import Path
from typing import Dict, Any, List

# 确保项目根目录在 sys.path 中
project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from src.analysis.annotation.types import AnnotationRunRequest, FeatureItem
from src.analysis.annotation.fuser import AnnotationFuser
from src.analysis.annotation.pipeline import AnnotationPipeline


class TestAnnotationCascade(unittest.IsolatedAsyncioTestCase):
    """测试多引擎流式级联互补机制"""

    def setUp(self):
        self.test_work_dir = project_root / "results" / "test_annotation_workdir"
        self.test_work_dir.mkdir(parents=True, exist_ok=True)

    def test_fuser_unannotated_detection(self):
        """测试未注释与假定蛋白判断"""
        self.assertTrue(AnnotationFuser.is_unannotated("hypothetical protein"))
        self.assertTrue(AnnotationFuser.is_unannotated("Hypothetical"))
        self.assertTrue(AnnotationFuser.is_unannotated("unknown protein"))
        self.assertTrue(AnnotationFuser.is_unannotated("putative uncharacterized protein"))
        self.assertTrue(AnnotationFuser.is_unannotated(""))
        self.assertTrue(AnnotationFuser.is_unannotated(None))

        self.assertFalse(AnnotationFuser.is_unannotated("DNA polymerase III"))
        self.assertFalse(AnnotationFuser.is_unannotated("major capsid protein"))
        self.assertFalse(AnnotationFuser.is_unannotated("terminase large subunit"))

    def test_fuser_category_inference(self):
        """测试生物学功能大类推断"""
        self.assertEqual(AnnotationFuser.infer_category("terminase large subunit"), "Packaging")
        self.assertEqual(AnnotationFuser.infer_category("major capsid protein"), "Structural")
        self.assertEqual(AnnotationFuser.infer_category("tail fiber protein"), "Structural")
        self.assertEqual(AnnotationFuser.infer_category("endolysin"), "Lysis")
        self.assertEqual(AnnotationFuser.infer_category("DNA polymerase"), "Replication & Repair")
        self.assertEqual(AnnotationFuser.infer_category("hypothetical protein"), "Hypothetical")

    def test_fuser_complement_feature(self):
        """测试单个特征的互补与证据链整合"""
        base = FeatureItem(
            id="ANNO_00001",
            locus_tag="ANNO_00001",
            feature_type="CDS",
            start=100,
            end=1000,
            strand="+",
            length_bp=901,
            product="hypothetical protein"
        )

        candidate = {
            "product": "tail tape measure protein",
            "gene_name": "tmp",
            "ec_number": "3.4.21.-",
            "evidence": "BLASTP hit to RefSeq NP_001 (Identity: 98%)"
        }

        updated = AnnotationFuser.complement_single_feature(base, candidate, engine_name="PhageScope")
        self.assertTrue(updated)
        self.assertEqual(base.product, "tail tape measure protein")
        self.assertEqual(base.gene_name, "tmp")
        self.assertEqual(base.ec_number, "3.4.21.-")
        self.assertEqual(base.category, "Structural")
        self.assertEqual(base.source_engine, "PhageScope")
        self.assertTrue(len(base.evidence_sources) > 0)
        self.assertIn("PhageScope", base.notes)

    async def test_pipeline_streaming_execution(self):
        """测试流水线端到端流式执行"""
        test_fasta_content = """>Test_Contig_1
ATGAAACGCATTAGCACCACCATTACCACCACCATCACCATTACCACAGGTAACGGTGCGGGCTGACGTATCGCGATCATGGCGATGCTGGCGTGCCTGGCTATCACCGTGATCGTCGCGATCCTGGTGCGTAAACCGGTTCTGCCGAACAAAGTTGTTGGTGTGACCACCCTGACCGATGACATCCTGCTGCTGAAATAG
>Test_Contig_2
ATGGCTAAACTGACCAAACGTCGCCGCCCGGCTCGTAAAAAACGTCTGCGTAAAAAACTGCGTAAAGCTGCTCGTGCTCGTGCTGCTGCTGCTGCTGCTGTTTAA
"""
        req = AnnotationRunRequest(
            task_name="Test_Streaming_Waterfall",
            sample_type="PHAGE",
            engine="builtin",
            fasta_content=test_fasta_content,
            prefix="TEST",
            min_contig_len=50,
            enable_waterfall=True,
            enable_homology=True,
            enable_safety_audit=False
        )

        pipeline = AnnotationPipeline(task_id="TEST_TASK_001", work_dir=self.test_work_dir)
        res = await pipeline.execute(req)

        self.assertIn("summary", res)
        self.assertIn("files", res)
        self.assertTrue(res["feature_count"] > 0)
        self.assertTrue(Path(res["files"]["gbk"]).exists())
        self.assertTrue(Path(res["files"]["tsv"]).exists())
        self.assertTrue(Path(res["files"]["features_json"]).exists())


if __name__ == "__main__":
    unittest.main()
