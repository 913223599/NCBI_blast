# -*- coding: utf-8 -*-
"""
PhyloCore 运行时支撑层：资源守卫、工具自动探测、可取消进程执行器
"""
from .process_runner import ProcessRunner
from .resource_guard import GpuGuard, get_safe_cpu_budget, get_total_logical_cores
from .tool_registry import ToolRegistry, get_tool_registry

__all__ = [
    "get_total_logical_cores",
    "get_safe_cpu_budget",
    "GpuGuard",
    "ToolRegistry",
    "get_tool_registry",
    "ProcessRunner",
]
