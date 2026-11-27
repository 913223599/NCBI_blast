# -*- coding: utf-8 -*-
"""
功能注释异步持久化任务队列调度器 (AnnotationQueue)
-----------------------------------------------
1. 顺序派发：串行任务调度控制 (max_workers=1)，保护主机算力与显存资源
2. 持久化与自愈：基于 SQLite 持久化任务元数据，支持服务重启崩溃自愈
3. 状态广播：基于 WebSocket 实时广播队列快照 (排队序号、运行状态)
4. 资源守卫：执行前后主动触发 GPU 显存回收与 CPU 核心保护
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable, Dict, List, Optional

from ...core.broadcaster import broadcaster
from ...core.serial_queue import BasePausableSerialQueue
from ...core.task_db import release_gpu_memory
from .db import annotation_db

logger = logging.getLogger("analysis.annotation.queue")


class AnnotationQueue(BasePausableSerialQueue):
    """功能注释任务队列管理器 (单例)"""

    _instance: Optional["AnnotationQueue"] = None
    _initialized: bool
    broadcast_label = "annotation_queue_broadcast"
    _broadcast_on_pause_resume = True

    def __new__(cls) -> "AnnotationQueue":
        if cls._instance is None:
            inst = super(AnnotationQueue, cls).__new__(cls)
            inst._initialized = False
            cls._instance = inst
        return cls._instance

    def __init__(self) -> None:
        if getattr(self, "_initialized", False):
            return
        self._init_base_state()
        self._initialized = True

    def _clean_gpu_cache(self) -> None:
        """安全回收 GPU 显存，防止混合计算库显存溢出"""
        release_gpu_memory()

    async def start_workers(self, processor_func: Callable[[Dict[str, Any]], Awaitable[None]]) -> None:
        """
        启动队列处理器 (包含服务重启状态自愈)
        :param processor_func: 实际执行注释管线的异步回调
        """
        self._ensure_queue()
        self._processor = processor_func

        if self._is_running:
            return

        self._is_running = True
        logger.info("[QUEUE] Annotation queue engine initializing...")

        try:
            exclude_ids = [self._current_task_id] if self._current_task_id else []
            annotation_db.reset_interrupted_tasks(exclude_task_ids=exclude_ids)
            logger.info("[QUEUE] Previous interrupted running tasks reconciled to cancelled.")
        except Exception as e:
            logger.warning(f"[QUEUE] Self-healing reset error: {e}")

        self._worker_task = asyncio.create_task(self._worker_loop())
        await self._broadcast_status()
        logger.info("[QUEUE] Annotation queue engine worker started successfully.")

    async def add_task(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """将新注释任务加入等待队列"""
        queue, new_task_event, _ = self._get_queue_parts()
        task_id = payload.get("task_id")
        if not task_id or not isinstance(task_id, str):
            return {"success": False, "error": "Missing or invalid task_id in payload"}

        if task_id in self._queued_ids:
            logger.info(f"[QUEUE] Task {task_id} is already queued, ignoring duplicate.")
            return {"success": True, "task_id": task_id, "status": "queued"}

        self._queued_ids.add(task_id)
        queue.append(payload)
        new_task_event.set()

        position = len(queue)
        logger.info(f"[QUEUE] Task enqueued: {task_id}, position: #{position}")

        await self._broadcast_status()
        return {
            "success": True,
            "task_id": task_id,
            "position": position,
            "status": "queued",
        }

    async def _before_dispatch(self, task_id: str, payload: Dict[str, Any]) -> bool:
        current_task = annotation_db.get_task(task_id)
        if not current_task or current_task.get("status") in ("cancelled", "failed", "completed"):
            logger.info(
                f"[QUEUE] Task {task_id} status is "
                f"{current_task.get('status') if current_task else 'None'}, skipping execution."
            )
            return False

        logger.info(f"[QUEUE] Dispatching annotation task: {task_id}")
        annotation_db.update_progress(task_id, 5, "正在初始化注释工作区与输入序列...", "running")
        await self._broadcast_status()
        self._clean_gpu_cache()
        return True

    async def _on_dispatch_cancelled(self, task_id: str) -> None:
        logger.warning(f"[QUEUE] Task {task_id} was cancelled during execution.")
        annotation_db.mark_cancelled(task_id)

    async def _on_dispatch_error(self, task_id: str, exc: Exception) -> None:
        logger.error(f"[QUEUE] Task {task_id} execution failure: {exc}", exc_info=True)
        annotation_db.mark_failed(task_id, str(exc))

    async def _after_dispatch(self, task_id: str) -> None:
        self._clean_gpu_cache()
        logger.info(f"[QUEUE] Task {task_id} lifecycle finished.")

    def remove_task_from_queue(self, task_id: str) -> bool:
        """从等待队列中移除指定任务"""
        if self._remove_task_inplace(task_id):
            annotation_db.mark_cancelled(task_id)
            self._schedule_broadcast()
            logger.info(f"[QUEUE] Task {task_id} removed from waiting queue.")
            return True
        return False

    def reorder_queue(self, task_ids: List[str]) -> None:
        """根据传入的 task_id 列表对等待队列进行重排"""
        super().reorder_queue(task_ids)
        logger.info(f"[QUEUE] Waiting queue reordered: {len(self._queue or [])} tasks.")

    def pause(self) -> None:
        """暂停队列派发"""
        was_paused = self._paused
        super().pause()
        if not was_paused:
            logger.info("[QUEUE] Queue paused.")

    def resume(self) -> None:
        """恢复队列派发"""
        was_paused = self._paused
        super().resume()
        if was_paused:
            logger.info("[QUEUE] Queue resumed.")

    async def get_queue_status(self) -> Dict[str, Any]:
        """获取当前队列状态快照"""
        waiting_tasks = []
        for idx, item in enumerate(self._queue or []):
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
                "created_at": meta.get("created_at", ""),
            })

        current_info = None
        if self._current_task_id:
            curr_meta = annotation_db.get_task(self._current_task_id) or {}
            current_info = {
                "task_id": self._current_task_id,
                "task_name": curr_meta.get("task_name", self._current_task_id),
                "status": curr_meta.get("status", "running"),
                "progress": curr_meta.get("progress", 0),
                "current_step": curr_meta.get("current_step", ""),
            }

        return {
            "is_busy": self._current_task_id is not None,
            "is_paused": self._paused,
            "current_task": current_info,
            "waiting_count": len(waiting_tasks),
            "waiting_tasks": waiting_tasks,
        }

    async def _broadcast_status(self) -> None:
        """广播最新队列状态快照给前端"""
        try:
            snapshot = await self.get_queue_status()
            broadcaster.broadcast_sync("annotation_queue_status", snapshot)
        except Exception as e:
            logger.debug(f"[QUEUE] Broadcast queue status error: {e}")


# 全局单例
annotation_queue = AnnotationQueue()
