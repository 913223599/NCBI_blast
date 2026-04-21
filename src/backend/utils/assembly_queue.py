import asyncio
import logging
from typing import Dict, Any, Callable, Awaitable

logger = logging.getLogger("api_server")

class AssemblyTaskQueue:
    """
    AssemblyTaskQueue - 生产者消费者模型
    用于限制高负载任务（如基因组组装）的并发数量，保护服务器资源。
    """
    
    _instance = None
    _max_workers = 2  # 限制同时运行的组装任务数量 (可配置)

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(AssemblyTaskQueue, cls).__new__(cls)
            cls._instance.workers = []
            # 延迟初始化 Queue，避免在模块导入时绑定到不存在的事件循环
            cls._instance._queue = None
        return cls._instance

    def _ensure_queue(self):
        """确保 Queue 在事件循环内被正确初始化"""
        if self._queue is None:
            self._queue = asyncio.Queue()

    async def start_workers(self, processor_func: Callable[[Dict[str, Any]], Awaitable[None]]):
        """启动后台工作线程"""
        self._ensure_queue()
        if self.workers:
            return
            
        logger.info(f"[Queue] 启动 {self._max_workers} 个组装任务工作流")
        for i in range(self._max_workers):
            worker = asyncio.create_task(self._worker_loop(i, processor_func))
            self.workers.append(worker)

    async def _worker_loop(self, worker_id: int, processor_func: Callable[[Dict[str, Any]], Awaitable[None]]):
        """消费者循环"""
        while True:
            # 等待新任务
            payload = await self._queue.get()
            task_id = payload.get('task_id')
            
            logger.info(f"[Worker-{worker_id}] 开始处理任务: {task_id}")
            try:
                await processor_func(payload)
            except Exception as e:
                logger.error(f"[Worker-{worker_id}] 任务执行崩溃: {task_id}, 错误: {e}")
            finally:
                self._queue.task_done()
                logger.info(f"[Worker-{worker_id}] 任务处理结束: {task_id}")

    async def add_task(self, payload: Dict[str, Any]):
        """生产者：添加任务到队列"""
        self._ensure_queue()
        await self._queue.put(payload)
        logger.info(f"[Queue] 任务已入队: {payload.get('task_id')}")

    def get_queue_size(self) -> int:
        return self._queue.qsize()

# 全局单例
assembly_queue = AssemblyTaskQueue()
