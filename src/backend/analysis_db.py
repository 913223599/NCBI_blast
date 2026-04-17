import sqlite3
import json
import os
from datetime import datetime

class AnalysisDB:
    def __init__(self, db_path="database/analysis.db"):
        self.db_path = db_path
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS analysis_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT,
                    mode TEXT,
                    query_name TEXT,
                    target_name TEXT,
                    identity REAL,
                    variant_count INTEGER,
                    rotated BOOLEAN,
                    results_json TEXT
                )
            ''')
            conn.commit()

    def save_record(self, mode, result):
        """保存单次比对结果"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('''
                INSERT INTO analysis_history 
                (timestamp, mode, query_name, target_name, identity, variant_count, rotated, results_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                mode,
                result.get("query_name", "Unknown"),
                result.get("target_name", "Unknown"),
                result.get("identity", 0),
                result.get("variant_count", 0),
                result.get("rotated", False),
                json.dumps(result)
            ))
            conn.commit()

    def get_history(self, limit=50):
        """获取最近的比对历史列表（不含大体积 JSON）"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute('''
                SELECT id, timestamp, mode, query_name, target_name, identity, variant_count, rotated 
                FROM analysis_history 
                ORDER BY id DESC LIMIT ?
            ''', (limit,))
            return [dict(row) for row in cursor.fetchall()]

    def get_detail(self, record_id):
        """获取某次比对的完整详细 JSON"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute('SELECT results_json FROM analysis_history WHERE id = ?', (record_id,))
            row = cursor.fetchone()
            return json.loads(row[0]) if row else None

    def delete_record(self, record_id):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('DELETE FROM analysis_history WHERE id = ?', (record_id,))
            conn.commit()

# 全局单例
db = AnalysisDB()
