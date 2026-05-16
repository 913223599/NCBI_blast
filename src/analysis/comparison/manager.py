"""
共线性分析任务管理器
职责：持久化任务元数据，管理物理文件清理。
扩展 Schema 以统一存储多种引擎的分析结果。
"""

import sqlite3
import json
import logging
import shutil
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any, Optional


class ComparisonManager:
    """
    共线性分析任务管理器
    职责：持久化任务元数据，管理物理文件清理。
    """

    def __init__(self):
        self.root_dir = Path(__file__).resolve().parent.parent.parent.parent
        self.results_dir = self.root_dir / "results" / "comparison"
        self.results_dir.mkdir(parents=True, exist_ok=True)

        self.db_path = self.results_dir / "comparison_meta.db"
        self._init_db()
        self.logger = logging.getLogger("Analysis.Comparison.Manager")

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            # 创建主表（兼容旧 Schema + 新增字段）
            conn.execute("""
                CREATE TABLE IF NOT EXISTS comparison_tasks (
                    task_id TEXT PRIMARY KEY,
                    ref_name TEXT,
                    query_name TEXT,
                    created_at TEXT,
                    matched_length INTEGER,
                    average_identity REAL,
                    total_matches INTEGER,
                    ref_length INTEGER,
                    query_length INTEGER,
                    was_flipped INTEGER,
                    status TEXT
                )
            """)

            # 安全升级 Schema：逐个检测并添加新字段
            existing = {row[1] for row in conn.execute("PRAGMA table_info(comparison_tasks)")}
            new_columns = {
                "engine": "TEXT DEFAULT 'mummer'",
                "variant_count": "INTEGER DEFAULT 0",
                "ref_length": "INTEGER DEFAULT 0",
                "query_length": "INTEGER DEFAULT 0"
            }
            for col_name, col_def in new_columns.items():
                if col_name not in existing:
                    conn.execute(f"ALTER TABLE comparison_tasks ADD COLUMN {col_name} {col_def}")

    def record_task(
        self,
        task_id: str,
        metadata: Dict[str, Any],
        summary: Dict[str, Any],
        variant_count: int = 0
    ):
        """记录分析任务到数据库"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    INSERT OR REPLACE INTO comparison_tasks 
                    (task_id, ref_name, query_name, created_at, matched_length, 
                     average_identity, total_matches, was_flipped, status, engine, variant_count,
                     ref_length, query_length)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    task_id,
                    metadata.get('ref_name'),
                    metadata.get('query_name'),
                    datetime.now().isoformat(),
                    summary.get('matched_length', 0),
                    summary.get('average_identity', 0.0),
                    summary.get('total_matches', 0),
                    1 if metadata.get('was_flipped') else 0,
                    'success',
                    metadata.get('engine', 'mummer'),
                    variant_count,
                    summary.get('ref_length', 0),
                    summary.get('query_length', 0)
                ))
        except Exception as e:
            self.logger.error(f"Failed to record comparison task: {e}")

    def list_history(self) -> List[Dict[str, Any]]:
        """获取所有历史任务列表"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.execute(
                    "SELECT * FROM comparison_tasks ORDER BY created_at DESC"
                )
                return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            self.logger.error(f"Failed to list history: {e}")
            return []

    def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        """获取单个任务详情"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.execute(
                    "SELECT * FROM comparison_tasks WHERE task_id = ?", (task_id,)
                )
                row = cursor.fetchone()
                return dict(row) if row else None
        except Exception as e:
            self.logger.error(f"Failed to get task {task_id}: {e}")
            return None

    def delete_task(self, task_id: str) -> bool:
        """
        原子化清理：删除数据库记录并物理粉碎文件夹
        """
        try:
            # 1. 物理删除
            task_dir = self.results_dir / task_id
            if task_dir.exists():
                shutil.rmtree(task_dir)

            # 2. 数据库删除
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    "DELETE FROM comparison_tasks WHERE task_id = ?", (task_id,)
                )

            return True
        except Exception as e:
            self.logger.error(f"Failed to delete task {task_id}: {e}")
            return False


# 单例导出
_manager = None


def get_comparison_manager():
    global _manager
    if _manager is None:
        _manager = ComparisonManager()
    return _manager
