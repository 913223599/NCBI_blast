# -*- coding: utf-8 -*-
"""
噬菌体结构与尾部形态预测异步任务队列调度器

职责：
1. 采用单序列串行任务队列，严格控制 HMM/CUDA 内存峰值并支持重启断点自愈；
2. 基于 WebSocket 实时向前端广播进度与队列快照；
3. 运行前后强制回收 CUDA 显存。
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from ...core.broadcaster import broadcaster
from ...core.serial_queue import BaseAsyncTaskQueue
from ...core.task_db import release_gpu_memory
from .db import PhageStructureDB, phage_structure_db

logger = logging.getLogger("analysis.phage_structure.queue")


class PhageStructureQueue(BaseAsyncTaskQueue):
    """单例异步噬菌体结构预测队列。"""

    queue_event_name = "phage_structure_queue_update"
    error_event_name = "phage_structure_error"
    bg_task_label = "phage_structure_queue_snapshot"
    engine_label = "PhageStructure"
    cancel_queued_message = "排队中的结构预测任务已取消"
    cancel_running_step = "正在请求中止当前分析..."
    cancel_running_message = "已发送中止请求，将在当前步骤安全退出"
    not_found_message = "任务不在队列中或已结束"
    _reset_state_on_start = True

    def __init__(self, max_workers: int = 1, db: Optional[PhageStructureDB] = None):
        super().__init__(max_workers=max_workers, db=db if db is not None else phage_structure_db)
        self._logger = logger

    def _build_task_meta(self, task_id: str, position: Optional[int] = None) -> Dict[str, Any]:
        meta = self.db.get_task(task_id) or {}
        item: Dict[str, Any] = {
            "task_id": task_id,
            "task_name": meta.get("task_name") or task_id,
            "source_mode": meta.get("source_mode") or "file",
            "status": meta.get("status") or ("queued" if position is not None else "running"),
            "progress": meta.get("progress", 0),
            "current_step": meta.get("current_step") or "",
            "created_at": meta.get("created_at") or "",
        }
        if position is not None:
            item["position"] = position
        return item

    async def _on_task_failed(self, task_id: str, exc: Exception) -> None:
        self.db.mark_failed(task_id, str(exc))
        await broadcaster.broadcast(
            "phage_structure_error",
            {"task_id": task_id, "error": str(exc), "status": "failed"},
        )


phage_structure_queue = PhageStructureQueue(max_workers=1, db=phage_structure_db)
__all__ = ["PhageStructureQueue", "phage_structure_queue", "release_gpu_memory"]
