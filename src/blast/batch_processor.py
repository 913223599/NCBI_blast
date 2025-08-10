"""
批量处理模块
负责批量处理序列文件的BLAST查询
"""

import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from src.utils.file_handler import FileHandler
from .executor import BlastExecutor
from .parser import BlastResultParser


class BatchProcessor:
    """
    批量处理器类
    负责多线程批量处理序列文件
    """
    
    def __init__(self, max_workers=3, advanced_settings=None):
        """
        初始化批量处理器
        
        Args:
            max_workers (int): 最大工作线程数，默认为3
            advanced_settings (dict): 高级设置参数，包含BLAST搜索的高级参数设置
                                      默认为None，表示使用BLAST的默认参数
        """
        self.max_workers = max_workers
        self.advanced_settings = advanced_settings or {}
        self.file_handler = FileHandler()
        self.blast_executor = BlastExecutor()
        self.result_parser = BlastResultParser()
        self.on_task_start = None  # 任务开始回调
        self.on_progress_update = None  # 进度更新回调
        self.on_result_received = None  # 结果接收回调
        self.on_all_tasks_complete = None  # 所有任务完成回调
        self._cancel_flag = False  # 取消标志
    
    def cancel_processing(self):
        """
        取消处理过程
        """
        self._cancel_flag = True
    
    def process_single_sequence(self, sequence_file):
        """
        处理单个序列文件
        
        Args:
            sequence_file (str): 序列文件路径
            
        Returns:
            dict: 处理结果信息，包含以下键值:
                  - file: 序列文件路径
                  - status: 处理状态 ("success" 或 "error")
                  - result_file: 结果文件路径 (仅在成功时存在)
                  - error: 错误信息 (仅在失败时存在)
                  - thread_id: 处理线程ID
                  - elapsed_time: 处理耗时(秒)
        """
        thread_id = threading.current_thread().ident
        start_time = time.time()
        
        try:
            # 获取文件名（不含扩展名）用于结果文件命名
            file_name = Path(sequence_file).stem
            result_file = Path("results") / f"{file_name}_blast_result.xml"
            
            # 调用任务开始回调
            if self.on_task_start:
                self.on_task_start(sequence_file)
            
            # 读取序列
            sequence = self.file_handler.read_sequence_file(str(sequence_file))
            
            # 准备BLAST参数
            blast_params = {}
            
            # 添加启用的参数
            if 'hitlist_size' in self.advanced_settings:
                blast_params['hitlist_size'] = self.advanced_settings['hitlist_size']
                
            if 'word_size' in self.advanced_settings:
                blast_params['word_size'] = self.advanced_settings['word_size']
                
            if 'evalue' in self.advanced_settings:
                blast_params['evalue'] = self.advanced_settings['evalue']
                
            if 'matrix_name' in self.advanced_settings:
                blast_params['matrix_name'] = self.advanced_settings['matrix_name']
                
            if 'filter' in self.advanced_settings:
                blast_params['filter'] = self.advanced_settings['filter']
                
            if 'alignments' in self.advanced_settings:
                blast_params['alignments'] = self.advanced_settings['alignments']
                
            if 'descriptions' in self.advanced_settings:
                blast_params['descriptions'] = self.advanced_settings['descriptions']
            
            # 执行BLAST搜索，传递参数
            result_handle = self.blast_executor.execute_with_retry(
                sequence, 
                **blast_params
            )
            
            # 保存结果到文件（使用序列文件名命名）
            self.file_handler.save_result_file(result_handle, str(result_file))
            result_handle.close()
            
            # 重新打开结果文件进行解析
            result_handle = open(result_file)
            result_handle.close()
            
            end_time = time.time()
            elapsed_time = end_time - start_time
            
            result = {
                "file": sequence_file,
                "status": "success",
                "result_file": result_file,
                "thread_id": thread_id,
                "elapsed_time": elapsed_time
            }
            
            return result
        except Exception as e:
            end_time = time.time()
            elapsed_time = end_time - start_time
            
            print(f"处理文件 {sequence_file} 时出错: {e}")
            result = {
                "file": sequence_file,
                "status": "error",
                "error": str(e),
                "thread_id": thread_id,
                "elapsed_time": elapsed_time
            }
            
            return result
    
    def process_sequences(self, sequence_files):
        """
        批量处理序列文件
        
        Args:
            sequence_files (list): 序列文件路径列表
            
        Returns:
            list: 处理结果列表
        """
        # 只有当有多个文件时才打印批量处理信息
        if len(sequence_files) > 1:
            print(f"开始批量处理 {len(sequence_files)} 个序列文件...")
            print(f"使用 {self.max_workers} 个线程进行处理")
        
        # 创建结果目录（如果不存在）
        Path("results").mkdir(exist_ok=True)
        
        # 使用线程池处理序列文件
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            # 提交所有任务
            future_to_file = {
                executor.submit(self.process_single_sequence, seq_file): seq_file
                for seq_file in sequence_files
            }
            
            # 收集结果
            results = []
            completed = 0
            total = len(sequence_files)
            
            for future in as_completed(future_to_file):
                # 更新进度
                if self.on_progress_update:
                    self.on_progress_update(completed, total)
                
                file = future_to_file[future]
                try:
                    result = future.result()
                    results.append(result)
                    if result["status"] == "success":
                        print(f"✓ 完成处理: {Path(file).name}")
                    else:
                        print(f"✗ 处理失败: {Path(file).name} - {result['error']}")
                    
                    # 发送结果（确保只发送一次）
                    if self.on_result_received:
                        self.on_result_received(result)
                except Exception as e:
                    print(f"✗ 处理 {file} 时发生异常: {e}")
                    error_result = {
                        "file": file,
                        "status": "error",
                        "error": str(e)
                    }
                    results.append(error_result)
                    if self.on_result_received:
                        self.on_result_received(error_result)
                
                # 更新完成计数
                completed += 1
                
                # 更新进度
                if self.on_progress_update:
                    self.on_progress_update(completed, total)
        
        # 调用所有任务完成回调
        if self.on_all_tasks_complete:
            self.on_all_tasks_complete(results)
            
        return results
    
    def print_summary(self, results):
        """
        打印处理结果总结
        
        Args:
            results (list): 处理结果列表
        """
        successful = sum(1 for r in results if r["status"] == "success")
        failed = len(results) - successful
        
        print(f"\n批量处理完成!")
        print(f"总共处理: {len(results)} 个文件")
        print(f"成功处理: {successful} 个文件")
        print(f"处理失败: {failed} 个文件")
        
        if failed > 0:
            print("\n失败的文件:")
            for result in results:
                if result["status"] == "error":
                    print(f"  - {Path(result['file']).name}: {result['error']}")
