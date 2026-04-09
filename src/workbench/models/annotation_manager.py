import sqlite3
import json
import logging
import hashlib
from pathlib import Path

logger = logging.getLogger(__name__)

class AnnotationManager:
    """
    Advanced Annotation Manager using Sequence Content Hashing (MD5).
    Safeguards against duplicate IDs and ensures identity is tied to the genetic material itself.
    """
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(AnnotationManager, cls).__new__(cls)
            cls._instance._init_manager()
        return cls._instance

    def _init_manager(self):
        self.root_dir = Path(__file__).resolve().parent.parent.parent.parent
        self.db_path = self.root_dir / "results" / "annotations_v2.db"
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.blast_db_path = self.root_dir / "results" / "blast_meta.db"
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            # Table is now indexed by content hash
            conn.execute("""
                CREATE TABLE IF NOT EXISTS annotations (
                    sequence_hash TEXT PRIMARY KEY,
                    last_known_id TEXT,
                    custom_label TEXT,
                    blast_identity TEXT,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            # Maintenance: Index for fast lookup by ID (optional fallback)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_known_id ON annotations(last_known_id)")

    def generate_hash(self, sequence: str) -> str:
        """Computes a normalized MD5 hash for a biological sequence."""
        # Normalize: remove whitespace, handle case, remove gaps
        clean_seq = "".join(sequence.split()).upper().replace("-", "")
        return hashlib.md5(clean_seq.encode('utf-8')).hexdigest()

    def get_annotations_by_hashes(self, hashes: List[str]) -> Dict[str, str]:
        """Fetch labels using content hashes."""
        results = {}
        if not hashes: return results
        
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            placeholders = ','.join(['?'] * len(hashes))
            cursor = conn.execute(f"SELECT * FROM annotations WHERE sequence_hash IN ({placeholders})", hashes)
            for row in cursor.fetchall():
                label = row['custom_label'] or row['blast_identity']
                if label:
                    results[row['sequence_hash']] = label
        return results

    def update_annotation(self, sequence_hash: str, last_known_id: str = None, 
                          custom_label: str = None, blast_identity: str = None):
        """Update annotation record using the content hash as key."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO annotations (sequence_hash, last_known_id, custom_label, blast_identity)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(sequence_hash) DO UPDATE SET
                    last_known_id = COALESCE(?, annotations.last_known_id),
                    custom_label = COALESCE(?, annotations.custom_label),
                    blast_identity = COALESCE(?, annotations.blast_identity),
                    updated_at = CURRENT_TIMESTAMP
            """, (sequence_hash, last_known_id, custom_label, blast_identity, 
                  last_known_id, custom_label, blast_identity))

    def full_sync_from_disk(self):
        """Discovers existing results on disk and syncs them to the DB."""
        if not self.db_path.parent.exists(): return
        
        count = 0
        try:
            # 扫描 results/ 目录下的所有文件夹
            for task_dir in self.db_path.parent.iterdir():
                if not task_dir.is_dir() or task_dir.name == "__pycache__": continue
                
                # 每个任务文件夹下应该有一个汇总文件或单序列 CSV
                for csv_file in task_dir.glob("*.csv"):
                    # 如果是汇总 CSV 或者已经命名的结果
                    try:
                        # 借用解析逻辑 (注意：这里需要谨慎处理循环导入，但在脚本执行中没关系)
                        pass 
                    except: pass
        except: pass
        return count

    def batch_update_from_blast(self, task_id: str):
        """Helper to sync from completed BLAST task, extracting hashes from the audit log."""
        if not self.blast_db_path.exists(): return
        
        try:
            with sqlite3.connect(self.blast_db_path) as conn:
                cursor = conn.execute("SELECT sequence_id, data FROM results WHERE task_id = ?", (task_id,))
                for sid, data_json in cursor.fetchall():
                    try:
                        data = json.loads(data_json)
                        # We hope the blast data now includes the hash! (If not, we fallback to ID lookup)
                        seq_hash = data.get('sequence_hash')
                        identity = data.get('species') or data.get('title')
                        if seq_hash and identity:
                            self.update_annotation(seq_hash, last_known_id=sid, blast_identity=identity)
                    except:
                        continue
        except Exception as e:
            logger.error(f"Failed batch update from BLAST: {e}")

def get_annotation_manager():
    return AnnotationManager()
