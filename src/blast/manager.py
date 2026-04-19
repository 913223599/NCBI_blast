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
            # Use REPLACE logic to avoid duplicates during Resumption
            conn.execute("DELETE FROM results WHERE task_id = ? AND sequence_id = ?", (task_id, seq_id))
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
                for i in range(missing):
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

    def _run_task(self, task: BlastTask):
        """Internal execution loop using the new Pipe Engine."""
        try:
            task.transition_to(TaskStatus.RUNNING)
            self.store.save_task(task)

            # [FIX] 设置任务独立的序列存储目录，将分拣文件归位，便于按任务管理和清理
            task_dir = self.results_dir / task.task_id
            seq_storage = task_dir / "sequences"
            seq_storage.mkdir(parents=True, exist_ok=True)

            # Setup Sequences
            from src.utils.file_handler import FileHandler
            import shutil
            fh = FileHandler()
            sequences = []
            
            # 处理选中的文件
            final_file_paths = []
            for f_path in task.params.get("files", []):
                p = Path(f_path)
                # 识别是否属于“分拣暂存区”的文件
                if "extracted" in p.parts:
                    # 将分拣出的临时文件迁移到当前任务的专属目录
                    dest_path = seq_storage / p.name
                    try:
                        # 如果目标已存在（可能有同名文件），增加后缀防止覆盖
                        if dest_path.exists():
                           dest_path = seq_storage / f"{p.stem}_{int(time.time())}{p.suffix}"
                        shutil.move(str(p), str(dest_path))
                        final_file_paths.append(str(dest_path))
                    except Exception as e:
                        self.logger.warning(f"Failed to migrate extracted file {p.name}: {e}. Using original path.")
                        final_file_paths.append(f_path)
                else:
                    final_file_paths.append(f_path)
            # 更新 Task Params 中的文件路径，确保持久化后的 params.json 指向归位后的文件
            task.params["files"] = final_file_paths

            # 提取序列内容
            # 提取序列内容
            def collect_sequences(path_list):
                # 预处理：按路径去重，并处理目录
                target_files = []
                # 记录已添加的绝对路径，防止重复处理同一文件
                processed_paths = set()
                
                # 内部整理函数
                def get_all_files(ps):
                    files = []
                    for p_str in ps:
                        p = Path(p_str).resolve()
                        if p.is_dir():
                            # 递归扫描目录
                            files.extend([str(sf) for sf in p.rglob('*') if sf.is_file()])
                        elif p.is_file():
                            files.append(str(p))
                    return files

                all_extracted_files = get_all_files(path_list)
                
                # 统一优先级映射：数值越大优先级越高 (与 api_server.py 对齐)
                priority_map = {
                    '.fasta': 10, '.fas': 10, '.fa': 10, '.fna': 10,
                    '.seq': 8,
                    '.txt': 5,
                    '.ab1': 3, '.abi': 3,
                    '.nwk': 1, '.newick': 1
                }
                
                # 改进的去重：仅对同一目录下的同名文件进行格式优选 (e.g. sample.seq vs sample.ab1)
                # 而不同目录下的同名文件 (e.g. a/1.seq vs b/1.seq) 应该全部保留
                dir_groups = {} # parent_dir -> { stem -> [full_paths] }
                
                for f_path in all_extracted_files:
                    p = Path(f_path)
                    parent = str(p.parent)
                    stem = p.stem.lower()
                    if parent not in dir_groups: dir_groups[parent] = {}
                    if stem not in dir_groups[parent]: dir_groups[parent][stem] = []
                    dir_groups[parent][stem].append(f_path)
                
                for parent, stems in dir_groups.items():
                    for stem, paths in stems.items():
                        if len(paths) == 1:
                            target_files.append(paths[0])
                        else:
                            # [FIX] 与 api_server 对齐，使用 reverse=True 配合 大值优先
                            paths.sort(key=lambda x: priority_map.get(Path(x).suffix.lower(), 0), reverse=True)
                            target_files.append(paths[0])

                # 执行读取
                for f_path in target_files:
                    if f_path in processed_paths: continue
                    try:
                        count_in_file = 0
                        for seq in fh.read_fasta_file_iter(f_path):
                            sequences.append(seq)
                            count_in_file += 1
                        processed_paths.add(f_path)
                        self.logger.debug(f"从 {f_path} 提取了 {count_in_file} 条序列")
                    except Exception as e:
                        self.logger.warning(f"无法从文件 {f_path} 提取序列: {e}")

            collect_sequences(final_file_paths)
           
            # Extract from query text (Support Multi-FASTA parse)
            query_text = task.params.get("query", "").strip()
            if query_text:
                if query_text.startswith(">"):
                    import io
                    from Bio import SeqIO
                    try:
                        for rec in SeqIO.parse(io.StringIO(query_text), "fasta"):
                            sequences.append({"id": rec.id, "sequence": str(rec.seq)})
                    except Exception as e:
                        self.logger.warning(f"Failed to parse query_text as Multi-FASTA: {e}")
                        sequences.append({"id": "Manual_Input", "sequence": query_text})
                else:
                    sequences.append({"id": "Manual_Input", "sequence": query_text})

            if not sequences:
                raise ValueError("没有检测到有效序列")

            # Initialize Engine
            engine = BlastEngine(task.task_id, task.params)
            task.engine = engine # Track for cancellation

            # Pre-populate placeholders so UI shows the entire list instantly
            existing_results = {r.get('sequence_id') for r in self.store.get_results(task.task_id)}
            for seq in sequences:
                seq_id = seq.get('id', 'unknown')
                if seq_id not in existing_results:
                    pending_data = {
                        "sequence_id": seq_id,
                        "status": "pending"
                    }
                    # [CRITICAL FIX] 把占位符存入数据库，防止刷新页面或重选任务时列表变空
                    self.store.save_result(task.task_id, seq_id, pending_data)
                    
                    # Emit to UI
                    if self.result_listeners:
                        for cb in self.result_listeners:
                            try: cb(task.task_id, pending_data)
                            except: pass
                    # Optional: DB persistence for pending items can be skipped if UI generates list live,
                    # but saving them guarantees history retention.
                    self.store.save_result(task.task_id, seq_id, pending_data)

            def on_progress(comp, total, info):
                new_prog = int(comp/total * 100)
                # Prevent progress bar rollback during breakpoint resuming (cached tasks loading)
                if new_prog >= getattr(task, 'progress', 0) or comp == total:
                    task.progress = new_prog
                    self.store.save_task(task)

            def on_result(data):
                # [核心增强] 为了支持一键入库，将原始序列内容回填到结果对象中
                seq_id = data.get('sequence_id')
                if seq_id:
                    original_seq = next((s['sequence'] for s in sequences if s['id'] == seq_id), None)
                    if original_seq:
                        data['raw_sequence'] = original_seq

                task.results.append(data)
                self.store.save_result(task.task_id, data.get('sequence_id','?'), data)
                # Notify active listeners (for real-time UI streaming)
                for callback in self.result_listeners:
                    try:
                        callback(task.task_id, data)
                    except Exception as e:
                        self.logger.error(f"Result listener callback error: {e}")

            engine.progress_callback = on_progress
            engine.result_callback = on_result
            
            # Run
            engine.run(sequences)

            # Cleanup
            task.transition_to(TaskStatus.COMPLETED)
            self.store.save_task(task)

            # ✨ [SILENT PIPELINE HOOK] 自动回填逻辑
            auto_task_id = task.params.get("auto_backfill_task_id")
            if auto_task_id:
                try:
                    self.logger.info(f"🚀 Triggering AUTO-BACKFILL for Assembly Task: {auto_task_id}")
                    from src.backend.utils.assembly_storage import AssemblyStorage
                    from src.backend.utils.assembly_gbk_fixer import GBKAnnotationBackfiller
                    from src.backend.utils.blast_utils import parse_blast_csv
                    
                    # 1. 搜集所有 Hit 结果
                    hits_to_backfill = {}
                    task_results = self.get_task_results(task.task_id)
                    for res in task_results:
                        csv_file = res.get('csv_file')
                        if csv_file and os.path.exists(csv_file):
                            top_hits = parse_blast_csv(csv_file, limit=1)
                            if top_hits:
                                best = top_hits[0]
                                # 保持与 apply_blast_hits 预期的格式一致
                                hits_to_backfill[res['sequence_id']] = {
                                    "product": best.get('stitle', 'hypothetical protein'),
                                    "evalue": best.get('evalue', 'N/A'),
                                    "accession": best.get('saccession', 'N/A')
                                }
                    
                    if hits_to_backfill:
                        # 2. 定位 GBK 文件并应用
                        task_dir = AssemblyStorage.get_task_dir(auto_task_id)
                        anno_dir = task_dir / "phageannotationstep"
                        phold_gbk = anno_dir / "phold_res" / "phold.gbk"
                        pharokka_gbk = anno_dir / "pharokka_res" / "PHAGE.gbk"
                        base_gbk = phold_gbk if phold_gbk.exists() else pharokka_gbk
                        
                        if base_gbk and base_gbk.exists():
                            fixer = GBKAnnotationBackfiller(base_gbk)
                            fixer.apply_blast_hits(hits_to_backfill)
                            self.logger.info(f"✅ AUTO-BACKFILL COMPLETED for {len(hits_to_backfill)} proteins.")
                        else:
                            self.logger.warning(f"❌ AUTO-BACKFILL SKIPPED: Base GBK not found in {anno_dir}")
                except Exception as eb:
                    self.logger.error(f"💥 AUTO-BACKFILL FAILED inside manager: {eb}", exc_info=True)

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
        """Request resume of a paused task, or restart a cancelled/failed task from breakpoint."""
        with self._lock:
            if task_id in self.tasks:
                task = self.tasks[task_id]
                
                # 1. Resume from Paused (Thread still alive)
                if task.status == TaskStatus.PAUSED and getattr(task, 'engine', None):
                    task.engine.resume()
                    task.transition_to(TaskStatus.RUNNING)
                    self.store.save_task(task)
                    self.logger.info(f"Resumed paused task: {task_id}")
                    
                # 2. Resubmit from Cancelled/Failed (Thread dead, breakpoint continuation)
                elif task.status in [TaskStatus.CANCELLED, TaskStatus.FAILED, 'error', 'failed', 'cancelled']:
                    task.transition_to(TaskStatus.PENDING)
                    task.error = None
                    self.store.save_task(task)
                    self.scheduler.submit(task)
                    self.logger.info(f"Resubmitted stopped task for breakpoint continuation: {task_id}")

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
