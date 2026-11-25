# -*- coding: utf-8 -*-
"""实时系统硬件微监控 (system_monitor) 与 /api/core/system_metrics 回归测试。"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from src.utils import system_monitor  # noqa: E402


def test_parse_nvidia_smi_csv_valid_and_na() -> None:
    parsed = system_monitor._parse_nvidia_smi_csv("NVIDIA GeForce RTX 5060, 7, 1092, 8123, 44\n")
    assert parsed is not None
    assert parsed["available"] is True
    assert parsed["name"] == "NVIDIA GeForce RTX 5060"
    assert parsed["utilization_percent"] == 7.0
    assert parsed["used_vram_mb"] == 1092
    assert parsed["total_vram_mb"] == 8123
    assert parsed["free_vram_mb"] == 7031
    assert parsed["vram_percent"] == 13.4
    assert parsed["temperature_c"] == 44
    assert parsed["source"] == "nvidia-smi"

    na_row = system_monitor._parse_nvidia_smi_csv("Tesla T4, [N/A], 512, 16384, N/A\n")
    assert na_row is not None
    assert na_row["utilization_percent"] is None
    assert na_row["temperature_c"] is None
    assert na_row["free_vram_mb"] == 15872


def test_collect_system_metrics_cache_and_force_refresh() -> None:
    system_monitor.reset_metrics_cache()
    calls = []

    def fake_cpu_percent(interval=None):
        calls.append(interval)
        return 25.4 if len(calls) == 1 else 68.2

    fake_vm = SimpleNamespace(percent=31.2, used=10.0 * (1024 ** 3), total=32.0 * (1024 ** 3))
    fake_gpu = {
        "available": True,
        "name": "NVIDIA GeForce RTX 5060",
        "utilization_percent": 7.0,
        "used_vram_mb": 1000,
        "free_vram_mb": 7123,
        "total_vram_mb": 8123,
        "vram_percent": 12.3,
        "temperature_c": 44,
        "source": "nvidia-smi",
    }

    with (
        patch("psutil.cpu_percent", side_effect=fake_cpu_percent),
        patch("psutil.virtual_memory", return_value=fake_vm),
        patch.object(system_monitor, "probe_gpu_metrics", return_value=fake_gpu),
    ):
        first = system_monitor.collect_system_metrics(force=False, cpu_sample_interval=0.25, ttl_sec=5.0)
        cached = system_monitor.collect_system_metrics(force=False, cpu_sample_interval=0.25, ttl_sec=5.0)
        refreshed = system_monitor.collect_system_metrics(force=True, cpu_sample_interval=0.25, ttl_sec=5.0)

    assert len(calls) == 2
    assert all(iv == 0.25 for iv in calls)
    assert first["cpu_percent"] == 25.4
    assert cached["cpu_percent"] == 25.4
    assert refreshed["cpu_percent"] == 68.2
    assert refreshed["gpu"]["utilization_percent"] == 7.0
    assert isinstance(refreshed["sampled_at"], float)


def test_probe_gpu_metrics_falls_back_to_torch_when_no_nvidia_smi() -> None:
    fallback_payload = {
        "available": True,
        "name": "Fallback CUDA",
        "total_vram_mb": 8000,
        "free_vram_mb": 6000,
    }
    with (
        patch.object(system_monitor.shutil, "which", return_value=None),
        patch.object(system_monitor.GpuGuard, "probe", return_value=fallback_payload),
    ):
        gpu = system_monitor.probe_gpu_metrics()

    assert gpu["available"] is True
    assert gpu["used_vram_mb"] == 2000
    assert gpu["vram_percent"] == 25.0
    assert gpu["utilization_percent"] is None
    assert gpu["temperature_c"] is None
    assert gpu["source"] == "torch"


def test_core_system_metrics_endpoint_fields() -> None:
    from src.backend.api_server import app

    system_monitor.reset_metrics_cache()
    client = TestClient(app)
    res = client.get("/api/core/system_metrics?force=true")
    assert res.status_code == 200
    body = res.json()
    for key in (
        "cpu_percent",
        "memory_percent",
        "memory_used_gb",
        "memory_total_gb",
        "cpu_cores",
        "safe_cpu_budget",
        "gpu",
        "sampled_at",
    ):
        assert key in body
    assert isinstance(body["gpu"], dict)
    for gkey in ("available", "utilization_percent", "used_vram_mb", "free_vram_mb", "total_vram_mb", "source"):
        assert gkey in body["gpu"]
