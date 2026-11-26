# -*- coding: utf-8 -*-
"""向后兼容门面：实际实现已下沉至 src/core/assembly_storage.py，消除跨层循环依赖。"""
from ...core.assembly_storage import (
    AssemblyStorage,
)

__all__ = [
    "AssemblyStorage",
]
