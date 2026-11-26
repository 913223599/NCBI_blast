# -*- coding: utf-8 -*-
"""
功能注释任务 SQLite 数据库持久化层（继承 src.core.task_db.BaseTaskDB）
"""
from __future__ import annotations

import json
from contextlib import closing
from typing import Any, Dict, List, Optional

from ...core.task_db import BaseTaskDB


class AnnotationDB(BaseTaskDB):
    table_name = "annotation_tasks"
    id_column = "task_id"
    json_columns = ("summary_json", "files_json", "safety_audit_json", "checkv_json")
    pop_json_columns = False

    def __init__(self, db_path: str = "database/annotation.db"):
        super().__init__(db_path)

    def _init_db(self) -> None:
        with closing(self._connect()) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS annotation_tasks (
                    task_id TEXT PRIMARY KEY,
                    task_name TEXT,
                    sample_type TEXT,
                    engine TEXT,
                    status TEXT,
                    progress INTEGER DEFAULT 0,
                    current_step TEXT,
                    error_msg TEXT,
                    created_at TEXT,
                    updated_at TEXT,
                    summary_json TEXT,
                    files_json TEXT,
                    safety_audit_json TEXT,
                    checkv_json TEXT
                )
                """
            )
            cursor = conn.execute("PRAGMA table_info(annotation_tasks)")
            existing_cols = {row[1] for row in cursor.fetchall()}
            if "safety_audit_json" not in existing_cols:
                conn.execute("ALTER TABLE annotation_tasks ADD COLUMN safety_audit_json TEXT")
            if "checkv_json" not in existing_cols:
                conn.execute("ALTER TABLE annotation_tasks ADD COLUMN checkv_json TEXT")

            conn.execute("CREATE INDEX IF NOT EXISTS idx_anno_status ON annotation_tasks(status)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_anno_created ON annotation_tasks(created_at)")
            conn.commit()

    def create_task(
        self,
        task_id: str,
        task_name: str,
        sample_type: str,
        engine: str,
        status: str = "queued",
    ) -> bool:
        now_str = self._now_str()
        with closing(self._connect()) as conn:
            conn.execute(
                """
                INSERT INTO annotation_tasks
                (task_id, task_name, sample_type, engine, status, progress, current_step,
                 created_at, updated_at, summary_json, files_json, safety_audit_json, checkv_json)
                VALUES (?, ?, ?, ?, ?, 0, '已加入排队队列...', ?, ?, '{}', '{}', '{}', '{}')
                """,
                (task_id, task_name, sample_type, engine, status, now_str, now_str),
            )
            conn.commit()
        return True

    def mark_completed(
        self,
        task_id: str,
        summary: Dict[str, Any],
        files: Dict[str, str],
        safety_audit: Optional[Dict[str, Any]] = None,
        checkv: Optional[Dict[str, Any]] = None,
    ) -> None:
        now_str = self._now_str()
        with closing(self._connect()) as conn:
            conn.execute(
                """
                UPDATE annotation_tasks
                SET status = 'completed', progress = 100, current_step = '注释已完成',
                    summary_json = ?, files_json = ?, safety_audit_json = ?, checkv_json = ?, updated_at = ?
                WHERE task_id = ?
                """,
                (
                    json.dumps(summary, ensure_ascii=False),
                    json.dumps(files, ensure_ascii=False),
                    json.dumps(safety_audit or {}, ensure_ascii=False),
                    json.dumps(checkv or {}, ensure_ascii=False),
                    now_str,
                    task_id,
                ),
            )
            conn.commit()

    def mark_failed(self, task_id: str, error_msg: str) -> None:
        self._mark_failed_with_step(task_id, error_msg, "分析失败")

    def mark_cancelled(self, task_id: str) -> None:
        self._mark_cancelled_with_step(task_id, "已取消")

    def list_tasks(self, limit: int = 200) -> List[Dict[str, Any]]:
        with closing(self._connect()) as conn:
            rows = conn.execute(
                """
                SELECT task_id, task_name, sample_type, engine, status, progress, current_step,
                       error_msg, created_at, updated_at, summary_json, files_json,
                       safety_audit_json, checkv_json
                FROM annotation_tasks
                ORDER BY created_at DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return [self._deserialize_row(r) for r in rows]

    def get_incomplete_tasks(self) -> List[Dict[str, Any]]:
        """获取所有未完成的任务（用于队列快照与自愈恢复）。"""
        with closing(self._connect()) as conn:
            rows = conn.execute(
                """
                SELECT task_id, task_name, sample_type, engine, status, progress,
                       current_step, created_at, updated_at
                FROM annotation_tasks
                WHERE status IN ('running', 'queued', 'pending')
                ORDER BY created_at ASC
                """
            ).fetchall()
            return [dict(r) for r in rows]

    def reset_interrupted_tasks(self, exclude_task_ids: Optional[List[str]] = None) -> int:
        """服务重启安全自愈：将此前处于 running 状态的遗留任务标记为 cancelled。"""
        return self._reset_interrupted_with_statuses(
            statuses=("running",),
            step_label="服务重启导致中断，已重置",
            exclude_task_ids=exclude_task_ids,
        )


# 全局单例
annotation_db = AnnotationDB()
