# -*- coding: utf-8 -*-
"""
生物数据库更新任务状态中心 (bio_db.state_registry)

统一管理线程安全的更新进度快照、取消信号量与后台 asyncio.Task 强引用托管，
彻底消除路由层与测试代码对底层私有集合的直接访问。
"""
from __future__ import annotations

import asyncio
import threading
import time
from typing import Any, Coroutine, Dict, Optional, Set, Tuple

from ....core.async_tasks import spawn_tracked_task


class DbUpdateStateRegistry:
    """线程安全的数据库更新状态与后台任务生命周期管理器。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._states: Dict[str, Dict[str, Any]] = {}
        self._cancel_events: Dict[str, threading.Event] = {}
        self._bg_tasks: Set[asyncio.Task[Any]] = set()

    def is_updating(self, db_id: str) -> bool:
        """判断指定数据库当前是否处于 updating 运行态。"""
        with self._lock:
            state = self._states.get(db_id)
            return bool(state and state.get("status") == "updating")

    def get_state(self, db_id: str) -> Optional[Dict[str, Any]]:
        """返回指定数据库最近一次更新状态副本（无记录返回 None）。"""
        with self._lock:
            state = self._states.get(db_id)
            return dict(state) if state is not None else None

    def begin_update(
        self,
        db_id: str,
        message: str,
    ) -> Tuple[bool, Dict[str, Any], Optional[threading.Event]]:
        """原子尝试开启更新任务；若已在更新中返回 (False, existing_state, None)。"""
        with self._lock:
            existing = self._states.get(db_id)
            if existing and existing.get("status") == "updating":
                return False, dict(existing), None
            cancel_event = threading.Event()
            state: Dict[str, Any] = {
                "db_id": db_id,
                "status": "updating",
                "progress": 5,
                "message": message,
                "updated_at": time.time(),
            }
            self._states[db_id] = state
            self._cancel_events[db_id] = cancel_event
            return True, dict(state), cancel_event

    def report_progress(self, db_id: str, progress: int, message: str) -> Dict[str, Any]:
        """更新内存中的进度快照并返回副本。"""
        with self._lock:
            state: Dict[str, Any] = {
                "db_id": db_id,
                "status": "updating",
                "progress": max(0, min(100, int(progress))),
                "message": message,
                "updated_at": time.time(),
            }
            self._states[db_id] = state
            return dict(state)

    def finish_update(self, db_id: str, status: str, progress: int, message: str) -> Dict[str, Any]:
        """写入终态（success / error / cancelled）并释放取消信号量。"""
        with self._lock:
            self._cancel_events.pop(db_id, None)
            state: Dict[str, Any] = {
                "db_id": db_id,
                "status": status,
                "progress": max(0, min(100, int(progress))),
                "message": message,
                "updated_at": time.time(),
            }
            self._states[db_id] = state
            return dict(state)

    def cancel_update(self, db_id: str) -> Tuple[bool, str]:
        """向正在更新中的数据库任务发送取消信号。"""
        with self._lock:
            ev = self._cancel_events.get(db_id)
            state = self._states.get(db_id)
            if ev is None or not state or state.get("status") != "updating":
                return False, f"数据库 {db_id} 当前未在更新中"
            ev.set()
            state["message"] = "正在取消更新任务..."
            state["updated_at"] = time.time()
            return True, f"已发送取消指令至 {db_id}"

    def spawn_task(self, db_id: str, coro: Coroutine[Any, Any, Any]) -> asyncio.Task[Any]:
        """在当前事件循环中启动受强引用托管的数据库更新任务。"""
        return spawn_tracked_task(coro, self._bg_tasks, label=f"db_update:{db_id}")

    async def wait_all_tasks(self) -> None:
        """等待当前所有托管中的后台更新任务结束。"""
        tasks = list(self._bg_tasks)
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    def clear_state(self, db_id: str) -> None:
        """清理指定数据库的状态记录与取消信号（用于测试重置）。"""
        with self._lock:
            self._states.pop(db_id, None)
            self._cancel_events.pop(db_id, None)
