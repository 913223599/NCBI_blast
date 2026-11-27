# -*- coding: utf-8 -*-
"""
PersistentAssemblyQueue - 基因组组装持久化串行任务队列
"""
from __future__ import annotations

import asyncio
import logging
import sqlite3
import time
from typing import Any, Awaitable, Callable, Dict, List, Optional

from ...core.serial_queue import BasePausableSerialQueue
from ..broadcaster import broadcaster
from .assembly_db import assembly_db

logger = logging.getLogger("Assembly.Queue")


class PersistentAssemblyQueue(BasePausableSerialQueue):
    """
    PersistentAssemblyQueue - 持久化串行任务队列
    -------------------------------------------
    1. 严格串行：同一时间只有一个 Worker (max_workers=1)
    2. 持久化：任务状态实时同步至 SQLite，支持崩溃重启后自愈
    3. 异步驱动：基于 BasePausableSerialQueue 实现轻量级调度
    4. 可暂停/恢复：pause() / resume() 控制新任务派发
    """

    _instance: Optional["PersistentAssemblyQueue"] = None
    broadcast_label = "assembly_queue_broadcast"
    _broadcast_on_pause_resume = False

    def __new__(cls) -> "PersistentAssemblyQueue":
        if cls._instance is None:
            inst = super(PersistentAssemblyQueue, cls).__new__(cls)
            inst._init_base_state()
            inst._queue = None
            cls._instance = inst
        return cls._instance

    async def start_workers(self, processor_func: Callable[[Dict[str, Any]], Awaitable[None]]) -> None:
        """
        启动队列处理器 (启动自愈)
        :param processor_func: 实际执行流水线的函数
        """
        self._ensure_queue()
        self._processor = processor_func

        if self._is_running:
            return

        self._is_running = True
        logger.info("[Queue] 串行持久化队列引擎启动中...")

        # 安全重置：将所有未完结的僵尸任务（running/pending/queued）标记为 aborted
        with sqlite3.connect(assembly_db.DB_PATH) as conn:
            conn.execute(
                "UPDATE assembly_tasks SET status = 'aborted', updated_at = ? WHERE status IN ('running', 'pending', 'queued')",
                (time.time(),),
            )
            conn.commit()
        logger.info("[Queue] 任务队列已重置：之前的未完结任务已设为'已中止'，请在历史记录中按需重跑。")

        self._worker_task = asyncio.create_task(self._worker_loop())
        await self._broadcast_status()

    async def add_task(self, payload: Dict[str, Any]) -> None:
        """入队新任务"""
        queue, new_task_event, _ = self._get_queue_parts()
        task_id = payload.get("task_id")
        if not isinstance(task_id, str) or not task_id:
            return
        if task_id in self._queued_ids:
            logger.info(f"[Queue] 任务 {task_id} 已经在队列中，忽略重复请求。")
            return

        self._queued_ids.add(task_id)
        queue.append(payload)
        new_task_event.set()
        logger.info(f"[Queue] 任务已追加至队列: {task_id}")
        await self._broadcast_status()

    async def _before_dispatch(self, task_id: str, payload: Dict[str, Any]) -> bool:
        current_task = assembly_db.get_task(task_id)
        if not current_task or current_task.get("status") == "aborted":
            logger.info(f"[Queue] 任务 {task_id} 已取消或不存在，跳过。")
            return False

        logger.info(f"[Queue] 正在派发任务: {task_id}")
        assembly_db.update_task_progress(task_id, "QUEUED", 0, "running")
        await self._broadcast_status()
        return True

    async def _on_dispatch_error(self, task_id: str, exc: Exception) -> None:
        logger.error(f"[Queue] 任务派发崩溃: {task_id}, 错误: {exc}")

    async def _after_dispatch(self, task_id: str) -> None:
        logger.info(f"[Queue] 任务生命周期结束: {task_id}")

    def remove_task_from_queue(self, task_id: str) -> bool:
        """从等待队列中移除指定任务（原地切片修改，保持 self._queue 引用不变）"""
        if self._remove_task_inplace(task_id):
            # 同步更新数据库状态为 aborted 以防前端闪烁
            assembly_db.update_task_progress(task_id, "ABORTED", 0, "aborted")
            self._schedule_broadcast()
            return True
        return False

    def pause(self) -> None:
        """暂停队列派发（当前运行中的任务不受影响）"""
        was_paused = self._paused
        super().pause()
        if not was_paused:
            logger.info("[Queue] 队列已暂停，新任务将等待恢复后再派发。")

    def resume(self) -> None:
        """恢复队列派发"""
        was_paused = self._paused
        super().resume()
        if was_paused:
            logger.info("[Queue] 队列已恢复，继续派发任务。")

    def get_queue_snapshot(self) -> Dict[str, Any]:
        """基于内存队列权威顺序与数据库元数据生成统一队列快照（供 REST API 与 WS 共用）。"""
        db_tasks = {t["id"]: t for t in assembly_db.get_incomplete_tasks()}

        running_item: Optional[Dict[str, Any]] = None
        if self._current_task_id:
            meta = db_tasks.get(self._current_task_id) or assembly_db.get_task(self._current_task_id) or {}
            running_item = {
                "id": self._current_task_id,
                "name": meta.get("name", self._current_task_id),
                "status": "running",
                "position": 0,
                "tech": meta.get("tech"),
                "sample_type": meta.get("sample_type"),
                "progress": meta.get("progress", 0.0),
                "last_step": meta.get("last_step", ""),
            }

        waiting_items: List[Dict[str, Any]] = []
        for idx, payload in enumerate(self._queue or [], start=1):
            tid = payload.get("task_id")
            if not isinstance(tid, str) or not tid or tid == self._current_task_id:
                continue
            meta = db_tasks.get(tid) or assembly_db.get_task(tid) or {}
            waiting_items.append(
                {
                    "id": tid,
                    "name": meta.get("name") or payload.get("name") or tid,
                    "status": "queued",
                    "position": idx,
                    "tech": meta.get("tech") or payload.get("tech"),
                    "sample_type": meta.get("sample_type") or payload.get("sample_type"),
                    "progress": meta.get("progress", 0.0),
                    "last_step": meta.get("last_step", ""),
                }
            )

        queue_list: List[Dict[str, Any]] = []
        if running_item is not None:
            queue_list.append(running_item)
        queue_list.extend(waiting_items)

        return {
            "queue": queue_list,
            "paused": self._paused,
            "current_task_id": self._current_task_id,
            "running_task": running_item,
            "waiting_count": len(waiting_items),
            "waiting_tasks": waiting_items,
            "is_busy": self._current_task_id is not None,
        }

    async def _broadcast_status(self) -> None:
        """同步并广播当前队列状态快照"""
        try:
            await broadcaster.broadcast("assembly_queue_status", self.get_queue_snapshot())
        except Exception as e:
            logger.error(f"广播队列状态失败: {e}")

    async def get_queue_status(self) -> List[Dict[str, Any]]:
        """获取当前队列状态快照 (供历史兼容调用)"""
        try:
            snap = self.get_queue_snapshot()
            return list(snap.get("queue", []))
        except Exception as e:
            logger.error(f"获取队列状态失败: {e}")
            return []


# 全局单例
persistent_queue = PersistentAssemblyQueue()
