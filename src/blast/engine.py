import json
import logging
import re
import threading
import time
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
    Modernised Unified BLAST Engine.
    Handles NCBI requests, local processing, and result conversion in a streaming manner.
    """
    
    NUCLEOTIDE_CHARS = set('ATCGNU')
    PROTEIN_CHARS = set('KERYWHDNQSTVRLEAICGPMF')
    
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
        """Create a dedicated directory for task results and archive parameters."""
        root = Path(__file__).resolve().parent.parent.parent
        dir_path = root / "results" / self.task_id
        dir_path.mkdir(parents=True, exist_ok=True)
        
        # Archive parameters (Scrubbing large query sequences for performance/audit)
        try:
            params_file = dir_path / "params.json"
            # Deep copy or filter to avoid mutating original settings if needed
            scrubbed_params = {k: v for k, v in self.settings.items() if k != 'query'}
            scrubbed_params['archived_at'] = datetime.now().isoformat()
            
            with open(params_file, 'w', encoding='utf-8') as f:
                json.dump(scrubbed_params, f, indent=4, ensure_ascii=False)
            logger.info(f"Engine [{self.task_id}] parameters archived to {params_file}")
        except Exception as e:
            logger.error(f"Failed to archive parameters for task {self.task_id}: {e}")
            
        return dir_path

    def cancel(self):
        self._cancel_flag.set()
        with self._pause_cond:
            self._pause_flag = False # Resume to allow threads to exit
            self._pause_cond.notify_all()

    def pause(self):
        with self._pause_cond:
            self._pause_flag = True

    def resume(self):
        with self._pause_cond:
            self._pause_flag = False
            self._pause_cond.notify_all()

    def _check_pause(self):
        """Block if pause flag is set."""
        with self._pause_cond:
            while self._pause_flag and not self._cancel_flag.is_set():
                self._pause_cond.wait(timeout=1.0)

    def detect_type(self, sequence: str) -> str:
        """Detect if sequence is Nucleotide or Protein."""
        seq = "".join(sequence.split()).upper()
        if not seq: return 'nucleotide'
        
        # Check first 100 chars
        sample = seq[:100]
        n_count = sum(1 for c in sample if c in self.NUCLEOTIDE_CHARS)
        p_count = sum(1 for c in sample if c in self.PROTEIN_CHARS)
        
        return 'protein' if p_count > n_count else 'nucleotide'

    def run(self, sequences: List[Dict[str, str]]):
        """Execute the analysis pipeline for a list of sequences."""
        total = len(sequences)
        completed = 0
        skipped_cached = 0
        max_workers = self.settings.get('max_workers', 2)

        # 断点续传预扫描：先统计有多少序列已经有有效结果
        for seq in sequences:
            seq_id = seq.get('id', 'unknown')
            safe_id = re.sub(r'[^a-zA-Z0-9_\-]', '_', seq_id)
            csv_path = self.results_dir / f"{safe_id}.csv"
            if self._verify_result_integrity(csv_path):
                skipped_cached += 1

        if skipped_cached > 0:
            logger.info(f"Engine [{self.task_id}] ★★ 断点续传模式 ★★ 检测到 {skipped_cached}/{total} 条序列已有有效缓存结果，将跳过这些序列。")
        else:
            logger.info(f"Engine [{self.task_id}] 全新任务，共 {total} 条序列待处理, {max_workers} 个工作线程。")

        executor = ThreadPoolExecutor(max_workers=max_workers)
        try:
            futures = []
            for seq in sequences:
                if self._cancel_flag.is_set():
                    break
                futures.append(executor.submit(self._process_single, seq))
            
            for future in as_completed(futures):
                if self._cancel_flag.is_set():
                    logger.info(f"Engine [{self.task_id}] cancellation detected. Sending immediate shutdown to pool.")
                    for f in futures:
                        f.cancel()
                    executor.shutdown(wait=False)
                    return
                
                try:
                    result = future.result()
                    if result.get("status") == "cancelled":
                        continue

                    completed += 1
                    
                    if self.result_callback:
                        self.result_callback(result)
                    
                    if self.progress_callback:
                        self.progress_callback(completed, total, f"Processed {completed}/{total}")
                        
                except Exception as e:
                    logger.error(f"Engine sequence processing error: {e}")
                    completed += 1
        finally:
            executor.shutdown(wait=False)

    def _verify_result_integrity(self, csv_path: Path) -> bool:
        """Verify if the CSV result file is structurally sound and complete.
        
        不依赖特定语言的表头文字（系统实际输出的是中文表头如 '标题,长度,访问号'），
        只检查文件是否存在、非空、且至少包含 header + 1 行数据。
        """
        if not csv_path.exists() or csv_path.stat().st_size == 0:
            return False
        
        try:
            with open(csv_path, 'r', encoding='utf-8-sig') as f:
                header = f.readline()
                if not header or not header.strip():
                    return False
                # 确保至少有一行数据 (header + data)
                data_line = f.readline()
                if not data_line or not data_line.strip():
                    return False
                return True
        except Exception:
            return False

    def _process_single(self, seq_data: Dict[str, str]) -> Dict[str, Any]:
        """Process a single sequence: Query -> Parse -> Convert -> Cache."""
        self._check_pause()
        if self._cancel_flag.is_set():
            return {"status": "cancelled", "error": "Cancelled"}

        seq_id = seq_data.get('id', 'unknown')
        query = seq_data.get('sequence', '')
        

        # 2. Determine Program/DB
        auto_prog = self.settings.get('program', 'auto')
        detected_type = self.detect_type(query)
        
        if auto_prog == 'auto':
            prog = 'blastp' if detected_type == 'protein' else 'blastn'
        else:
            prog = auto_prog
            
        db = self.settings.get('database')
        logger.info(f"Sequence {seq_id} | Type: {detected_type} | Program: {prog} | DB: {db}")
        
        # 数据库类型与程序兼容性检查 (针对 NCBI)
        # 如果是蛋白程序(blastp)但选择了核酸库(nt)，且处于 auto 模式，自动校正为 nr
        if prog == 'blastp' and db == 'nt' and auto_prog == 'auto':
             logger.info(f"Auto-switch: Protein detected, switching database from {db} to nr.")
             db = 'nr'
        # 如果是核酸程序(blastn)但选择了蛋白库(nr)，且处于 auto 模式，自动校正为 nt
        elif prog == 'blastn' and db == 'nr' and auto_prog == 'auto':
             logger.info(f"Auto-switch: Nucleotide detected, switching database from {db} to nt.")
             db = 'nt'
             
        if not db:
            db = self.settings.get('protein_database', 'nr') if 'p' in prog else self.settings.get('nucleotide_database', 'nt')

        # 3. Execute
        start_time = time.time()
        try:
            # Prepare result paths
            safe_id = re.sub(r'[^a-zA-Z0-9_\-]', '_', seq_id)
            xml_path = self.results_dir / f"{safe_id}.xml"
            csv_path = self.results_dir / f"{safe_id}.csv"
            
            # 1. 核心改进：生成序列内容哈希 (MD5) 作为唯一识别指纹
            seq_hash = get_annotation_manager().generate_hash(query)

            # RESUMPTION: Check if valid result already exists
            if self._verify_result_integrity(csv_path):
                logger.info(f"★ 断点跳过: {seq_id} | 磁盘上已存在有效 CSV 结果，无需重新比对。")
                return {
                    "task_id": self.task_id,
                    "sequence_id": seq_id,
                    "sequence_hash": seq_hash,
                    "status": "success",
                    "elapsed_time": 0.0,
                    "xml_file": str(xml_path),
                    "csv_file": str(csv_path),
                    "program": prog,
                    "database": db,
                    "cached": True
                }

            # Call Executor
            # CHECK AGAIN BEFORE IO
            if self._cancel_flag.is_set():
                return {"status": "cancelled", "seq_id": seq_id}

            exec_params = {k: v for k, v in self.settings.items() if k in ['evalue', 'word_size', 'hitlist_size', 'matrix_name', 'filter', 'gap_open', 'gap_extend']}
            
            # CRITICAL FIX: Remove protein-specific params for nucleotide searches
            if prog in ['blastn', 'megablast']:
                if 'matrix_name' in exec_params:
                    del exec_params['matrix_name']
                # nucleotide defaults usually differ, removing them lets NCBI use defaults
                if 'gap_open' in exec_params:
                    del exec_params['gap_open']
                if 'gap_extend' in exec_params:
                    del exec_params['gap_extend']
            
            handle = self.executor.execute_with_retry(
                query,
                program=prog,
                database=db,
                timeout_minutes=self.settings.get('request_timeout', 6),
                cancel_event=self._cancel_flag, # Pass event down for IO interrupt
                **exec_params
            )
            
            if self._cancel_flag.is_set():
                if handle: handle.close()
                return {"status": "cancelled", "seq_id": seq_id}
            
            # Save and Convert
            self.file_handler.save_result_file(handle, str(xml_path))
            handle.close()
            self.converter.convert_xml_to_csv(str(xml_path), str(csv_path))
            
            elapsed = time.time() - start_time
            
            result = {
                "task_id": self.task_id,
                "sequence_id": seq_id,
                "sequence_hash": seq_hash,
                "status": "success",
                "elapsed_time": elapsed,
                "xml_file": str(xml_path),
                "csv_file": str(csv_path),
                "program": prog,
                "database": db
            }
            
            return result

        except Exception as e:
            return {
                "sequence_id": seq_id,
                "status": "error",
                "error": str(e),
                "elapsed_time": time.time() - start_time
            }
