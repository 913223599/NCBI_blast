# -*- coding: utf-8 -*-
"""
异步后台任务托管辅助 (async_tasks)

统一持有 fire-and-forget asyncio.Task 强引用并在完成后自动回收、记录未捕获异常，
防止任务在事件循环中被垃圾回收静默中断 (RUF006)。
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Coroutine, Optional, Set

logger = logging.getLogger("core.async_tasks")


def spawn_tracked_task(
    coro: Coroutine[Any, Any, Any],
    registry: Set[asyncio.Task[Any]],
    *,
    label: str = "",
    loop: Optional[asyncio.AbstractEventLoop] = None,
) -> asyncio.Task[Any]:
    """创建并托管异步任务，在结束时自动移出集合并记录非取消异常。"""
    task = loop.create_task(coro) if loop is not None else asyncio.create_task(coro)
    registry.add(task)

    def _on_done(done_task: asyncio.Task[Any]) -> None:
        registry.discard(done_task)
        if done_task.cancelled():
            return
        exc = done_task.exception()
        if exc is not None:
            logger.warning("后台异步任务执行异常 [%s]: %s", label or done_task.get_name(), exc)

    task.add_done_callback(_on_done)
    return task
