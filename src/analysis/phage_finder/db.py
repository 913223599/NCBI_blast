# -*- coding: utf-8 -*-
"""
前噬菌体发现任务 SQLite 持久化层 (WAL 模式)
"""
import json
import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[3]


class PhageDiscoveryDB:
    """持久化管理前噬菌体扫描任务元信息、队列状态与产物索引。"""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = Path(db_path) if db_path is not None else (PROJECT_ROOT / "database" / "phage_discovery.db")
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
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
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

    def update_progress(self, task_id: str, progress: int, current_step: str, status: str = "running") -> None:
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with closing(self._connect()) as conn:
            conn.execute(
                """
                UPDATE phage_scan_tasks
                SET progress = ?, current_step = ?,
                    status = CASE WHEN status IN ('completed', 'failed', 'cancelled') THEN status ELSE ? END,
                    updated_at = ?
                WHERE task_id = ?
                """,
                (progress, current_step, status, now_str, task_id),
            )
            conn.commit()

    def mark_completed(
        self,
        task_id: str,
        summary: Dict[str, Any],
        files: Dict[str, str],
        result_path: str,
        model_version: Optional[str] = None,
        device_used: Optional[str] = None,
    ) -> None:
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
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
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with closing(self._connect()) as conn:
            conn.execute(
                """
                UPDATE phage_scan_tasks
                SET status = 'failed', error_msg = ?, current_step = '扫描执行失败', updated_at = ?
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
                UPDATE phage_scan_tasks
                SET status = 'cancelled', current_step = '任务已取消', updated_at = ?
                WHERE task_id = ?
                """,
                (now_str, task_id),
            )
            conn.commit()

    def reset_interrupted_tasks(self, exclude_task_ids: Optional[List[str]] = None) -> None:
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        excludes = [tid for tid in (exclude_task_ids or []) if tid]
        with closing(self._connect()) as conn:
            if excludes:
                placeholders = ",".join("?" for _ in excludes)
                conn.execute(
                    f"""
                    UPDATE phage_scan_tasks
                    SET status = 'cancelled', current_step = '服务重启中断，任务已自动安全重置', updated_at = ?
                    WHERE status IN ('running', 'queued') AND task_id NOT IN ({placeholders})
                    """,
                    [now_str, *excludes],
                )
            else:
                conn.execute(
                    """
                    UPDATE phage_scan_tasks
                    SET status = 'cancelled', current_step = '服务重启中断，任务已自动安全重置', updated_at = ?
                    WHERE status IN ('running', 'queued')
                    """,
                    (now_str,),
                )
            conn.commit()

    def _row_to_dict(self, row: sqlite3.Row) -> Dict[str, Any]:
        d = dict(row)
        for key in ("summary_json", "files_json"):
            raw = d.pop(key, None) or "{}"
            target_key = key.replace("_json", "")
            try:
                d[target_key] = json.loads(raw)
            except Exception:
                d[target_key] = {}
        d["apply_protein_gate"] = bool(d.get("apply_protein_gate", 0))
        return d

    def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT * FROM phage_scan_tasks WHERE task_id = ?",
                (task_id,),
            ).fetchone()
            return self._row_to_dict(row) if row else None

    def list_tasks(self, limit: int = 200) -> List[Dict[str, Any]]:
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT * FROM phage_scan_tasks ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [self._row_to_dict(r) for r in rows]

    def delete_task(self, task_id: str) -> None:
        with closing(self._connect()) as conn:
            conn.execute("DELETE FROM phage_scan_tasks WHERE task_id = ?", (task_id,))
            conn.commit()


phage_discovery_db = PhageDiscoveryDB()

