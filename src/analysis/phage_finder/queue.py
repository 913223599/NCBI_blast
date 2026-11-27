# -*- coding: utf-8 -*-
"""
前噬菌体发现异步单序列调度队列引擎

采用单任务串行调度 (max_workers=1) 严格控制物理显存占用，
支持服务重启后的断点自愈、运行前/后 CUDA 显存回收与 WebSocket 实时队列广播。
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from ...core.broadcaster import broadcaster
from ...core.serial_queue import BaseAsyncTaskQueue
from ...core.task_db import release_gpu_memory
from .db import PhageDiscoveryDB, phage_discovery_db

logger = logging.getLogger("PhageDiscoveryQueue")


class PhageDiscoveryQueue(BaseAsyncTaskQueue):
    """单例异步前噬菌体扫描任务队列。"""

    queue_event_name = "phage_discovery_queue_update"
    error_event_name = "phage_discovery_error"
    bg_task_label = "phage_finder_queue_snapshot"
    engine_label = "PhageDiscovery"
    cancel_queued_message = "排队中的前噬菌体扫描任务已取消"
    cancel_running_step = "正在请求中止当前扫描..."
    cancel_running_message = "已发送中止请求，将在当前阶段安全退出"
    not_found_message = "任务不在当前队列或已完成"
    _reset_state_on_start = False

    def __init__(self, max_workers: int = 1, db: Optional[PhageDiscoveryDB] = None):
        super().__init__(max_workers=max_workers, db=db if db is not None else phage_discovery_db)
        self._logger = logger

    def _build_task_meta(self, task_id: str, position: Optional[int] = None) -> Dict[str, Any]:
        meta = self.db.get_task(task_id) or {}
        item: Dict[str, Any] = {
            "task_id": task_id,
            "task_name": meta.get("task_name") or task_id,
            "model_version": meta.get("model_version") or "Stage 1.2",
            "device": meta.get("device") or "cpu",
            "apply_protein_gate": bool(meta.get("apply_protein_gate", False)),
            "status": meta.get("status") or ("queued" if position is not None else "running"),
            "progress": meta.get("progress", 0),
            "current_step": meta.get("current_step") or "",
            "created_at": meta.get("created_at") or "",
        }
        if position is not None:
            item["position"] = position
        return item

    async def _on_task_started(self, task_id: str) -> None:
        self.db.update_progress(task_id, 2, "正在调度计算引擎启动扫描...", status="running")
        await broadcaster.broadcast(
            "phage_discovery_progress",
            {"task_id": task_id, "progress": 2, "message": "正在调度计算引擎启动扫描...", "status": "running"},
        )
        await self._broadcast_snapshot()


phage_discovery_queue = PhageDiscoveryQueue(max_workers=1)
__all__ = ["PhageDiscoveryQueue", "phage_discovery_queue", "release_gpu_memory"]
