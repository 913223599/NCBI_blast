"""
BLAST executor module
Communication with NCBI servers
"""

import os
import logging
import ssl
import threading
import time
import urllib.error
from urllib.request import HTTPSHandler, build_opener, install_opener

from Bio.Blast import NCBIWWW
from .local_blast import LocalBlastExecutor

# Constants
MIN_SEQUENCE_LENGTH = 5
DEFAULT_WAIT_TIME = 5
MAX_WAIT_TIME = 20
MAX_RETRIES = 3

request_counter = 0
request_lock = threading.Lock()

def delay_before_request():
    with request_lock:
        global request_counter
        request_counter += 1
        time.sleep(0.5) 

class BlastExecutor:
    def __init__(self):
        self._setup_ssl()
        self.local_executor = None # 延迟初始化

    def _setup_ssl(self):
        try:
            self.ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            self.ssl_context.check_hostname = False
            self.ssl_context.verify_mode = ssl.CERT_NONE
            self.ssl_context.minimum_version = ssl.TLSVersion.TLSv1_2
        except AttributeError:
            self.ssl_context = ssl.create_default_context()
            self.ssl_context.check_hostname = False
            self.ssl_context.verify_mode = ssl.CERT_NONE

        https_handler = HTTPSHandler(context=self.ssl_context)
        opener = build_opener(https_handler)
        install_opener(opener)
        logging.info("SSL context initialized.")

    def _validate_sequence(self, sequence):
        if not sequence:
            raise ValueError("Empty sequence")
        valid_chars = set('ATCGNUatcgnuXxACDEFGHIKLMNPQRSTVWYacdefghiklmnpqrstvw>_-.| 0123456789\n\r')
        if not set(sequence).issubset(valid_chars):
             sequence = "".join(c for c in sequence if c in valid_chars)
        return sequence

    def execute_blast_search(self, sequence, program="blastn", database="nt", **kwargs):
        import io
        import tempfile
        from pathlib import Path as _Path
        sequence = self._validate_sequence(sequence)

        blast_params = {
            'program': program,
            'database': database,
            'sequence': sequence
        }

        if program not in ['blastp', 'blastx', 'rpsblast', 'rpstblastn']:
            blast_params['megablast'] = 'on'

        param_map = {
            'hitlist_size': 'hitlist_size',
            'word_size': 'word_size',
            'evalue': 'expect',
            'matrix_name': 'matrix_name',
            'filter': 'filter',
            'alignments': 'alignments',
            'descriptions': 'descriptions'
        }

        if 'gap_open' in kwargs and 'gap_extend' in kwargs:
            blast_params['gapcosts'] = f"{kwargs['gap_open']} {kwargs['gap_extend']}"

        if 'filter' in kwargs:
            f_val = kwargs['filter']
            if isinstance(f_val, bool):
                 blast_params['filter'] = 'L' if f_val else 'F'
            else:
                 blast_params['filter'] = str(f_val)

        for key, ncbi_key in param_map.items():
            if key in kwargs:
                if key == 'filter': continue
                blast_params[ncbi_key] = kwargs[key]

        threads = kwargs.get('threads')

        try:
            # === PhageScope 本地蛋白库快速通道 ===
            phagescope_aliases = {'phagescope_proteins', 'phagescope_rep'}
            if database in phagescope_aliases:
                project_root = _Path(__file__).resolve().parent.parent.parent
                ps_index = project_root / "database" / "phagescope" / "phagescope_proteins"
                
                if ps_index.with_suffix(".psq").exists():
                    if not self.local_executor:
                        self.local_executor = LocalBlastExecutor(
                            database_path=str(ps_index), program="blastp"
                        )
                    self.local_executor.database_path = str(ps_index)
                    
                    logging.info(f"[PhageScope] 命中本地噬菌体蛋白库: {ps_index}")
                    
                    with tempfile.NamedTemporaryFile(suffix=".fasta", delete=False, mode='w', encoding='utf-8') as tmp:
                        tmp.write(sequence)
                        tmp_in = tmp.name
                    
                    tmp_out = tmp_in.replace(".fasta", ".xml")
                    
                    try:
                        self.local_executor.execute_local_blast(
                            tmp_in, tmp_out,
                            max_hits=kwargs.get('hitlist_size', 50),
                            program="blastp",
                            num_threads=threads
                        )
                        if os.path.exists(tmp_out):
                            with open(tmp_out, 'r', encoding='utf-8') as f_out:
                                xml_data = f_out.read()
                            return io.StringIO(xml_data)
                        else:
                            raise RuntimeError("PhageScope local BLAST failed to generate output")
                    finally:
                        for p in [tmp_in, tmp_out]:
                            try:
                                if os.path.exists(p): os.unlink(p)
                            except Exception: pass
                else:
                    logging.warning(f"[PhageScope] 本地库索引未就绪: {ps_index}")

            # 优先检查是否为已部署的本地生物数据库 (16S/18S)
            from ..backend.utils.bio_db_manager import bio_db_manager
            
            if database in bio_db_manager.dbs:
                db_obj = bio_db_manager.dbs[database]
                if db_obj.get_status().get('installed'):
                    db_ver = db_obj.config.get("version", "latest")
                    if database == 'silva':
                        index_path = str(db_obj.base_dir / f"silva_{db_ver}")
                    elif database == 'ncbi_16s':
                        index_path = str(db_obj.base_dir / "16S_ribosomal_RNA")
                    else:
                        index_path = str(db_obj.base_dir / f"{database}_{db_ver}")
                    
                    if not self.local_executor:
                        self.local_executor = LocalBlastExecutor(database_path=index_path)
                    
                    self.local_executor.database_path = index_path
                    logging.info(f"[LocalBLAST] 命中本地库: {database} -> {index_path}")
                    
                    with tempfile.NamedTemporaryFile(suffix=".fasta", delete=False, mode='w', encoding='utf-8') as tmp:
                        tmp.write(sequence)
                        tmp_in = tmp.name
                    
                    tmp_out = tmp_in.replace(".fasta", ".xml")
                    
                    try:
                        self.local_executor.execute_local_blast(
                            tmp_in, tmp_out, 
                            max_hits=kwargs.get('hitlist_size', 50),
                            num_threads=threads
                        )
                        if os.path.exists(tmp_out):
                            with open(tmp_out, 'r', encoding='utf-8') as f_out:
                                xml_data = f_out.read()
                            return io.StringIO(xml_data)
                        else:
                            raise RuntimeError("Local BLAST failed to generate XML output")
                    finally:
                        for p in [tmp_in, tmp_out]:
                            try:
                                if os.path.exists(p): os.unlink(p)
                            except Exception: pass
            
            # 回退到原有的 NCBI 联机比对逻辑 (仅在联机请求前进行限速等待)
            delay_before_request()
            return NCBIWWW.qblast(**blast_params)
        except Exception as e:
            raise e

    def execute_with_retry(self, sequence, program="blastn", database="nt",
                          max_retries=MAX_RETRIES, timeout_minutes=6, cancel_event=None, **kwargs):
        def run_thread(result_container, exception_container):
            try:
                result_container[0] = self.execute_blast_search(sequence, program, database, **kwargs)
            except Exception as e:
                exception_container[0] = e

        retries = 0
        current_wait = DEFAULT_WAIT_TIME

        while retries < max_retries:
            result_container = [None]
            exception_container = [None]

            worker = threading.Thread(target=run_thread, args=(result_container, exception_container))
            worker.daemon = True
            worker.start()
            
            total_timeout = timeout_minutes * 60
            elapsed = 0
            check_interval = 0.5
            while elapsed < total_timeout and worker.is_alive():
                if cancel_event and cancel_event.is_set():
                    return None
                worker.join(check_interval)
                elapsed += check_interval

            if not worker.is_alive() and exception_container[0] is None and result_container[0] is not None:
                return result_container[0]

            retries += 1
            error_reason = "Unknown error"
            
            if worker.is_alive():
                error_reason = f"Timeout (> {timeout_minutes}m)"
            elif exception_container[0]:
                e = exception_container[0]
                if isinstance(e, urllib.error.HTTPError):
                    if e.code == 429:
                        error_reason = "NCBI Busy (HTTP 429)"
                        current_wait = MAX_WAIT_TIME * 2
                    elif 400 <= e.code < 500:
                        raise RuntimeError(f"NCBI Rejected (HTTP {e.code}): {e.reason}")
                    else:
                        error_reason = f"NCBI Server Error (HTTP {e.code})"
                elif isinstance(e, urllib.error.URLError):
                    error_reason = f"Network Error: {e.reason}"
                else:
                    error_reason = str(e)

            if retries >= max_retries:
                raise TimeoutError(f"BLAST failed (Retries {retries}): {error_reason}")

            wait_time = current_wait * (2 ** (retries - 1))
            err_lower = error_reason.lower()
            if "error code: -1" in err_lower or "error code: 1" in err_lower:
                wait_time = MAX_WAIT_TIME

            wait_time = min(wait_time, 60)
            logging.info(f"Retry {retries}: {error_reason}. Waiting {wait_time:.1f}s...")
            
            slept = 0
            while slept < wait_time:
                if cancel_event and cancel_event.is_set():
                    return None
                time.sleep(0.5)
                slept += 0.5

        raise Exception("Logic error")
