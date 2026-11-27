# -*- coding: utf-8 -*-
"""
AnnotationPipeline 策略链、引擎降级与阶段诊断回归测试。
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from src.analysis.annotation import pipeline as pipeline_mod
from src.analysis.annotation.pipeline import AnnotationPipeline
from src.analysis.annotation.types import AnnotationRunRequest

pytestmark = pytest.mark.offline


def test_resolve_primary_engine_plan_for_auto_and_explicit() -> None:
    phage_plan = [k for k, _, _ in AnnotationPipeline._resolve_primary_engine_plan("auto", "PHAGE")]
    assert phage_plan == ["pharokka", "prodigal"]

    bact_plan = [k for k, _, _ in AnnotationPipeline._resolve_primary_engine_plan("auto", "BACTERIA")]
    assert bact_plan == ["prodigal"]

    explicit_plan = [k for k, _, _ in AnnotationPipeline._resolve_primary_engine_plan("prokka", "PHAGE")]
    assert explicit_plan == ["prokka"]

    assert AnnotationPipeline._resolve_primary_engine_plan("builtin", "PHAGE") == []


def test_annotation_pipeline_auto_fallback_to_builtin_offline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """当 Pharokka 与 Prodigal 均不可用时，自动降级至 BuiltinEngine 并完整落盘产物。"""

    class _UnavailableEngine:
        unavailable_reason = "mock unavailable"

        async def is_available(self) -> bool:
            return False

    monkeypatch.setattr(pipeline_mod, "PharokkaEngine", _UnavailableEngine)
    monkeypatch.setattr(pipeline_mod, "ProdigalEngine", _UnavailableEngine)
    monkeypatch.setattr(pipeline_mod.broadcaster, "broadcast_sync", lambda *a, **kw: None)
    monkeypatch.setattr(pipeline_mod.annotation_db, "update_progress", lambda *a, **kw: None)
    monkeypatch.setattr(pipeline_mod.annotation_db, "mark_completed", lambda *a, **kw: None)
    monkeypatch.setattr(pipeline_mod.annotation_db, "mark_failed", lambda *a, **kw: None)

    seq = "ATG" + ("GCT" * 60) + "TAA"
    req = AnnotationRunRequest(
        fasta_content=f">Phage_Test_1\n{seq}\n",
        sample_type="PHAGE",
        engine="auto",
        min_contig_len=50,
        enable_homology=False,
        enable_phold=False,
        enable_safety_audit=False,
    )
    pipe = AnnotationPipeline(task_id="ANNO_UNIT_TEST", work_dir=tmp_path / "anno_work")
    res: dict[str, Any] = asyncio.run(pipe.execute(req))

    assert res["task_id"] == "ANNO_UNIT_TEST"
    assert Path(res["files"]["summary_json"]).is_file()
    assert Path(res["files"]["features_json"]).is_file()
    stages = {d["stage"]: d["status"] for d in pipe.diagnostics}
    assert stages["阶段1 主引擎 Pharokka"] == "skipped"
    assert stages["阶段1 主引擎 Prodigal"] == "skipped"
    assert stages["阶段1 基础特征预测"] == "ok"
    assert stages["阶段2 同源打捞"] == "skipped"
    assert stages["阶段6 生物安全审计"] == "skipped"


def test_deep_safety_auditor_offline_scans_and_error_tolerance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """验证 DeepSafetyAuditor 在模拟 PhageScope/CARD/VFDB 库与异常坏行下的评级逻辑。"""
    import subprocess
    from types import SimpleNamespace

    from src.analysis.annotation import deep_audit as deep_audit_mod
    from src.analysis.annotation.deep_audit import DeepSafetyAuditor
    from src.workbench.models.tool_config import ToolConfig

    db_root = tmp_path / "db"
    ps_dir = db_root / "phagescope"
    card_dir = db_root / "card"
    vfdb_dir = db_root / "vfdb"
    for d, prefix in (
        (ps_dir, "phagescope_proteins.pin"),
        (card_dir, "card_protein.pin"),
        (vfdb_dir, "vfdb.pin"),
    ):
        d.mkdir(parents=True, exist_ok=True)
        (d / prefix).write_bytes(b"stub")

    for sub, header, rows in (
        ("amr", "Protein_id\tAligned_Protein_in_CARD", ["PS_AMR_1\tBeta-lactamase"]),
        ("virulent_factor", "Protein_id\tAligned_Protein_in_VFDB", ["PS_VF_1\tToxinA"]),
        ("anti_crispr", "Protein_ID\tSource", ["PS_ACR_LOW\tAcranker ML", "PS_ACR_HI\tExperiment"]),
    ):
        meta_sub = ps_dir / "metadata" / sub
        meta_sub.mkdir(parents=True, exist_ok=True)
        (meta_sub / "meta.tsv").write_text("\n".join([header, *rows]) + "\n", encoding="utf-8")

    def _mock_get_db_dir(name: str) -> Path:
        return {"phagescope": ps_dir, "card": card_dir, "vfdb": vfdb_dir}[name]

    monkeypatch.setattr(ToolConfig, "get_db_dir", staticmethod(_mock_get_db_dir))
    monkeypatch.setattr(ToolConfig, "resolve_bio_tool", staticmethod(lambda name: "/usr/bin/blastp"))

    auditor = DeepSafetyAuditor(root_dir=tmp_path)
    work_dir = tmp_path / "work"
    work_dir.mkdir(parents=True, exist_ok=True)

    # 1. 空文件直接 SAFE 返回
    empty_faa = tmp_path / "empty.faa"
    empty_faa.write_text("", encoding="utf-8")
    assert auditor.run_safety_audit(empty_faa, work_dir)["safety_passed"] is True

    # 2. 模拟三库 blastp 输出（含 <40% 过滤项与无法转 float 的坏行）
    query_faa = tmp_path / "proteins.faa"
    query_faa.write_text(">cds_1\nMKKK\n>cds_2\nMLLL\n", encoding="utf-8")

    def _fake_run(cmd: list[str], **kwargs: Any) -> SimpleNamespace:
        db_name = cmd[cmd.index("-db") + 1]
        out_path = Path(cmd[cmd.index("-out") + 1])
        if db_name == "phagescope_proteins":
            out_path.write_text(
                "\n".join(
                    [
                        "cds_1\tPS_AMR_1\t92.5\t120\t1e-50\t220.0\tamr_hit",
                        "cds_2\tPS_ACR_HI\t88.0\t90\t1e-30\t160.0\tacr_hit",
                        "cds_bad\tPS_VF_1\tnot_a_float\t50\t1e-12\t80.0\tbad_row",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
        elif db_name == "card_protein":
            out_path.write_text(
                "\n".join(
                    [
                        "cds_1\tCARD_1\t35.0\t80\t1e-12\t90.0\tbelow_40_ignored",
                        "cds_3\tCARD_2\t75.0\t150\t1e-40\t180.0\tMexB efflux",
                        "cds_bad\tCARD_BAD\tbad_num\t50\t1e-12\t70.0\tbad",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
        elif db_name == "vfdb":
            out_path.write_text(
                "cds_4\tVF_1\t65.0\t100\t1e-25\t140.0\tHemolysin\n",
                encoding="utf-8",
            )
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(deep_audit_mod.subprocess, "run", _fake_run)
    res = auditor.run_safety_audit(query_faa, work_dir, threads=2)

    assert res["safety_passed"] is False
    assert {h["cds_id"] for h in res["amr_genes"]} == {"cds_1", "cds_3"}
    assert [h["cds_id"] for h in res["virulent_factors"]] == ["cds_4"]
    assert len(res["anti_crispr_genes"]) == 1
    assert "Detected (1 high-confidence Acr genes)" == res["anti_crispr_status"]
    assert len(res["risk_warnings"]) == 2

    # 3. 模拟 Acranker 低置信 Acr 且 blastp 超时异常时安全降级
    def _timeout_or_low_acr(cmd: list[str], **kwargs: Any) -> SimpleNamespace:
        db_name = cmd[cmd.index("-db") + 1]
        out_path = Path(cmd[cmd.index("-out") + 1])
        if db_name == "phagescope_proteins":
            out_path.write_text(
                "cds_5\tPS_ACR_LOW\t55.0\t60\t1e-15\t95.0\tacr_ml\n",
                encoding="utf-8",
            )
            return SimpleNamespace(returncode=0)
        raise subprocess.TimeoutExpired(cmd=cmd, timeout=180)

    monkeypatch.setattr(deep_audit_mod.subprocess, "run", _timeout_or_low_acr)
    res2 = auditor.run_safety_audit(query_faa, work_dir, threads=2)
    assert res2["safety_passed"] is True
    assert "Candidate Predicted (1 ML predictions, low confidence)" == res2["anti_crispr_status"]

    # 4. 缺失 blastp 时标记 diagnostics 并返回 SAFE
    monkeypatch.setattr(ToolConfig, "resolve_bio_tool", staticmethod(lambda name: None))
    auditor_no_bin = DeepSafetyAuditor(root_dir=tmp_path)
    res3 = auditor_no_bin.run_safety_audit(query_faa, work_dir)
    assert res3["safety_passed"] is True
    assert auditor_no_bin.diagnostics["blastp"] == "missing"
