import sqlite3
import json
import logging
import os
from pathlib import Path
from datetime import datetime

class StrainDBManager:
    def __init__(self, db_path="database/strain.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.logger = logging.getLogger(__name__)
        self._init_db()

    def _init_db(self):
        """初始化数据库表结构"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # 1. 冰箱表 - 存储冰箱的基本信息和层级结构
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS freezers (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    model TEXT,
                    location TEXT,
                    structure TEXT, -- 存储 shelves/cabinets/boxes 的 JSON 结构
                    created_at TEXT,
                    updated_at TEXT
                )
            ''')
            
            # 2. 样本记录表 - 存储具体的生物样本数据
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS records (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    accession TEXT,
                    species TEXT,
                    strain TEXT,
                    sample_type TEXT,
                    sequence_type TEXT,
                    source TEXT,
                    host TEXT,
                    collection_date TEXT,
                    freezer_id TEXT,
                    shelf_id TEXT,
                    cabinet_id TEXT,
                    drawer_id TEXT,
                    box_id TEXT,
                    position TEXT,
                    metadata TEXT, -- 存储特定品类的元数据 JSON
                    added_at TEXT,
                    FOREIGN KEY (freezer_id) REFERENCES freezers (id)
                )
            ''')
            # 3. 系统配置表 - 存储编码字典等全局设置
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS sys_config (
                    key TEXT PRIMARY KEY,
                    value TEXT,
                    updated_at TEXT
                )
            ''')
            
            conn.commit()
            conn.close()
            self.logger.info(f"Strain database initialized at {self.db_path}")
        except Exception as e:
            self.logger.error(f"Failed to initialize strain database: {e}")

    def save_freezer(self, freezer_data):
        """保存或更新冰箱"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            fid = freezer_data.get('id')
            name = freezer_data.get('name')
            model = freezer_data.get('model')
            location = freezer_data.get('location')
            # 这里的 shelves 包含嵌套结构，存为 JSON
            structure = json.dumps(freezer_data.get('shelves', []))
            now = datetime.now().isoformat()
            
            cursor.execute('''
                INSERT OR REPLACE INTO freezers (id, name, model, location, structure, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, COALESCE((SELECT created_at FROM freezers WHERE id=?), ?), ?)
            ''', (fid, name, model, location, structure, fid, now, now))
            
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            self.logger.error(f"Error saving freezer: {e}")
            return False

    def delete_freezer(self, freezer_id):
        """删除冰箱及其关联记录"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('DELETE FROM records WHERE freezer_id = ?', (freezer_id,))
            cursor.execute('DELETE FROM freezers WHERE id = ?', (freezer_id,))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            self.logger.error(f"Error deleting freezer: {e}")
            return False

    def save_record(self, record_data):
        """保存或更新样本记录"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            rid = record_data.get('id')
            metadata = json.dumps(record_data.get('metadata', {}))
            now = datetime.now().isoformat()
            
            fields = [
                'id', 'name', 'accession', 'species', 'strain', 'sampleType', 
                'sequenceType', 'source', 'host', 'collectionDate', 
                'freezerId', 'shelfId', 'cabinetId', 'drawerId', 'boxId', 'position'
            ]
            
            values = [record_data.get(f) for f in fields]
            values.append(metadata)
            values.append(record_data.get('addedAt') or now)
            
            cursor.execute(f'''
                INSERT OR REPLACE INTO records (
                    id, name, accession, species, strain, sample_type, 
                    sequence_type, source, host, collection_date, 
                    freezer_id, shelf_id, cabinet_id, drawer_id, box_id, position,
                    metadata, added_at
                )
                VALUES ({",".join(["?"] * 18)})
            ''', tuple(values))
            
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            self.logger.error(f"Error saving record: {e}")
            return False

    def delete_record(self, record_id):
        """删除样本记录"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('DELETE FROM records WHERE id = ?', (record_id,))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            self.logger.error(f"Error deleting record: {e}")
            return False

    def save_sys_config(self, key, value_data):
        """保存系统全局配置项"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            now = datetime.now().isoformat()
            cursor.execute('''
                INSERT OR REPLACE INTO sys_config (key, value, updated_at)
                VALUES (?, ?, ?)
            ''', (key, json.dumps(value_data), now))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            self.logger.error(f"Error saving sys config {key}: {e}")
            return False

    def load_all_data(self):
        """加载所有冰箱和记录数据"""
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            # 加载冰箱
            cursor.execute('SELECT * FROM freezers')
            freezers = []
            for row in cursor.fetchall():
                freezers.append({
                    'id': row['id'],
                    'name': row['name'],
                    'model': row['model'],
                    'location': row['location'],
                    'shelves': json.loads(row['structure']),
                    'createdAt': row['created_at'],
                    'updatedAt': row['updated_at']
                })
            
            # 加载记录
            cursor.execute('SELECT * FROM records')
            records = []
            for row in cursor.fetchall():
                records.append({
                    'id': row['id'],
                    'name': row['name'],
                    'accession': row['accession'],
                    'species': row['species'],
                    'strain': row['strain'],
                    'sampleType': row['sample_type'],
                    'sequenceType': row['sequence_type'],
                    'source': row['source'],
                    'host': row['host'],
                    'collectionDate': row['collection_date'],
                    'freezerId': row['freezer_id'],
                    'shelfId': row['shelf_id'],
                    'cabinetId': row['cabinet_id'],
                    'drawerId': row['drawer_id'],
                    'boxId': row['box_id'],
                    'position': row['position'],
                    'metadata': json.loads(row['metadata'] or '{}'),
                    'addedAt': row['added_at']
                })
            # 加载系统配置
            cursor.execute('SELECT * FROM sys_config WHERE key = "codeLookup"')
            row = cursor.fetchone()
            code_lookup = json.loads(row['value']) if row and row['value'] else None

            conn.close()
            return {'freezers': freezers, 'records': records, 'codeLookup': code_lookup}
        except Exception as e:
            self.logger.error(f"Error loading data: {e}")
            return {'freezers': [], 'records': []}

    def clear_all(self):
        """清除所有数据"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('DELETE FROM records')
            cursor.execute('DELETE FROM freezers')
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            self.logger.error(f"Error clearing data: {e}")
            return False

_strain_db_manager = None

def get_strain_db_manager():
    global _strain_db_manager
    if _strain_db_manager is None:
        _strain_db_manager = StrainDBManager()
    return _strain_db_manager
