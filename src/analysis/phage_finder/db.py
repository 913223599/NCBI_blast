# -*- coding: utf-8 -*-
"""
前噬菌体发现任务 SQLite 持久化层（继承 src.core.task_db.BaseTaskDB，WAL 模式）
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any, Dict, List, Optional

from ...core.task_db import BaseTaskDB

PROJECT_ROOT = Path(__file__).resolve().parents[3]


class PhageDiscoveryDB(BaseTaskDB):
    """持久化管理前噬菌体扫描任务元信息、队列状态与产物索引。"""

    table_name = "phage_scan_tasks"
    id_column = "task_id"
    json_columns = ("summary_json", "files_json")
    pop_json_columns = True

    def __init__(self, db_path: Optional[Path] = None):
        resolved = Path(db_path) if db_path is not None else (PROJECT_ROOT / "database" / "phage_discovery.db")
        super().__init__(resolved)

    def _init_db(self) -> None:
        with closing(self._connect()) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS phage_scan_tasks (
                    task_id TEXT PRIMARY KEY,
                    task_name TEXT,
                    model_id TEXT,
                    model_version TEXT,
                    device TEXT,
                    apply_protein_gate INTEGER DEFAULT 0,
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
            conn.execute("CREATE INDEX IF NOT EXISTS idx_phage_scan_status ON phage_scan_tasks(status)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_phage_scan_created ON phage_scan_tasks(created_at)")
            conn.commit()

    def create_task(
        self,
        task_id: str,
        task_name: str,
        model_id: str,
        model_version: str,
        device: str,
        apply_protein_gate: bool,
        status: str = "queued",
    ) -> bool:
        now_str = self._now_str()
        with closing(self._connect()) as conn:
            conn.execute(
                """
                INSERT INTO phage_scan_tasks (
                    task_id, task_name, model_id, model_version, device,
                    apply_protein_gate, status, progress, current_step,
                    created_at, updated_at, summary_json, files_json, result_path
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, 0, '已加入扫描等待队列...', ?, ?, '{}', '{}', '')
                """,
                (
                    task_id,
                    task_name,
                    model_id,
                    model_version,
                    device,
                    1 if apply_protein_gate else 0,
                    status,
                    now_str,
                    now_str,
                ),
            )
            conn.commit()
        return True

    def mark_completed(
        self,
        task_id: str,
        summary: Dict[str, Any],
        files: Dict[str, str],
        result_path: str,
        model_version: Optional[str] = None,
        device_used: Optional[str] = None,
    ) -> None:
        now_str = self._now_str()
        with closing(self._connect()) as conn:
            conn.execute(
                """
                UPDATE phage_scan_tasks
                SET status = 'completed',
                    progress = 100,
                    current_step = '扫描与边界精细分割已完成',
                    summary_json = ?,
                    files_json = ?,
                    result_path = ?,
                    model_version = COALESCE(?, model_version),
                    device = COALESCE(?, device),
                    updated_at = ?
                WHERE task_id = ?
                """,
                (
                    json.dumps(summary, ensure_ascii=False),
                    json.dumps(files, ensure_ascii=False),
                    result_path,
                    model_version,
                    device_used,
                    now_str,
                    task_id,
                ),
            )
            conn.commit()

    def mark_failed(self, task_id: str, error_msg: str) -> None:
        self._mark_failed_with_step(task_id, error_msg, "扫描执行失败")

    def mark_cancelled(self, task_id: str) -> None:
        self._mark_cancelled_with_step(task_id, "任务已取消")

    def reset_interrupted_tasks(self, exclude_task_ids: Optional[List[str]] = None) -> None:
        self._reset_interrupted_with_statuses(
            statuses=("running", "queued"),
            step_label="服务重启中断，任务已自动安全重置",
            exclude_task_ids=exclude_task_ids,
        )

    def _deserialize_row(self, row: sqlite3.Row) -> Dict[str, Any]:
        data = super()._deserialize_row(row)
        data["apply_protein_gate"] = bool(data.get("apply_protein_gate", 0))
        return data

    def list_tasks(self, limit: int = 200) -> List[Dict[str, Any]]:
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT * FROM phage_scan_tasks ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [self._deserialize_row(r) for r in rows]


phage_discovery_db = PhageDiscoveryDB()
