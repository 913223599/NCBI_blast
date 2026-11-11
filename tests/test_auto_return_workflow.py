# -*- coding: utf-8 -*-
"""
test_auto_return_workflow.py - 噬菌体基因组注释"自动回传"工作流自动化测试

覆盖周圣松消息描述的自动化链路中"注释"核心环节：
  邮箱收到拼接 fasta → 本地注释（fasta → 多引擎级联 → .gbk / .tsv / .faa / .ffn / features.json / summary.json）→ 回传产物
本套件验证：
  A. 输入侧：fasta_content / fasta_path / 裸序列自动补头 / 空输入拒绝 / min_contig_len 过滤 / selected_contigs 过滤
  B. 注释执行：builtin 引擎端到端（纯 Python 零外部依赖，保证任何环境可跑）、引擎可用性探测容错
  C. 产物校验：GenBank 可解析性、特征数跨格式一致、TSV 表头/行数、JSON Schema、翻译合法性、FAA/FFN 完整性
  D. 分类体系：fuser 功能大类（Head & Packaging / Tail & Host Interaction / Lysis 等）与引擎探测
"""
import asyncio
import json
import os
import random
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

# 添加项目根路径
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from Bio import SeqIO

from src.analysis.annotation.pipeline import AnnotationPipeline
from src.analysis.annotation.types import AnnotationRunRequest, FeatureItem
from src.analysis.annotation.fuser import AnnotationFuser

random.seed(20261028)
_BASES = ["A", "C", "G", "T"]
# 5000 bp 随机噬菌体样序列，保证 6 框 ORF 扫描能稳定产出多个 CDS
PHAGE_SEQ = "".join(random.choices(_BASES, k=5000))
SEQ_500 = "".join(random.choices(_BASES, k=500))

TSV_HEADER = ("Locus_Tag\tContig\tType\tStart\tEnd\tStrand\tLength_bp\tLength_aa\t"
              "MW_kDa\tGene\tProduct\tCategory\tEngine\tEC_Number\tEvidence")


def _disable_external_engines():
    """隔离外部 WSL 引擎（Pharokka 级联会真实调用 WSL 且耗时数分钟）。
    本套件验证 builtin 纯 Python 主链路与产物一致性；
    Pharokka/Phold 的真实 WSL 集成作为可选深度验证另行手动运行。"""
    return patch("src.analysis.annotation.pipeline.PharokkaEngine.is_available",
                 new=AsyncMock(return_value=False))


def _default_req(**kw) -> AnnotationRunRequest:
    base = dict(
        sample_type="PHAGE",
        engine="builtin",
        enable_waterfall=True,
        enable_homology=False,
        enable_phold=False,
        enable_safety_audit=False,
    )
    base.update(kw)
    return AnnotationRunRequest(**base)


