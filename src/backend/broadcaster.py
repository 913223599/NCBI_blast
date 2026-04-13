import asyncio
import json
import logging
import threading
from typing import List, Dict, Any, Optional
from fastapi import WebSocket, WebSocketDisconnect

logger = logging.getLogger("broadcaster")

class EventBroadcaster:
    """
    统一广播模块 - 负责管理所有端（Electron/Web）的实时状态同步
    
    职责：
    1. 管理 WebSocket 活动连接池。
    2. 提供异步与同步环境兼容的广播接口。
    3. 屏蔽底层通信细节，实现业务逻辑与消息分发的解耦。
    """

    def __init__(self):
        self.active_connections: List[WebSocket] = []
        self._lock = threading.Lock()

    async def connect(self, websocket: WebSocket):
        """处理新连接进入"""
        await websocket.accept()
        with self._lock:
            # 检查是否已存在相同连接,防止重复添加
            if websocket not in self.active_connections:
                self.active_connections.append(websocket)
                logger.info(f"WebSocket 客户端已接入。当前总连接数: {len(self.active_connections)}")
            else:
                logger.warning("检测到重复的 WebSocket 连接,已忽略")

    def disconnect(self, websocket: WebSocket):
        """处理连接断开"""
        with self._lock:
            if websocket in self.active_connections:
                self.active_connections.remove(websocket)
        logger.info(f"WebSocket 客户端已离开。剩余连接数: {len(self.active_connections)}")

    async def broadcast(self, event_type: str, data: Optional[Dict[str, Any]] = None):
        """
        核心异步广播接口
        :param event_type: 事件类型标识 (如 'data_updated', 'task_progress')
        :param data: 消息负载
        """
        message = json.dumps({
            "type": event_type, 
            "data": data or {},
            "timestamp": asyncio.get_event_loop().time()
        }, ensure_ascii=False)
        
        disconnected = []
        # 创建副本进行遍历，避免锁竞争时间过长
        with self._lock:
            targets = list(self.active_connections)
        
        # 性能监控:记录广播目标数量
        if len(targets) > 5:
            logger.warning(f"⚠️ 广播目标过多: {len(targets)} 个连接,事件={event_type}")
            
        for connection in targets:
            try:
                await connection.send_text(message)
                logger.debug(f"已向客户端 {connection.client} 发送 {event_type} 事件")
            except Exception as e:
                logger.warning(f"向客户端发送消息失败: {e}")
                disconnected.append(connection)
        
        if targets:
            logger.info(f"广播完成: 事件={event_type}, 目标数={len(targets)}")
        
        # 清理失效连接
        for conn in disconnected:
            self.disconnect(conn)

    def broadcast_sync(self, event_type: str, data: Optional[Dict[str, Any]] = None):
        """
        同步兼容接口 - 允许在普通的 Python 函数/线程中触发广播
        会自动寻找或创建事件循环来处理异步发送任务。
        """
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # 如果当前线程已有运行中的循环，以此循环提交任务
                asyncio.ensure_future(self.broadcast(event_type, data))
            else:
                loop.run_until_complete(self.broadcast(event_type, data))
        except RuntimeError:
            # 针对没有事件循环的纯后台线程 (如 BLAST Worker)
            new_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(new_loop)
            new_loop.run_until_complete(self.broadcast(event_type, data))

# 导出单例，确保全项目使用同一个连接池
broadcaster = EventBroadcaster()
