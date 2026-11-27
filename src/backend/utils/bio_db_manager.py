# -*- coding: utf-8 -*-
"""
生物数据库统一门面 (bio_db_manager)

底层实现已按单一职责原则拆解至 src/backend/utils/bio_db/ 子包，
对外保持 100% 向后兼容的导出符号、单例注册与调用契约。
"""
from __future__ import annotations

import asyncio
import logging
import threading
from typing import Any, Coroutine, Dict, List, Optional, Tuple

from ...workbench.models.tool_config import ToolConfig
from .bio_db.providers import (
    BioDatabase,
    CardDatabase,
    CddPfamDatabase,
    DefenseFinderDatabase,
    FastaProtDatabase,
    Ncbi16SDatabase,
    PhageScopeDatabase,
    PharokkaDatabase,
    PholdDatabase,
    ProgressReporter,
    RdpDatabase,
    SilvaDatabase,
    create_database_provider,
)
from .bio_db.state_registry import DbUpdateStateRegistry
from .bio_db.subprocess_runner import build_wsl_script_argv, build_wsl_script_command

logger = logging.getLogger("api_server")


class BioDbManager:
    """生物数据库管理门面 (Facade)：汇聚所有数据库实例与更新状态中心。"""

    def __init__(self) -> None:
        self.dbs: Dict[str, BioDatabase] = {}
        self.state_registry = DbUpdateStateRegistry()

        # [Migration] 将散落在 16S 目录下的 NCBI 文件归位到 16S/ncbi
        self._perform_migration()

        # 合并主注册表与历史 legacy 注册表
        ToolConfig.sync_registry()

        registry = ToolConfig.get_remote_registry()
        for db_id, config in registry.items():
            self.dbs[db_id] = create_database_provider(db_id, config)

        logger.info(
            "生物数据库注册完成: %s 个条目 %s（database 根目录: %s）",
            len(self.dbs),
            sorted(self.dbs.keys()),
            ToolConfig.DATABASE_ROOT,
        )
        if ToolConfig.LEGACY_DATABASE_ROOT.exists():
            legacy_used = sorted(
                name
                for name, db in self.dbs.items()
                if str(db.base_dir).startswith(str(ToolConfig.LEGACY_DATABASE_ROOT))
            )
            if legacy_used:
                logger.warning(
                    "检测到历史遗留的 database/database 布局，以下库已自动回退到该目录: %s",
                    legacy_used,
                )

    def _perform_migration(self) -> None:
        """处理 NCBI 16S 目录不规范的历史遗留问题。"""
        source_dir = ToolConfig.DATABASE_ROOT / "16S"
        target_dir = source_dir / "ncbi"
        if not source_dir.exists():
            return

        scattered_files = list(source_dir.glob("16S_ribosomal_RNA*"))
        if scattered_files:
            logger.info("发现散落的 NCBI 文件 (%s个)，正在迁移至: %s", len(scattered_files), target_dir)
            target_dir.mkdir(parents=True, exist_ok=True)
            for f in scattered_files:
                try:
                    dest = target_dir / f.name
                    if dest.exists():
                        f.unlink()
                    else:
                        f.rename(dest)
                except Exception as e:
                    logger.error("迁移文件 %s 失败: %s", f.name, e)

    # ────────── 状态中心与任务编排委托 API ──────────

    def is_updating(self, db_id: str) -> bool:
        return self.state_registry.is_updating(db_id)

    def get_update_state(self, db_id: str) -> Optional[Dict[str, Any]]:
        return self.state_registry.get_state(db_id)

    def begin_update(self, db_id: str, message: str) -> Tuple[bool, Dict[str, Any], Optional[threading.Event]]:
        return self.state_registry.begin_update(db_id, message)

    def report_progress(self, db_id: str, progress: int, message: str) -> Dict[str, Any]:
        return self.state_registry.report_progress(db_id, progress, message)

    def finish_update(self, db_id: str, status: str, progress: int, message: str) -> Dict[str, Any]:
        return self.state_registry.finish_update(db_id, status, progress, message)

    def cancel_update(self, db_id: str) -> Tuple[bool, str]:
        return self.state_registry.cancel_update(db_id)

    def spawn_update_task(self, db_id: str, coro: Coroutine[Any, Any, Any]) -> asyncio.Task[Any]:
        return self.state_registry.spawn_task(db_id, coro)

    async def wait_active_updates(self) -> None:
        await self.state_registry.wait_all_tasks()

    def clear_update_state(self, db_id: str) -> None:
        self.state_registry.clear_state(db_id)

    def list_all_status(self) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []
        for db_id, db in self.dbs.items():
            status = db.get_status()
            status["update_state"] = self.get_update_state(db_id)
            results.append(status)
        return results


bio_db_manager = BioDbManager()

from ...core.service_registry import register_bio_db_manager  # noqa: E402

register_bio_db_manager(bio_db_manager)

__all__ = [
    "BioDatabase",
    "BioDbManager",
    "CardDatabase",
    "CddPfamDatabase",
    "DefenseFinderDatabase",
    "FastaProtDatabase",
    "Ncbi16SDatabase",
    "PhageScopeDatabase",
    "PharokkaDatabase",
    "PholdDatabase",
    "ProgressReporter",
    "RdpDatabase",
    "SilvaDatabase",
    "bio_db_manager",
    "build_wsl_script_argv",
    "build_wsl_script_command",
]
