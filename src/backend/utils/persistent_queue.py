import asyncio
import sqlite3
import json
import logging
import time
from typing import Dict, Any, Callable, Awaitable, List
from .assembly_db import assembly_db
from ..broadcaster import broadcaster

logger = logging.getLogger("Assembly.Queue")

class PersistentAssemblyQueue:
    """
    PersistentAssemblyQueue - 持久化串行任务队列
    -------------------------------------------
    1. 严格串行：同一时间只有一个 Worker (max_workers=1)
    2. 持久化：任务状态实时同步至 SQLite，支持崩溃重启后自愈
    3. 异步驱动：基于 asyncio.Queue 实现轻量级调度
    4. 可暂停/恢复：pause() / resume() 控制新任务派发
    """
    
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(PersistentAssemblyQueue, cls).__new__(cls)
            cls._instance._queue = None
            cls._instance._worker_task = None
            cls._instance._processor = None
            cls._instance._is_running = False
            cls._instance._queued_ids = set()
            cls._instance._paused = False
            cls._instance._resume_event = None  # 延迟初始化
            cls._instance._new_task_event = None
            cls._instance._current_task_id = None
        return cls._instance

    def _ensure_queue(self):
        if self._queue is None:
            self._queue = []
            self._new_task_event = asyncio.Event()
        if self._resume_event is None:
            self._resume_event = asyncio.Event()
            self._resume_event.set()  # 默认非暂停状态

    async def start_workers(self, processor_func: Callable[[Dict[str, Any]], Awaitable[None]]):
        """
        启动队列处理器 (启动自愈)
        :param processor_func: 实际执行流水线的函数
        """
        self._ensure_queue()
        self._processor = processor_func
        
        if self._is_running:
            return
            
        self._is_running = True
        logger.info("⚙️ 串行持久化队列引擎启动中...")
        
        # 安全重置：将所有处于 running 的任务标记为 aborted
        with sqlite3.connect(assembly_db.DB_PATH) as conn:
            conn.execute(
                "UPDATE assembly_tasks SET status = 'aborted', updated_at = ? WHERE status = 'running'",
                (time.time(),)
            )
            conn.commit()
        logger.info("✨ 任务队列已重置：之前的运行中任务已设为'已中止'，请在历史记录中恢复。")
        
        self._worker_task = asyncio.create_task(self._worker_loop())
        await self._broadcast_status()

    async def add_task(self, payload: Dict[str, Any]):
        """入队新任务"""
        self._ensure_queue()
        task_id = payload.get('task_id')
        if task_id in self._queued_ids:
            logger.info(f"⚠️ 任务 {task_id} 已经在队列中，忽略重复请求。")
            return
            
        self._queued_ids.add(task_id)
        self._queue.append(payload)
        self._new_task_event.set()
        logger.info(f"📥 任务已追加至队列: {task_id}")
        await self._broadcast_status()

    async def _worker_loop(self):
        """消费者循环 (并发数=1，支持暂停门控)"""
        while True:
            # 暂停门控：如果队列被暂停，等待 resume 信号
            await self._resume_event.wait()
            
            if not self._queue:
                self._new_task_event.clear()
                await self._new_task_event.wait()
                continue
                
            payload = self._queue.pop(0)
            task_id = payload.get('task_id')
            self._queued_ids.discard(task_id)
            self._current_task_id = task_id
            
            try:
                current_task = assembly_db.get_task(task_id)
                if not current_task or current_task.get('status') == 'aborted':
                    logger.info(f"⏭️ 任务 {task_id} 已取消或不存在，跳过。")
                    continue

                logger.info(f"🚀 [Queue] 正在派发任务: {task_id}")
                assembly_db.update_task_progress(task_id, "QUEUED", 0, "running")
                await self._broadcast_status()
                
                await self._processor(payload)
                
            except Exception as e:
                logger.error(f"❌ [Queue] 任务派发崩溃: {task_id}, 错误: {e}")
            finally:
                self._current_task_id = None
                logger.info(f"🏁 [Queue] 任务生命周期结束: {task_id}")
                await self._broadcast_status()

    def remove_task_from_queue(self, task_id: str) -> bool:
        """从等待队列中移除指定任务"""
        self._ensure_queue()
        initial_len = len(self._queue)
        self._queue = [p for p in self._queue if p.get('task_id') != task_id]
        if len(self._queue) < initial_len:
            self._queued_ids.discard(task_id)
            # 同步更新数据库状态为 aborted 以防前端闪烁
            assembly_db.update_task_progress(task_id, "ABORTED", 0, "aborted")
            asyncio.create_task(self._broadcast_status())
            return True
        return False

    def reorder_queue(self, task_ids: List[str]):
        """根据传入的 task_id 列表对等待队列进行重排"""
        self._ensure_queue()
        new_queue = []
        for tid in task_ids:
            for p in self._queue:
                if p.get('task_id') == tid:
                    new_queue.append(p)
                    break
        
        # 将传入列表中不存在的其他任务垫底
        existing_tids = {p.get('task_id') for p in new_queue}
        for p in self._queue:
            if p.get('task_id') not in existing_tids:
                new_queue.append(p)
                
        self._queue = new_queue
        asyncio.create_task(self._broadcast_status())

    # ─── 暂停/恢复控制 ────────────────────────────────────
    def pause(self):
        """暂停队列派发（当前运行中的任务不受影响）"""
        self._ensure_queue()
        if not self._paused:
            self._paused = True
            self._resume_event.clear()
            logger.info("⏸️ 队列已暂停，新任务将等待恢复后再派发。")

    def resume(self):
        """恢复队列派发"""
        self._ensure_queue()
        if self._paused:
            self._paused = False
            self._resume_event.set()
            logger.info("▶️ 队列已恢复，继续派发任务。")

    @property
    def is_paused(self) -> bool:
        return self._paused

    @property
    def current_task_id(self) -> str:
        return self._current_task_id

    # ─── 状态查询与广播 ────────────────────────────────────
    async def _broadcast_status(self):
        """同步并广播当前队列状态快照"""
        try:
            snapshot = await self.get_queue_status()
            await broadcaster.broadcast("assembly_queue_status", {
                "queue": snapshot,
                "paused": self._paused,
                "current_task_id": self._current_task_id
            })
        except Exception as e:
            logger.error(f"广播队列状态失败: {e}")

    async def get_queue_status(self) -> List[Dict[str, Any]]:
        """获取当前队列状态快照 (供 REST API 调用)"""
        try:
            tasks = assembly_db.get_incomplete_tasks()
            queue_snapshot = []
            for i, t in enumerate(tasks):
                queue_snapshot.append({
                    "id": t["id"],
                    "name": t["name"],
                    "status": t["status"],
                    "position": i + 1,
                    "tech": t.get("tech"),
                    "sample_type": t.get("sample_type")
                })
            return queue_snapshot
        except Exception as e:
            logger.error(f"获取队列状态失败: {e}")
            return []

    def get_queue_size(self) -> int:
        if not self._queue: return 0
        return len(self._queue)

# 全局单例
persistent_queue = PersistentAssemblyQueue()

