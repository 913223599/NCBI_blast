# -*- coding: utf-8 -*-
"""
噬菌体结构与尾部形态预测异步任务队列调度器

职责：
1. 采用单序列串行任务队列，严格控制 HMM/CUDA 内存峰值并支持重启断点自愈；
2. 基于 WebSocket 实时向前端广播进度与队列快照；
3. 运行前后强制回收 CUDA 显存。
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

from ...core.async_tasks import spawn_tracked_task
from ...core.broadcaster import broadcaster
from ...core.task_db import release_gpu_memory
from .db import PhageStructureDB, phage_structure_db

logger = logging.getLogger("analysis.phage_structure.queue")


class PhageStructureQueue:
    """单例异步噬菌体结构预测队列。"""

    def __init__(self, max_workers: int = 1, db: Optional[PhageStructureDB] = None):
        self.max_workers = max(1, max_workers)
        self.db = db if db is not None else phage_structure_db
        self.queue: asyncio.Queue[Tuple[str, Any, Dict[str, Any]]] = asyncio.Queue()
        self.queued_ids: List[str] = []
        self.running_ids: List[str] = []
        self.cancelled_ids: set[str] = set()
        self._workers: List[asyncio.Task[None]] = []
        self._bg_tasks: set[asyncio.Task[Any]] = set()
        self._executor: Optional[Callable[[str, Any, Dict[str, Any]], Awaitable[None]]] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._started = False

    def set_executor(self, executor: Callable[[str, Any, Dict[str, Any]], Awaitable[None]]) -> None:
        self._executor = executor

    async def start(self) -> None:
        loop = asyncio.get_running_loop()
        if (
            self._started
            and self._loop is loop
            and any(not w.done() for w in self._workers)
        ):
            return
        self._started = True
        self._loop = loop
        self.queue = asyncio.Queue()
        self.queued_ids.clear()
        self.running_ids.clear()
        self.cancelled_ids.clear()
        self._workers = []
        self.db.reset_interrupted_tasks(exclude_task_ids=[])
        for idx in range(self.max_workers):
            self._workers.append(asyncio.create_task(self._worker_loop(idx)))
        logger.info("PhageStructure 队列引擎已启动 (workers=%s)", self.max_workers)

    async def broadcast_snapshot(self) -> None:
        """向前端广播当前最新队列快照。"""
        await self._broadcast_snapshot()

    async def enqueue(
        self,
        task_id: str,
        req: Any,
        context: Dict[str, Any],
        broadcast: bool = True,
    ) -> Dict[str, Any]:
        await self.start()
        was_busy = len(self.running_ids) > 0 or len(self.queued_ids) > 0
        self.queued_ids.append(task_id)
        queue_pos = len(self.queued_ids)
        await self.queue.put((task_id, req, context))
        if broadcast:
            await self._broadcast_snapshot()
        return {
            "task_id": task_id,
            "queue_position": queue_pos,
            "is_busy": was_busy,
            "running_count": len(self.running_ids),
            "queued_count": len(self.queued_ids),
        }

    def remove_from_waiting(self, task_id: str) -> bool:
        removed = False
        if task_id in self.queued_ids:
            self.queued_ids.remove(task_id)
            self.cancelled_ids.add(task_id)
            removed = True
        elif task_id in self.running_ids:
            self.cancelled_ids.add(task_id)
        if removed:
            try:
                loop = asyncio.get_running_loop()
                spawn_tracked_task(
                    self._broadcast_snapshot(),
                    self._bg_tasks,
                    label="phage_structure_queue_snapshot",
                    loop=loop,
                )
            except RuntimeError:
                logger.debug("remove_from_waiting: 无运行中事件循环，跳过快照广播")
        return removed

    async def cancel_task(self, task_id: str) -> Dict[str, Any]:
        if task_id in self.queued_ids:
            self.queued_ids.remove(task_id)
            self.cancelled_ids.add(task_id)
            self.db.mark_cancelled(task_id)
            await broadcaster.broadcast(
                "phage_structure_error",
                {"task_id": task_id, "error": "排队中的结构预测任务已取消", "status": "cancelled"},
            )
            await self._broadcast_snapshot()
            return {"status": "cancelled", "message": "排队中的结构预测任务已取消"}
        if task_id in self.running_ids:
            self.cancelled_ids.add(task_id)
            self.db.update_progress(task_id, -1, "正在请求中止当前分析...", status="running")
            await self._broadcast_snapshot()
            return {"status": "cancelling", "message": "已发送中止请求，将在当前步骤安全退出"}
        return {"status": "not_found", "message": "任务不在队列中或已结束"}

    def is_cancelled(self, task_id: str) -> bool:
        return task_id in self.cancelled_ids

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

    def get_queue_snapshot(self) -> Dict[str, Any]:
        running = list(self.running_ids)
        queued = list(self.queued_ids)
        return {
            "max_workers": self.max_workers,
            "is_busy": len(running) > 0 or len(queued) > 0,
            "running": running,
            "queued": queued,
            "running_count": len(running),
            "queued_count": len(queued),
            "running_tasks": [self._build_task_meta(tid) for tid in running],
            "waiting_tasks": [self._build_task_meta(tid, idx + 1) for idx, tid in enumerate(queued)],
        }

    async def _broadcast_snapshot(self) -> None:
        await broadcaster.broadcast("phage_structure_queue_update", self.get_queue_snapshot())

    async def _worker_loop(self, worker_idx: int) -> None:
        logger.info("PhageStructure 工作协程-%s 已就绪", worker_idx)
        while True:
            task_id, req, context = await self.queue.get()
            try:
                if task_id in self.cancelled_ids:
                    if task_id in self.queued_ids:
                        self.queued_ids.remove(task_id)
                    continue
                if task_id in self.queued_ids:
                    self.queued_ids.remove(task_id)
                self.running_ids.append(task_id)
                await self._broadcast_snapshot()
                release_gpu_memory()

                if self._executor is not None:
                    await self._executor(task_id, req, context)
            except Exception as exc:
                logger.exception("PhageStructure 执行异常 (%s): %s", task_id, exc)
                self.db.mark_failed(task_id, str(exc))
                await broadcaster.broadcast(
                    "phage_structure_error",
                    {"task_id": task_id, "error": str(exc), "status": "failed"},
                )
            finally:
                release_gpu_memory()
                if task_id in self.running_ids:
                    self.running_ids.remove(task_id)
                self.cancelled_ids.discard(task_id)
                self.queue.task_done()
                await self._broadcast_snapshot()


phage_structure_queue = PhageStructureQueue(max_workers=1, db=phage_structure_db)
