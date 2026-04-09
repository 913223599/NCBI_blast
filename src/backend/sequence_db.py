import json
import logging
import sqlite3
from datetime import datetime
from pathlib import Path


class SequenceDBManager:
    def __init__(self, db_path="database/sequences.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.logger = logging.getLogger(__name__)
        self._init_db()

    def _init_db(self):
        """初始化基因序列数据库"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # 序列信息表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS sequences (
                    id TEXT PRIMARY KEY,
                    sample_id TEXT,       -- 关联的样本库 ID
                    sample_code TEXT,     -- 冗余存储 14 位编号，方便跨库检索
                    seq_type TEXT,        -- 16S, WGS, ITS, etc.
                    title TEXT,           -- 序列名称/标题
                    sequence TEXT,        -- FASTA 内容
                    seq_len INTEGER,      -- 序列长度
                    metadata TEXT,        -- 测序引物、测序公司、质量评估等
                    added_at TEXT
                )
            ''')
            
            # 索引优化，方便通过样本 ID 快速查询
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_sample_id ON sequences(sample_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_sample_code ON sequences(sample_code)')
            
            conn.commit()
            conn.close()
            self.logger.info(f"Sequence database initialized at {self.db_path}")
        except Exception as e:
            self.logger.error(f"Failed to initialize sequence database: {e}")

    def save_sequence(self, seq_data):
        """保存或更新序列"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            sid = seq_data.get('id')
            metadata = json.dumps(seq_data.get('metadata', {}))
            now = datetime.now().isoformat()
            
            fields = [
                'id', 'sample_id', 'sample_code', 'seq_type', 
                'title', 'sequence', 'seq_len'
            ]
            
            col_names = fields + ['metadata', 'added_at']
            values = [seq_data.get(f) for f in fields]
            values.append(metadata)
            values.append(seq_data.get('addedAt') or now)
            
            cols_str = ", ".join(col_names)
            placeholders = ", ".join(["?"] * len(col_names))
            
            cursor.execute(f'''
                INSERT OR REPLACE INTO sequences ({cols_str})
                VALUES ({placeholders})
            ''', tuple(values))
            
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            self.logger.error(f"Error saving sequence: {e}")
            return False

    def load_sequences_by_sample(self, sample_id):
        """查询特定样本关联的所有序列"""
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM sequences WHERE sample_id = ?', (sample_id,))
            
            results = []
            for row in cursor.fetchall():
                results.append(self._row_to_dict(row))
            conn.close()
            return results
        except Exception as e:
            self.logger.error(f"Error loading sequences for sample {sample_id}: {e}")
            return []

    def search_sequences(self, keyword):
        """跨库检索：通过关键字（编号、类型、标题）搜索序列"""
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            query = f"%{keyword}%"
            cursor.execute('''
                SELECT * FROM sequences 
                WHERE sample_code LIKE ? OR title LIKE ? OR seq_type LIKE ?
            ''', (query, query, query))
            
            results = []
            for row in cursor.fetchall():
                results.append(self._row_to_dict(row))
            conn.close()
            return results
        except Exception as e:
            self.logger.error(f"Error searching sequences: {e}")
            return []

    def delete_sequence(self, seq_id):
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('DELETE FROM sequences WHERE id = ?', (seq_id,))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            self.logger.error(f"Error deleting sequence: {e}")
            return False

    def _row_to_dict(self, row):
        return {
            'id': row['id'],
            'sampleId': row['sample_id'],
            'sampleCode': row['sample_code'],
            'seqType': row['seq_type'],
            'title': row['title'],
            'sequence': row['sequence'],
            'seqLen': row['seq_len'],
            'metadata': json.loads(row['metadata'] or '{}'),
            'addedAt': row['added_at']
        }

_sequence_db_manager = None

def get_sequence_db_manager():
    global _sequence_db_manager
    if _sequence_db_manager is None:
        _sequence_db_manager = SequenceDBManager()
    return _sequence_db_manager
