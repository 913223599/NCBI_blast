# -*- coding: utf-8 -*-
"""
全局硬件资源守卫向后兼容门面。
实际实现已下沉至 src/core/resource_guard.py，以消除与 workbench 的反向循环依赖。
"""
from ..core.resource_guard import (
    DEFAULT_RESERVED_CORES,
    MIN_RESERVED_CORES_HARD,
    GpuGuard,
    get_safe_cpu_budget,
    get_total_logical_cores,
)

__all__ = [
    "DEFAULT_RESERVED_CORES",
    "MIN_RESERVED_CORES_HARD",
    "GpuGuard",
    "get_safe_cpu_budget",
    "get_total_logical_cores",
]
