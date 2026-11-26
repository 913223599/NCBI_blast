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
