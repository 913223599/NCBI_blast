# -*- coding: utf-8 -*-
"""PholdEngine GPU 诊断、显存回收与 SequenceAnnotator WSL 上下文一致性测试。"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from src.analysis.annotation.engines.phold_engine import PholdEngine  # noqa: E402
from src.analysis.annotation.types import FeatureItem  # noqa: E402
from src.analysis.phage_structure import sequence_annotator  # noqa: E402


def test_parse_gpu_probe_output_valid_and_invalid() -> None:
    payload = {
        "has_wsl_gpu": True,
        "python_bin": "/usr/bin/python3",
        "torch_version": "2.11.0+cu130",
        "cuda_available": True,
        "kernel_ok": True,
        "device_name": "NVIDIA GeForce RTX 4070 Laptop GPU",
        "error": "",
    }
    parsed = PholdEngine._parse_gpu_probe_output("noise line\n" + json.dumps(payload))
    assert parsed["ok"] is True
    assert parsed["kernel_ok"] is True
    assert parsed["device_name"] == "NVIDIA GeForce RTX 4070 Laptop GPU"

    bad = PholdEngine._parse_gpu_probe_output("unexpected shell error")
    assert bad["ok"] is False
    assert "unexpected shell error" in bad["error"]


def test_format_gpu_probe_notice_variants() -> None:
    # 1. GPU 正常
    lvl, msg = PholdEngine._format_gpu_probe_notice(
        {
            "ok": True,
            "has_wsl_gpu": True,
            "kernel_ok": True,
            "torch_version": "2.7.0+cu128",
            "device_name": "NVIDIA GeForce RTX 5060",
            "python_bin": "/usr/bin/python3",
        }
    )
    assert lvl == "info"
    assert "RTX 5060" in msg

    # 2. 有 WSL GPU 但误装 CPU 版 torch
    lvl_cpu, msg_cpu = PholdEngine._format_gpu_probe_notice(
        {
            "ok": True,
            "has_wsl_gpu": True,
            "kernel_ok": False,
            "torch_version": "2.7.0+cpu",
            "python_bin": "/usr/bin/python3",
            "error": "CUDA unavailable",
        }
    )
    assert lvl_cpu == "warning"
    assert "fix_phold_gpu_wsl.ps1" in msg_cpu

    # 3. 有 WSL GPU 但 kernel 失败 (RTX 5060 cu124/sm_120 不兼容)
    lvl_kern, msg_kern = PholdEngine._format_gpu_probe_notice(
        {
            "ok": True,
            "has_wsl_gpu": True,
            "kernel_ok": False,
            "torch_version": "2.5.1+cu124",
            "python_bin": "/usr/bin/python3",
            "error": "no kernel image is available for execution on the device",
        }
    )
    assert lvl_kern == "warning"
    assert "cu128" in msg_kern

    # 4. 纯 CPU WSL 环境
    lvl_nogpu, msg_nogpu = PholdEngine._format_gpu_probe_notice(
        {
            "ok": True,
            "has_wsl_gpu": False,
            "kernel_ok": False,
            "torch_version": "2.7.0+cpu",
            "python_bin": "/usr/bin/python3",
        }
    )
    assert lvl_nogpu == "info"
    assert "CPU 模式" in msg_nogpu


def test_complement_from_gbk_gpu_probe_cleanup_and_log_detection(tmp_path: Path) -> None:
    gbk_path = tmp_path / "in.gbk"
    gbk_path.write_text("LOCUS       c1 100 bp DNA linear\n//\n", encoding="utf-8")
    work_dir = tmp_path / "work"
    work_dir.mkdir()

    features = [
        FeatureItem(
            id="CDS_1",
            locus_tag="CDS_1",
            contig_id="c1",
            feature_type="CDS",
            start=1,
            end=90,
            strand="+",
            length_bp=90,
            product="hypothetical protein",
        )
    ]

    engine = PholdEngine()
    events = []
    progress_msgs = []

    def on_progress(pct: int, msg: str, raw: str | None) -> None:
        progress_msgs.append((pct, msg, raw))

    async def fake_run_command(cmd, cwd=None, on_output=None, **kwargs):
        events.append("run_command")
        if on_output:
            on_output("2026-11-25 INFO Using device: cuda:0")
            on_output("No available GPU was found, but --cpu was not specified")
        return 1

    fake_runner = MagicMock()
    fake_runner.run_command = AsyncMock(side_effect=fake_run_command)

    def fake_cleanup():
        events.append("cleanup")

    with (
        patch.object(engine, "_cleanup_gpu_memory", side_effect=fake_cleanup),
        patch.object(
            engine,
            "_probe_wsl_gpu_runtime",
            AsyncMock(
                return_value={
                    "ok": True,
                    "has_wsl_gpu": True,
                    "kernel_ok": False,
                    "torch_version": "2.6.0+cpu",
                    "python_bin": "/usr/bin/python3",
                    "error": "CUDA 不可用",
                }
            ),
        ),
        patch("src.assembly.engine.runner.CommandRunner", return_value=fake_runner),
        patch("src.assembly.env.wsl_manager.WSLManager.ensure_project_link"),
        patch("src.assembly.env.wsl_manager.WSLManager.to_wsl_path", side_effect=lambda p: p),
        patch("src.workbench.models.tool_config.ToolConfig.get_db_dir", return_value=tmp_path),
    ):
        updated = asyncio.run(engine.complement_from_gbk(features, gbk_path, work_dir, 4, on_progress=on_progress))

    assert updated == 0
    assert events == ["cleanup", "run_command", "cleanup"]
    assert any("fix_phold_gpu_wsl.ps1" in m for _, m, _ in progress_msgs)
    assert any("Using device: cuda:0" in m for _, m, _ in progress_msgs)
    assert any("未检测到可用 CUDA" in m for _, m, _ in progress_msgs)


def test_sequence_annotator_phold_uses_wsl_root_user(tmp_path: Path) -> None:
    phold_db = tmp_path / "phold_db"
    phold_db.mkdir()
    (phold_db / "all_phold_structures").write_text("ok", encoding="utf-8")

    captured_cmds = []

    def fake_run(cmd, **kwargs):
        captured_cmds.append(cmd)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    with (
        patch.object(sequence_annotator.ToolConfig, "get_db_dir", return_value=phold_db),
        patch.object(sequence_annotator.WSLManager, "is_available", return_value=True),
        patch.object(sequence_annotator.WSLManager, "get_best_distro", return_value="NCBIUbuntu"),
        patch.object(sequence_annotator.subprocess, "run", side_effect=fake_run),
    ):
        assert sequence_annotator.check_phold_ready() is True

    assert captured_cmds[0][:5] == ["wsl", "-d", "NCBIUbuntu", "-u", "root"]

    captured_cmds.clear()
    contig_map = {
        "c1": {
            "proteins": [
                sequence_annotator.StructureProteinItem(
                    locus_tag="CDS_1",
                    contig_id="c1",
                    start=1,
                    end=900,
                    strand="+",
                    length_aa=250,
                    product="hypothetical protein",
                    translation="M" * 250,
                )
            ]
        }
    }

    with (
        patch.object(sequence_annotator, "check_phold_ready", return_value=True),
        patch.object(sequence_annotator.ToolConfig, "get_db_dir", return_value=phold_db),
        patch.object(sequence_annotator.WSLManager, "ensure_project_link"),
        patch.object(sequence_annotator.WSLManager, "to_wsl_path", side_effect=lambda p: p),
        patch.object(sequence_annotator.WSLManager, "get_best_distro", return_value="NCBIUbuntu"),
        patch.object(sequence_annotator.subprocess, "run", side_effect=fake_run),
    ):
        res_cnt = sequence_annotator.enhance_with_phold_3d(contig_map, workers=4, min_aa=200)

    assert res_cnt == 0
    assert captured_cmds[0][:5] == ["wsl", "-d", "NCBIUbuntu", "-u", "root"]
