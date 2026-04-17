import asyncio
import json
import logging
import threading
import time
from typing import List, Dict, Any, Optional
from fastapi import WebSocket, WebSocketDisconnect
from .utils.json_encoder import BioJsonEncoder

logger = logging.getLogger("broadcaster")

class EventBroadcaster:
    """
    升级版广播模块 - 具备发送者识别与排除能力，防止同步死循环。
    """

    def __init__(self):
        # 记录 WebSocket -> client_id 的映射
        self.connections: Dict[WebSocket, str] = {}
        self._lock = threading.Lock()
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    async def connect(self, websocket: WebSocket, client_id: str = "unknown"):
        """处理新连接进入，记录其唯一的 client_id"""
        # 记录主线程循环，确保后续从其它线程广播时能正确调度
        if not self._loop:
            self._loop = asyncio.get_running_loop()
            
        await websocket.accept()
        with self._lock:
            self.connections[websocket] = client_id
            logger.info(f"WebSocket 接入: ID={client_id}, 当前总连接数: {len(self.connections)}")

    def disconnect(self, websocket: WebSocket):
        """处理连接断开"""
        with self._lock:
            if websocket in self.connections:
                client_id = self.connections.pop(websocket)
                logger.info(f"WebSocket 离开: ID={client_id}, 剩余连接数: {len(self.connections)}")

    async def broadcast(self, event_type: str, data: Optional[Dict[str, Any]] = None, exclude_id: Optional[str] = None):
        """
        核心广播逻辑：
        :param exclude_id: 如果指定，将不会向该 ID 的客户端发送消息（防止回环）
        """
        # 构建消息包，包含发送者信息
        payload = {
            "type": event_type, 
            "data": data or {},
            "sender_id": exclude_id, # 让接收端也能知道是谁发的
            "timestamp": time.time()
        }
        message = json.dumps(payload, ensure_ascii=False)
        
        targets = []
        with self._lock:
            targets = list(self.connections.keys())

        if not targets:
            return

        disconnected = []
        for connection in targets:
            # 广播阶段需再次检查 cid 过滤
            with self._lock:
                cid = self.connections.get(connection)
                if not cid or (exclude_id and cid == exclude_id):
                    continue

            try:
                await connection.send_text(message)
            except Exception:
                disconnected.append(connection)
        
        # 清理失效连接
        for conn in disconnected:
            self.disconnect(conn)

    def broadcast_sync(self, event_type: str, data: Optional[Dict[str, Any]] = None, exclude_id: Optional[str] = None):
        """同步接口兼容：优先使用主循环，不产生多余线程/循环"""
        if self._loop and self._loop.is_running():
            # 线程安全地调度广播任务到主线程 EventLoop
            asyncio.run_coroutine_threadsafe(
                self.broadcast(event_type, data, exclude_id), 
                self._loop
            )
        else:
            # 兜底 logic: 如果还没 connect 过就没 loop，或者 loop 停了
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    asyncio.ensure_future(self.broadcast(event_type, data, exclude_id))
                else:
                    loop.run_until_complete(self.broadcast(event_type, data, exclude_id))
            except RuntimeError:
                pass # 忽略无循环状态下的广播

    async def broadcast_to_client(self, client_id: str, event_type: str, data: Optional[Dict[str, Any]] = None):
        """定向广播：仅发送给特定 client_id 的客户端"""
        payload = {
            "type": event_type, 
            "data": data or {},
            "timestamp": time.time()
        }
        from .utils.json_encoder import BioJsonEncoder
        message = json.dumps(payload, ensure_ascii=False, cls=BioJsonEncoder)
        
        targets = []
        with self._lock:
            for conn, cid in self.connections.items():
                if cid == client_id:
                    targets.append(conn)

        for connection in targets:
            try:
                await connection.send_text(message)
            except Exception:
                self.disconnect(connection)

    def broadcast_to_client_sync(self, client_id: str, event_type: str, data: Optional[Dict[str, Any]] = None):
        """定向广播的同步包装"""
        if self._loop and self._loop.is_running():
            asyncio.run_coroutine_threadsafe(
                self.broadcast_to_client(client_id, event_type, data), 
                self._loop
            )

# 导出单例
broadcaster = EventBroadcaster()