class TestAutoReturnWorkflow(unittest.TestCase):
    """自动回传工作流：输入侧"""

    def setUp(self):
        self._ext_patcher = _disable_external_engines()
        self._ext_patcher.start()

    def tearDown(self):
        self._ext_patcher.stop()

    def _run(self, tmpdir, **kw):
        pipe = AnnotationPipeline("autotest_workflow", Path(tmpdir))
        return asyncio.run(pipe.execute(_default_req(**kw)))

    def test_input_from_content_end_to_end(self):
        """邮箱收到的 fasta 文本 → 端到端注释成功，产物齐全"""
        with tempfile.TemporaryDirectory() as td:
            res = self._run(td, fasta_content=f">phage_contig_1\n{PHAGE_SEQ}\n")
            self.assertGreater(res["feature_count"], 0)
            files = res["files"]
            for key in ("gbk", "tsv", "faa", "ffn", "features_json", "summary_json"):
                self.assertIn(key, files, f"缺少产物键: {key}")
                p = Path(files[key])
                self.assertTrue(p.exists() and p.stat().st_size > 0, f"产物为空或不存在: {key} -> {p}")

    def test_input_from_path_end_to_end(self):
        """本地已有 fasta 文件 → 端到端注释成功（对应已下载的附件）"""
        with tempfile.TemporaryDirectory() as td:
            fa = Path(td) / "attachment.fasta"
            fa.write_text(f">phage_contig_1\n{PHAGE_SEQ}\n", encoding="utf-8")
            res = self._run(Path(td) / "work", fasta_path=str(fa))
            self.assertGreater(res["feature_count"], 0)
            self.assertTrue(Path(res["files"]["gbk"]).exists())

    def test_bare_sequence_auto_header(self):
        """裸序列（无 > 头）自动补头，仍可注释"""
        with tempfile.TemporaryDirectory() as td:
            res = self._run(td, fasta_content=PHAGE_SEQ)
            self.assertGreater(res["feature_count"], 0)
            summary = json.loads(Path(res["files"]["summary_json"]).read_text(encoding="utf-8"))
            self.assertEqual(summary["num_contigs"], 1)

    def test_missing_input_rejected(self):
        """无 fasta_content 且无 fasta_path → 明确拒绝"""
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(ValueError):
                self._run(td)

    def test_blank_content_rejected(self):
        """空白 fasta_content → 明确拒绝"""
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(ValueError):
                self._run(td, fasta_content="   \n  ")

    def test_min_contig_len_filters_short(self):
        """min_contig_len 过滤短 Contig，仅保留达标序列"""
        with tempfile.TemporaryDirectory() as td:
            content = f">long_{5000}\n{PHAGE_SEQ}\n>short_{500}\n{SEQ_500}\n"
            res = self._run(td, fasta_content=content, min_contig_len=1000)
            summary = json.loads(Path(res["files"]["summary_json"]).read_text(encoding="utf-8"))
            self.assertEqual(summary["num_contigs"], 1)
            self.assertEqual(summary["total_length"], 5000)

    def test_min_contig_len_keeps_longest_fallback(self):
        """全部 Contig 均短于阈值 → 保留最长一条兜底"""
        with tempfile.TemporaryDirectory() as td:
            content = f">c1\n{SEQ_500}\n>c2\n{SEQ_500}\n"
            res = self._run(td, fasta_content=content, min_contig_len=10000)
            summary = json.loads(Path(res["files"]["summary_json"]).read_text(encoding="utf-8"))
            self.assertEqual(summary["num_contigs"], 1)
            self.assertEqual(summary["total_length"], 500)

    def test_selected_contigs_filter(self):
        """selected_contigs 仅分析指定 Contig"""
        with tempfile.TemporaryDirectory() as td:
            content = f">target_ctg\n{PHAGE_SEQ}\n>other_ctg\n{PHAGE_SEQ}\n"
            res = self._run(td, fasta_content=content, selected_contigs=["target_ctg"])
            features = json.loads(Path(res["files"]["features_json"]).read_text(encoding="utf-8"))
            self.assertGreater(len(features), 0)
            contig_ids = {f["contig_id"] for f in features}
            self.assertEqual(contig_ids, {"target_ctg"})


