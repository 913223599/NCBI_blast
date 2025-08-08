"""
BLAST执行器模块
负责执行BLAST搜索并与NCBI服务器通信
"""

import time
import ssl
from urllib.request import HTTPSHandler, build_opener, install_opener

from Bio.Blast import NCBIWWW


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
            **kwargs: 其他BLAST参数
            
        Returns:
            result_handle: BLAST搜索结果句柄
        """
        print("正在执行BLAST搜索...")
        print("这可能需要一些时间...")
        
        try:
            # 准备参数字典
            blast_params = {
                'program': program,
                'database': database,
                'sequence': sequence,
                'megablast': True
            }
            
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
            print("BLAST搜索完成!")
            return result_handle
        except Exception as e:
            print(f"执行BLAST搜索时出错: {e}")
            raise e
    
    def execute_with_retry(self, sequence, program="blastn", database="nt", max_retries=3):
        """
        带重试机制的BLAST搜索执行
        
        Args:
            sequence (str): 要搜索的序列
            program (str): BLAST程序类型，默认为"blastn"
            database (str): 数据库，默认为"nt"
            max_retries (int): 最大重试次数，默认为3
            
        Returns:
            result_handle: BLAST搜索结果句柄
        """
        retries = 0
        while retries < max_retries:
            try:
                return self.execute_blast_search(sequence, program, database)
            except Exception as e:
                retries += 1
                if retries >= max_retries:
                    raise e
                else:
                    wait_time = 5 * (2 ** (retries - 1))  # 指数退避
                    print(f"搜索失败，{wait_time}秒后进行第{retries}次重试...")
                    time.sleep(wait_time)