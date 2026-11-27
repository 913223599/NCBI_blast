# -*- coding: utf-8 -*-
"""
前噬菌体与噬菌体智能发现工作台分析包 (Phage Finder Workbench Integration)

将深度学习 Student V4.2 边界精修模型与可选蛋白门控封装为异步持久化队列任务、
零硬编码 V4.2 模型发现器与多格式科研产物导出器。
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .model_registry import (
    detect_compute_environment,
    discover_available_models,
    resolve_model_dir,
    resolve_protein_gate_resources,
)
from .types import PhageConfigPathRequest, PhageScanInspectRequest, PhageScanRunRequest

if TYPE_CHECKING:
    from .manager import PhageDiscoveryManager, get_phage_discovery_manager

__all__ = [
    "PhageDiscoveryManager",
    "PhageScanInspectRequest",
    "PhageScanRunRequest",
    "PhageConfigPathRequest",
    "detect_compute_environment",
    "discover_available_models",
    "get_phage_discovery_manager",
    "resolve_model_dir",
    "resolve_protein_gate_resources",
]


def __getattr__(name: str) -> Any:
    if name in ("PhageDiscoveryManager", "get_phage_discovery_manager"):
        from . import manager

        return getattr(manager, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
