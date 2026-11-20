# -*- coding: utf-8 -*-
"""
噬菌体结构与尾部形态预测任务 SQLite 持久化层 (WAL 模式)
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[3]


class PhageStructureDB:
    """持久化管理结构与形态预测任务元数据、队列状态与产物索引。"""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = Path(db_path) if db_path is not None else (PROJECT_ROOT / "database" / "phage_structure.db")
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        return conn

    def _init_db(self) -> None:
        with closing(self._connect()) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS phage_structure_tasks (
                    task_id TEXT PRIMARY KEY,
                    task_name TEXT,
                    source_mode TEXT,
                    status TEXT,
                    progress INTEGER DEFAULT 0,
                    current_step TEXT,
                    error_msg TEXT,
                    created_at TEXT,
                    updated_at TEXT,
                    summary_json TEXT,
                    files_json TEXT,
                    result_path TEXT
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_ps_status ON phage_structure_tasks(status)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_ps_created ON phage_structure_tasks(created_at)")
            conn.commit()

    def create_task(
        self,
        task_id: str,
        task_name: str,
        source_mode: str,
        status: str = "queued",
    ) -> bool:
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with closing(self._connect()) as conn:
            conn.execute(
                """
                INSERT INTO phage_structure_tasks (
                    task_id, task_name, source_mode, status, progress,
                    current_step, created_at, updated_at, summary_json, files_json, result_path
                )
                VALUES (?, ?, ?, ?, 0, '已加入结构与形态预测等待队列...', ?, ?, '{}', '{}', '')
                """,
                (task_id, task_name, source_mode, status, now_str, now_str),
            )
            conn.commit()
        return True

    def update_progress(self, task_id: str, progress: int, current_step: str, status: str = "running") -> None:
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with closing(self._connect()) as conn:
            if progress >= 0:
                conn.execute(
                    """
                    UPDATE phage_structure_tasks
                    SET progress = ?, current_step = ?,
                        status = CASE WHEN status IN ('completed', 'failed', 'cancelled') THEN status ELSE ? END,
                        updated_at = ?
                    WHERE task_id = ?
                    """,
                    (progress, current_step, status, now_str, task_id),
                )
            else:
                conn.execute(
                    """
                    UPDATE phage_structure_tasks
                    SET current_step = ?, updated_at = ?
                    WHERE task_id = ?
                    """,
                    (current_step, now_str, task_id),
                )
            conn.commit()

    def mark_completed(
        self,
        task_id: str,
        summary: Dict[str, Any],
        files: Dict[str, str],
        result_path: str,
    ) -> None:
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with closing(self._connect()) as conn:
            conn.execute(
                """
                UPDATE phage_structure_tasks
                SET status = 'completed', progress = 100, current_step = '结构与形态预测完成',
                    summary_json = ?, files_json = ?, result_path = ?, updated_at = ?
                WHERE task_id = ?
                """,
                (
                    json.dumps(summary, ensure_ascii=False),
                    json.dumps(files, ensure_ascii=False),
                    result_path,
                    now_str,
                    task_id,
                ),
            )
            conn.commit()

    def mark_failed(self, task_id: str, error_msg: str) -> None:
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with closing(self._connect()) as conn:
            conn.execute(
                """
                UPDATE phage_structure_tasks
                SET status = 'failed', current_step = '结构预测失败', error_msg = ?, updated_at = ?
                WHERE task_id = ?
                """,
                (error_msg, now_str, task_id),
            )
            conn.commit()

    def mark_cancelled(self, task_id: str) -> None:
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with closing(self._connect()) as conn:
            conn.execute(
                """
                UPDATE phage_structure_tasks
                SET status = 'cancelled', current_step = '已取消', updated_at = ?
                WHERE task_id = ?
                """,
                (now_str, task_id),
            )
            conn.commit()

    def reset_interrupted_tasks(self, exclude_task_ids: Optional[List[str]] = None) -> int:
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        exclude = [tid for tid in (exclude_task_ids or []) if tid]
        with closing(self._connect()) as conn:
            if exclude:
                placeholders = ",".join("?" for _ in exclude)
                cur = conn.execute(
                    f"""
                    UPDATE phage_structure_tasks
                    SET status = 'cancelled', current_step = '服务重启中断，已自动重置', updated_at = ?
                    WHERE status IN ('running', 'queued') AND task_id NOT IN ({placeholders})
                    """,
                    [now_str, *exclude],
                )
            else:
                cur = conn.execute(
                    """
                    UPDATE phage_structure_tasks
                    SET status = 'cancelled', current_step = '服务重启中断，已自动重置', updated_at = ?
                    WHERE status IN ('running', 'queued')
                    """,
                    (now_str,),
                )
            conn.commit()
            return cur.rowcount or 0

    def _deserialize(self, row: sqlite3.Row) -> Dict[str, Any]:
        d = dict(row)
        try:
            d["summary"] = json.loads(d.pop("summary_json") or "{}")
        except Exception:
            d["summary"] = {}
        try:
            d["files"] = json.loads(d.pop("files_json") or "{}")
        except Exception:
            d["files"] = {}
        return d

    def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        with closing(self._connect()) as conn:
            row = conn.execute("SELECT * FROM phage_structure_tasks WHERE task_id = ?", (task_id,)).fetchone()
            return self._deserialize(row) if row else None

    def list_history(self, limit: int = 100) -> List[Dict[str, Any]]:
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT * FROM phage_structure_tasks ORDER BY created_at DESC, rowid DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [self._deserialize(r) for r in rows]

    def delete_task(self, task_id: str) -> None:
        with closing(self._connect()) as conn:
            conn.execute("DELETE FROM phage_structure_tasks WHERE task_id = ?", (task_id,))
            conn.commit()


phage_structure_db = PhageStructureDB()
