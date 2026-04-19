import json
import logging
import re
import threading
import time
import io
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional, Callable

from src.utils.file_handler import FileHandler
from src.workbench.models.annotation_manager import get_annotation_manager
from .executor import BlastExecutor
from .parser import BlastResultParser
from .result_converter import BlastResultConverter

logger = logging.getLogger(__name__)

class BlastEngine:
    """
    Modernised Unified BLAST Engine with Batching & Fingerprint Support.
    """
    
    NUCLEOTIDE_CHARS = set('ATCGNU')
    PROTEIN_CHARS = set('KERYWHDNQSTVRLEAICGPMF')
    
    # 批处理策略 (限制单个连接最大 10 条以防止 NCBI 拒绝解析)
    MAX_BATCH_SIZE = 10
    BATCH_CHAR_LIMIT = 50000 
    
    def __init__(self, task_id: str, settings: Dict[str, Any]):
        self.task_id = task_id
        self.settings = settings
        self.results_dir = self._init_results_dir()
        
        self.executor = BlastExecutor()
        self.parser = BlastResultParser()
        self.converter = BlastResultConverter()
        self.file_handler = FileHandler()
        
        self._cancel_flag = threading.Event()
        self._pause_flag = False
        self._pause_cond = threading.Condition(threading.Lock())
        
        self.progress_callback: Optional[Callable[[int, int, str], None]] = None
        self.result_callback: Optional[Callable[[Dict[str, Any]], None]] = None

    def _init_results_dir(self) -> Path:
        # 由 Manager 注入的 root/results/blast/{task_id}
        root = Path(__file__).resolve().parent.parent.parent
        dir_path = root / "results" / "blast" / self.task_id
        
        # 强制创建子目录结构
        (dir_path / "reports").mkdir(parents=True, exist_ok=True)
        (dir_path / "xml_raw").mkdir(parents=True, exist_ok=True)
        
        try:
            params_file = dir_path / "params.json"
            scrubbed_params = {k: v for k, v in self.settings.items() if k != 'query'}
            scrubbed_params['archived_at'] = datetime.now().isoformat()
            
            with open(params_file, 'w', encoding='utf-8') as f:
                json.dump(scrubbed_params, f, indent=4, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Failed to archive parameters: {e}")
            
        return dir_path

    def cancel(self):
        self._cancel_flag.set()
        with self._pause_cond:
            self._pause_flag = False
            self._pause_cond.notify_all()

    def pause(self):
        with self._pause_cond:
            self._pause_flag = True

    def resume(self):
        with self._pause_cond:
            self._pause_flag = False
            self._pause_cond.notify_all()

    def _check_pause(self):
        with self._pause_cond:
            while self._pause_flag and not self._cancel_flag.is_set():
                self._pause_cond.wait(timeout=1.0)

    def detect_type(self, sequence: str) -> str:
        seq = "".join(sequence.split()).upper()
        if not seq: return 'nucleotide'
        sample = seq[:100]
        n_count = sum(1 for c in sample if c in self.NUCLEOTIDE_CHARS)
        p_count = sum(1 for c in sample if c in self.PROTEIN_CHARS)
        return 'protein' if p_count > n_count else 'nucleotide'

    def run(self, sequences: List[Dict[str, str]]):
        total = len(sequences)
        completed = 0
        max_threads = self.settings.get('max_workers', 2)

        to_process = []
        for seq in sequences:
            seq_id = seq.get('id', 'unknown')
            query_str = seq.get('sequence', '')
            safe_id = re.sub(r'[^a-zA-Z0-9_\-]', '_', seq_id)
            csv_path = self.results_dir / "reports" / f"{safe_id}.csv"
            
            # 必须重算 Hash，否则缓存项将无法连接进化树
            seq_hash = get_annotation_manager().generate_hash(query_str)
            
            if self._verify_result_integrity(csv_path):
                completed += 1
                if self.result_callback:
                    self.result_callback({
                        "sequence_id": seq_id,
                        "sequence_hash": seq_hash, # 核心修复
                        "status": "success",
                        "cached": True,
                        "csv_file": str(csv_path),
                        "program": self.settings.get('program'),
                        "database": self.settings.get('database')
                    })
            else:
                to_process.append(seq)

        if completed > 0:
            if self.progress_callback:
                self.progress_callback(completed, total, f"Cache restored: {completed}/{total}")

        if not to_process:
            return

        # [优化] 只有当序列总数超过上限时才进行任务分片
        batch_size = self.MAX_BATCH_SIZE 
        
        batches = []
        current_batch = []
        current_char_count = 0
        for seq in to_process:
            seq_len = len(seq.get('sequence', ''))
            if len(current_batch) >= batch_size or (current_char_count + seq_len) > self.BATCH_CHAR_LIMIT:
                if current_batch: batches.append(current_batch)
                current_batch = [seq]
                current_char_count = seq_len
            else:
                current_batch.append(seq)
                current_char_count += seq_len
        if current_batch: batches.append(current_batch)

        # 🚀 提速：增加并发数到 4，减少由于串行等待 NCBI 响应造成的延迟
        final_max_workers = max(max_threads, 4)
        executor = ThreadPoolExecutor(max_workers=final_max_workers)
        try:
            futures = []
            for batch in batches:
                if self._cancel_flag.is_set(): break
                futures.append(executor.submit(self._process_batch, batch))
            
            for future in as_completed(futures):
                if self._cancel_flag.is_set(): break
                
                try:
                    batch_results = future.result()
                    for res in batch_results:
                        completed += 1
                        if self.result_callback:
                            self.result_callback(res)
                    
                    if self.progress_callback:
                        self.progress_callback(completed, total, f"Progress: {completed}/{total}")
                except Exception as e:
                    logger.error(f"Batch fail: {e}")
        finally:
            executor.shutdown(wait=False)

    def _process_batch(self, batch_seqs: List[Dict[str, str]]) -> List[Dict[str, Any]]:
        self._check_pause()
        if self._cancel_flag.is_set(): return []

        results = []
        multi_fasta = ""
        for seq in batch_seqs:
            multi_fasta += f">{seq.get('id', 'unknown')}\n{seq.get('sequence', '')}\n"

        first_seq = batch_seqs[0].get('sequence', '')
        detected_type = self.detect_type(first_seq)
        auto_prog = self.settings.get('program', 'auto')
        prog = ('blastp' if detected_type == 'protein' else 'blastn') if auto_prog == 'auto' else auto_prog
        db = self.settings.get('database')
        
        if prog == 'blastp' and db == 'nt' and auto_prog == 'auto': db = 'nr'
        elif prog == 'blastn' and db == 'nr' and auto_prog == 'auto': db = 'nt'
        if not db: db = 'nr' if 'p' in prog else 'nt'

        try:
            exec_params = {k: v for k, v in self.settings.items() if k in ['evalue', 'word_size', 'hitlist_size', 'matrix_name', 'filter', 'gap_open', 'gap_extend']}
            if prog in ['blastn', 'megablast']:
                for k in ['matrix_name', 'gap_open', 'gap_extend']:
                    if k in exec_params: del exec_params[k]

            start_t = time.time()
            handle = self.executor.execute_with_retry(
                multi_fasta,
                program=prog,
                database=db,
                timeout_minutes=self.settings.get('request_timeout', 10),
                cancel_event=self._cancel_flag,
                **exec_params
            )
            
            if not handle: return []

            xml_content = handle.read()
            handle.close()
            
            # ✨ [加速核心1] 每个 Batch 只写一次原始 XML，避免对同一个大文件进行 10 次冗余写入
            batch_xml_path = self.results_dir / "xml_raw" / f"batch_{int(time.time())}.xml"
            try:
                with open(batch_xml_path, 'w', encoding='utf-8') as f_xml:
                    f_xml.write(xml_content)
            except Exception as xml_err:
                logger.warning(f"Failed to save batch XML: {xml_err}")

            from Bio.Blast import NCBIXML
            records = NCBIXML.parse(io.StringIO(xml_content))
            
            elapsed = time.time() - start_t
            avg_time = elapsed / len(batch_seqs)
            
            for i, record in enumerate(records):
                if i >= len(batch_seqs): break
                
                orig_seq = batch_seqs[i]
                sid = orig_seq.get('id', 'unknown')
                query_str = orig_seq.get('sequence', '')
                safe_id = re.sub(r'[^a-zA-Z0-9_\-]', '_', sid)
                
                seq_hash = get_annotation_manager().generate_hash(query_str)
                
                # 保存结果
                csv_path = self.results_dir / "reports" / f"{safe_id}.csv"
                results_data = list(self.parser.parse_single_record(record))
                self.converter.save_parsed_to_csv(results_data, str(csv_path))

                results.append({
                    "task_id": self.task_id,
                    "sequence_id": sid,
                    "sequence_hash": seq_hash, 
                    "status": "success",
                    "elapsed_time": avg_time,
                    "csv_file": str(csv_path),
                    "xml_file": str(batch_xml_path) if batch_xml_path.exists() else None,
                    "program": prog,
                    "database": db,
                    "raw_sequence": query_str 
                })
                
            return results

        except Exception as e:
            logger.error(f"Batch processing error: {e}")
            return [{"sequence_id": s.get('id'), "status": "error", "error": str(e)} for s in batch_seqs]

    def _verify_result_integrity(self, csv_path: Path) -> bool:
        if not csv_path.exists() or csv_path.stat().st_size == 0: return False
        try:
            with open(csv_path, 'r', encoding='utf-8-sig') as f:
                header = f.readline()
                if not header or not header.strip(): return False
                data_line = f.readline()
                return bool(data_line and data_line.strip())
        except: return False
