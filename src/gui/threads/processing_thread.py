"""
处理线程模块
负责在后台执行BLAST处理任务
"""

from PyQt6.QtCore import QThread, pyqtSignal
from src.blast.batch_processor import BatchProcessor


class ProcessingThread(QThread):
    """
    处理线程类
    """
    progress_updated = pyqtSignal(int, int)  # completed, total
    task_started = pyqtSignal(str)  # sequence_file
    result_received = pyqtSignal(dict)  # result
    all_tasks_completed = pyqtSignal(int)  # total_tasks
    processing_error = pyqtSignal(str)  # error_message
    
    def __init__(self, batch_processor, sequence_files):
        super().__init__()
        self.batch_processor = batch_processor
        self.sequence_files = sequence_files
        self.setup_batch_processor_callbacks()
    
    def setup_batch_processor_callbacks(self):
        """
        设置批处理处理器的回调函数
        """
        self.batch_processor.on_task_start = self.on_task_start
        self.batch_processor.on_progress_update = self.on_progress_update
        self.batch_processor.on_result_received = self.on_result_received
        self.batch_processor.on_all_tasks_complete = self.on_all_tasks_complete
    
    def run(self):
        """
        线程执行函数
        """
        try:
            self.results = self.batch_processor.process_sequences(self.sequence_files)
            # 发送所有任务完成信号，传递结果数量
            self.all_tasks_completed.emit(len(self.results))
        except Exception as e:
            self.processing_error.emit(str(e))
    
    def on_task_start(self, sequence_file):
        """
        任务开始回调
        
        Args:
            sequence_file (str): 序列文件路径
        """
        # 确保传入的是字符串而不是数字
        if isinstance(sequence_file, (int, float)):
            # 如果是数字，可能是任务总数，忽略它
            return
            
        self.task_started.emit(str(sequence_file))
    
    def on_progress_update(self, completed, total):
        """
        进度更新回调
        
        Args:
            completed (int): 已完成的任务数
            total (int): 总任务数
        """
        self.progress_updated.emit(completed, total)
    
    def on_result_received(self, result):
        """
        结果接收回调
        
        Args:
            result (dict): 处理结果
        """
        # 确保结果是字典类型
        if isinstance(result, dict):
            self.result_received.emit(result)
    
    def on_all_tasks_complete(self, total_tasks):
        """
        所有任务完成回调
        
        Args:
            total_tasks (int): 总任务数
        """
        # 确保total_tasks是整数类型
        if isinstance(total_tasks, int):
            self.all_tasks_completed.emit(total_tasks)
