# -*- coding: utf-8 -*-
"""
轻量内核服务注册表 (ServiceRegistry)

用于解耦 domain 层（如 blast）与 backend 层（如 bio_db_manager）之间的反向循环依赖：
由 backend 初始化时注册具体实现，domain 层仅依赖本协议接口。
"""
from __future__ import annotations

from typing import Any, Optional

_bio_db_manager: Optional[Any] = None


def register_bio_db_manager(instance: Any) -> None:
    """由后端初始化阶段注册 BioDbManager 实例。"""
    global _bio_db_manager
    _bio_db_manager = instance


def get_bio_db_manager() -> Optional[Any]:
    """获取已注册的 BioDbManager；若尚未由后端初始化则返回 None。"""
    return _bio_db_manager
