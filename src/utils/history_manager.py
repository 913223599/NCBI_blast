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
            
            # 创建 tasks 表
            # [修改] 移除 id 列，使用 task_name 作为主键（或唯一索引），添加详细统计字段
            
            # 检查表是否存在
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='tasks'")
            if not cursor.fetchone():
                cursor.execute('''
                    CREATE TABLE tasks (
                        task_name TEXT PRIMARY KEY,
                        timestamp TEXT,
                        parameters TEXT,
                        status TEXT,
                        total_sequences INTEGER DEFAULT 0,
                        completed_sequences INTEGER DEFAULT 0,
                        failed_sequences INTEGER DEFAULT 0,
                        result_dir TEXT
                    )
                ''')
            else:
                # 尝试添加新列（如果不存在）
                try:
                    cursor.execute("ALTER TABLE tasks ADD COLUMN total_sequences INTEGER DEFAULT 0")
                except sqlite3.OperationalError: pass
                try:
                    cursor.execute("ALTER TABLE tasks ADD COLUMN completed_sequences INTEGER DEFAULT 0")
                except sqlite3.OperationalError: pass
                try:
                    cursor.execute("ALTER TABLE tasks ADD COLUMN failed_sequences INTEGER DEFAULT 0")
                except sqlite3.OperationalError: pass
            
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"初始化历史数据库失败: {e}")

    # --- 任务级操作 ---

    def add_or_update_task(self, task_name, parameters=None, result_dir=None, 
                          total=0, completed=0, failed=0, status="running"):
        """添加或更新任务记录"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # 检查任务是否存在
            cursor.execute("SELECT * FROM tasks WHERE task_name = ?", (task_name,))
            existing = cursor.fetchone()
            
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            if existing:
                # 更新现有任务
                update_fields = []
                params = []
                
                if parameters is not None:
                    params_json = json.dumps(parameters) if isinstance(parameters, dict) else parameters
                    update_fields.append("parameters = ?")
                    params.append(params_json)
                
                if result_dir is not None:
                    update_fields.append("result_dir = ?")
                    params.append(str(result_dir))
                    
                if status is not None:
                    update_fields.append("status = ?")
                    params.append(status)
                    
                # 只有当数值大于0或者显式更新时才更新统计数据
                # 这里我们假设调用者会传递最新的累积值
                if total > 0:
                    update_fields.append("total_sequences = ?")
                    params.append(total)
                
                # completed 和 failed 可能是 0，但也需要更新
                if completed >= 0:
                    update_fields.append("completed_sequences = ?")
                    params.append(completed)
                    
                if failed >= 0:
                    update_fields.append("failed_sequences = ?")
                    params.append(failed)
                
                # 总是更新时间戳
                update_fields.append("timestamp = ?")
                params.append(timestamp)
                
                params.append(task_name)
                
                sql = f"UPDATE tasks SET {', '.join(update_fields)} WHERE task_name = ?"
                cursor.execute(sql, params)
                
            else:
                # 插入新任务
                params_json = json.dumps(parameters) if isinstance(parameters, dict) else parameters
                cursor.execute('''
                    INSERT INTO tasks (task_name, timestamp, parameters, status, 
                                     total_sequences, completed_sequences, failed_sequences, result_dir)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ''', (task_name, timestamp, params_json, status, total, completed, failed, str(result_dir)))
            
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"保存任务记录失败: {e}")
            return False

    # 兼容旧接口
    def add_task(self, task_name, parameters, result_dir, file_count=0, status="completed"):
        return self.add_or_update_task(task_name, parameters, result_dir, total=file_count, status=status)

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

    def delete_task(self, task_name):
        """删除任务记录"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            # 支持通过 task_name 删除
            cursor.execute('DELETE FROM tasks WHERE task_name = ?', (task_name,))
            # 兼容旧的 id 删除 (如果传入的是 int)
            if isinstance(task_name, int):
                 cursor.execute('DELETE FROM tasks WHERE rowid = ?', (task_name,))
                 
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"删除任务失败: {e}")
            return False

    # --- 旧接口保留 (可选) ---
    def add_record(self, query_file, database, program, parameters, result_file, status="success"):
        pass

    def get_all_records(self):
        return []
            
    def delete_record(self, record_id):
        return False
            
    def clear_history(self):
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('DELETE FROM tasks')
            conn.commit()
            conn.close()
            return True
        except Exception:
            return False