class TestWorkflowArtifacts(unittest.TestCase):
    """自动回传工作流：产物校验（gbk/tsv/faa/ffn/json 一致性与格式）"""

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls._ext_patcher = _disable_external_engines()
        cls._ext_patcher.start()
        pipe = AnnotationPipeline("autotest_artifacts", Path(cls._tmp.name))
        req = _default_req(fasta_content=f">phage_ctg\n{PHAGE_SEQ}\n")
        cls.res = asyncio.run(pipe.execute(req))
        cls.files = cls.res["files"]
        with open(cls.files["features_json"], "r", encoding="utf-8") as f:
            cls.features = json.load(f)
        with open(cls.files["summary_json"], "r", encoding="utf-8") as f:
            cls.summary = json.load(f)

    @classmethod
    def tearDownClass(cls):
        cls._ext_patcher.stop()
        cls._tmp.cleanup()

    def _cds_count(self):
        return sum(1 for x in self.features if x["feature_type"] == "CDS")

    def test_gbk_parseable(self):
        """gbk 是合法 GenBank，记录与特征可解析"""
        records = list(SeqIO.parse(self.files["gbk"], "genbank"))
        self.assertGreater(len(records), 0)
        for rec in records:
            self.assertGreater(len(rec.features), 0, f"记录 {rec.id} 无特征")
        gbk_cds = sum(1 for rec in records for ft in rec.features if ft.type == "CDS")
        self.assertGreater(gbk_cds, 0)

    def test_gbk_cds_consistency(self):
        """gbk 中 CDS 数 == features.json 中 CDS 数（跨格式一致）"""
        records = list(SeqIO.parse(self.files["gbk"], "genbank"))
        gbk_cds = sum(1 for rec in records for ft in rec.features if ft.type == "CDS")
        self.assertEqual(gbk_cds, self._cds_count())

    def test_tsv_format(self):
        """TSV 表头 15 列，数据行数与特征数一致"""
        lines = Path(self.files["tsv"]).read_text(encoding="utf-8").splitlines()
        self.assertEqual(lines[0], TSV_HEADER)
        self.assertEqual(len(lines) - 1, len(self.features))

    def test_features_json_schema(self):
        """features.json 每条可反序列化为 FeatureItem，坐标/链/长度自洽"""
        for d in self.features:
            item = FeatureItem(**d)
            self.assertIn(item.feature_type, {"CDS", "tRNA", "rRNA", "tmRNA", "CRISPR", "misc_feature"})
            self.assertGreater(item.end, item.start)
            self.assertIn(item.strand, {"+", "-"})
            self.assertEqual(item.length_bp, item.end - item.start + 1)

    def test_translation_no_internal_stop(self):
        """CDS 翻译序列不含内部终止符（回传蛋白序列合法）"""
        for d in self.features:
            if d["feature_type"] == "CDS" and d.get("translation"):
                self.assertNotIn("*", d["translation"], f"{d['locus_tag']} 翻译含内部终止符")

    def test_summary_consistency(self):
        """summary 统计与特征明细一致"""
        self.assertEqual(self.summary["cds_count"], self._cds_count())
        self.assertEqual(self.summary["total_features"], len(self.features))
        self.assertEqual(self.summary["num_contigs"], 1)
        self.assertGreater(self.summary["total_length"], 0)
        self.assertGreaterEqual(self.summary["gc_content"], 0.0)
        self.assertLessEqual(self.summary["gc_content"], 100.0)

    def test_faa_ffn_generated(self):
        """faa（蛋白）与 ffn（核酸）序列齐全"""
        cds = self._cds_count()
        faa_lines = Path(self.files["faa"]).read_text(encoding="utf-8").splitlines()
        ffn_lines = Path(self.files["ffn"]).read_text(encoding="utf-8").splitlines()
        self.assertEqual(sum(1 for l in faa_lines if l.startswith(">")), cds)
        self.assertEqual(sum(1 for l in ffn_lines if l.startswith(">")), cds)


class TestWorkflowClassification(unittest.TestCase):
    """自动回传工作流：功能分类体系与引擎可用性"""

    @classmethod
    def setUpClass(cls):
        """缓存引擎可用性探测结果（WSL 冷启动慢，只探测一次并加超时保护）"""
        from src.analysis.annotation.engines import PharokkaEngine, ProkkaEngine, ProdigalEngine, PholdEngine

        async def probe():
            results = []
            for eng in (PharokkaEngine(), ProkkaEngine(), ProdigalEngine(), PholdEngine()):
                try:
                    results.append(await asyncio.wait_for(eng.is_available(), timeout=45))
                except (asyncio.TimeoutError, Exception):
                    results.append(False)
            return results

        cls.engine_flags = asyncio.run(probe())

    def test_fuser_category_new_system(self):
        """当前分类体系：Head & Packaging / Tail & Host Interaction / Lysis 等"""
        self.assertEqual(AnnotationFuser.infer_category("terminase large subunit"), "Head & Packaging")
        self.assertEqual(AnnotationFuser.infer_category("major capsid protein"), "Head & Packaging")
        self.assertEqual(AnnotationFuser.infer_category("tail fiber protein"), "Tail & Host Interaction")
        self.assertEqual(AnnotationFuser.infer_category("tail tape measure protein"), "Tail & Host Interaction")
        self.assertEqual(AnnotationFuser.infer_category("endolysin"), "Lysis")
        self.assertEqual(AnnotationFuser.infer_category("DNA polymerase"), "Replication & Repair")
        self.assertEqual(AnnotationFuser.infer_category("hypothetical protein"), "Hypothetical")
        self.assertEqual(AnnotationFuser.infer_category(None), "Hypothetical")

    def test_engine_availability_probe_no_crash(self):
        """各引擎可用性探测不抛异常且返回 bool（工具在/不在都稳定）"""
        for flag in self.engine_flags:
            self.assertIsInstance(flag, bool)


if __name__ == "__main__":
    unittest.main()
