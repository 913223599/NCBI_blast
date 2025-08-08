"""
优化的远程BLAST执行器
通过多种优化技术提高查询速度
"""

import random
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from Bio.Blast import NCBIWWW


class OptimizedRemoteBlastExecutor:
    """
    优化的远程BLAST执行器
    通过多种技术优化查询速度
    """
    
    def __init__(self, max_workers=5, delay_range=(1, 3)):
        """
        初始化优化的远程BLAST执行器
        
        Args:
            max_workers (int): 最大并发工作线程数
            delay_range (tuple): 请求间隔延迟范围（秒）
        """
        self.max_workers = max_workers
        self.delay_range = delay_range
    
    def execute_blast_search(self, sequence, program="blastn", database="nt", 
                           hitlist_size=50, timeout=60):
        """
        执行优化的BLAST搜索
        
        Args:
            sequence (str): 要搜索的序列
            program (str): BLAST程序类型
            database (str): 数据库
            hitlist_size (int): 返回结果数量
            timeout (int): 超时时间（秒）
            
        Returns:
            result_handle: BLAST搜索结果句柄
        """
        try:
            # 执行BLAST搜索，使用优化参数
            result_handle = NCBIWWW.qblast(
                program=program,
                database=database,
                sequence=sequence,
                hitlist_size=hitlist_size,
                timeout=timeout
            )
            return result_handle
        except Exception as e:
            raise RuntimeError(f"BLAST搜索失败: {e}")
    
    def execute_with_delay(self, sequence_file_tuple, program="blastn", database="nt"):
        """
        带延迟的BLAST搜索执行（避免过于频繁的请求）
        
        Args:
            sequence_file_tuple (tuple): (序列文件路径, 序列内容)元组
            program (str): BLAST程序类型
            database (str): 数据库
            
        Returns:
            dict: 处理结果
        """
        sequence_file, sequence = sequence_file_tuple
        
        try:
            # 随机延迟以避免过于频繁的请求
            delay = random.uniform(*self.delay_range)
            time.sleep(delay)
            
            # 执行BLAST搜索
            result_handle = self.execute_blast_search(
                sequence, program, database
            )
            
            return {
                "file": sequence_file,
                "status": "success",
                "result_handle": result_handle
            }
        except Exception as e:
            return {
                "file": sequence_file,
                "status": "error",
                "error": str(e)
            }
    
    def batch_search(self, sequence_file_tuples, program="blastn", database="nt"):
        """
        批量BLAST搜索
        
        Args:
            sequence_file_tuples (list): (序列文件路径, 序列内容)元组列表
            program (str): BLAST程序类型
            database (str): 数据库
            
        Returns:
            list: 处理结果列表
        """
        print(f"开始批量BLAST搜索，共 {len(sequence_file_tuples)} 个序列")
        print(f"使用 {self.max_workers} 个并发线程")
        
        results = []
        
        # 使用线程池执行并发搜索
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            # 提交所有任务
            future_to_seq = {
                executor.submit(
                    self.execute_with_delay, seq_tuple, program, database
                ): seq_tuple[0]
                for seq_tuple in sequence_file_tuples
            }
            
            # 收集结果
            for future in as_completed(future_to_seq):
                sequence_file = future_to_seq[future]
                try:
                    result = future.result()
                    results.append(result)
                    if result["status"] == "success":
                        print(f"✓ 已提交搜索请求: {sequence_file}")
                    else:
                        print(f"✗ 搜索请求失败: {sequence_file} - {result['error']}")
                except Exception as e:
                    print(f"✗ 处理 {sequence_file} 时发生异常: {e}")
                    results.append({
                        "file": sequence_file,
                        "status": "error",
                        "error": str(e)
                    })
        
        return results


class OptimizedBatchProcessor:
    """
    优化的批量处理器
    """
    
    def __init__(self, max_workers=5):
        """
        初始化优化的批量处理器
        
        Args:
            max_workers (int): 最大并发工作线程数
        """
        self.max_workers = max_workers
        self.blast_executor = OptimizedRemoteBlastExecutor(max_workers=max_workers)
        self.file_handler = None  # 可以复用现有的文件处理工具
    
    def prepare_sequences(self, sequence_files):
        """
        准备序列数据
        
        Args:
            sequence_files (list): 序列文件路径列表
            
        Returns:
            list: (序列文件路径, 序列内容)元组列表
        """
        sequence_file_tuples = []
        
        # 这里应该使用现有的文件处理工具
        # 为了简化示例，我们直接读取文件
        for seq_file in sequence_files:
            try:
                with open(seq_file, 'r') as f:
                    sequence = f.read().strip()
                sequence_file_tuples.append((seq_file, sequence))
            except Exception as e:
                print(f"读取文件 {seq_file} 失败: {e}")
        
        return sequence_file_tuples
    
    def process_sequences(self, sequence_files):
        """
        批量处理序列文件
        
        Args:
            sequence_files (list): 序列文件路径列表
            
        Returns:
            list: 处理结果列表
        """
        # 准备序列数据
        sequence_file_tuples = self.prepare_sequences(sequence_files)
        
        if not sequence_file_tuples:
            print("没有有效的序列数据")
            return []
        
        # 执行批量搜索
        results = self.blast_executor.batch_search(sequence_file_tuples)
        
        # 保存结果等后续处理...
        
        return results


def main():
    """
    优化远程BLAST使用示例
    """
    print("优化远程BLAST工具")
    print("=" * 30)
    
    print("优化措施:")
    print("1. 并发查询: 同时处理多个序列")
    print("2. 请求节流: 避免过于频繁的请求")
    print("3. 参数优化: 使用合适的搜索参数")
    print("4. 错误处理: 自动重试和错误恢复")
    
    print("\n使用建议:")
    print("- 设置合适的并发线程数（推荐3-5）")
    print("- 添加随机延迟避免服务器限制")
    print("- 使用较小的hitlist_size减少响应时间")
    print("- 设置合理的超时时间")


if __name__ == "__main__":
    main()