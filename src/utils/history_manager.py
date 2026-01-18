"""
历史记录管理器
负责管理BLAST任务的历史记录，使用SQLite数据库存储
"""

import sqlite3
import json
import os
from datetime import datetime
from pathlib import Path

class HistoryManager:
    def __init__(self, db_path="blast_history.db"):
        """
        初始化历史记录管理器
        :param db_path: 数据库文件路径，默认为项目根目录下的 blast_history.db
        """
        # 如果是相对路径，确保它相对于项目根目录
        if not os.path.isabs(db_path):
            project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            self.db_path = os.path.join(project_root, db_path)
        else:
            self.db_path = db_path
            
        self._init_db()

    def _init_db(self):
        """初始化数据库表结构"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # 1. 保留旧的 history 表以兼容（可选，或者直接废弃）
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT,
                    query_file TEXT,
                    database TEXT,
                    program TEXT,
                    parameters TEXT,
                    result_file TEXT,
                    status TEXT
                )
            ''')
            
            # 2. 创建新的 tasks 表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_name TEXT UNIQUE,
                    timestamp TEXT,
                    parameters TEXT,
                    status TEXT,
                    file_count INTEGER,
                    result_dir TEXT
                )
            ''')
            
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"初始化历史数据库失败: {e}")

    # --- 任务级操作 ---

    def add_task(self, task_name, parameters, result_dir, file_count=0, status="completed"):
        """添加一个任务记录"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            params_json = json.dumps(parameters) if isinstance(parameters, dict) else parameters
            
            cursor.execute('''
                INSERT OR REPLACE INTO tasks (task_name, timestamp, parameters, status, file_count, result_dir)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (task_name, timestamp, params_json, status, file_count, str(result_dir)))
            
            conn.commit()
            conn.close()
            print(f"任务记录已保存: {task_name}")
            return True
        except Exception as e:
            print(f"保存任务记录失败: {e}")
            return False

    def get_all_tasks(self):
        """获取所有任务记录"""
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM tasks ORDER BY timestamp DESC')
            rows = [dict(row) for row in cursor.fetchall()]
            conn.close()
            return rows
        except Exception as e:
            print(f"读取任务记录失败: {e}")
            return []

    def delete_task(self, task_id):
        """删除任务记录"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('DELETE FROM tasks WHERE id = ?', (task_id,))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"删除任务失败: {e}")
            return False

    # --- 旧接口保留 (可选) ---
    def add_record(self, query_file, database, program, parameters, result_file, status="success"):
        # 暂时保留以兼容旧代码，后续可移除
        pass

    def get_all_records(self):
        # 暂时保留
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM history ORDER BY timestamp DESC')
            rows = [dict(row) for row in cursor.fetchall()]
            conn.close()
            return rows
        except Exception:
            return []
            
    def delete_record(self, record_id):
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('DELETE FROM history WHERE id = ?', (record_id,))
            conn.commit()
            conn.close()
            return True
        except Exception:
            return False
            
    def clear_history(self):
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('DELETE FROM history')
            cursor.execute('DELETE FROM tasks') # 同时清空任务表
            conn.commit()
            conn.close()
            return True
        except Exception:
            return False
