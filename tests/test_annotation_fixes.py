# -*- coding: utf-8 -*-
"""
功能注释修复专项单元测试 (TestAnnotationFixes)
验证:
1. is_unannotated 对各类未表征/假定蛋白的准确识别 (解决虚高与漏判)
2. GenBank 导出时保留 PHROG, function, score, inference 等标准 qualifier
3. 纯机器学习预测 (如 Acranker) 不会暴力修改假定蛋白的 product
"""
import sys
import unittest
from pathlib import Path
from Bio import SeqIO
from Bio.Seq import Seq
from Bio.SeqRecord import SeqRecord

project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from src.analysis.annotation.types import FeatureItem
from src.analysis.annotation.fuser import AnnotationFuser
from src.analysis.annotation.builtin_annotator import BuiltinAnnotator


class TestAnnotationFixes(unittest.TestCase):
    """测试功能注释关键缺陷修复"""

    def test_unannotated_patterns_coverage(self):
        """测试对各类假定蛋白与未表征蛋白的严格判定"""
        # 1. 基础假定蛋白
        self.assertTrue(AnnotationFuser.is_unannotated("hypothetical protein"))
        self.assertTrue(AnnotationFuser.is_unannotated("Hypothetical"))
        self.assertTrue(AnnotationFuser.is_unannotated("unknown protein"))
        self.assertTrue(AnnotationFuser.is_unannotated("putative uncharacterized protein"))

        # 2. 之前漏判的 Pharokka 原生 "unknown function"
        self.assertTrue(AnnotationFuser.is_unannotated("unknown function"))
        self.assertTrue(AnnotationFuser.is_unannotated("Unknown Function"))

        # 3. 之前漏判的 Swiss-Prot 基因间区未表征条目
        self.assertTrue(AnnotationFuser.is_unannotated("Uncharacterized 10.2 kDa protein in sp-Gp41 intergenic region"))
        self.assertTrue(AnnotationFuser.is_unannotated("Uncharacterized 8.3 kDa protein in mrh-soc intergenic region"))
        self.assertTrue(AnnotationFuser.is_unannotated("uncharacterized protein"))

        # 4. 之前漏判的占位名与无意义名称
        self.assertTrue(AnnotationFuser.is_unannotated("Phage protein"))
        self.assertTrue(AnnotationFuser.is_unannotated("phage protein"))
        self.assertTrue(AnnotationFuser.is_unannotated("gp52.1 conserved hypothetical predicted membrane protein"))
        self.assertTrue(AnnotationFuser.is_unannotated("conserved hypothetical protein"))
        self.assertTrue(AnnotationFuser.is_unannotated("DUF5417 domain-containing protein"))
        self.assertTrue(AnnotationFuser.is_unannotated("DUF3045 family protein"))
        self.assertTrue(AnnotationFuser.is_unannotated("protein GP45.2"))
        self.assertTrue(AnnotationFuser.is_unannotated("gp267"))

        # 5. 真实确切的已知功能蛋白应判定为 False (不是未注释)
        self.assertFalse(AnnotationFuser.is_unannotated("major capsid protein"))
        self.assertFalse(AnnotationFuser.is_unannotated("holin"))
        self.assertFalse(AnnotationFuser.is_unannotated("endolysin"))
        self.assertFalse(AnnotationFuser.is_unannotated("terminase large subunit"))
        self.assertFalse(AnnotationFuser.is_unannotated("tail fiber protein"))
        self.assertFalse(AnnotationFuser.is_unannotated("Anti-DarT factor A"))
        self.assertFalse(AnnotationFuser.is_unannotated("anti-CRISPR protein"))

    def test_gbk_export_preserves_phrog_qualifiers(self):
        """测试 export_features_to_files 导出 gbk 时正确写入 phrog / function / score / inference 标准 qualifier"""
        annotator = BuiltinAnnotator(prefix="TEST_ANNO")
        work_dir = project_root / "results" / "test_gbk_export_qualifiers"
        work_dir.mkdir(parents=True, exist_ok=True)

        rec = SeqRecord(Seq("ATGGCTAAACTGACCAAACGTCGCCGCCCGGCTCGTAAAAAACGTCTGCGTAAAAAACTGCGTAAAGCTGCTCGTGCTCGTGCTGCTGCTGCTGCTGCTGTTTAA"), id="Contig_1")
        
        feat = FeatureItem(
            id="TEST_0001",
            locus_tag="TEST_0001",
            feature_type="CDS",
            contig_id="Contig_1",
            start=1,
            end=108,
            strand="+",
            length_bp=108,
            product="DnaB-like replicative helicase",
            phrog="19",
            function="DNA, RNA and nucleotide metabolism",
            score="-186832600.0",
            inference="ab initio prediction:PHANOTATE:1.6.7",
            transl_table="11"
        )

        _, _, files = annotator.export_features_to_files(
            records=[rec],
            all_features=[feat],
            output_dir=work_dir
        )

        gbk_path = Path(files["gbk"])
        self.assertTrue(gbk_path.exists())

        parsed_rec = next(SeqIO.parse(gbk_path, "genbank"))
        cds_feats = [f for f in parsed_rec.features if f.type == "CDS"]
        self.assertEqual(len(cds_feats), 1)
        q = cds_feats[0].qualifiers

        self.assertIn("phrog", q)
        self.assertEqual(q["phrog"], ["19"])
        self.assertIn("function", q)
        self.assertEqual(q["function"], ["DNA, RNA and nucleotide metabolism"])
        self.assertIn("score", q)
        self.assertEqual(q["score"], ["-186832600.0"])
        self.assertIn("inference", q)
        self.assertEqual(q["inference"], ["ab initio prediction:PHANOTATE:1.6.7"])
        self.assertIn("transl_table", q)
        self.assertEqual(q["transl_table"], ["11"])

    def test_integrate_safety_audit_pure_prediction_no_overwrite(self):
        """测试纯机器学习预测 (如 Acranker) 不会将假定蛋白暴力改名为 anti-CRISPR protein"""
        feat = FeatureItem(
            id="CDS_TEST_01",
            locus_tag="CDS_TEST_01",
            feature_type="CDS",
            start=100,
            end=300,
            strand="+",
            length_bp=201,
            product="hypothetical protein"
        )

        safety_audit = {
            "anti_crispr_genes": [
                {
                    "cds_id": "CDS_TEST_01",
                    "target_id": "YP_010278434.1",
                    "identity": 95.0,
                    "evalue": "1e-30",
                    "source": "Acranker"
                }
            ]
        }

        upd = AnnotationFuser.integrate_safety_audit([feat], safety_audit)
        # 不应该因为纯 Acranker 预测把 product 改成 anti-CRISPR protein (Acranker)
        self.assertEqual(feat.product, "hypothetical protein")
        self.assertIn("Anti-CRISPR", feat.notes)
        self.assertIn("Acranker", feat.notes)

    def test_hypothetical_category_not_polluted_by_notes(self):
        """测试假定蛋白不会因 notes 中其他引擎的证据被归入功能大类"""
        notes = "[Pharokka] PHROG #622, Category: unknown function; [Phold AI] Phold Structure: DNA, RNA and nucleotide metabolism"
        self.assertEqual(AnnotationFuser.infer_category("unknown function", notes), "Hypothetical")
        self.assertEqual(AnnotationFuser.infer_category("Uncharacterized 7.2 kDa protein in Gp39-comCA intergenic region", notes), "Hypothetical")
        self.assertEqual(AnnotationFuser.infer_category("Phage protein", "[Phold AI] Phold Structure: lysis"), "Hypothetical")

    def test_known_product_category_product_first(self):
        """测试已知功能蛋白以 product 判定为准，notes 仅兜底"""
        # product 命中 Head，即使 notes 含 lysis 也不改判
        self.assertEqual(AnnotationFuser.infer_category("major capsid protein", "[Phold AI] Phold Structure: lysis"), "Head & Packaging")
        # product 命中 Defense (Anti-DarT)，即使 notes 含 lysis 也以 product 优先
        self.assertEqual(AnnotationFuser.infer_category("Anti-DarT factor A", "[Phold AI] Phold Structure: lysis"), "Defense & Host Interaction")
        # product 未命中任何规则，notes 兜底
        self.assertEqual(AnnotationFuser.infer_category("Custom factor X", "[Phold AI] Phold Structure: lysis"), "Lysis")
        self.assertEqual(AnnotationFuser.infer_category("Custom factor X", None), "Other Functional")


if __name__ == "__main__":
    unittest.main()
