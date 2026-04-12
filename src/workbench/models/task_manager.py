"""
TaskManager - 进化树构建任务的线程安全管理器

职责：
- 管理后台分析任务的生命周期（提交、追踪、取消）
- 通过互斥锁防止并发冲突
- 提供任务状态查询接口
"""
import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger(__name__)


class TaskStatus(Enum):
    """任务状态枚举"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class TaskRecord:
    """任务记录数据结构"""
    task_id: str
    task_type: str
    status: TaskStatus = TaskStatus.PENDING
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    error_message: Optional[str] = None
    result: Optional[Dict[str, Any]] = None
    thread: Optional[threading.Thread] = None


# 并发控制：最大同时运行的分析任务数
MAX_CONCURRENT_TASKS = 1


class TaskManager:
    """
    线程安全的任务管理器（单例模式）

    功能：
    - 防止多次点击启动重复任务
    - 支持任务状态查询
    - 支持取消正在运行的任务
    - 记录历史任务日志用于故障排查
    """

    _instance: Optional["TaskManager"] = None
    _lock = threading.Lock()

    def __new__(cls) -> "TaskManager":
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        self._initialized = True
        self._tasks: Dict[str, TaskRecord] = {}
        self._task_lock = threading.Lock()
        self._cancel_events: Dict[str, threading.Event] = {}
        logger.info("TaskManager initialized (singleton)")

    def submit_task(
        self,
        task_type: str,
        worker_fn: Callable[..., None],
        *args: Any,
        **kwargs: Any
    ) -> Optional[str]:
        """
        提交一个后台任务

        Args:
            task_type: 任务类型标识（如 'tree_analysis'）
            worker_fn: 工作函数
            *args, **kwargs: 传递给工作函数的参数

        Returns:
            任务ID（成功提交时），None（任务被拒绝时）
        """
        with self._task_lock:
            # 防护：检查是否已有同类型任务正在运行
            running_count = sum(
                1 for record in self._tasks.values()
                if record.task_type == task_type
                and record.status == TaskStatus.RUNNING
            )
            if running_count >= MAX_CONCURRENT_TASKS:
                logger.warning(
                    f"Task submission rejected: {running_count} {task_type} "
                    f"tasks already running (limit: {MAX_CONCURRENT_TASKS})"
                )
                return None

            task_id = uuid.uuid4().hex[:12]
            cancel_event = threading.Event()
            self._cancel_events[task_id] = cancel_event

            record = TaskRecord(
                task_id=task_id,
                task_type=task_type,
            )
            self._tasks[task_id] = record

        def _wrapped_worker() -> None:
            with self._task_lock:
                record.status = TaskStatus.RUNNING
                record.started_at = time.time()

            try:
                worker_fn(*args, cancel_event=cancel_event, **kwargs)
                with self._task_lock:
                    if record.status == TaskStatus.RUNNING:
                        record.status = TaskStatus.COMPLETED
            except Exception as exc:
                logger.error(f"Task {task_id} failed: {exc}")
                with self._task_lock:
                    record.status = TaskStatus.FAILED
                    record.error_message = str(exc)
            finally:
                with self._task_lock:
                    record.finished_at = time.time()
                    elapsed = record.finished_at - (record.started_at or record.created_at)
                    logger.info(
                        f"Task {task_id} ({task_type}) finished: "
                        f"status={record.status.value}, elapsed={elapsed:.2f}s"
                    )

        thread = threading.Thread(
            target=_wrapped_worker,
            name=f"task-{task_type}-{task_id}",
            daemon=True,
        )
        with self._task_lock:
            record.thread = thread
        thread.start()

        logger.info(f"Task submitted: id={task_id}, type={task_type}")
        return task_id

    def cancel_task(self, task_id: str) -> bool:
        """
        请求取消一个任务

        Args:
            task_id: 要取消的任务ID

        Returns:
            True 如果取消信号已发送
        """
        cancel_event = self._cancel_events.get(task_id)
        if cancel_event is None:
            return False

        cancel_event.set()
        with self._task_lock:
            record = self._tasks.get(task_id)
            if record and record.status == TaskStatus.RUNNING:
                record.status = TaskStatus.CANCELLED
                logger.info(f"Task {task_id} cancellation requested")
                return True
        return False

    def get_task_status(self, task_id: str) -> Optional[Dict[str, Any]]:
        """
        查询任务状态

        Args:
            task_id: 任务ID

        Returns:
            任务状态字典，或 None
        """
        with self._task_lock:
            record = self._tasks.get(task_id)
            if record is None:
                return None
            return {
                "task_id": record.task_id,
                "task_type": record.task_type,
                "status": record.status.value,
                "created_at": record.created_at,
                "started_at": record.started_at,
                "finished_at": record.finished_at,
                "error": record.error_message,
                "elapsed": (
                    (record.finished_at or time.time())
                    - (record.started_at or record.created_at)
                ),
            }

    def get_active_tasks(self, task_type: Optional[str] = None) -> list[Dict[str, Any]]:
        """
        获取活跃任务列表

        Args:
            task_type: 可选过滤器

        Returns:
            活跃任务信息列表
        """
        results = []
        with self._task_lock:
            for record in self._tasks.values():
                if record.status in (TaskStatus.PENDING, TaskStatus.RUNNING):
                    if task_type is None or record.task_type == task_type:
                        results.append({
                            "task_id": record.task_id,
                            "task_type": record.task_type,
                            "status": record.status.value,
                            "elapsed": time.time() - (record.started_at or record.created_at),
                        })
        return results

    def cleanup_old_tasks(self, max_age_seconds: float = 3600) -> int:
        """
        清理过期的已完成任务记录

        Args:
            max_age_seconds: 最大保留时间（秒）

        Returns:
            清理的任务数
        """
        now = time.time()
        to_remove = []
        with self._task_lock:
            for task_id, record in self._tasks.items():
                if (
                    record.status
                    in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED)
                    and record.finished_at
                    and now - record.finished_at > max_age_seconds
                ):
                    to_remove.append(task_id)

            for task_id in to_remove:
                del self._tasks[task_id]
                self._cancel_events.pop(task_id, None)

        return len(to_remove)


def get_task_manager() -> TaskManager:
    """获取全局唯一的 TaskManager 实例"""
    return TaskManager()
