# -*- coding: utf-8 -*-
"""
前噬菌体发现异步单序列调度队列引擎

采用单任务串行调度 (max_workers=1) 严格控制物理显存占用，
支持服务重启后的断点自愈、运行前/后 CUDA 显存回收与 WebSocket 实时队列广播。
"""
import asyncio
import gc
import logging
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

from ...backend.broadcaster import broadcaster
from .db import PhageDiscoveryDB, phage_discovery_db

logger = logging.getLogger("PhageDiscoveryQueue")


def release_gpu_memory() -> None:
    """在推理前后强制回收 Python 对象与 CUDA 显存缓存，防止显存溢出至共享内存。"""
    gc.collect()
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            if hasattr(torch.cuda, "ipc_collect"):
                torch.cuda.ipc_collect()
    except Exception:
        pass


class PhageDiscoveryQueue:
    """单例异步前噬菌体扫描任务队列。"""

    def __init__(self, max_workers: int = 1, db: Optional[PhageDiscoveryDB] = None):
        self.max_workers = max(1, max_workers)
        self.db = db if db is not None else phage_discovery_db
        self.queue: asyncio.Queue[Tuple[str, Any, Dict[str, Any]]] = asyncio.Queue()
        self.queued_ids: List[str] = []
        self.running_ids: List[str] = []
        self.cancelled_ids: set[str] = set()
        self._workers: List[asyncio.Task[None]] = []
        self._executor: Optional[Callable[[str, Any, Dict[str, Any]], Awaitable[None]]] = None
        self._started = False

    def set_executor(
        self,
        executor: Callable[[str, Any, Dict[str, Any]], Awaitable[None]],
    ) -> None:
        self._executor = executor

    async def start(self) -> None:
        if self._started:
            return
        self._started = True

        # 重启恢复：清理之前意外中断的运行中或排队任务
        active_ids = list(set(self.queued_ids + self.running_ids))
        self.db.reset_interrupted_tasks(exclude_task_ids=active_ids)

        for idx in range(self.max_workers):
            worker = asyncio.create_task(self._worker_loop(idx))
            self._workers.append(worker)
        logger.info("PhageDiscovery 队列引擎已启动 (workers=%s)", self.max_workers)

    async def enqueue(self, task_id: str, req: Any, context: Dict[str, Any]) -> None:
        if not self._started:
            await self.start()

        self.queued_ids.append(task_id)
        await self.queue.put((task_id, req, context))
        logger.info("前噬菌体扫描任务已入队: %s (当前排队 %s)", task_id, len(self.queued_ids))
        await self._broadcast_snapshot()

    async def cancel_task(self, task_id: str) -> Dict[str, Any]:
        if task_id in self.queued_ids:
            self.cancelled_ids.add(task_id)
            self.db.mark_cancelled(task_id)
            await self._broadcast_snapshot()
            return {"status": "cancelled", "message": "排队中的前噬菌体扫描任务已取消"}
        if task_id in self.running_ids:
            self.cancelled_ids.add(task_id)
            self.db.update_progress(task_id, -1, "正在请求中止当前扫描...", status="running")
            await self._broadcast_snapshot()
            return {"status": "cancelling", "message": "已发送中止请求，将在当前阶段安全退出"}
        return {"status": "not_found", "message": "任务不在当前队列或已完成"}

    def is_cancelled(self, task_id: str) -> bool:
        return task_id in self.cancelled_ids

    def get_queue_snapshot(self) -> Dict[str, Any]:
        return {
            "max_workers": self.max_workers,
            "running": list(self.running_ids),
            "queued": list(self.queued_ids),
            "running_count": len(self.running_ids),
            "queued_count": len(self.queued_ids),
        }

    async def _broadcast_snapshot(self) -> None:
        await broadcaster.broadcast("phage_discovery_queue_update", self.get_queue_snapshot())

    async def _worker_loop(self, worker_idx: int) -> None:
        while True:
            task_id, req, context = await self.queue.get()
            if task_id in self.queued_ids:
                self.queued_ids.remove(task_id)

            if task_id in self.cancelled_ids:
                self.cancelled_ids.discard(task_id)
                self.db.mark_cancelled(task_id)
                self.queue.task_done()
                await self._broadcast_snapshot()
                continue

            self.running_ids.append(task_id)
            await self._broadcast_snapshot()

            try:
                release_gpu_memory()
                if self._executor is not None:
                    await self._executor(task_id, req, context)
            except Exception as exc:
                logger.exception("PhageDiscovery 队列执行异常 (%s): %s", task_id, exc)
                self.db.mark_failed(task_id, str(exc))
            finally:
                if task_id in self.running_ids:
                    self.running_ids.remove(task_id)
                self.cancelled_ids.discard(task_id)
                release_gpu_memory()
                self.queue.task_done()
                await self._broadcast_snapshot()


phage_discovery_queue = PhageDiscoveryQueue(max_workers=1)
