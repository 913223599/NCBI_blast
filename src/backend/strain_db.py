import sqlite3
import json
import logging
from pathlib import Path
from datetime import datetime

class StrainDBManager:
    def __init__(self, db_path="database/strain.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.logger = logging.getLogger(__name__)
        self._init_db()

    def _init_db(self):
        """初始化数据库表结构及版本迁移"""
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

            # 3. 动态升级：向 records 表追加缺失的字段 (P1 改动同步)
            # 通过 pragma table_info 检查列是否存在
            cursor.execute("PRAGMA table_info(records)")
            columns = [col[1] for col in cursor.fetchall()]
            
            new_columns = [
                ('sample_code', 'TEXT'),
                ('code_source', 'TEXT'),
                ('code_category', 'TEXT'),
                ('code_genus', 'TEXT'),
                ('code_species', 'TEXT'),
                ('code_passage', 'INTEGER'),
                ('code_serial', 'INTEGER'),
                ('sequence', 'TEXT'),
                ('country', 'TEXT')
            ]
            
            for col_name, col_type in new_columns:
                if col_name not in columns:
                    self.logger.info(f"Database Migration: Adding column {col_name} to records table")
                    cursor.execute(f"ALTER TABLE records ADD COLUMN {col_name} {col_type}")

            # 4. 系统配置表 - 存储编码字典等全局设置
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
        """保存或更新样本记录 (适应 14 位编号系统)"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            rid = record_data.get('id')
            metadata = json.dumps(record_data.get('metadata', {}))
            now = datetime.now().isoformat()
            
            # 映射前端驼峰到后端下划线字段
            fields_mapping = [
                ('id', 'id'),
                ('name', 'name'),
                ('accession', 'accession'),
                ('species', 'species'),
                ('strain', 'strain'),
                ('sample_type', 'sampleType'),
                ('sequence_type', 'sequenceType'),
                ('source', 'source'),
                ('host', 'host'),
                ('collection_date', 'collectionDate'),
                ('freezer_id', 'freezerId'),
                ('shelf_id', 'shelfId'),
                ('cabinet_id', 'cabinetId'),
                ('drawer_id', 'drawerId'),
                ('box_id', 'boxId'),
                ('position', 'position'),
                ('sample_code', 'sampleCode'),
                ('code_source', 'codeSource'),
                ('code_category', 'codeCategory'),
                ('code_genus', 'codeGenus'),
                ('code_species', 'codeSpecies'),
                ('code_passage', 'codePassage'),
                ('code_serial', 'codeSerial'),
                ('sequence', 'sequence'),
                ('country', 'country')
            ]
            
            col_names = [m[0] for m in fields_mapping] + ['metadata', 'added_at']
            values = [record_data.get(m[1]) for m in fields_mapping]
            values.append(metadata)
            values.append(record_data.get('addedAt') or now)
            
            cols_str = ", ".join(col_names)
            placeholders = ", ".join(["?"] * len(col_names))
            
            cursor.execute(f'''
                INSERT OR REPLACE INTO records ({cols_str})
                VALUES ({placeholders})
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
                    'shelves': json.loads(row['structure'] or '[]'),
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
                    'sampleCode': row['sample_code'],
                    'codeSource': row['code_source'],
                    'codeCategory': row['code_category'],
                    'codeGenus': row['code_genus'],
                    'codeSpecies': row['code_species'],
                    'codePassage': row['code_passage'],
                    'codeSerial': row['code_serial'],
                    'sequence': row['sequence'],
                    'country': row['country'],
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
