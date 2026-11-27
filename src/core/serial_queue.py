# -*- coding: utf-8 -*-
"""
共享异步串行任务队列基座 (BaseAsyncTaskQueue / BasePausableSerialQueue)

职责：
1. 抽取全仓后台耗资源任务队列的公共调度内核（严格单 worker 串行、延迟事件循环绑定、
   优雅取消/异常隔离、原地重排与移除、暂停/恢复门控、GPU 显存回收与追踪后台广播）；
2. 保持在 src/core 底层，严禁反向依赖 src/backend、src/analysis 或 src/utils。
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable, Dict, List, Optional, Set, Tuple

from .async_tasks import spawn_tracked_task
from .broadcaster import broadcaster
from .task_db import release_gpu_memory


class BaseAsyncTaskQueue:
    """
    基于 asyncio.Queue 的异步串行任务队列基类。
    适用于 PhageDiscoveryQueue 与 PhageStructureQueue 等单/受限并发计算队列。
    """

    queue_event_name: str = ""
    error_event_name: str = ""
    bg_task_label: str = "async_queue_snapshot"
    engine_label: str = "AsyncTaskQueue"
    cancel_queued_message: str = "排队中的任务已取消"
    cancel_running_step: str = "正在请求中止当前分析..."
    cancel_running_message: str = "已发送中止请求，将在当前步骤安全退出"
    not_found_message: str = "任务不在队列中或已结束"
    _reset_state_on_start: bool = False

    def __init__(self, max_workers: int = 1, db: Any = None) -> None:
        self.max_workers = max(1, max_workers)
        self.db = db
        self.queue: asyncio.Queue[Tuple[str, Any, Dict[str, Any]]] = asyncio.Queue()
        self.queued_ids: List[str] = []
        self.running_ids: List[str] = []
        self.cancelled_ids: Set[str] = set()
        self._workers: List[asyncio.Task[None]] = []
        self._bg_tasks: Set[asyncio.Task[Any]] = set()
        self._executor: Optional[Callable[[str, Any, Dict[str, Any]], Awaitable[None]]] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._started = False
        self._logger = logging.getLogger(type(self).__module__)

    def set_executor(
        self,
        executor: Callable[[str, Any, Dict[str, Any]], Awaitable[None]],
    ) -> None:
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
        if self._reset_state_on_start:
            self.queue = asyncio.Queue()
            self.queued_ids.clear()
            self.running_ids.clear()
            self.cancelled_ids.clear()
            exclude_ids: List[str] = []
        else:
            if not isinstance(self.queue, asyncio.Queue):
                self.queue = asyncio.Queue()
            exclude_ids = list(set(self.queued_ids + self.running_ids))

        self._workers = []
        if self.db is not None and hasattr(self.db, "reset_interrupted_tasks"):
            self.db.reset_interrupted_tasks(exclude_task_ids=exclude_ids)

        for idx in range(self.max_workers):
            self._workers.append(asyncio.create_task(self._worker_loop(idx)))
        self._logger.info("%s 队列引擎已启动 (workers=%s)", self.engine_label, self.max_workers)

    async def broadcast_snapshot(self) -> None:
        """向前端广播当前最新队列快照。"""
        await self._broadcast_snapshot()

    async def _broadcast_snapshot(self) -> None:
        if not self.queue_event_name:
            return
        await broadcaster.broadcast(self.queue_event_name, self.get_queue_snapshot())

    def remove_from_waiting(self, task_id: str) -> bool:
        """从等待队列中同步剔除指定任务并调度快照更新。"""
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
                    label=self.bg_task_label,
                    loop=loop,
                )
            except RuntimeError:
                self._logger.debug("remove_from_waiting: 无运行中事件循环，跳过快照广播")
        return removed

    async def cancel_task(self, task_id: str) -> Dict[str, Any]:
        """取消排队中或正在运行的任务。"""
        if task_id in self.queued_ids:
            self.queued_ids.remove(task_id)
            self.cancelled_ids.add(task_id)
            if self.db is not None:
                self.db.mark_cancelled(task_id)
            if self.error_event_name:
                await broadcaster.broadcast(
                    self.error_event_name,
                    {"task_id": task_id, "error": self.cancel_queued_message, "status": "cancelled"},
                )
            await self._broadcast_snapshot()
            return {"status": "cancelled", "message": self.cancel_queued_message}

        if task_id in self.running_ids:
            self.cancelled_ids.add(task_id)
            if self.db is not None:
                self.db.update_progress(task_id, -1, self.cancel_running_step, status="running")
            await self._broadcast_snapshot()
            return {"status": "cancelling", "message": self.cancel_running_message}

        return {"status": "not_found", "message": self.not_found_message}

    def is_cancelled(self, task_id: str) -> bool:
        return task_id in self.cancelled_ids

    def _build_task_meta(self, task_id: str, position: Optional[int] = None) -> Dict[str, Any]:
        meta = (self.db.get_task(task_id) if self.db is not None else None) or {}
        item: Dict[str, Any] = {
            "task_id": task_id,
            "task_name": meta.get("task_name") or task_id,
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
        running_cnt = len(self.running_ids)
        queued_cnt = len(self.queued_ids)
        await self.queue.put((task_id, req, context))
        self._logger.info(
            "%s 任务已入队: %s (当前排队位次 #%s, 运行中 %s)",
            self.engine_label,
            task_id,
            queue_pos,
            running_cnt,
        )
        if broadcast:
            await self._broadcast_snapshot()
        return {
            "task_id": task_id,
            "queue_position": queue_pos,
            "is_busy": was_busy,
            "running_count": running_cnt,
            "queued_count": queued_cnt,
        }

    async def _on_cancelled_before_start(self, task_id: str) -> None:
        if self.db is not None and self.db.get_task(task_id) is not None:
            self.db.mark_cancelled(task_id)

    async def _on_task_started(self, task_id: str) -> None:
        await self._broadcast_snapshot()

    async def _on_task_failed(self, task_id: str, exc: Exception) -> None:
        if self.db is not None:
            self.db.mark_failed(task_id, str(exc))

    async def _worker_loop(self, worker_idx: int) -> None:
        self._logger.debug("%s 工作协程-%s 已就绪", self.engine_label, worker_idx)
        while True:
            task_id, req, context = await self.queue.get()
            if task_id in self.queued_ids:
                self.queued_ids.remove(task_id)

            if task_id in self.cancelled_ids:
                self.cancelled_ids.discard(task_id)
                await self._on_cancelled_before_start(task_id)
                self.queue.task_done()
                await self._broadcast_snapshot()
                continue

            self.running_ids.append(task_id)
            try:
                await self._on_task_started(task_id)
                release_gpu_memory()
                if self._executor is not None:
                    await self._executor(task_id, req, context)
            except Exception as exc:
                self._logger.exception("%s 队列执行异常 (%s): %s", self.engine_label, task_id, exc)
                await self._on_task_failed(task_id, exc)
            finally:
                if task_id in self.running_ids:
                    self.running_ids.remove(task_id)
                self.cancelled_ids.discard(task_id)
                release_gpu_memory()
                self.queue.task_done()
                await self._broadcast_snapshot()


class BasePausableSerialQueue:
    """
    可暂停、可原地重排的严格串行任务队列基类。
    适用于 AnnotationQueue 与 PersistentAssemblyQueue。
    """

    broadcast_label: str = "serial_queue_broadcast"
    _broadcast_on_pause_resume: bool = False

    _queue: Optional[List[Dict[str, Any]]]
    _queued_ids: Set[str]
    _worker_task: Optional[asyncio.Task[Any]]
    _processor: Optional[Callable[[Dict[str, Any]], Awaitable[None]]]
    _is_running: bool
    _paused: bool
    _resume_event: Optional[asyncio.Event]
    _new_task_event: Optional[asyncio.Event]
    _current_task_id: Optional[str]
    _bg_tasks: Set[asyncio.Task[Any]]

    def _init_base_state(self) -> None:
        self._queue = []
        self._queued_ids = set()
        self._worker_task = None
        self._processor = None
        self._is_running = False
        self._paused = False
        self._resume_event = None
        self._new_task_event = None
        self._current_task_id = None
        self._bg_tasks = set()

    def _ensure_queue(self) -> None:
        if self._queue is None:
            self._queue = []
        if getattr(self, "_new_task_event", None) is None:
            self._new_task_event = asyncio.Event()
        if getattr(self, "_resume_event", None) is None:
            self._resume_event = asyncio.Event()
            self._resume_event.set()
        if getattr(self, "_bg_tasks", None) is None:
            self._bg_tasks = set()

    def _get_queue_parts(self) -> Tuple[List[Dict[str, Any]], asyncio.Event, asyncio.Event]:
        self._ensure_queue()
        assert self._queue is not None
        assert self._new_task_event is not None
        assert self._resume_event is not None
        return self._queue, self._new_task_event, self._resume_event

    def _schedule_broadcast(self) -> None:
        """在有运行中事件循环时安全调度队列快照广播，避免非异步上下文报错。"""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        bg_tasks: Optional[Set[asyncio.Task[Any]]] = getattr(self, "_bg_tasks", None)
        if bg_tasks is None:
            bg_tasks = set()
            self._bg_tasks = bg_tasks
        spawn_tracked_task(self._broadcast_status(), bg_tasks, label=self.broadcast_label, loop=loop)

    def _remove_task_inplace(self, task_id: str) -> bool:
        """原地切片移除等待队列中指定 task_id，保持 self._queue 列表引用不变。"""
        if not task_id or not isinstance(task_id, str):
            return False
        queue, _, _ = self._get_queue_parts()
        initial_len = len(queue)
        queue[:] = [p for p in queue if p.get("task_id") != task_id]
        if len(queue) < initial_len:
            self._queued_ids.discard(task_id)
            return True
        return False

    def reorder_queue(self, task_ids: List[str]) -> None:
        """根据传入 task_id 列表原地重排等待队列，并保留未提及任务垫底。"""
        queue, _, _ = self._get_queue_parts()
        new_queue: List[Dict[str, Any]] = []
        for tid in task_ids:
            for item in queue:
                if item.get("task_id") == tid:
                    new_queue.append(item)
                    break

        existing_tids = {item.get("task_id") for item in new_queue}
        for item in queue:
            if item.get("task_id") not in existing_tids:
                new_queue.append(item)

        queue[:] = new_queue
        self._schedule_broadcast()

    def pause(self) -> None:
        """暂停队列新任务派发（不中断当前运行任务）。"""
        _, _, resume_event = self._get_queue_parts()
        if not self._paused:
            self._paused = True
            resume_event.clear()
            if self._broadcast_on_pause_resume:
                self._schedule_broadcast()

    def resume(self) -> None:
        """恢复队列任务派发。"""
        _, _, resume_event = self._get_queue_parts()
        if self._paused:
            self._paused = False
            resume_event.set()
            if self._broadcast_on_pause_resume:
                self._schedule_broadcast()

    @property
    def is_paused(self) -> bool:
        return self._paused

    @property
    def current_task_id(self) -> Optional[str]:
        return self._current_task_id

    def get_waiting_ids(self) -> List[str]:
        """按权威排队顺序返回等待中的 task_id 列表。"""
        if not self._queue:
            return []
        return [
            tid
            for item in self._queue
            if isinstance((tid := item.get("task_id")), str) and tid
        ]

    def get_queue_position(self, task_id: str) -> int:
        """返回 task_id 在等待队列中的 1-based 位次；正在运行或未排队统一返回 0。"""
        if not task_id or not self._queue:
            return 0
        for idx, item in enumerate(self._queue, start=1):
            if item.get("task_id") == task_id:
                return idx
        return 0

    def get_queue_size(self) -> int:
        if not self._queue:
            return 0
        return len(self._queue)

    async def _broadcast_status(self) -> None:
        raise NotImplementedError

    async def _before_dispatch(self, task_id: str, payload: Dict[str, Any]) -> bool:
        return True

    async def _on_dispatch_cancelled(self, task_id: str) -> None:
        return None

    async def _on_dispatch_error(self, task_id: str, exc: Exception) -> None:
        return None

    async def _after_dispatch(self, task_id: str) -> None:
        return None

    async def _worker_loop(self) -> None:
        """严格串行消费者循环（含暂停门控与无竞态唤醒）。"""
        while True:
            queue, new_task_event, resume_event = self._get_queue_parts()
            await resume_event.wait()

            if not queue:
                new_task_event.clear()
                if not queue:
                    await new_task_event.wait()
                continue

            payload = queue.pop(0)
            task_id = payload.get("task_id")
            if not isinstance(task_id, str) or not task_id:
                continue
            self._queued_ids.discard(task_id)
            self._current_task_id = task_id

            cancelled = False
            try:
                should_run = await self._before_dispatch(task_id, payload)
                if not should_run:
                    continue
                if self._processor is not None:
                    await self._processor(payload)
            except asyncio.CancelledError:
                cancelled = True
                await self._on_dispatch_cancelled(task_id)
                raise
            except Exception as exc:
                await self._on_dispatch_error(task_id, exc)
            finally:
                self._current_task_id = None
                await self._after_dispatch(task_id)
                if not cancelled:
                    await self._broadcast_status()
