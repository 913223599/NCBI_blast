import json
import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any


class StrainDBManager:
    def __init__(self, db_path="database/strain.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.logger = logging.getLogger(__name__)
        # 性能优化:使用连接池避免频繁打开关闭数据库
        self._conn_cache = None
        self._init_db()

    def _get_connection(self):
        """获取数据库连接(带缓存)"""
        if self._conn_cache is None:
            self._conn_cache = sqlite3.connect(self.db_path)
            self._conn_cache.row_factory = sqlite3.Row
            # 开启高并发读写模式
            self._conn_cache.execute('PRAGMA journal_mode=WAL')
            self._conn_cache.execute('PRAGMA synchronous=NORMAL')
        return self._conn_cache
    
    def _close_connection(self):
        """关闭数据库连接"""
        if self._conn_cache:
            try:
                self._conn_cache.close()
            except:
                pass
            finally:
                self._conn_cache = None

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

            # 4. 进化树历史记录表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS tree_history (
                    id TEXT PRIMARY KEY,
                    source_file TEXT,
                    name TEXT,
                    items_json TEXT, -- 存储 items 数组的 JSON
                    updated_at TEXT
                )
            ''')

            # 5. 系统配置表 - 存储编码字典等全局设置
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
            conn = self._get_connection()
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
            return True
        except Exception as e:
            self.logger.error(f"Error saving freezer: {e}")
            return False

    def delete_freezer(self, freezer_id):
        """删除冰箱及其关联记录"""
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute('DELETE FROM records WHERE freezer_id = ?', (freezer_id,))
            cursor.execute('DELETE FROM freezers WHERE id = ?', (freezer_id,))
            conn.commit()
            return True
        except Exception as e:
            self.logger.error(f"Error deleting freezer: {e}")
            return False

    def save_record(self, record_data):
        """保存或更新样本记录 (适应 14 位编号系统)"""
        return self.save_records_batch([record_data])

    def save_records_batch(self, records_list):
        """批量保存样本记录 (单一事务提高性能)"""
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            now = datetime.now().isoformat()
            
            # 使用与 save_record 相同的字段映射逻辑
            fields_mapping = [
                ('id', 'id'), ('name', 'name'), ('accession', 'accession'),
                ('species', 'species'), ('strain', 'strain'), ('sample_type', 'sampleType'),
                ('sequence_type', 'sequenceType'), ('source', 'source'), ('host', 'host'),
                ('collection_date', 'collectionDate'), ('freezer_id', 'freezerId'),
                ('shelf_id', 'shelfId'), ('cabinet_id', 'cabinetId'), ('drawer_id', 'drawerId'),
                ('box_id', 'boxId'), ('position', 'position'), ('sample_code', 'sampleCode'),
                ('code_source', 'codeSource'), ('code_category', 'codeCategory'),
                ('code_genus', 'codeGenus'), ('code_species', 'codeSpecies'),
                ('code_passage', 'codePassage'), ('code_serial', 'codeSerial'),
                ('sequence', 'sequence'), ('country', 'country')
            ]
            col_names = [m[0] for m in fields_mapping] + ['metadata', 'added_at']
            cols_str = ", ".join(col_names)
            placeholders = ", ".join(["?"] * len(col_names))
            
            data_to_insert = []
            for record_data in records_list:
                metadata = json.dumps(record_data.get('metadata', {}))
                values = [record_data.get(m[1]) for m in fields_mapping]
                values.append(metadata)
                values.append(record_data.get('addedAt') or now)
                data_to_insert.append(tuple(values))

            cursor.executemany(f'''
                INSERT OR REPLACE INTO records ({cols_str})
                VALUES ({placeholders})
            ''', data_to_insert)
            
            conn.commit()
            return True
        except Exception as e:
            self.logger.error(f"Error saving batch records: {e}")
            self._close_connection()  # 异常时关闭连接
            return False

    def delete_record(self, record_id):
        """删除单个样本记录"""
        return self.delete_records_batch([record_id])

    def delete_records_batch(self, record_ids: List[str]):
        """批量删除样本记录"""
        if not record_ids:
            return True
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            # 规避 SQLite 默认变量绑定数量上限限制
            data_to_delete = [(rid,) for rid in record_ids]
            cursor.executemany('DELETE FROM records WHERE id = ?', data_to_delete)
            conn.commit()
            return True
        except Exception as e:
            self.logger.error(f"Error deleting batch records: {e}")
            self._close_connection()
            return False

    def save_sys_config(self, key, value_data):
        """保存系统全局配置项"""
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            now = datetime.now().isoformat()
            cursor.execute('''
                INSERT OR REPLACE INTO sys_config (key, value, updated_at)
                VALUES (?, ?, ?)
            ''', (key, json.dumps(value_data), now))
            conn.commit()
            return True
        except Exception as e:
            self.logger.error(f"Error saving sys config {key}: {e}")
            return False

    def load_all_data(self):
        """加载所有冰箱和记录数据"""
        try:
            conn = self._get_connection()
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
            
            # 加载记录 (核心优化：列表不加载庞大的 sequence 字段，防止内存溢出)
            cursor.execute('''
                SELECT id, name, accession, species, strain, sample_type, sequence_type, 
                       source, host, collection_date, freezer_id, shelf_id, cabinet_id, 
                       drawer_id, box_id, position, sample_code, code_source, 
                       code_category, code_genus, code_species, code_passage, 
                       code_serial, country, added_at 
                FROM records
            ''')
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
                    'country': row['country'],
                    'addedAt': row['added_at']
                })
            # 加载系统配置
            cursor.execute('SELECT * FROM sys_config WHERE key = "codeLookup"')
            row = cursor.fetchone()
            code_lookup = json.loads(row['value']) if row and row['value'] else None

            return {'freezers': freezers, 'records': records, 'codeLookup': code_lookup}
        except Exception as e:
            self.logger.error(f"Error loading data: {e}")
            return {'freezers': [], 'records': []}

    def search_by_species_list(self, species_names: List[str]) -> List[Dict[str, Any]]:
        """根据物种列表筛选记录"""
        if not species_names:
            return []
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            
            records = []
            chunk_size = 900
            for i in range(0, len(species_names), chunk_size):
                chunk = species_names[i:i + chunk_size]
                placeholders = ", ".join(["?"] * len(chunk))
                cursor.execute(f'SELECT * FROM records WHERE species IN ({placeholders})', tuple(chunk))
                
                for row in cursor.fetchall():
                    # 复用转换逻辑 (由于代码块限制，这里简化，实际开发中建议提取私有方法)
                    records.append({
                        'id': row['id'],
                        'name': row['name'],
                        'species': row['species'],
                        'strain': row['strain'],
                        'accession': row['accession']
                    })
            return records
        except Exception as e:
            self.logger.error(f"Search by species list error: {e}")
            return []

    def save_tree_history(self, history_data):
        """保存进化树项目组历史"""
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            now = datetime.now().isoformat()
            
            for group in history_data:
                gid = group.get('id')
                source = group.get('sourceFile')
                name = group.get('name')
                items = json.dumps(group.get('items', []))
                
                cursor.execute('''
                    INSERT OR REPLACE INTO tree_history (id, source_file, name, items_json, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                ''', (gid, source, name, items, now))
            
            conn.commit()
            return True
        except Exception as e:
            self.logger.error(f"Error saving tree history: {e}")
            return False

    def load_tree_history(self):
        """加载进化树历史，如果数据库为空则尝试从物理归档扫描恢复"""
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            
            # 1. 先尝试从数据库读取
            cursor.execute('SELECT * FROM tree_history ORDER BY updated_at DESC')
            rows = cursor.fetchall()
            
            # 2. 检查是否已经执行过首次自动重建
            cursor.execute('SELECT value FROM sys_config WHERE key = "tree_history_reconstructed"')
            reconstructed_flag = cursor.fetchone()
            
            if not rows and not reconstructed_flag:
                # 仅在数据库为空且从未执行过重建时，才触发自动扫描
                self.logger.info("First time initialization: RECONSTRUCTION START")
                
                self._reconstruct_from_fs()
                
                # 记录重建已完成
                cursor.execute('INSERT OR REPLACE INTO sys_config (key, value, updated_at) VALUES (?, ?, ?)',
                             ('tree_history_reconstructed', 'true', datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
                conn.commit()

                cursor.execute('SELECT * FROM tree_history ORDER BY updated_at DESC')
                rows = cursor.fetchall()
                self.logger.info("First time initialization: RECONSTRUCTION FINISHED")

            # --- 动态路径适配 (Issue: 磁盘迁移后历史记录路径依旧指向 D:\) ---
            from src.workbench.models.tool_config import ToolConfig
            current_root = str(ToolConfig.PROJECT_ROOT).rstrip("\\/")
            
            history = []
            for row in rows:
                items = json.loads(row['items_json'] or '[]')
                
                # 对每一条记录进行路径重定向尝试
                for item in items:
                    fp = item.get('filePath', '')
                    if fp and (":" in fp or fp.startswith("/mnt/")):
                        # 如果路径不在当前根目录下且路径包含 "results"
                        if "results" in fp and not fp.startswith(current_root):
                            rel_part = fp.split("results")[-1].lstrip("\\/")
                            new_fp = str(ToolConfig.PROJECT_ROOT / "results" / rel_part)
                            item['filePath'] = new_fp
                            
                history.append({
                    'id': row['id'],
                    'sourceFile': row['source_file'],
                    'name': row['name'],
                    'items': items
                })
            return history
        except Exception as e:
            self.logger.error(f"Error loading tree history: {e}")
            return []

    def _reconstruct_from_fs(self):
        """内部方法：从文件系统物理扫描并填充索引数据库"""
        import re
        import os
        import hashlib
        results_dir = self.db_path.parent.parent / "results" / "tree_results"
        if not results_dir.exists(): return
        
        history_map = {}
        for p_dir in results_dir.iterdir():
            if not p_dir.is_dir(): continue
            p_id = p_dir.name
            if p_id not in history_map: history_map[p_id] = []
            # 预提取：尝试在父文件夹找通用的 FASTA (针对同一比对任务的不同构树 Session)
            parent_fasta = None
            for ext in ("*.fasta", "*.fa", "*.seq", "*.fna"):
                f_list = list(p_dir.glob(ext))
                if f_list:
                    parent_fasta = f_list[0]
                    break

            for s_dir in p_dir.iterdir():
                if not s_dir.is_dir(): continue
                nwk = next(s_dir.glob("*.nwk"), None)
                if not nwk: continue
                
                # 优先在 session 目录找，找不到用父目录的
                fasta = None
                for ext in ("*.fasta", "*.fa", "*.seq", "*.fna", "*.txt"):
                    f_list = list(s_dir.glob(ext))
                    if f_list:
                        fasta = f_list[0]
                        break
                if not fasta: fasta = parent_fasta
                
                try:
                    mtime = s_dir.stat().st_mtime
                    id_to_hash = {}
                    algorithm = "Archived Task"
                    
                    # 优先从 metadata 恢复参数命名
                    params_file = s_dir / "analysis_params.json"
                    if params_file.exists():
                        try:
                            params = json.loads(params_file.read_text(encoding='utf-8'))
                            msa = params.get("msa", "Rapid").upper()
                            engine = params.get("engine", "NJ").upper()
                            model = params.get("model", "JC").upper()
                            algorithm = f"{msa} / {engine} ({model})"
                        except: pass
                    
                    # 尝试从 manifest 恢复指纹
                    manifest_file = s_dir / "sequence_manifest.json"
                    if manifest_file.exists():
                        try:
                            id_to_hash = json.loads(manifest_file.read_text(encoding='utf-8'))
                        except: pass
                    
                    # 如果没有 manifest 但有 FASTA，手动生成指纹
                    if not id_to_hash and fasta and fasta.exists():
                        try:
                            self.logger.info(f"Generating fingerprints from: {fasta}")
                            content = fasta.read_text(encoding='utf-8', errors='ignore')
                            sections = content.split('>')
                            for sec in sections:
                                if not sec.strip(): continue
                                lines = sec.split('\n')
                                header = lines[0].strip()
                                seq_id = header.split()[0].replace("'", "").replace('"', '').strip()
                                seq_body = "".join(lines[1:]).strip().upper()
                                if seq_id and seq_body:
                                    md5 = hashlib.md5(seq_body.encode()).hexdigest()
                                    id_to_hash[seq_id] = md5
                            self.logger.info(f"Generated {len(id_to_hash)} fingerprints for {s_dir.name}")
                        except Exception as e:
                            self.logger.warning(f"Fingerprint generation failed for {fasta}: {e}")

                    items_data = {
                        "id": os.urandom(4).hex(),
                        "algorithm": algorithm,
                        "nwk": nwk.read_text(encoding='utf-8', errors='ignore'),
                        "filePath": str(fasta) if fasta else "",
                        "archiveFile": f"{p_id}/{s_dir.name}/{fasta.name}" if fasta else "",
                        "idToHash": id_to_hash if id_to_hash else None,
                        "time": int(mtime * 1000)
                    }
                    history_map[p_id].append(items_data)
                except: continue
        
        if not history_map: return
        
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            for p_id, items in history_map.items():
                if not items: continue
                items.sort(key=lambda x: x['time'], reverse=True)
                logical_id = re.sub(r'^Tree_\d+_\d+_', '', p_id)
                display_name = logical_id.replace(".fasta", "").replace(".seq", "")
                
                # 提取基准源文件路径 (取最近一次分析的归档路径)
                base_source = items[0].get("archiveFile", "")
                
                cursor.execute('''
                    INSERT OR REPLACE INTO tree_history (id, source_file, name, items_json, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                ''', (p_id, base_source, display_name, 
                       json.dumps(items), datetime.fromtimestamp(items[0]['time']/1000).strftime('%Y-%m-%d %H:%M:%S')))
            conn.commit()
        except Exception as e:
            self.logger.error(f"Failed to save reconstructed history: {e}")

    def delete_tree_history_group(self, group_id):
        """删除进化树项目组"""
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute('DELETE FROM tree_history WHERE id = ?', (group_id,))
            conn.commit()
            return True
        except Exception as e:
            self.logger.error(f"Error deleting tree history: {e}")
            return False

    def clear_all(self):
        """清除所有数据"""
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute('DELETE FROM records')
            cursor.execute('DELETE FROM freezers')
            conn.commit()
            return True
        except Exception as e:
            self.logger.error(f"Error clearing data: {e}")
            self._close_connection()
            return False
    
    def cleanup(self):
        """清理数据库连接(在应用关闭时调用)"""
        self._close_connection()
        self.logger.info("StrainDB connection pool cleaned up")

_strain_db_manager = None

def get_strain_db_manager():
    global _strain_db_manager
    if _strain_db_manager is None:
        _strain_db_manager = StrainDBManager()
    return _strain_db_manager
