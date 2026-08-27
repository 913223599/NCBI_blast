# -*- coding: utf-8 -*-
"""
功能注释任务 SQLite 数据库持久化层
"""
import sqlite3
import json
import os
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional


class AnnotationDB:
    def __init__(self, db_path: str = "database/annotation.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('''
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
            ''')
            # 兼容：为已存在的旧表增量增加列
            try:
                conn.execute('ALTER TABLE annotation_tasks ADD COLUMN safety_audit_json TEXT')
            except Exception:
                pass
            try:
                conn.execute('ALTER TABLE annotation_tasks ADD COLUMN checkv_json TEXT')
            except Exception:
                pass

            conn.execute('CREATE INDEX IF NOT EXISTS idx_anno_status ON annotation_tasks(status)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_anno_created ON annotation_tasks(created_at)')
            conn.commit()

    def create_task(self, task_id: str, task_name: str, sample_type: str, engine: str, status: str = "queued") -> bool:
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('''
                INSERT INTO annotation_tasks 
                (task_id, task_name, sample_type, engine, status, progress, current_step, created_at, updated_at, summary_json, files_json, safety_audit_json, checkv_json)
                VALUES (?, ?, ?, ?, ?, 0, '已加入排队队列...', ?, ?, '{}', '{}', '{}', '{}')
            ''', (task_id, task_name, sample_type, engine, status, now_str, now_str))
            conn.commit()
        return True

    def update_progress(self, task_id: str, progress: int, current_step: str, status: str = "running"):
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('''
                UPDATE annotation_tasks 
                SET progress = ?, current_step = ?, 
                    status = CASE WHEN status IN ('completed', 'failed', 'cancelled') THEN status ELSE ? END, 
                    updated_at = ?
                WHERE task_id = ?
            ''', (progress, current_step, status, now_str, task_id))
            conn.commit()

    def mark_completed(self, task_id: str, summary: Dict[str, Any], files: Dict[str, str], 
                       safety_audit: Optional[Dict[str, Any]] = None, checkv: Optional[Dict[str, Any]] = None):
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('''
                UPDATE annotation_tasks 
                SET status = 'completed', progress = 100, current_step = '注释已完成', 
                    summary_json = ?, files_json = ?, safety_audit_json = ?, checkv_json = ?, updated_at = ?
                WHERE task_id = ?
            ''', (
                json.dumps(summary, ensure_ascii=False), 
                json.dumps(files, ensure_ascii=False),
                json.dumps(safety_audit or {}, ensure_ascii=False),
                json.dumps(checkv or {}, ensure_ascii=False),
                now_str, 
                task_id
            ))
            conn.commit()

    def mark_failed(self, task_id: str, error_msg: str):
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('''
                UPDATE annotation_tasks 
                SET status = 'failed', current_step = '分析失败', error_msg = ?, updated_at = ?
                WHERE task_id = ?
            ''', (error_msg, now_str, task_id))
            conn.commit()

    def mark_cancelled(self, task_id: str):
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('''
                UPDATE annotation_tasks 
                SET status = 'cancelled', current_step = '已取消', updated_at = ?
                WHERE task_id = ?
            ''', (now_str, task_id))
            conn.commit()

    def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute('SELECT * FROM annotation_tasks WHERE task_id = ?', (task_id,))
            row = cursor.fetchone()
            if not row:
                return None
            data = dict(row)
            data["summary"] = json.loads(data.get("summary_json") or "{}")
            data["files"] = json.loads(data.get("files_json") or "{}")
            data["safety_audit"] = json.loads(data.get("safety_audit_json") or "{}")
            data["checkv"] = json.loads(data.get("checkv_json") or "{}")
            return data

    def list_tasks(self, limit: int = 50) -> List[Dict[str, Any]]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute('''
                SELECT task_id, task_name, sample_type, engine, status, progress, current_step, error_msg, created_at, updated_at, summary_json, files_json, safety_audit_json, checkv_json
                FROM annotation_tasks 
                ORDER BY created_at DESC LIMIT ?
            ''', (limit,))
            results = []
            for row in cursor.fetchall():
                data = dict(row)
                data["summary"] = json.loads(data.get("summary_json") or "{}")
                data["files"] = json.loads(data.get("files_json") or "{}")
                data["safety_audit"] = json.loads(data.get("safety_audit_json") or "{}")
                data["checkv"] = json.loads(data.get("checkv_json") or "{}")
                results.append(data)
            return results

    def get_incomplete_tasks(self) -> List[Dict[str, Any]]:
        """获取所有未完成的任务（用于队列快照与自愈恢复）"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute('''
                SELECT task_id, task_name, sample_type, engine, status, progress, current_step, created_at, updated_at
                FROM annotation_tasks 
                WHERE status IN ('running', 'queued', 'pending')
                ORDER BY created_at ASC
            ''')
            return [dict(r) for r in cursor.fetchall()]

    def reset_interrupted_tasks(self, exclude_task_ids: Optional[List[str]] = None):
        """服务重启安全自愈：将此前处于 running 状态的遗留任务标记为 cancelled（排除当前正在运行的任务）"""
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        exclude = [tid for tid in (exclude_task_ids or []) if tid]
        with sqlite3.connect(self.db_path) as conn:
            if exclude:
                placeholders = ','.join('?' for _ in exclude)
                conn.execute(f'''
                    UPDATE annotation_tasks 
                    SET status = 'cancelled', current_step = '服务重启导致中断，已重置', updated_at = ?
                    WHERE status = 'running' AND task_id NOT IN ({placeholders})
                ''', [now_str] + exclude)
            else:
                conn.execute('''
                    UPDATE annotation_tasks 
                    SET status = 'cancelled', current_step = '服务重启导致中断，已重置', updated_at = ?
                    WHERE status = 'running'
                ''', (now_str,))
            conn.commit()

    def delete_task(self, task_id: str) -> bool:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('DELETE FROM annotation_tasks WHERE task_id = ?', (task_id,))
            conn.commit()
        return True


# 全局单例
annotation_db = AnnotationDB()
