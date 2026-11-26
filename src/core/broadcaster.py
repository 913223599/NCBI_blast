# -*- coding: utf-8 -*-
"""全局事件广播器 (EventBroadcaster)，供 backend 路由与各领域引擎单向复用。"""
from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from typing import Any, Dict, Optional, Set

from .async_tasks import spawn_tracked_task
from .json_encoder import BioJsonEncoder

logger = logging.getLogger("broadcaster")


class EventBroadcaster:
    """具备发送者识别与排除能力的 WebSocket 广播器，防止多端同步回环。"""

    def __init__(self) -> None:
        self.connections: Dict[Any, str] = {}
        self._lock = threading.Lock()
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._bg_tasks: Set[asyncio.Task[Any]] = set()

    async def connect(self, websocket: Any, client_id: str = "unknown") -> None:
        """处理新连接进入，记录其唯一的 client_id。"""
        if not self._loop:
            self._loop = asyncio.get_running_loop()

        await websocket.accept()
        with self._lock:
            self.connections[websocket] = client_id
            logger.info("WebSocket 接入: ID=%s, 当前总连接数: %s", client_id, len(self.connections))

    def disconnect(self, websocket: Any) -> None:
        """处理连接断开。"""
        with self._lock:
            if websocket in self.connections:
                client_id = self.connections.pop(websocket)
                logger.info("WebSocket 离开: ID=%s, 剩余连接数: %s", client_id, len(self.connections))

    async def broadcast(
        self,
        event_type: str,
        data: Optional[Dict[str, Any]] = None,
        exclude_id: Optional[str] = None,
    ) -> None:
        """向全部在线客户端广播消息（可选排除发送者本身）。"""
        payload = {
            "type": event_type,
            "data": data or {},
            "sender_id": exclude_id,
            "timestamp": time.time(),
        }
        message = json.dumps(payload, ensure_ascii=False, cls=BioJsonEncoder)

        with self._lock:
            targets = list(self.connections.keys())

        if not targets:
            return

        disconnected = []
        for connection in targets:
            with self._lock:
                cid = self.connections.get(connection)
                if not cid or (exclude_id and cid == exclude_id):
                    continue
            try:
                await connection.send_text(message)
            except Exception:
                disconnected.append(connection)

        for conn in disconnected:
            self.disconnect(conn)

    def broadcast_sync(
        self,
        event_type: str,
        data: Optional[Dict[str, Any]] = None,
        exclude_id: Optional[str] = None,
    ) -> None:
        """线程安全的同步广播包装。"""
        if self._loop and self._loop.is_running():
            asyncio.run_coroutine_threadsafe(
                self.broadcast(event_type, data, exclude_id),
                self._loop,
            )
            return
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                spawn_tracked_task(
                    self.broadcast(event_type, data, exclude_id),
                    self._bg_tasks,
                    label=f"broadcast:{event_type}",
                    loop=loop,
                )
            else:
                loop.run_until_complete(self.broadcast(event_type, data, exclude_id))
        except RuntimeError:
            logger.debug("No active event loop for broadcast_sync(%s)", event_type)

    async def broadcast_to_client(
        self,
        client_id: str,
        event_type: str,
        data: Optional[Dict[str, Any]] = None,
    ) -> None:
        """定向广播：仅发送给特定 client_id 的客户端。"""
        payload = {
            "type": event_type,
            "data": data or {},
            "timestamp": time.time(),
        }
        message = json.dumps(payload, ensure_ascii=False, cls=BioJsonEncoder)

        with self._lock:
            targets = [conn for conn, cid in self.connections.items() if cid == client_id]

        for connection in targets:
            try:
                await connection.send_text(message)
            except Exception:
                self.disconnect(connection)

    def broadcast_to_client_sync(
        self,
        client_id: str,
        event_type: str,
        data: Optional[Dict[str, Any]] = None,
    ) -> None:
        """定向广播的同步包装。"""
        if self._loop and self._loop.is_running():
            asyncio.run_coroutine_threadsafe(
                self.broadcast_to_client(client_id, event_type, data),
                self._loop,
            )
            return
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                spawn_tracked_task(
                    self.broadcast_to_client(client_id, event_type, data),
                    self._bg_tasks,
                    label=f"broadcast_to_client:{event_type}",
                    loop=loop,
                )
            else:
                loop.run_until_complete(self.broadcast_to_client(client_id, event_type, data))
        except RuntimeError:
            logger.debug("No active event loop for broadcast_to_client_sync(%s)", event_type)


# 全局共享单例
broadcaster = EventBroadcaster()
