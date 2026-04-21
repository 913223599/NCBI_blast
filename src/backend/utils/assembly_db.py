import sqlite3
import json
import logging
import time
from pathlib import Path
from typing import List, Dict, Any, Optional
from .json_encoder import BioJsonEncoder

logger = logging.getLogger("Assembly.DB")

class AssemblyDB:
    """
    AssemblyDB - 负责任务元数据的持久化存储与历史追溯
    单一职责：管理任务在 SQLite 中的状态记录
    """
    # 使用 __file__ 计算绝对路径，避免依赖运行时 CWD
    DB_PATH = Path(__file__).resolve().parent.parent.parent.parent / "database" / "assembly.db"

    def __init__(self):
        self.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self):
        """初始化数据库表结构"""
        with sqlite3.connect(self.DB_PATH) as conn:
            # 1. 创建基础表
            conn.execute('''
                CREATE TABLE IF NOT EXISTS assembly_tasks (
                    id TEXT PRIMARY KEY,
                    name TEXT,
                    sample_id TEXT,
                    sample_type TEXT,
                    tech TEXT,
                    status TEXT,
                    last_step TEXT,
                    progress REAL DEFAULT 0.0,
                    config TEXT,
                    results TEXT,
                    created_at REAL,
                    updated_at REAL
                )
            ''')
            
            # 2. 动态迁移：检查是否存在新列 (兼容旧库)
            cursor = conn.execute("PRAGMA table_info(assembly_tasks)")
            columns = [col[1] for col in cursor.fetchall()]
            if 'sample_type' not in columns:
                logger.info("🛠️ 正在迁移数据库: 添加 sample_type 列...")
                conn.execute('ALTER TABLE assembly_tasks ADD COLUMN sample_type TEXT')
            if 'duration_seconds' not in columns:
                logger.info("🛠️ 正在迁移数据库: 添加 duration_seconds 列...")
                conn.execute('ALTER TABLE assembly_tasks ADD COLUMN duration_seconds REAL')
            
            # 3. 开启 WAL 模式，防止多 Worker 并发写入时 "database is locked"
            conn.execute("PRAGMA journal_mode=WAL")
            
            conn.commit()

    def create_task(self, task_id: str, name: str, sample_id: str, sample_type: str, tech: str, config: Dict[str, Any]):
        """新建任务记录"""
        now = time.time()
        # 🔗 确保 config 中也持久化存储 sample_type 方便前端解析
        if isinstance(config, dict):
            config['sample_type'] = sample_type

        with sqlite3.connect(self.DB_PATH) as conn:
            conn.execute(
                "INSERT INTO assembly_tasks (id, name, sample_id, sample_type, tech, status, last_step, config, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (task_id, name, sample_id, sample_type, tech, "pending", "INITIALIZING", json.dumps(config, cls=BioJsonEncoder), now, now)
            )
            conn.commit()

    def update_task_progress(self, task_id: str, step: str, progress: float, status: str = "running"):
        """更新任务实时进度与步骤"""
        now = time.time()
        with sqlite3.connect(self.DB_PATH) as conn:
            conn.execute(
                "UPDATE assembly_tasks SET last_step = ?, progress = ?, status = ?, updated_at = ? WHERE id = ?",
                (step, progress, status, now, task_id)
            )
            conn.commit()

    def finalize_task(self, task_id: str, status: str, results: Dict[str, Any] = None):
        """标记任务结束并存储结果摘要，补全耗时统计"""
        now = time.time()
        
        # 自动计算耗时
        duration = 0
        task = self.get_task(task_id)
        if task and task.get('created_at'):
            duration = now - task['created_at']

        results_str = json.dumps(results, cls=BioJsonEncoder) if results else None
        with sqlite3.connect(self.DB_PATH) as conn:
            conn.execute(
                "UPDATE assembly_tasks SET status = ?, results = ?, updated_at = ?, progress = 100.0, duration_seconds = ? WHERE id = ?",
                (status, results_str, now, duration, task_id)
            )
            conn.commit()

    def get_history(self, limit: int = 50) -> List[Dict[str, Any]]:
        """获取任务历史列表"""
        with sqlite3.connect(self.DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("SELECT * FROM assembly_tasks ORDER BY created_at DESC LIMIT ?", (limit,))
            return [dict(row) for row in cursor.fetchall()]

    def delete_task(self, task_id: str):
        """物理清理数据库记录"""
        with sqlite3.connect(self.DB_PATH) as conn:
            conn.execute("DELETE FROM assembly_tasks WHERE id = ?", (task_id,))
            conn.commit()

    def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        """查询特定任务"""
        with sqlite3.connect(self.DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("SELECT * FROM assembly_tasks WHERE id = ?", (task_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

# 单例导出
assembly_db = AssemblyDB()
