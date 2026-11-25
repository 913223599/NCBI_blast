# -*- coding: utf-8 -*-
"""
实时系统硬件微监控采集器 (system_monitor)

单一职责：
1. 以短采样窗口计算实时 CPU 利用率，避免 interval=None 全局状态污染导致的数值严重滞后；
2. 优先通过 nvidia-smi CLI 采集 GPU 核心算力利用率、显存占用与温度，避免在主 API 进程初始化 CUDA 上下文；
3. 缺少 nvidia-smi 时平滑回退至 GpuGuard.probe()，并结合短期 TTL 缓存防止多前端并发轮询引发性能开销。
"""
from __future__ import annotations

import logging
import shutil
import subprocess
import threading
import time
from typing import Any, Dict, Optional

from .resource_guard import GpuGuard, get_safe_cpu_budget, get_total_logical_cores

logger = logging.getLogger("utils.system_monitor")

_CACHE_LOCK = threading.Lock()
_CACHED_METRICS: Optional[Dict[str, Any]] = None
_CACHED_AT: float = 0.0
_DEFAULT_TTL_SEC = 1.5


def reset_metrics_cache() -> None:
    """清空监控缓存（主要用于单元测试隔离）。"""
    global _CACHED_METRICS, _CACHED_AT
    with _CACHE_LOCK:
        _CACHED_METRICS = None
        _CACHED_AT = 0.0


def _safe_float(raw: str) -> Optional[float]:
    txt = (raw or "").strip()
    if not txt or txt.upper() in {"N/A", "[N/A]", "NONE", "NULL"}:
        return None
    try:
        return float(txt)
    except ValueError:
        return None


def _safe_int(raw: str) -> Optional[int]:
    val = _safe_float(raw)
    if val is None:
        return None
    return int(round(val))


def _parse_nvidia_smi_csv(stdout: str) -> Optional[Dict[str, Any]]:
    """解析 nvidia-smi --query-gpu=name,utilization.gpu,memory.used,memory.total,temperature.gpu CSV 首行。"""
    for raw_line in (stdout or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 5:
            continue
        name = parts[0]
        util = _safe_float(parts[1])
        used_mb = _safe_int(parts[2])
        total_mb = _safe_int(parts[3])
        temp_c = _safe_int(parts[4])

        if total_mb is None or total_mb <= 0:
            continue
        safe_used = max(0, min(total_mb, used_mb or 0))
        free_mb = max(0, total_mb - safe_used)
        vram_pct = round(safe_used * 100.0 / total_mb, 1)
        return {
            "available": True,
            "name": name or "NVIDIA GPU",
            "utilization_percent": round(util, 1) if util is not None else None,
            "used_vram_mb": safe_used,
            "free_vram_mb": free_mb,
            "total_vram_mb": total_mb,
            "vram_percent": vram_pct,
            "temperature_c": temp_c,
            "source": "nvidia-smi",
        }
    return None


def probe_gpu_metrics() -> Dict[str, Any]:
    """实时探测 GPU 算力、显存与温度；不可用 nvidia-smi 时回退 GpuGuard.probe()。"""
    smi_exe = shutil.which("nvidia-smi")
    if smi_exe:
        try:
            creation_flags = int(getattr(subprocess, "CREATE_NO_WINDOW", 0))
            res = subprocess.run(
                [
                    smi_exe,
                    "--query-gpu=name,utilization.gpu,memory.used,memory.total,temperature.gpu",
                    "--format=csv,noheader,nounits",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=2.0,
                creationflags=creation_flags,
            )
            if res.returncode == 0:
                parsed = _parse_nvidia_smi_csv(res.stdout)
                if parsed is not None:
                    return parsed
        except Exception as exc:
            logger.debug("nvidia-smi probe failed, falling back to GpuGuard: %s", exc)

    torch_gpu = GpuGuard.probe()
    total_mb = int(torch_gpu.get("total_vram_mb") or 0)
    free_mb = int(torch_gpu.get("free_vram_mb") or 0)
    used_mb = max(0, total_mb - free_mb) if total_mb > 0 else 0
    vram_pct = round(used_mb * 100.0 / total_mb, 1) if total_mb > 0 else None
    avail = bool(torch_gpu.get("available"))
    return {
        "available": avail,
        "name": str(torch_gpu.get("name") or ""),
        "utilization_percent": None,
        "used_vram_mb": used_mb,
        "free_vram_mb": free_mb,
        "total_vram_mb": total_mb,
        "vram_percent": vram_pct,
        "temperature_c": None,
        "source": "torch" if avail else "none",
    }


def collect_system_metrics(
    force: bool = False,
    cpu_sample_interval: float = 0.25,
    ttl_sec: float = _DEFAULT_TTL_SEC,
) -> Dict[str, Any]:
    """采集实时 CPU、内存、安全并发预算与 GPU 指标（带短 TTL 缓存防并发重复采样）。"""
    global _CACHED_METRICS, _CACHED_AT

    now = time.monotonic()
    with _CACHE_LOCK:
        if (
            not force
            and _CACHED_METRICS is not None
            and (now - _CACHED_AT) < max(0.0, ttl_sec)
        ):
            return {**_CACHED_METRICS, "gpu": dict(_CACHED_METRICS["gpu"])}

    cpu_percent: Optional[float] = None
    memory_percent: Optional[float] = None
    memory_used_gb: Optional[float] = None
    memory_total_gb: Optional[float] = None
    try:
        import psutil

        safe_interval = max(0.05, float(cpu_sample_interval))
        cpu_percent = round(float(psutil.cpu_percent(interval=safe_interval)), 1)
        vm = psutil.virtual_memory()
        memory_percent = round(float(vm.percent), 1)
        memory_used_gb = round(float(vm.used) / (1024 ** 3), 2)
        memory_total_gb = round(float(vm.total) / (1024 ** 3), 2)
    except Exception as exc:
        logger.debug("psutil metrics unavailable: %s", exc)

    snapshot: Dict[str, Any] = {
        "cpu_percent": cpu_percent,
        "memory_percent": memory_percent,
        "memory_used_gb": memory_used_gb,
        "memory_total_gb": memory_total_gb,
        "cpu_cores": get_total_logical_cores(),
        "safe_cpu_budget": get_safe_cpu_budget(),
        "gpu": probe_gpu_metrics(),
        "sampled_at": round(time.time(), 3),
    }

    with _CACHE_LOCK:
        _CACHED_METRICS = snapshot
        _CACHED_AT = time.monotonic()

    return {**snapshot, "gpu": dict(snapshot["gpu"])}
