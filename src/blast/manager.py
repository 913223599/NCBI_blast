import json
from enum import Enum
import logging
import os
import queue
import re
import shutil
import sqlite3
import threading
import time
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional

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

    def _connect(self):
        return closing(sqlite3.connect(self.db_path))

    def _init_db(self):
        with self._connect() as conn, conn:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA synchronous=NORMAL;")
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
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_results_task_seq
                ON results(task_id, sequence_id)
            """)

    def save_task(self, task: 'BlastTask'):
        with self._connect() as conn, conn:
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
        with self._connect() as conn, conn:
            # Use REPLACE logic to avoid duplicates during Resumption
            conn.execute("DELETE FROM results WHERE task_id = ? AND sequence_id = ?", (task_id, seq_id))
            conn.execute("INSERT INTO results (task_id, sequence_id, data) VALUES (?, ?, ?)",
                        (task_id, seq_id, json.dumps(data, ensure_ascii=False)))

    def save_results_batch(self, task_id: str, items: List[Any]):
        """单事务批量落盘序列结果占位符或分片结果，避免逐条 fsync 阻塞"""
        if not items:
            return
        normalized = []
        for item in items:
            if isinstance(item, dict):
                normalized.append((str(item.get("sequence_id", "")), item))
            else:
                seq_id, payload = item
                normalized.append((str(seq_id), payload))
        with self._connect() as conn, conn:
            conn.executemany(
                "DELETE FROM results WHERE task_id = ? AND sequence_id = ?",
                [(task_id, seq_id) for seq_id, _ in normalized]
            )
            conn.executemany(
                "INSERT INTO results (task_id, sequence_id, data) VALUES (?, ?, ?)",
                [(task_id, seq_id, json.dumps(payload, ensure_ascii=False)) for seq_id, payload in normalized]
            )

    def load_all_tasks(self) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("SELECT * FROM tasks ORDER BY start_time DESC")
            return [dict(row) for row in cursor.fetchall()]

    def get_results(self, task_id: str) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            cursor = conn.execute("SELECT data FROM results WHERE task_id = ? ORDER BY id ASC", (task_id,))
            return [json.loads(row[0]) for row in cursor.fetchall()]

    def clear_all(self):
        """Wipe all history data."""
        with self._connect() as conn, conn:
            conn.execute("DELETE FROM results")
            conn.execute("DELETE FROM tasks")

    def delete_task(self, task_id: str):
        """Delete a specific task and its results."""
        with self._connect() as conn, conn:
            conn.execute("DELETE FROM results WHERE task_id = ?", (task_id,))
            conn.execute("DELETE FROM tasks WHERE task_id = ?", (task_id,))


class BlastTask:
    """Represents a single BLAST analysis task in the system."""
    def __init__(self, task_id: str, params: Dict[str, Any], priority: int = 10):
        self.task_id = task_id
        self.params = params
        self.priority = priority # lower is higher priority
        self.status = TaskStatus.PENDING
        self.progress = 0
        self.results = []
        self.result_count = 0
        self.error = None
        self.start_time: Optional[datetime] = datetime.now()
        self.end_time: Optional[datetime] = None
        self.engine = None
        self.created_at = time.time() # For FIFO in same priority

    def transition_to(self, new_status: TaskStatus, error_msg: Optional[str] = None):
        """
        Executes a state transition with validation logic.
        """
        # 1. 终态检查
        if self.status in [TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED]:
             # [FIX] 允许从 FAILED 或 CANCELLED 重置为 PENDING (为了断点续传/重试)
             if new_status != TaskStatus.PENDING:
                 logger.warning(f"Task {self.task_id} ignoring transition {self.status} -> {new_status} (Terminal State)")
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
            "result_count": max(self.result_count, len(self.results)),
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
        self._ensure_workers_alive()
        self.queue.put(task)
        logger.info(f"Task {task.task_id} submitted (Priority: {task.priority})")

    def _ensure_workers_alive(self):
        """Self-healing: 确保工人线程始终在线"""
        with self._lock:
            # 清理已经死掉的线程引用
            self._workers = [t for t in self._workers if t.is_alive()]
            
            # 补齐空位
            missing = self.max_workers - len(self._workers)
            if missing > 0:
                logger.warning(f"Detected {missing} missing/dead BLAST workers. Reviving...")
                for _ in range(missing):
                    t = threading.Thread(target=self._worker_loop, name=f"BlastWorker-Revived-{time.time()}", daemon=True)
                    self._workers.append(t)
                    t.start()

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
                    # [FIX] Removed redundant task_done() here
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
                # [FIX] task_done must be called EXACTLY once per get()
                # Previous code called it both in main try and in 'if task.status != PENDING'
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
        # Absolute project root detection
        self.root_dir = Path(__file__).resolve().parent.parent.parent
        self.results_dir = self.root_dir / "results" / "blast"
        self.results_dir.mkdir(parents=True, exist_ok=True)
        
        # 结果数据库也直接放入 blast 子目录，实现模块化存储
        self.store = BlastStore(db_path=str(self.results_dir / "blast_meta.db"))
        self.logger = logging.getLogger("BlastManager")
        self.result_listeners = [] # [callback(task_id, result_data)]
        
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
            if t_data['start_time']:
                t.start_time = datetime.fromisoformat(t_data['start_time'])
            if t_data['end_time']:
                t.end_time = datetime.fromisoformat(t_data['end_time'])
            
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
                self.logger.warning(f"Found interrupted task: {t.task_id}. Marking as CANCELLED for resumption.")
                # 将中断任务标记为 CANCELLED，以便用户通过“继续分析”恢复
                t.status = TaskStatus.CANCELLED
                t.error = "任务异常中断 (应用重启)"
                t.end_time = datetime.now()
                self.store.save_task(t)


    def create_task(self, params: Dict[str, Any], priority: int = 10) -> str:
        """Create and start a new BLAST task."""
        raw_name = params.get("task_name") or f"blast_{datetime.now().strftime('%m%d_%H%M%S')}"
        
        # [FIX] Sanitize task_id to remove illegal filesystem characters (especially ':' on Windows)
        # These appear when using timestamps as titles
        task_id = re.sub(r'[\\/:*?"<>|]', '_', raw_name)
        
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

    def _migrate_extracted_files(self, files: List[str], seq_storage: Path) -> List[str]:
        """将分拣暂存区文件归位至当前任务的专属存储目录。"""
        final_file_paths: List[str] = []
        for f_path in files:
            p = Path(f_path)
            if "extracted" not in p.parts:
                final_file_paths.append(f_path)
                continue
            dest_path = seq_storage / p.name
            try:
                if dest_path.exists():
                    dest_path = seq_storage / f"{p.stem}_{int(time.time())}{p.suffix}"
                shutil.move(str(p), str(dest_path))
                final_file_paths.append(str(dest_path))
            except Exception as e:
                self.logger.warning(f"Failed to migrate extracted file {p.name}: {e}. Using original path.")
                final_file_paths.append(f_path)
        return final_file_paths

    def _collect_sequences_from_paths(self, fh: Any, path_list: List[str]) -> List[Dict[str, Any]]:
        """从文件或目录列表提取并按优先级去重序列。"""
        all_extracted_files: List[str] = []
        for p_str in path_list:
            p = Path(p_str).resolve()
            if p.is_dir():
                all_extracted_files.extend([str(sf) for sf in p.rglob('*') if sf.is_file()])
            elif p.is_file():
                all_extracted_files.append(str(p))

        priority_map = {
            '.fasta': 10, '.fas': 10, '.fa': 10, '.fna': 10,
            '.seq': 8,
            '.txt': 5,
            '.ab1': 3, '.abi': 3,
            '.nwk': 1, '.newick': 1
        }
        dir_groups: Dict[str, Dict[str, List[str]]] = {}
        for f_path in all_extracted_files:
            p = Path(f_path)
            parent = str(p.parent)
            stem = p.stem.lower()
            dir_groups.setdefault(parent, {}).setdefault(stem, []).append(f_path)

        target_files: List[str] = []
        for stems in dir_groups.values():
            for paths in stems.values():
                if len(paths) > 1:
                    paths.sort(key=lambda x: priority_map.get(Path(x).suffix.lower(), 0), reverse=True)
                target_files.append(paths[0])

        sequences: List[Dict[str, Any]] = []
        processed_paths = set()
        for f_path in target_files:
            if f_path in processed_paths:
                continue
            try:
                count_in_file = 0
                for seq in fh.read_fasta_file_iter(f_path):
                    sequences.append(seq)
                    count_in_file += 1
                processed_paths.add(f_path)
                self.logger.debug(f"从 {f_path} 提取了 {count_in_file} 条序列")
            except Exception as e:
                self.logger.warning(f"无法从文件 {f_path} 提取序列: {e}")
        return sequences

    def _parse_manual_query_sequences(self, query_text: str) -> List[Dict[str, Any]]:
        """解析手动输入的 FASTA 或裸序列。"""
        text = query_text.strip()
        if not text:
            return []
        if not text.startswith(">"):
            return [{"id": "Manual_Input", "sequence": text}]
        import io
        from Bio import SeqIO
        try:
            return [{"id": rec.id, "sequence": str(rec.seq)} for rec in SeqIO.parse(io.StringIO(text), "fasta")]
        except Exception as e:
            self.logger.warning(f"Failed to parse query_text as Multi-FASTA: {e}")
            return [{"id": "Manual_Input", "sequence": text}]

    def _populate_pending_placeholders(self, task: BlastTask, sequences: List[Dict[str, Any]]) -> None:
        """单事务批量落盘占位结果并通知监听者，使 UI 秒级展示序列列表。"""
        existing_results = {r.get('sequence_id') for r in self.store.get_results(task.task_id)}
        pending_batch = []
        for seq in sequences:
            seq_id = seq.get('id', 'unknown')
            if seq_id not in existing_results:
                pending_batch.append((seq_id, {"sequence_id": seq_id, "status": "pending"}))
        if not pending_batch:
            return
        self.store.save_results_batch(task.task_id, pending_batch)
        if not self.result_listeners:
            return
        for _, pending_data in pending_batch:
            for cb in self.result_listeners:
                try:
                    cb(task.task_id, pending_data)
                except Exception as exc:
                    self.logger.warning("Pending 占位回调执行失败 (task=%s): %s", task.task_id, exc)

    def _run_auto_backfill(self, task: BlastTask, auto_task_id: str) -> None:
        """任务完成后尝试将最佳命中自动回填到关联的 GBK 注释文件。"""
        try:
            self.logger.info(f"[AutoBackfill] 触发自动回填任务: {auto_task_id}")
            from src.core.assembly_gbk_fixer import GBKAnnotationBackfiller
            from src.core.assembly_storage import AssemblyStorage
            from src.core.blast_utils import parse_blast_csv

            hits_to_backfill = {}
            for res in self.get_task_results(task.task_id):
                csv_file = res.get('csv_file')
                if csv_file and os.path.exists(csv_file):
                    top_hits = parse_blast_csv(csv_file, limit=1)
                    if top_hits:
                        best = top_hits[0]
                        hits_to_backfill[res['sequence_id']] = {
                            "product": best.get('stitle', 'hypothetical protein'),
                            "evalue": best.get('evalue', 'N/A'),
                            "accession": best.get('saccession', 'N/A')
                        }
            if not hits_to_backfill:
                return

            task_dir = AssemblyStorage.get_task_dir(auto_task_id)
            anno_dir = task_dir / "phageannotationstep"
            phold_gbk = anno_dir / "phold_res" / "phold.gbk"
            pharokka_gbk = anno_dir / "pharokka_res" / "PHAGE.gbk"
            base_gbk = phold_gbk if phold_gbk.exists() else pharokka_gbk
            if base_gbk and base_gbk.exists():
                GBKAnnotationBackfiller(base_gbk).apply_blast_hits(hits_to_backfill)
                self.logger.info(f"[AutoBackfill] 自动回填完成，更新了 {len(hits_to_backfill)} 个蛋白注释。")
            else:
                self.logger.warning(f"[AutoBackfill] 跳过自动回填: 未找到基础 GBK 文件: {anno_dir}")
        except Exception as eb:
            self.logger.error(f"[AutoBackfill] 自动回填异常: {eb}", exc_info=True)

    def _run_task(self, task: BlastTask):
        """Internal execution loop using the new Pipe Engine."""
        try:
            task.transition_to(TaskStatus.RUNNING)
            self.store.save_task(task)

            task_dir = self.results_dir / task.task_id
            seq_storage = task_dir / "sequences"
            seq_storage.mkdir(parents=True, exist_ok=True)

            from src.utils.file_handler import FileHandler
            fh = FileHandler()
            final_file_paths = self._migrate_extracted_files(task.params.get("files", []), seq_storage)
            task.params["files"] = final_file_paths

            sequences = self._collect_sequences_from_paths(fh, final_file_paths)
            sequences.extend(self._parse_manual_query_sequences(task.params.get("query", "")))
            if not sequences:
                raise ValueError("没有检测到有效序列")

            engine = BlastEngine(task.task_id, task.params)
            task.engine = engine

            self._populate_pending_placeholders(task, sequences)

            seq_lookup: Dict[str, str] = {}
            for s in sequences:
                sid = s.get('id')
                seq_val = s.get('sequence')
                if sid and isinstance(seq_val, str) and sid not in seq_lookup:
                    seq_lookup[sid] = seq_val
            max_in_memory_results = 500

            def on_progress(comp, total, info):
                new_prog = int(comp / total * 100)
                if new_prog >= getattr(task, 'progress', 0) or comp == total:
                    task.progress = new_prog
                    self.store.save_task(task)

            def on_result(data):
                seq_id = data.get('sequence_id')
                if seq_id and seq_id in seq_lookup:
                    original_seq = seq_lookup[seq_id]
                    if original_seq:
                        data['raw_sequence'] = original_seq

                self.store.save_result(task.task_id, data.get('sequence_id', '?'), data)
                task.result_count += 1
                if len(task.results) < max_in_memory_results:
                    task.results.append(data)

                for callback in self.result_listeners:
                    try:
                        callback(task.task_id, data)
                    except Exception as e:
                        self.logger.error(f"Result listener callback error: {e}")

            engine.progress_callback = on_progress
            engine.result_callback = on_result
            engine.run(sequences)

            task.transition_to(TaskStatus.COMPLETED)
            self.store.save_task(task)

            auto_task_id = task.params.get("auto_backfill_task_id")
            if auto_task_id:
                self._run_auto_backfill(task, auto_task_id)

        except Exception as e:
            self.logger.error(f"Task {task.task_id} failed: {e}", exc_info=True)
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
                
                # [FIX] 从 params 中提取 task_name 供前端显示
                if isinstance(t.get('params'), str):
                    try:
                        parsed_params = json.loads(t['params'])
                        t['task_name'] = parsed_params.get('task_name')
                    except Exception as _exc:
                        logger.warning("解析 BLAST 历史任务 params JSON 失败: %s", _exc)
                elif isinstance(t.get('params'), dict):
                    t['task_name'] = t['params'].get('task_name')

                if tid in self.tasks:
                    mem_t = self.tasks[tid]
                    t['status'] = mem_t.status
                    t['progress'] = mem_t.progress
                    if 'task_name' in mem_t.params:
                        t['task_name'] = mem_t.params['task_name']
            return stored_tasks

    def get_task_results(self, task_id: str) -> List[Dict[str, Any]]:
        """Retrieve results for a task from store."""
        with self._lock:
            return self.store.get_results(task_id)

    def clear_history(self):
        """Clear all tasks and results safely. Returns list of failed paths."""
        failed_tasks = []
        with self._lock:
            # 1. 首先尝试清理已知的数据库任务
            all_task_ids = list(self.tasks.keys())
            for task_id in all_task_ids:
                success, failed_path = self.delete_task(task_id)
                if not success:
                    failed_tasks.append(failed_path)
            
            # 2. 核心补丁：物理层全量清扫 (清理那些不在数据库记录中的孤儿文件夹)
            try:
                for entry in self.results_dir.iterdir():
                    if entry.is_dir() and entry.name != "__pycache__":
                        # 如果数据库清理后这个文件夹还活着，说明它是孤儿文件夹
                        try:
                            import shutil
                            shutil.rmtree(entry)
                        except Exception as e:
                            self.logger.warning(f"Could not remove orphan directory {entry}: {e}")
                            failed_tasks.append(str(entry))
            except Exception as e:
                self.logger.error(f"Physical cleanup scan failed: {e}")

            # 3. 彻底清空数据库
            self.store.clear_all()
            
            self.logger.info(f"Batch clear finished. {len(failed_tasks)} folders still locked/failed.")
            return failed_tasks

    def delete_task(self, task_id: str):
        """Delete a specific task with protection. Returns (success, failed_path)"""
        with self._lock:
            # Check if task exists (even if only in store)
            task_dir = self.results_dir / task_id
            
            if task_id in self.tasks:
                task = self.tasks[task_id]
                if task.status == "running" and task.engine:
                    task.engine.cancel()
                    time.sleep(0.3) # Wait for process release
            
            # ATOMIC PROTECTION: Try to rename the directory first to detect lock
            if task_dir.exists():
                temp_dir = task_dir.with_name(f"{task_id}_deleting_{int(time.time())}")
                try:
                    # Rename is usually atomic on the same filesystem. 
                    # If any file inside is open, rename might fail or subsequent rmtree will fail.
                    # On Windows, renaming a directory fails if any file inside is open.
                    task_dir.rename(temp_dir)
                    
                    # If rename succeeded, we are likely safe to delete
                    shutil.rmtree(temp_dir)
                    self.logger.info(f"Physical directory for {task_id} cleared successfully.")
                except Exception as e:
                    self.logger.warning(f"Deletion PROTECTED for {task_id}: Directory is locked/in use. {e}")
                    # ABORT database deletion to keep UI consistent with disk
                    return (False, str(task_dir))

            # Only reach here if directory was successfully deleted OR didn't exist
            if task_id in self.tasks:
                del self.tasks[task_id]
            self.store.delete_task(task_id)
            self.logger.info(f"Task {task_id} removed from tracking and store.")
            return (True, None)

    def rename_task(self, task_id: str, new_name: str):
        """Update the display name of a task."""
        with self._lock:
            if task_id in self.tasks:
                self.tasks[task_id].params['task_name'] = new_name
                self.store.save_task(self.tasks[task_id])
            else:
                # Make sure it's updated in DB if not in memory
                tasks_data = self.store.load_all_tasks()
                for target in tasks_data:
                    if target['task_id'] == task_id:
                        params = json.loads(target['params'])
                        params['task_name'] = new_name
                        target_task = BlastTask(task_id, params)
                        target_task.status = target['status']
                        target_task.progress = target['progress']
                        target_task.start_time = datetime.fromisoformat(target['start_time']) if target['start_time'] else None
                        self.store.save_task(target_task)
                        break

            # [FIX] 也要同步更新物理文件夹里的 params.json，防止断点续传/重载时名字被覆盖回来
            task_dir = self.results_dir / task_id
            params_file = task_dir / "params.json"
            if params_file.exists():
                try:
                    with open(params_file, 'r', encoding='utf-8') as f:
                        disk_params = json.load(f)
                    disk_params['task_name'] = new_name
                    with open(params_file, 'w', encoding='utf-8') as f:
                        json.dump(disk_params, f, indent=4, ensure_ascii=False)
                except Exception as e:
                    self.logger.warning(f"Failed to update params.json during rename: {e}")

    def resume_task(self, task_id: str):
        """Resume a failed/cancelled task from its last physical checkpoint."""
        with self._lock:
            if task_id not in self.tasks:
                # Try to load if it exists in store but not in memory
                tasks_data = self.store.load_all_tasks()
                target = next((t for t in tasks_data if t['task_id'] == task_id), None)
                if not target:
                    self.logger.error(f"Cannot resume task {task_id}: Not found in store.")
                    return False
                
                # Restore to memory 
                task = BlastTask(task_id, json.loads(target['params']))
                task.status = TaskStatus(target['status']) if target['status'] in [s.value for s in TaskStatus] else target['status']
                task.progress = target['progress']
                self.tasks[task_id] = task
            
            task = self.tasks[task_id]
            
            # Check if already running or queued
            if task.status in [TaskStatus.RUNNING, TaskStatus.PENDING]:
                self.logger.warning(f"Task {task_id} is already in active queue (Status: {task.status})")
                return True
            
            # LOCK PARAMETERS: Reload from physical params.json to ensure 100% consistency
            task_dir = self.results_dir / task_id
            params_file = task_dir / "params.json"
            if params_file.exists():
                try:
                    with open(params_file, 'r', encoding='utf-8') as f:
                        archived_params = json.load(f)
                        # Ensure we don't accidentally bring in audit fields like 'archived_at' as core params
                        task.params = archived_params
                        self.logger.info(f"Task {task_id} resumed with locked parameters from disk.")
                except Exception as e:
                    self.logger.error(f"Failed to load params.json for resumption: {e}")

            # Prepare for restart
            task.error = None
            task.end_time = None
            # We clear memory results so the Engine can refill them (skipped items + new items)
            # This ensures the progress calculation and UI lists are reconstructed correctly.
            task.results = []
            task.result_count = 0
            
            # Update status and submit
            task.transition_to(TaskStatus.PENDING)
            self.store.save_task(task)
            self.scheduler.submit(task)
            self.logger.info(f"Task {task_id} resumed and resubmitted to scheduler.")
            return True

    def open_directory(self, path: str):
        """Open a directory in system file explorer."""
        try:
            p = Path(path).resolve()
            if p.exists() and p.is_dir():
                os.startfile(p)
                return True
        except Exception as e:
            self.logger.error(f"Failed to open directory {path}: {e}")
        return False


# Global Accessor
_manager = None
def get_blast_manager():
    global _manager
    if _manager is None:
        _manager = BlastManager()
    return _manager
