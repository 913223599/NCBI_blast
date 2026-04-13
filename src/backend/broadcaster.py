import asyncio
import json
import logging
import threading
from typing import List, Dict, Any, Optional
from fastapi import WebSocket, WebSocketDisconnect

logger = logging.getLogger("broadcaster")

class EventBroadcaster:
    """
    升级版广播模块 - 具备发送者识别与排除能力，防止同步死循环。
    """

    def __init__(self):
        # 记录 WebSocket -> client_id 的映射
        self.connections: Dict[WebSocket, str] = {}
        self._lock = threading.Lock()

    async def connect(self, websocket: WebSocket, client_id: str = "unknown"):
        """处理新连接进入，记录其唯一的 client_id"""
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
            "timestamp": asyncio.get_event_loop().time()
        }
        message = json.dumps(payload, ensure_ascii=False)
        
        targets = []
        with self._lock:
            for ws, cid in self.connections.items():
                if exclude_id and cid == exclude_id:
                    continue
                targets.append(ws)

        disconnected = []
        for connection in targets:
            try:
                await connection.send_text(message)
            except Exception:
                disconnected.append(connection)
        
        # 清理失效连接
        for conn in disconnected:
            self.disconnect(conn)

    def broadcast_sync(self, event_type: str, data: Optional[Dict[str, Any]] = None, exclude_id: Optional[str] = None):
        """同步接口兼容"""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.ensure_future(self.broadcast(event_type, data, exclude_id))
            else:
                loop.run_until_complete(self.broadcast(event_type, data, exclude_id))
        except RuntimeError:
            new_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(new_loop)
            new_loop.run_until_complete(self.broadcast(event_type, data, exclude_id))

# 导出单例
broadcaster = EventBroadcaster()
