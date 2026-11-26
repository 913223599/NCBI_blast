# -*- coding: utf-8 -*-
"""
噬菌体结构与尾部形态预测任务 SQLite 持久化层（继承 src.core.task_db.BaseTaskDB，WAL 模式）
"""
from __future__ import annotations

import json
from contextlib import closing
from pathlib import Path
from typing import Any, Dict, List, Optional

from ...core.task_db import BaseTaskDB

PROJECT_ROOT = Path(__file__).resolve().parents[3]


class PhageStructureDB(BaseTaskDB):
    """持久化管理结构与形态预测任务元数据、队列状态与产物索引。"""

    table_name = "phage_structure_tasks"
    id_column = "task_id"
    json_columns = ("summary_json", "files_json")
    pop_json_columns = True

    def __init__(self, db_path: Optional[Path] = None):
        resolved = Path(db_path) if db_path is not None else (PROJECT_ROOT / "database" / "phage_structure.db")
        super().__init__(resolved)

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
        now_str = self._now_str()
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

    def mark_completed(
        self,
        task_id: str,
        summary: Dict[str, Any],
        files: Dict[str, str],
        result_path: str,
    ) -> None:
        now_str = self._now_str()
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
        self._mark_failed_with_step(task_id, error_msg, "结构预测失败")

    def mark_cancelled(self, task_id: str) -> None:
        self._mark_cancelled_with_step(task_id, "已取消")

    def reset_interrupted_tasks(self, exclude_task_ids: Optional[List[str]] = None) -> int:
        return self._reset_interrupted_with_statuses(
            statuses=("running", "queued"),
            step_label="服务重启中断，已自动重置",
            exclude_task_ids=exclude_task_ids,
        )

    def list_history(self, limit: int = 100) -> List[Dict[str, Any]]:
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT * FROM phage_structure_tasks ORDER BY created_at DESC, rowid DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [self._deserialize_row(r) for r in rows]


phage_structure_db = PhageStructureDB()
