# -*- coding: utf-8 -*-
"""
功能注释异步持久化任务队列调度器 (AnnotationQueue)
-----------------------------------------------
1. 顺序派发：串行任务调度控制 (max_workers=1)，保护主机算力与显存资源
2. 持久化与自愈：基于 SQLite 持久化任务元数据，支持服务重启崩溃自愈
3. 状态广播：基于 WebSocket 实时广播队列快照 (排队序号、运行状态)
4. 资源守卫：执行前后主动触发 GPU 显存回收与 CPU 核心保护
"""
import os
import time
import asyncio
import logging
from typing import Dict, Any, Callable, Awaitable, List, Optional, Set

from .db import annotation_db
from ...backend.broadcaster import broadcaster

logger = logging.getLogger("analysis.annotation.queue")


class AnnotationQueue:
    """功能注释任务队列管理器 (单例)"""
    _instance: Optional["AnnotationQueue"] = None
    _initialized: bool

    _queue: List[Dict[str, Any]]
    _worker_task: Optional[asyncio.Task[Any]]
    _processor: Optional[Callable[[Dict[str, Any]], Awaitable[None]]]
    _is_running: bool
    _queued_ids: Set[str]
    _paused: bool
    _resume_event: asyncio.Event
    _new_task_event: asyncio.Event
    _current_task_id: Optional[str]

    def __new__(cls) -> "AnnotationQueue":
        if cls._instance is None:
            inst = super(AnnotationQueue, cls).__new__(cls)
            inst._initialized = False
            cls._instance = inst
        return cls._instance

    def __init__(self):
        if getattr(self, "_initialized", False):
            return
        self._queue = []
        self._queued_ids = set()
        self._worker_task = None
        self._processor = None
        self._is_running = False
        self._paused = False
        self._resume_event = asyncio.Event()
        self._resume_event.set()
        self._new_task_event = asyncio.Event()
        self._current_task_id = None
        self._initialized = True

    def _clean_gpu_cache(self):
        """安全回收 GPU 显存，防止混合计算库显存溢出"""
        try:
            import torch  # type: ignore
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                torch.cuda.ipc_collect()
        except Exception:
            pass

    async def start_workers(self, processor_func: Callable[[Dict[str, Any]], Awaitable[None]]):
        """
        启动队列处理器 (包含服务重启状态自愈)
        :param processor_func: 实际执行注释管线的异步回调
        """
        self._processor = processor_func

        if self._is_running:
            return

        self._is_running = True
        logger.info("[QUEUE] Annotation queue engine initializing...")

        # 启动安全自愈：将此前残留为 running 的任务重置为 cancelled（排除当前活跃任务）
        try:
            exclude_ids = [self._current_task_id] if self._current_task_id else []
            annotation_db.reset_interrupted_tasks(exclude_task_ids=exclude_ids)
            logger.info("[QUEUE] Previous interrupted running tasks reconciled to cancelled.")
        except Exception as e:
            logger.warning(f"[QUEUE] Self-healing reset error: {e}")

        # 启动后台消费者协程
        self._worker_task = asyncio.create_task(self._worker_loop())
        await self._broadcast_status()
        logger.info("[QUEUE] Annotation queue engine worker started successfully.")

    async def add_task(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        将新注释任务加入等待队列
        """
        task_id = payload.get("task_id")
        if not task_id or not isinstance(task_id, str):
            return {"success": False, "error": "Missing or invalid task_id in payload"}

        if task_id in self._queued_ids:
            logger.info(f"[QUEUE] Task {task_id} is already queued, ignoring duplicate.")
            return {"success": True, "task_id": task_id, "status": "queued"}

        self._queued_ids.add(task_id)
        self._queue.append(payload)
        self._new_task_event.set()
        
        position = len(self._queue)
        logger.info(f"[QUEUE] Task enqueued: {task_id}, position: #{position}")
        
        await self._broadcast_status()
        return {
            "success": True,
            "task_id": task_id,
            "position": position,
            "status": "queued"
        }

    async def _worker_loop(self):
        """主工作消费循环 (严格顺序派发)"""
        while True:
            await self._resume_event.wait()

            if not self._queue:
                self._new_task_event.clear()
                await self._new_task_event.wait()
                continue

            payload = self._queue.pop(0)
            task_id = payload.get("task_id")
            if not task_id or not isinstance(task_id, str):
                continue

            self._queued_ids.discard(task_id)
            self._current_task_id = task_id

            try:
                # 检查任务是否已被取消或删除
                current_task = annotation_db.get_task(task_id)
                if not current_task or current_task.get("status") in ("cancelled", "failed", "completed"):
                    logger.info(f"[QUEUE] Task {task_id} status is {current_task.get('status') if current_task else 'None'}, skipping execution.")
                    continue

                logger.info(f"[QUEUE] Dispatching annotation task: {task_id}")
                
                # 更新任务状态为 running
                annotation_db.update_progress(task_id, 5, "正在初始化注释工作区与输入序列...", "running")
                
                # 广播最新队列快照
                await self._broadcast_status()

                # 执行前显存清理
                self._clean_gpu_cache()

                # 执行具体流水线
                if self._processor:
                    await self._processor(payload)

            except asyncio.CancelledError:
                logger.warning(f"[QUEUE] Task {task_id} was cancelled during execution.")
                annotation_db.mark_cancelled(task_id)
            except Exception as e:
                logger.error(f"[QUEUE] Task {task_id} execution failure: {e}", exc_info=True)
                annotation_db.mark_failed(task_id, str(e))
            finally:
                self._current_task_id = None
                self._clean_gpu_cache()
                logger.info(f"[QUEUE] Task {task_id} lifecycle finished.")
                await self._broadcast_status()

    def remove_task_from_queue(self, task_id: str) -> bool:
        """从等待队列中移除指定任务"""
        if not task_id or not isinstance(task_id, str):
            return False

        initial_len = len(self._queue)
        self._queue = [p for p in self._queue if p.get("task_id") != task_id]
        if len(self._queue) < initial_len:
            self._queued_ids.discard(task_id)
            annotation_db.mark_cancelled(task_id)
            asyncio.create_task(self._broadcast_status())
            logger.info(f"[QUEUE] Task {task_id} removed from waiting queue.")
            return True
        return False

    def reorder_queue(self, task_ids: List[str]):
        """根据传入的 task_id 列表对等待队列进行重排"""
        new_queue = []
        for tid in task_ids:
            for p in self._queue:
                if p.get("task_id") == tid:
                    new_queue.append(p)
                    break

        existing_tids = {p.get("task_id") for p in new_queue}
        for p in self._queue:
            if p.get("task_id") not in existing_tids:
                new_queue.append(p)

        self._queue = new_queue
        asyncio.create_task(self._broadcast_status())
        logger.info(f"[QUEUE] Waiting queue reordered: {len(self._queue)} tasks.")

    def pause(self):
        """暂停队列派发"""
        if not self._paused:
            self._paused = True
            self._resume_event.clear()
            logger.info("[QUEUE] Queue paused.")
            asyncio.create_task(self._broadcast_status())

    def resume(self):
        """恢复队列派发"""
        if self._paused:
            self._paused = False
            self._resume_event.set()
            logger.info("[QUEUE] Queue resumed.")
            asyncio.create_task(self._broadcast_status())

    @property
    def is_paused(self) -> bool:
        return self._paused

    @property
    def current_task_id(self) -> Optional[str]:
        return self._current_task_id

    async def get_queue_status(self) -> Dict[str, Any]:
        """获取当前队列状态快照"""
        waiting_tasks = []
        for idx, item in enumerate(self._queue):
            tid = item.get("task_id")
            if not tid or not isinstance(tid, str):
                continue
            meta = annotation_db.get_task(tid) or {}
            waiting_tasks.append({
                "task_id": tid,
                "task_name": meta.get("task_name") or item.get("task_name") or tid,
                "sample_type": meta.get("sample_type") or item.get("sample_type", "BACTERIA"),
                "engine": meta.get("engine") or item.get("engine", "auto"),
                "status": "queued",
                "position": idx + 1,
                "created_at": meta.get("created_at", "")
            })

        current_info = None
        if self._current_task_id:
            curr_meta = annotation_db.get_task(self._current_task_id) or {}
            current_info = {
                "task_id": self._current_task_id,
                "task_name": curr_meta.get("task_name", self._current_task_id),
                "status": curr_meta.get("status", "running"),
                "progress": curr_meta.get("progress", 0),
                "current_step": curr_meta.get("current_step", "")
            }

        return {
            "is_busy": self._current_task_id is not None,
            "is_paused": self._paused,
            "current_task": current_info,
            "waiting_count": len(waiting_tasks),
            "waiting_tasks": waiting_tasks
        }

    async def _broadcast_status(self):
        """广播最新队列状态快照给前端"""
        try:
            snapshot = await self.get_queue_status()
            broadcaster.broadcast_sync("annotation_queue_status", snapshot)
        except Exception as e:
            logger.debug(f"[QUEUE] Broadcast queue status error: {e}")


# 全局单例
annotation_queue = AnnotationQueue()
