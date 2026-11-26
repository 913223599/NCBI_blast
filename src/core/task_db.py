# -*- coding: utf-8 -*-
"""
共享 SQLite 任务持久化基类 (BaseTaskDB) 与统一 GPU 显存回收工具

消除 annotation / phage_finder / phage_structure 等模块重复实现的 SQLite WAL 连接、
任务进度更新、失败/取消状态流转、服务重启自愈重置及 JSON 反序列化样板。
"""
from __future__ import annotations

import gc
import json
import logging
import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

logger = logging.getLogger("core.task_db")


def release_gpu_memory() -> None:
    """在推理/分析任务前后强制回收 Python 对象与 CUDA 显存缓存，严防显存溢出至共享内存。"""
    gc.collect()
    try:
        import torch  # type: ignore

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            if hasattr(torch.cuda, "ipc_collect"):
                torch.cuda.ipc_collect()
    except Exception as exc:
        logger.debug("CUDA memory cleanup skipped: %s", exc)


class BaseTaskDB:
    """通用 WAL 模式任务 SQLite 数据库基类。"""

    table_name: str = ""
    id_column: str = "task_id"
    json_columns: Sequence[str] = ("summary_json", "files_json")
    pop_json_columns: bool = True

    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        return conn

    def _init_db(self) -> None:
        raise NotImplementedError

    @staticmethod
    def _now_str() -> str:
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    @staticmethod
    def _safe_json_loads(raw: Any, default: Any = None) -> Any:
        if default is None:
            default = {}
        if not raw:
            return default
        try:
            return json.loads(raw)
        except Exception:
            return default

    def _deserialize_row(self, row: sqlite3.Row) -> Dict[str, Any]:
        data = dict(row)
        for col in self.json_columns:
            raw = data.pop(col, None) if self.pop_json_columns else data.get(col)
            target = col[:-5] if col.endswith("_json") else col
            data[target] = self._safe_json_loads(raw, {})
        return data

    def update_progress(
        self,
        task_id: str,
        progress: int,
        current_step: str,
        status: str = "running",
    ) -> None:
        now_str = self._now_str()
        with closing(self._connect()) as conn:
            if progress >= 0:
                conn.execute(
                    f"""
                    UPDATE {self.table_name}
                    SET progress = ?, current_step = ?,
                        status = CASE WHEN status IN ('completed', 'failed', 'cancelled') THEN status ELSE ? END,
                        updated_at = ?
                    WHERE {self.id_column} = ?
                    """,
                    (progress, current_step, status, now_str, task_id),
                )
            else:
                conn.execute(
                    f"""
                    UPDATE {self.table_name}
                    SET current_step = ?, updated_at = ?
                    WHERE {self.id_column} = ?
                    """,
                    (current_step, now_str, task_id),
                )
            conn.commit()

    def _mark_failed_with_step(self, task_id: str, error_msg: str, step_label: str) -> None:
        now_str = self._now_str()
        with closing(self._connect()) as conn:
            conn.execute(
                f"""
                UPDATE {self.table_name}
                SET status = 'failed', current_step = ?, error_msg = ?, updated_at = ?
                WHERE {self.id_column} = ?
                """,
                (step_label, error_msg, now_str, task_id),
            )
            conn.commit()

    def _mark_cancelled_with_step(self, task_id: str, step_label: str = "已取消") -> None:
        now_str = self._now_str()
        with closing(self._connect()) as conn:
            conn.execute(
                f"""
                UPDATE {self.table_name}
                SET status = 'cancelled', current_step = ?, updated_at = ?
                WHERE {self.id_column} = ?
                """,
                (step_label, now_str, task_id),
            )
            conn.commit()

    def _reset_interrupted_with_statuses(
        self,
        *,
        statuses: Iterable[str],
        step_label: str,
        exclude_task_ids: Optional[List[str]] = None,
    ) -> int:
        now_str = self._now_str()
        status_list = [s for s in statuses if s]
        status_placeholders = ",".join("?" for _ in status_list)
        exclude = [tid for tid in (exclude_task_ids or []) if tid]
        with closing(self._connect()) as conn:
            if exclude:
                ex_placeholders = ",".join("?" for _ in exclude)
                cur = conn.execute(
                    f"""
                    UPDATE {self.table_name}
                    SET status = 'cancelled', current_step = ?, updated_at = ?
                    WHERE status IN ({status_placeholders})
                      AND {self.id_column} NOT IN ({ex_placeholders})
                    """,
                    [step_label, now_str, *status_list, *exclude],
                )
            else:
                cur = conn.execute(
                    f"""
                    UPDATE {self.table_name}
                    SET status = 'cancelled', current_step = ?, updated_at = ?
                    WHERE status IN ({status_placeholders})
                    """,
                    [step_label, now_str, *status_list],
                )
            conn.commit()
            return int(cur.rowcount or 0)

    def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        with closing(self._connect()) as conn:
            row = conn.execute(
                f"SELECT * FROM {self.table_name} WHERE {self.id_column} = ?",
                (task_id,),
            ).fetchone()
            return self._deserialize_row(row) if row else None

    def delete_task(self, task_id: str) -> bool:
        with closing(self._connect()) as conn:
            conn.execute(
                f"DELETE FROM {self.table_name} WHERE {self.id_column} = ?",
                (task_id,),
            )
            conn.commit()
        return True
