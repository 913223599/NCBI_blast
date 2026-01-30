"""
BLAST执行器模块
负责执行BLAST搜索并与NCBI服务器通信
"""

import ssl
import threading
import time
import logging
import urllib.error
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
# 限制并发请求数为 3，遵循 NCBI 最佳实践 (可通过 set_concurrency_limit 修改)
concurrent_limit = threading.Semaphore(3)

def set_concurrency_limit(limit: int):
    """设置全局并发请求限制"""
    global concurrent_limit
    logging.info(f"Setting NCBI BLAST concurrency limit to {limit}")
    concurrent_limit = threading.Semaphore(limit)

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

        # 字符检查：支持 FASTA 格式（包含 > 头部、数字、下划线、空格等）
        # 允许的基本字符：核酸/蛋白字母 + FASTA 头部常用字符
        valid_chars = set('ATCGNUatcgnuXxACDEFGHIKLMNPQRSTVWYacdefghiklmnpqrstvw>_-.| 0123456789\n\r')
        
        # 不要使用 join(split())，因为那会破坏多序列的换行结构
        # 我们只做基础验证，或者在清理时保留必要结构
        if not set(sequence).issubset(valid_chars):
             logging.warning("序列包含非标准字符，已自动清理")
             sequence = "".join(c for c in sequence if c in valid_chars)
             
        return sequence

    def execute_blast_search(self, sequence, program="blastn", database="nt", **kwargs):
        """执行单词BLAST搜索"""
        sequence = self._validate_sequence(sequence)

        # 使用信号量限制并发
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

            # 特殊处理 Gap Costs (合并 open 和 extend)
            if 'gap_open' in kwargs and 'gap_extend' in kwargs:
                # NCBI QBLAST API 期望格式: "open extend" (例如 "11 1")
                # 注意: 具体数值必须符合矩阵要求 (例如 BLOSUM62 默认 11 1)
                blast_params['gapcosts'] = f"{kwargs['gap_open']} {kwargs['gap_extend']}"

            # 特殊处理 Filter (转换布尔值为 NCBI 字符串)
            if 'filter' in kwargs:
                f_val = kwargs['filter']
                if isinstance(f_val, bool):
                     # True -> 'L' (Low complexity), False -> 'F' (None)
                     blast_params['filter'] = 'L' if f_val else 'F'
                else:
                     blast_params['filter'] = str(f_val)

            for key, ncbi_key in param_map.items():
                if key in kwargs:
                    # Filter 上面已经处理了，这里跳过以防覆盖
                    if key == 'filter': continue
                    blast_params[ncbi_key] = kwargs[key]

            try:
                return NCBIWWW.qblast(**blast_params)
            except Exception as e:
                # 抛出原始异常以便上层区分处理
                raise e

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
                
                # 3.1 HTTP 错误处理
                if isinstance(e, urllib.error.HTTPError):
                    if e.code == 429: # Too Many Requests
                        error_reason = "NCBI服务器繁忙 (HTTP 429)"
                        current_wait = MAX_WAIT_TIME * 2 # 惩罚性等待
                    elif 400 <= e.code < 500: # 客户端错误 (400, 403, 404等)
                        # 这些错误重试通常无效，直接抛出
                        raise RuntimeError(f"NCBI请求被拒绝 (HTTP {e.code}): {e.reason}")
                    else: # 5xx 服务器错误
                        error_reason = f"NCBI服务器错误 (HTTP {e.code})"
                
                # 3.2 网络连接错误
                elif isinstance(e, urllib.error.URLError):
                    error_reason = f"网络连接失败: {e.reason}"
                    
                # 3.3 其他错误
                else:
                    error_reason = str(e)

            # 达到最大重试次数
            if retries >= max_retries:
                raise TimeoutError(f"BLAST失败 (重试 {retries} 次): {error_reason}")

            # 计算等待时间 (指数退避)
            wait_time = current_wait * (2 ** (retries - 1))
            
            # 特殊错误代码处理 (保留旧逻辑兼容)
            if "error code: -1" in str(error_reason).lower():
                wait_time = MAX_WAIT_TIME
            if "error code: 1" in str(error_reason).lower():
                wait_time = MAX_WAIT_TIME

            # 限制最大等待时间
            wait_time = min(wait_time, 60)

            logging.info(f"尝试 {retries}/{max_retries} 失败: {error_reason}. {wait_time:.1f}s 后重试...")
            time.sleep(wait_time)

        raise Exception("未知流程错误")