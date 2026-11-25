# -*- coding: utf-8 -*-
"""实时系统硬件微监控 (system_monitor) 与 /api/core/system_metrics 回归测试。"""
from __future__ import annotations

import logging
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from src.backend.utils.access_log_filter import (  # noqa: E402
    QuietPollingAccessFilter,
    install_uvicorn_access_filter,
)
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


def _make_access_record(
    method: str,
    path: str,
    status_code: int,
    *,
    use_uvicorn_args: bool = True,
) -> logging.LogRecord:
    if use_uvicorn_args:
        return logging.LogRecord(
            name="uvicorn.access",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg='%s - "%s %s HTTP/%s" %d',
            args=("127.0.0.1:55154", method, path, "1.1", status_code),
            exc_info=None,
        )
    return logging.LogRecord(
        name="uvicorn.access",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg=f'127.0.0.1:55154 - "{method} {path} HTTP/1.1" {status_code} OK',
        args=(),
        exc_info=None,
    )


def test_quiet_polling_access_filter_suppresses_200_metrics_only() -> None:
    log_filter = QuietPollingAccessFilter()

    for use_args in (True, False):
        # 高频监控/健康检查 200 GET 日志应当被抑制 (返回 False)
        assert log_filter.filter(_make_access_record("GET", "/api/core/system_metrics", 200, use_uvicorn_args=use_args)) is False
        assert log_filter.filter(_make_access_record("GET", "/api/core/system_metrics?force=true", 200, use_uvicorn_args=use_args)) is False
        assert log_filter.filter(_make_access_record("GET", "/api/health", 200, use_uvicorn_args=use_args)) is False

        # 异常状态码 (4xx/5xx)、非 GET 方法及普通业务路由必须保留输出 (返回 True)
        assert log_filter.filter(_make_access_record("GET", "/api/core/system_metrics", 500, use_uvicorn_args=use_args)) is True
        assert log_filter.filter(_make_access_record("GET", "/api/health", 503, use_uvicorn_args=use_args)) is True
        assert log_filter.filter(_make_access_record("POST", "/api/core/system_metrics", 200, use_uvicorn_args=use_args)) is True
        assert log_filter.filter(_make_access_record("GET", "/api/assembly/history", 200, use_uvicorn_args=use_args)) is True
        assert log_filter.filter(_make_access_record("POST", "/api/assembly/run", 200, use_uvicorn_args=use_args)) is True


def test_install_uvicorn_access_filter_is_idempotent() -> None:
    logger_name = "test.uvicorn.access.idempotent"
    test_logger = logging.getLogger(logger_name)
    test_logger.filters.clear()

    first = install_uvicorn_access_filter(logger_name=logger_name)
    second = install_uvicorn_access_filter(logger_name=logger_name)

    assert first is second
    installed = [flt for flt in test_logger.filters if isinstance(flt, QuietPollingAccessFilter)]
    assert len(installed) == 1
    test_logger.filters.clear()
