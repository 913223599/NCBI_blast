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

    async def enqueue(self, task_id: str, req: Any, context: Dict[str, Any]) -> Dict[str, Any]:
        if not self._started:
            await self.start()

        was_busy = len(self.running_ids) > 0 or len(self.queued_ids) > 0
        self.queued_ids.append(task_id)
        queue_pos = len(self.queued_ids)
        running_cnt = len(self.running_ids)
        queued_cnt = len(self.queued_ids)
        await self.queue.put((task_id, req, context))
        logger.info("前噬菌体扫描任务已入队: %s (当前排队位次 #%s, 运行中 %s)", task_id, queue_pos, running_cnt)
        await self._broadcast_snapshot()
        return {
            "task_id": task_id,
            "queue_position": queue_pos,
            "is_busy": was_busy,
            "running_count": running_cnt,
            "queued_count": queued_cnt,
        }

    def remove_from_waiting(self, task_id: str) -> bool:
        """从等待队列中同步剔除指定任务并触发快照更新。"""
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
                loop.create_task(self._broadcast_snapshot())
            except RuntimeError:
                pass
        return removed

    async def cancel_task(self, task_id: str) -> Dict[str, Any]:
        if task_id in self.queued_ids:
            self.queued_ids.remove(task_id)
            self.cancelled_ids.add(task_id)
            self.db.mark_cancelled(task_id)
            await broadcaster.broadcast(
                "phage_discovery_error",
                {"task_id": task_id, "error": "排队中的前噬菌体扫描任务已取消", "status": "cancelled"},
            )
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

    def _build_task_meta(self, task_id: str, position: Optional[int] = None) -> Dict[str, Any]:
        meta = self.db.get_task(task_id) or {}
        item: Dict[str, Any] = {
            "task_id": task_id,
            "task_name": meta.get("task_name") or task_id,
            "model_version": meta.get("model_version") or "V4.2",
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
        await broadcaster.broadcast("phage_discovery_queue_update", self.get_queue_snapshot())

    async def _worker_loop(self, worker_idx: int) -> None:
        while True:
            task_id, req, context = await self.queue.get()
            if task_id in self.queued_ids:
                self.queued_ids.remove(task_id)

            if task_id in self.cancelled_ids:
                self.cancelled_ids.discard(task_id)
                if self.db.get_task(task_id) is not None:
                    self.db.mark_cancelled(task_id)
                self.queue.task_done()
                await self._broadcast_snapshot()
                continue

            self.running_ids.append(task_id)
            self.db.update_progress(task_id, 2, "正在调度计算引擎启动扫描...", status="running")
            await broadcaster.broadcast(
                "phage_discovery_progress",
                {"task_id": task_id, "progress": 2, "message": "正在调度计算引擎启动扫描...", "status": "running"},
            )
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
