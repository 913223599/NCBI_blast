# -*- coding: utf-8 -*-
"""
向后兼容导出层：统一委托至公共硬件资源守卫 src.utils.resource_guard。
"""
from src.utils.resource_guard import (
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
