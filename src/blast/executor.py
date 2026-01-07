"""
BLAST执行器模块
负责执行BLAST搜索并与NCBI服务器通信
"""

import ssl
import time
import threading
from urllib.request import HTTPSHandler, build_opener, install_opener
from Bio.Blast import NCBIWWW

# 全局请求计数器和锁，用于控制请求频率
request_counter = 0
request_lock = threading.Lock()


def delay_before_request():
    """
    在请求前添加延迟以控制请求频率
    NCBI限制每秒最多3个请求，所以我们控制请求间隔
    使用0.4秒的延迟，允许每秒2.5个请求，低于NCBI的3个/秒限制
    """
    global request_counter
    with request_lock:
        request_counter += 1
        # 计算需要等待的时间，以保持每秒不超过3个请求的频率
        time.sleep(0.4)


class BlastExecutor:
    """
    BLAST执行器类
    负责执行BLAST搜索请求
    """
    
    def __init__(self):
        """
        初始化BLAST执行器
        """
        # 创建一个不验证SSL证书的上下文
        self.ssl_context = ssl.create_default_context()
        self.ssl_context.check_hostname = False
        self.ssl_context.verify_mode = ssl.CERT_NONE
        
        # 创建一个使用自定义SSL上下文的HTTPS处理器
        self.https_handler = HTTPSHandler(context=self.ssl_context)
        
        # 创建并安装使用自定义SSL上下文的opener
        self.opener = build_opener(self.https_handler)
        install_opener(self.opener)
    
    def execute_blast_search(self, sequence, program="blastn", database="nt", **kwargs):
        """
        执行BLAST搜索
        
        Args:
            sequence (str): 要搜索的序列
            program (str): BLAST程序类型，默认为"blastn"
            database (str): 数据库，默认为"nt"
            **kwargs: 其他BLAST参数，支持的参数包括:
                     - hitlist_size: 返回结果数量
                     - word_size: 词大小
                     - evalue: 期望值阈值
                     - matrix_name: 打分矩阵
                     - filter: 过滤器设置
                     - alignments: 比对数量
                     - descriptions: 描述数量
            
        Returns:
            result_handle: BLAST搜索结果句柄，可用于读取搜索结果
            
        Raises:
            Exception: 如果BLAST搜索执行过程中出现错误
        """
        # 只有在处理多个文件时才打印这些信息
        # 这些信息在批处理器中已经打印过了
        # print("正在执行BLAST搜索...")
        # print("这可能需要一些时间...")
        
        try:
            # 在发送请求前添加延迟，以控制请求频率并遵循NCBI限制
            delay_before_request()  # 使用伪队列机制控制请求频率
            
            # 准备参数字典
            blast_params = {
                'program': program,
                'database': database,
                'sequence': sequence
            }
            
            # 对于蛋白质搜索，不使用megablast参数
            if program not in ['blastp', 'blastx', 'rpsblast', 'rpstblastn']:
                blast_params['megablast'] = True
            
            # 添加可选参数
            if 'hitlist_size' in kwargs:
                blast_params['hitlist_size'] = kwargs['hitlist_size']
                
            if 'word_size' in kwargs:
                blast_params['word_size'] = kwargs['word_size']
                
            if 'evalue' in kwargs:
                blast_params['expect'] = kwargs['evalue']
                
            if 'matrix_name' in kwargs:
                blast_params['matrix_name'] = kwargs['matrix_name']
                
            if 'filter' in kwargs:
                blast_params['filter'] = kwargs['filter']
                
            if 'alignments' in kwargs:
                blast_params['alignments'] = kwargs['alignments']
                
            if 'descriptions' in kwargs:
                blast_params['descriptions'] = kwargs['descriptions']
            
            # 执行BLAST搜索，传递参数
            result_handle = NCBIWWW.qblast(**blast_params)
            # print("BLAST搜索完成!")
            return result_handle
        except Exception as e:
            print(f"执行BLAST搜索时出错: {e}")
            raise e
    
    def execute_with_retry(self, sequence, program="blastn", database="nt", max_retries=3, timeout_minutes=6, **kwargs):
        """
        带重试机制的BLAST搜索执行
        
        Args:
            sequence (str): 要搜索的序列
            program (str): BLAST程序类型，默认为"blastn"
            database (str): 数据库，默认为"nt"
            max_retries (int): 最大重试次数，默认为3
            timeout_minutes (int): 请求超时时间（分钟），默认为6分钟
            **kwargs: 其他BLAST参数，支持的参数包括:
                     - hitlist_size: 返回结果数量
                     - word_size: 词大小
                     - evalue: 期望值阈值
                     - matrix_name: 打分矩阵
                     - filter: 过滤器设置
                     - alignments: 比对数量
                     - descriptions: 描述数量
            
        Returns:
            result_handle: BLAST搜索结果句柄
        """

        def run_with_timeout(func, args, timeout):
            """在指定时间内运行函数，超时则抛出异常"""
            result = [None]
            exception = [None]
            
            def target():
                try:
                    result[0] = func(*args)
                except Exception as e:
                    exception[0] = e
            
            thread = threading.Thread(target=target)
            thread.daemon = True
            thread.start()
            thread.join(timeout)
            
            if thread.is_alive():
                # 注意：threading._stop() 在新版本Python中不可用，这里我们仅记录超时
                print(f"警告：BLAST请求超过{timeout_minutes}分钟超时，将重新提交")
                raise TimeoutError(f"BLAST请求超过{timeout_minutes}分钟超时")
            
            if exception[0]:
                raise exception[0]
            
            return result[0]
        
        retries = 0
        # 使用更长的等待时间以避免服务器过载
        base_wait_time = 5  # 增加基础等待时间
        
        while retries < max_retries:
            try:
                # 使用超时包装器执行BLAST搜索
                result = run_with_timeout(
                    self.execute_blast_search,
                    (sequence, program, database) + tuple(),
                    timeout_minutes * 60  # 转换为秒
                )
                return result
            except Exception as e:
                # 检查错误类型，如果是NCBI服务器拒绝请求，需要特别处理
                error_msg = str(e).lower()
                if "cannot accept request" in error_msg or "error code: -1" in error_msg:
                    # 根据历史经验，错误码-1表示服务器过载，需要大幅增加等待时间
                    wait_time = 20  # 20秒等待时间
                    print(f"NCBI服务器拒绝请求，{wait_time}秒后重试... (错误: {e})")
                    time.sleep(wait_time)
                    retries += 1
                    continue
                elif "taking longer than" in error_msg:
                    # 长时间请求警告，根据用户需求，超过一定时间应视为超时并重新提交
                    print(f"检测到长时间运行的BLAST请求，视为超时，将重新提交... (警告: {e})")
                    retries += 1
                    if retries >= max_retries:
                        raise e
                    else:
                        # 使用指数退避策略，但确保等待时间足够长
                        wait_time = base_wait_time * (2 ** (retries - 1))  # 指数退避
                        print(f"超时重试，{wait_time:.1f}秒后进行第{retries}次重试... (错误: {e})")
                        time.sleep(wait_time)
                    continue
                elif isinstance(e, TimeoutError):
                    # 超时错误，按用户需求重新提交
                    print(f"BLAST请求超时({timeout_minutes}分钟)，将重新提交... (错误: {e})")
                    retries += 1
                    if retries >= max_retries:
                        raise e
                    else:
                        # 使用指数退避策略，但确保等待时间足够长
                        wait_time = base_wait_time * (2 ** (retries - 1))  # 指数退避
                        print(f"超时重试，{wait_time:.1f}秒后进行第{retries}次重试... (错误: {e})")
                        time.sleep(wait_time)
                    continue
                else:
                    retries += 1
                    if retries >= max_retries:
                        raise e
                    else:
                        # 使用指数退避策略，但确保等待时间足够长
                        wait_time = base_wait_time * (2 ** (retries - 1))  # 指数退避
                        print(f"搜索失败，{wait_time:.1f}秒后进行第{retries}次重试... (错误: {e})")
                        time.sleep(wait_time)