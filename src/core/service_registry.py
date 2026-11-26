# -*- coding: utf-8 -*-
"""
轻量内核服务注册表 (ServiceRegistry)

用于解耦 domain/core 层与 backend/utils 层之间的反向循环依赖：
由上层初始化时注册具体实现，core/domain 层仅依赖本注册表契约。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Optional

_bio_db_manager: Optional[Any] = None
_taxonomy_db_path_resolver: Optional[Callable[[], Optional[str]]] = None


def register_bio_db_manager(instance: Any) -> None:
    """由后端初始化阶段注册 BioDbManager 实例。"""
    global _bio_db_manager
    _bio_db_manager = instance


def get_bio_db_manager() -> Optional[Any]:
    """获取已注册的 BioDbManager；若尚未由后端初始化则返回 None。"""
    return _bio_db_manager


def register_taxonomy_db_path_resolver(resolver: Optional[Callable[[], Optional[str]]]) -> None:
    """注册分类学 SQLite 数据库路径解析回调（解耦 core.blast_utils 与 utils.taxonomy_provider）。"""
    global _taxonomy_db_path_resolver
    _taxonomy_db_path_resolver = resolver


def resolve_taxonomy_db_path() -> Optional[str]:
    """解析本地分类学数据库 taxa.sqlite 路径；未就绪或不存在时返回 None。"""
    if _taxonomy_db_path_resolver is not None:
        return _taxonomy_db_path_resolver()
    default_db = Path(__file__).resolve().parents[2] / "database" / "taxonomy" / "taxa.sqlite"
    return str(default_db) if default_db.exists() else None
