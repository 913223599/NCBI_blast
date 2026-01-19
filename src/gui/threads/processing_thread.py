"""
处理线程模块
负责在后台线程中处理序列文件
"""

from PyQt6.QtCore import QThread, pyqtSignal


class BaseProcessingThread(QThread):
    """
    处理线程基类
    """
    # 定义信号
    task_started = pyqtSignal(str)  # 任务开始信号，传递文件路径或序列ID
    progress_updated = pyqtSignal(int, int)  # 进度更新信号，传递已完成和总数
    result_received = pyqtSignal(dict)  # 结果接收信号，传递处理结果
    all_tasks_completed = pyqtSignal(int)  # 所有任务完成信号，传递总任务数
    processing_error = pyqtSignal(str)  # 处理错误信号，传递错误消息
    finished = pyqtSignal()  # 线程完成信号

    def __init__(self, processor, sequence_files):
        super().__init__()
        self.processor = processor
        self.sequence_files = sequence_files
        self._connect_processor_signals()

    def _connect_processor_signals(self):
        """连接处理器的回调函数"""
        self.processor.on_task_start = self._on_task_start
        self.processor.on_progress_update = self._on_progress_update
        self.processor.on_result_received = self._on_result_received
        self.processor.on_all_tasks_complete = self._on_all_tasks_complete

    def _on_task_start(self, info):
        """任务开始回调"""
        # 确保传入的是字符串而不是数字
        if isinstance(info, (int, float)):
            return
        self.task_started.emit(str(info))

    def _on_progress_update(self, completed, total):
        """进度更新回调"""
        self.progress_updated.emit(completed, total)

    def _on_result_received(self, result):
        """结果接收回调"""
        if isinstance(result, dict):
            self.result_received.emit(result)

    def _on_all_tasks_complete(self, total_tasks):
        """所有任务完成回调"""
        if isinstance(total_tasks, int):
            self.all_tasks_completed.emit(total_tasks)


class ProcessingThread(BaseProcessingThread):
    """
    处理线程类 (单文件单序列)
    """
    def run(self):
        try:
            # 开始处理序列文件
            results = self.processor.process_sequences(self.sequence_files)
            self.all_tasks_completed.emit(len(results))
        except Exception as e:
            self.processing_error.emit(str(e))
        finally:
            self.finished.emit()


class MultiSequenceProcessingThread(BaseProcessingThread):
    """
    多序列处理线程类 (单文件多序列)
    """
    def run(self):
        try:
            # 对每个包含多条序列的文件进行处理
            all_results = []
            for sequence_file in self.sequence_files:
                results = self.processor.process_sequences_from_file(sequence_file)
                all_results.extend(results)
            
            self.all_tasks_completed.emit(len(all_results))
        except Exception as e:
            self.processing_error.emit(str(e))
        finally:
            self.finished.emit()
