# -*- coding: utf-8 -*-
"""向后兼容门面：实际实现已下沉至 src/core/assembly_gbk_fixer.py，消除跨层循环依赖。"""
from ...core.assembly_gbk_fixer import (
    GBKAnnotationBackfiller,
)

__all__ = [
    "GBKAnnotationBackfiller",
]
