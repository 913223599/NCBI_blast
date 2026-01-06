"""
处理线程模块
负责在后台线程中处理序列文件
"""

from PyQt6.QtCore import QThread, pyqtSignal
from src.blast.batch_processor import BatchProcessor, MultiSequenceBatchProcessor


class ProcessingThread(QThread):
    """
    处理线程类
    负责在后台线程中处理序列文件
    """
    
    # 定义信号
    task_started = pyqtSignal(str)  # 任务开始信号，传递文件路径
    progress_updated = pyqtSignal(int, int)  # 进度更新信号，传递已完成和总数
    result_received = pyqtSignal(dict)  # 结果接收信号，传递处理结果
    all_tasks_completed = pyqtSignal(int)  # 所有任务完成信号，传递总任务数
    processing_error = pyqtSignal(str)  # 处理错误信号，传递错误消息
    finished = pyqtSignal()  # 线程完成信号
    
    def __init__(self, batch_processor, sequence_files):
        """
        初始化处理线程
        
        Args:
            batch_processor: 批量处理器实例
            sequence_files (list): 序列文件路径列表
        """
        super().__init__()
        self.batch_processor = batch_processor
        self.sequence_files = sequence_files
        
        # 连接批量处理器的回调函数
        self.batch_processor.on_task_start = self._on_task_start
        self.batch_processor.on_progress_update = self._on_progress_update
        self.batch_processor.on_result_received = self._on_result_received
        self.batch_processor.on_all_tasks_complete = self._on_all_tasks_complete
    
    def run(self):
        """
        线程执行的主要方法
        """
        try:
            # 开始处理序列文件
            results = self.batch_processor.process_sequences(self.sequence_files)
            
            # 发送完成信号
            self.all_tasks_completed.emit(len(results))
        except Exception as e:
            # 发送错误信号
            self.processing_error.emit(str(e))
        finally:
            # 发送完成信号
            self.finished.emit()
    
    def _on_task_start(self, sequence_file):
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
    
    def _on_progress_update(self, completed, total):
        """
        进度更新回调
        
        Args:
            completed (int): 已完成的任务数
            total (int): 总任务数
        """
        self.progress_updated.emit(completed, total)
    
    def _on_result_received(self, result):
        """
        结果接收回调
        
        Args:
            result (dict): 处理结果
        """
        # 确保结果是字典类型
        if isinstance(result, dict):
            self.result_received.emit(result)
    
    def _on_all_tasks_complete(self, total_tasks):
        """
        所有任务完成回调
        
        Args:
            total_tasks (int): 总任务数
        """
        # 确保total_tasks是整数类型
        if isinstance(total_tasks, int):
            self.all_tasks_completed.emit(total_tasks)


class MultiSequenceProcessingThread(QThread):
    """
    多序列处理线程类
    负责在后台线程中处理包含多个序列的单个文件
    """
    
    # 定义信号
    task_started = pyqtSignal(str)  # 任务开始信号，传递文件路径和序列ID
    progress_updated = pyqtSignal(int, int)  # 进度更新信号，传递已完成和总数
    result_received = pyqtSignal(dict)  # 结果接收信号，传递处理结果
    all_tasks_completed = pyqtSignal(int)  # 所有任务完成信号，传递总任务数
    processing_error = pyqtSignal(str)  # 处理错误信号，传递错误消息
    finished = pyqtSignal()  # 线程完成信号
    
    def __init__(self, multi_sequence_processor, sequence_files):
        """
        初始化多序列处理线程
        
        Args:
            multi_sequence_processor: 多序列批量处理器实例
            sequence_files (list): 序列文件路径列表
        """
        super().__init__()
        self.multi_sequence_processor = multi_sequence_processor
        self.sequence_files = sequence_files
        
        # 连接批量处理器的回调函数
        self.multi_sequence_processor.on_task_start = self._on_task_start
        self.multi_sequence_processor.on_progress_update = self._on_progress_update
        self.multi_sequence_processor.on_result_received = self._on_result_received
        self.multi_sequence_processor.on_all_tasks_complete = self._on_all_tasks_complete
    
    def run(self):
        """
        线程执行的主要方法
        """
        try:
            # 对每个包含多条序列的文件进行处理
            all_results = []
            for sequence_file in self.sequence_files:
                results = self.multi_sequence_processor.process_sequences_from_file(sequence_file)
                all_results.extend(results)
            
            # 发送完成信号
            self.all_tasks_completed.emit(len(all_results))
        except Exception as e:
            # 发送错误信号
            self.processing_error.emit(str(e))
        finally:
            # 发送完成信号
            self.finished.emit()
    
    def _on_task_start(self, sequence_identifier):
        """
        任务开始回调
        
        Args:
            sequence_identifier (str): 序列标识符（文件路径和序列ID）
        """
        # 确保传入的是字符串
        if isinstance(sequence_identifier, (int, float)):
            # 如果是数字，可能是任务总数，忽略它
            return
            
        self.task_started.emit(str(sequence_identifier))
    
    def _on_progress_update(self, completed, total):
        """
        进度更新回调
        
        Args:
            completed (int): 已完成的任务数
            total (int): 总任务数
        """
        self.progress_updated.emit(completed, total)
    
    def _on_result_received(self, result):
        """
        结果接收回调
        
        Args:
            result (dict): 处理结果
        """
        # 确保结果是字典类型
        if isinstance(result, dict):
            self.result_received.emit(result)
    
    def _on_all_tasks_complete(self, total_tasks):
        """
        所有任务完成回调
        
        Args:
            total_tasks (int): 总任务数
        """
        # 确保total_tasks是整数类型
        if isinstance(total_tasks, int):
            self.all_tasks_completed.emit(total_tasks)