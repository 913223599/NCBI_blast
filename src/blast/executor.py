"""
BLAST执行器模块
负责执行BLAST搜索并与NCBI服务器通信
"""

import ssl
import threading
import time
import logging
from urllib.request import HTTPSHandler, build_opener, install_opener
from Bio.Blast import NCBIWWW

# 常量定义
MIN_SEQUENCE_LENGTH = 5
DEFAULT_WAIT_TIME = 5
MAX_WAIT_TIME = 20
MAX_RETRIES = 3

# 全局请求控制
request_counter = 0
request_lock = threading.Lock()
# [新增] 限制并发请求数为 3，遵循 NCBI 最佳实践
concurrent_limit = threading.Semaphore(3)

def delay_before_request():
    """控制请求频率，遵循NCBI规则"""
    with request_lock:
        global request_counter
        request_counter += 1
        time.sleep(0.5) # 稍微增加间隔

class BlastExecutor:
    def __init__(self):
        # 统一SSL上下文设置
        self._setup_ssl()

    def _setup_ssl(self):
        """配置非验证的SSL上下文（用于应对特定网络环境）"""
        self.ssl_context = ssl.create_default_context()
        self.ssl_context.check_hostname = False
        self.ssl_context.verify_mode = ssl.CERT_NONE
        https_handler = HTTPSHandler(context=self.ssl_context)
        opener = build_opener(https_handler)
        install_opener(opener)

    def _validate_sequence(self, sequence):
        """验证并清理序列"""
        if not sequence:
            raise ValueError("序列为空")

        # 清理空白
        clean_seq = "".join(sequence.split())

        if len(clean_seq) < MIN_SEQUENCE_LENGTH:
            raise ValueError(f"序列过短: {len(clean_seq)} < {MIN_SEQUENCE_LENGTH}")

        # 简单字符检查（可选优化：正则）
        valid_chars = set('ATCGNUatcgnuXxACDEFGHIKLMNPQRSTVWYacdefghiklmnpqrstvw')
        if not set(clean_seq).issubset(valid_chars):
             logging.warning("序列包含非标准字符")
             clean_seq = "".join(c for c in clean_seq if c in valid_chars)

        return clean_seq

    def execute_blast_search(self, sequence, program="blastn", database="nt", **kwargs):
        """执行单词BLAST搜索"""
        sequence = self._validate_sequence(sequence)

        # [新增] 使用信号量限制并发
        with concurrent_limit:
            delay_before_request()

            blast_params = {
                'program': program,
                'database': database,
                'sequence': sequence
            }

            # 参数映射优化
            if program not in ['blastp', 'blastx', 'rpsblast', 'rpstblastn']:
                blast_params['megablast'] = 'on'

            # 批量映射可选参数
            param_map = {
                'hitlist_size': 'hitlist_size',
                'word_size': 'word_size',
                'evalue': 'expect',
                'matrix_name': 'matrix_name',
                'filter': 'filter',
                'alignments': 'alignments',
                'descriptions': 'descriptions'
            }

            for key, ncbi_key in param_map.items():
                if key in kwargs:
                    blast_params[ncbi_key] = kwargs[key]

            try:
                return NCBIWWW.qblast(**blast_params)
            except Exception as e:
                # 简单封装异常以便上层处理
                raise RuntimeError(f"NCBI BLAST请求失败: {e}") from e

    def execute_with_retry(self, sequence, program="blastn", database="nt",
                          max_retries=MAX_RETRIES, timeout_minutes=6, **kwargs):
        """带重试和超时机制的执行"""

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

            # 使用线程实现超时控制
            worker = threading.Thread(target=run_thread, args=(result_container, exception_container))
            worker.daemon = True
            worker.start()
            worker.join(timeout_minutes * 60)

            # 情况1: 成功
            if not worker.is_alive() and exception_container[0] is None and result_container[0] is not None:
                return result_container[0]

            # 准备重试逻辑
            retries += 1
            error_reason = "未知错误"
            should_wait = True

            # 情况2: 超时
            if worker.is_alive():
                error_reason = f"请求超时 (> {timeout_minutes}m)"
                # 注意: Python线程无法强制终止，只能丢弃引用

            # 情况3: 抛出异常
            elif exception_container[0]:
                e = exception_container[0]
                error_reason = str(e)
                # 检查是否是严重错误（如认证失败等），可能不需要重试
                # 这里假设网络错误都需要重试

            # 达到最大重试次数
            if retries >= max_retries:
                raise TimeoutError(f"BLAST失败 (重试 {retries} 次): {error_reason}")

            # 计算等待时间 (指数退避)
            wait_time = current_wait * (2 ** (retries - 1))
            # 如果是服务器拒绝 (-1)，使用更长的固定等待
            if "error code: -1" in str(error_reason).lower():
                wait_time = MAX_WAIT_TIME
            # 如果是 error code: 1 (Cannot accept request)，也增加等待
            if "error code: 1" in str(error_reason).lower():
                wait_time = MAX_WAIT_TIME

            logging.info(f"尝试 {retries}/{max_retries} 失败: {error_reason}. {wait_time:.1f}s 后重试...")
            time.sleep(wait_time)

        raise Exception("未知流程错误")