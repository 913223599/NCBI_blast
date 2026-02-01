import logging
import threading
import json
import sqlite3
import os
import queue
import time
from enum import Enum, auto
from datetime import datetime
from typing import Dict, List, Any, Optional
from pathlib import Path

from .engine import BlastEngine

logger = logging.getLogger(__name__)

class TaskStatus(str, Enum):
    """标准任务状态枚举"""
    PENDING = "pending"   # 等待中/排队中 (Scheduler)
    RUNNING = "running"   # 执行中
    PAUSED = "paused"     # 已暂停
    COMPLETED = "completed" # 完成
    FAILED = "failed"     # 失败/错误
    CANCELLED = "cancelled" # 已取消

class BlastStore:
    """Handles persistence of BLAST tasks using SQLite."""
    def __init__(self, db_path: str = "results/blast_meta.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS tasks (
                    task_id TEXT PRIMARY KEY,
                    params TEXT,
                    status TEXT,
                    progress INTEGER,
                    start_time TEXT,
                    end_time TEXT,
                    error TEXT
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS results (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT,
                    sequence_id TEXT,
                    data TEXT,
                    FOREIGN KEY(task_id) REFERENCES tasks(task_id)
                )
            """)

    def save_task(self, task: 'BlastTask'):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO tasks (task_id, params, status, progress, start_time, end_time, error)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                task.task_id, 
                json.dumps(task.params), 
                task.status.value if isinstance(task.status, TaskStatus) else task.status, 
                task.progress, 
                task.start_time.isoformat() if task.start_time else None,
                task.end_time.isoformat() if task.end_time else None,
                task.error
            ))

    def save_result(self, task_id: str, seq_id: str, data: Dict[str, Any]):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("INSERT INTO results (task_id, sequence_id, data) VALUES (?, ?, ?)",
                        (task_id, seq_id, json.dumps(data)))

    def load_all_tasks(self) -> List[Dict[str, Any]]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("SELECT * FROM tasks ORDER BY start_time DESC")
            return [dict(row) for row in cursor.fetchall()]

    def get_results(self, task_id: str) -> List[Dict[str, Any]]:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("SELECT data FROM results WHERE task_id = ?", (task_id,))
            return [json.loads(row[0]) for row in cursor.fetchall()]

    def clear_all(self):
        """Wipe all history data."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM results")
            conn.execute("DELETE FROM tasks")
            conn.commit()

    def delete_task(self, task_id: str):
        """Delete a specific task and its results."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM results WHERE task_id = ?", (task_id,))
            conn.execute("DELETE FROM tasks WHERE task_id = ?", (task_id,))
            conn.commit()


class BlastTask:
    """Represents a single BLAST analysis task in the system."""
    def __init__(self, task_id: str, params: Dict[str, Any], priority: int = 10):
        self.task_id = task_id
        self.params = params
        self.priority = priority # lower is higher priority
        self.status = TaskStatus.PENDING
        self.progress = 0
        self.results = []
        self.error = None
        self.start_time = datetime.now()
        self.end_time = None
        self.engine = None
        self.created_at = time.time() # For FIFO in same priority

    def transition_to(self, new_status: TaskStatus, error_msg: Optional[str] = None):
        """
        Executes a state transition with validation logic.
        """
        # 1. 终态检查
        if self.status in [TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED]:
             # 允许重试逻辑：如果当前是 Failed 但由于某种原因要重置为 Pending/Running (虽然这通常意味着新建任务)
             # 但一般情况下，终态不可变，除非是特定的 Force Reset
             logger.warning(f"Task {self.task_id} ignoring transition {self.status} -> {new_status} (Terminal State)")
             # 简单起见，目前不允许从终态跳出，防止逻辑混乱
             return

        # 2. 状态更新
        logger.info(f"Task {self.task_id} transition: {self.status.value} -> {new_status.value}")
        self.status = new_status
        
        # 3. 伴随动作
        if error_msg:
            self.error = error_msg
        
        if new_status in [TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED]:
            self.end_time = datetime.now()
            self.progress = 100 if new_status == TaskStatus.COMPLETED else self.progress

    def __lt__(self, other):
        # 优先级比较：小数值优先
        if self.priority != other.priority:
            return self.priority < other.priority
        # 同优先级：先创建的优先
        return self.created_at < other.created_at

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "status": self.status.value if isinstance(self.status, TaskStatus) else self.status,
            "progress": self.progress,
            "result_count": len(self.results),
            "error": self.error,
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "params": {k: v for k, v in self.params.items() if k != 'query'} # Hide large query data
        }

class TaskScheduler:
    """
    Priority-based Task Scheduler.
    Manages a pool of worker threads and executes tasks based on priority.
    """
    def __init__(self, executor_func, max_workers: int = 2):
        self.queue = queue.PriorityQueue()
        self.max_workers = max_workers
        self.executor_func = executor_func # Function to run the task (e.g., BlastManager._run_task)
        self.active_tasks: List[str] = []
        self._lock = threading.Lock()
        self._shutdown_event = threading.Event()
        self._workers = []

        self._start_workers()

    def _start_workers(self):
        for i in range(self.max_workers):
            t = threading.Thread(target=self._worker_loop, name=f"BlastWorker-{i}", daemon=True)
            self._workers.append(t)
            t.start()
    
    def submit(self, task: BlastTask):
        """Submit a task to the priority queue."""
        self.queue.put(task)
        logger.info(f"Task {task.task_id} submitted (Priority: {task.priority})")

    def _worker_loop(self):
        while not self._shutdown_event.is_set():
            try:
                # Get task with timeout to allow checking shutdown flag
                task = self.queue.get(timeout=1.0)
            except queue.Empty:
                continue

            try:
                # 只有 Pending 状态任务才执行 (防止已在队列中被取消)
                if task.status != TaskStatus.PENDING:
                    logger.info(f"Skipping task {task.task_id} with status {task.status}")
                    self.queue.task_done()
                    continue

                with self._lock:
                    self.active_tasks.append(task.task_id)
                
                logger.info(f"Worker started processing task: {task.task_id}")
                self.executor_func(task)
                
            except Exception as e:
                logger.error(f"Worker failed on task {task.task_id}: {e}", exc_info=True)
            finally:
                with self._lock:
                    if task.task_id in self.active_tasks:
                        self.active_tasks.remove(task.task_id)
                self.queue.task_done()

    def shutdown(self):
        self._shutdown_event.set()
        for t in self._workers:
            t.join(timeout=1.0)


class BlastManager:
    """
    Singleton Service to manage BLAST analysis tasks.
    Decouples execution from the PyQt UI widgets.
    """
    _instance = None
    _lock = threading.RLock() # Use RLock for re-entrant safety

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(BlastManager, cls).__new__(cls)
                cls._instance._init_manager()
            return cls._instance

    def _init_manager(self):
        self.tasks: Dict[str, BlastTask] = {}
        self.store = BlastStore()
        self.logger = logging.getLogger("BlastManager")
        
        # Initialize Scheduler (default 2 concurrent tasks)
        # Pass self._run_task as the execution logic
        self.scheduler = TaskScheduler(executor_func=self._run_task, max_workers=2)

        # Load previous tasks into memory state (simplified)
        for t_data in self.store.load_all_tasks():
            t = BlastTask(t_data['task_id'], json.loads(t_data['params']))
            # 尝试将字符串状态转换为枚举
            try:
                t.status = TaskStatus(t_data['status'])
            except ValueError:
                t.status = t_data['status'] # Fallback for unknown or legacy states
                
            t.progress = t_data['progress']
            t.error = t_data['error']
            if t_data['start_time']: t.start_time = datetime.fromisoformat(t_data['start_time'])
            if t_data['end_time']: t.end_time = datetime.fromisoformat(t_data['end_time'])
            
            self.tasks[t.task_id] = t

            # -------------------------------------------------------------
            # 持久化恢复逻辑 (Persistence Recovery Logic)
            # -------------------------------------------------------------
            
            # 1. 恢复排队 (Resume Pending)
            if t.status == TaskStatus.PENDING:
                self.logger.info(f"Resuming pending task on startup: {t.task_id}")
                self.scheduler.submit(t)

            # 2. 处理异常中断 (Handle Interrupted)
            elif t.status == TaskStatus.RUNNING:
                self.logger.warning(f"Found interrupted task: {t.task_id}. Marking as FAILED.")
                # 直接修改状态，不使用 transition_to (避免触发额外逻辑)，并保存到DB
                t.status = TaskStatus.FAILED
                t.error = "任务异常中断 (应用重启)"
                t.end_time = datetime.now()
                self.store.save_task(t)


    def create_task(self, params: Dict[str, Any], priority: int = 10) -> str:
        """Create and start a new BLAST task."""
        task_id = params.get("task_name") or f"blast_{datetime.now().strftime('%m%d_%H%M%S')}"
        
        # Ensure unique task ID (Check Enum status)
        if task_id in self.tasks and self.tasks[task_id].status == TaskStatus.RUNNING:
            task_id = f"{task_id}_{int(datetime.now().timestamp())}"

        # Initialize Task with Priority
        task = BlastTask(task_id, params, priority)
        # 默认是 PENDING
        self.tasks[task_id] = task
        self.store.save_task(task) # 立即保存 PENDING 状态
        
        # Submit to Scheduler instead of raw Thread
        self.scheduler.submit(task)
        
        return task_id

    def _run_task(self, task: BlastTask):
        """Internal execution loop using the new Pipe Engine."""
        try:
            task.transition_to(TaskStatus.RUNNING)
            self.store.save_task(task)

            # Setup Sequences
            from src.utils.file_handler import FileHandler
            fh = FileHandler()
            sequences = []
            
            # Extract from files
            for f_path in task.params.get("files", []):
                for seq in fh.read_fasta_file_iter(f_path):
                    sequences.append(seq)
            
            # Extract from query text
            query_text = task.params.get("query", "").strip()
            if query_text:
                sequences.append({"id": "Manual_Input", "sequence": query_text})

            if not sequences:
                raise ValueError("没有检测到有效序列")

            # Initialize Engine
            engine = BlastEngine(task.task_id, task.params)
            task.engine = engine # Track for cancellation

            def on_progress(comp, total, info):
                task.progress = int(comp/total * 100)
                self.store.save_task(task)

            def on_result(data):
                # Ensure data is JSON serializable
                task.results.append(data)
                self.store.save_result(task.task_id, data.get('sequence_id','?'), data)

            engine.progress_callback = on_progress
            engine.result_callback = on_result
            
            # Run
            engine.run(sequences)

            # Cleanup
            task.transition_to(TaskStatus.COMPLETED)
            self.store.save_task(task)

        except Exception as e:
            self.logger.error(f"Task {task.task_id} failed: {e}", exc_info=True)
            # 只有非 Cancelled 的才置为 Failed
            if task.status != TaskStatus.CANCELLED:
                 task.transition_to(TaskStatus.FAILED, error_msg=str(e))
            self.store.save_task(task)

    def stop_task(self, task_id: str):
        """Request cancellation of a running task."""
        with self._lock:
            if task_id in self.tasks:
                task = self.tasks[task_id]
                if task.engine:
                    task.engine.cancel()
                
                # 使用 transition
                task.transition_to(TaskStatus.CANCELLED)
                self.store.save_task(task)

    def pause_task(self, task_id: str):
        """Request pause of a running task."""
        with self._lock:
            if task_id in self.tasks:
                task = self.tasks[task_id]
                if task.status == TaskStatus.RUNNING and task.engine:
                    task.engine.pause()
                    task.transition_to(TaskStatus.PAUSED)
                    self.store.save_task(task)

    def resume_task(self, task_id: str):
        """Request resume of a paused task."""
        with self._lock:
            if task_id in self.tasks:
                task = self.tasks[task_id]
                if task.status == TaskStatus.PAUSED and task.engine:
                    task.engine.resume()
                    task.transition_to(TaskStatus.RUNNING)
                    self.store.save_task(task)

    def get_task_status(self, task_id: str) -> Optional[Dict[str, Any]]:
        """Query status of a specific task."""
        with self._lock:
            task = self.tasks.get(task_id)
            return task.to_dict() if task else None

    def list_tasks(self) -> List[Dict[str, Any]]:
        """List all managed tasks from store + current state."""
        with self._lock:
            # Refresh from store to get historical ones
            stored_tasks = self.store.load_all_tasks()
            # Merge with in-memory status (for 'running' ones & 'queued' ones)
            for t in stored_tasks:
                tid = t['task_id']
                if tid in self.tasks:
                    mem_t = self.tasks[tid]
                    t['status'] = mem_t.status
                    t['progress'] = mem_t.progress
            return stored_tasks

    def get_task_results(self, task_id: str) -> List[Dict[str, Any]]:
        """Retrieve results for a task from store."""
        with self._lock:
            return self.store.get_results(task_id)

    def clear_history(self):
        """Clear all tasks from memory and storage."""
        with self._lock:
            # Cancel all running tasks if any
            for task in self.tasks.values():
                if task.status == "running" and task.engine:
                    task.engine.cancel()
            
            self.tasks.clear()
            self.store.clear_all()
            self.logger.info("All history cleared successfully.")

    def delete_task(self, task_id: str):
        """Delete a specific task."""
        with self._lock:
            if task_id in self.tasks:
                task = self.tasks[task_id]
                if task.status == "running" and task.engine:
                    task.engine.cancel()
                del self.tasks[task_id]
            
            self.store.delete_task(task_id)
            self.logger.info(f"Task {task_id} deleted successfully.")


# Global Accessor
_manager = None
def get_blast_manager():
    global _manager
    if _manager is None:
        _manager = BlastManager()
    return _manager
