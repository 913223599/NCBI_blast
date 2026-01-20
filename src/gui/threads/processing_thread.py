"""
处理线程模块
负责在后台线程中处理序列文件
"""

import logging
import traceback
from PyQt6.QtCore import QThread, pyqtSignal

# 配置日志
logger = logging.getLogger(__name__)

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
        # 这里的 total_tasks 可能是结果列表，也可能是数字
        if isinstance(total_tasks, list):
            self.all_tasks_completed.emit(len(total_tasks))
        elif isinstance(total_tasks, int):
            self.all_tasks_completed.emit(total_tasks)


class ProcessingThread(BaseProcessingThread):
    """
    处理线程类 (单文件单序列)
    """
    def run(self):
        try:
            logger.info(f"ProcessingThread started with {len(self.sequence_files)} files")
            # 开始处理序列文件
            results = self.processor.process_sequences(self.sequence_files)
            # 信号已在回调中发出，这里不需要再次发出 all_tasks_completed，除非回调未触发
            # 但为了保险起见，如果回调未被正确调用，这里可以补发
            # self.all_tasks_completed.emit(len(results)) 
        except Exception as e:
            logger.error(f"ProcessingThread error: {e}")
            logger.debug(traceback.format_exc())
            self.processing_error.emit(str(e))
        finally:
            self.finished.emit()


class MultiSequenceProcessingThread(BaseProcessingThread):
    """
    多序列处理线程类 (单文件多序列)
    """
    def run(self):
        try:
            logger.info(f"MultiSequenceProcessingThread started with {len(self.sequence_files)} files")
            
            # [修改] 使用 process_multiple_files 统一处理所有文件
            # 这允许线程池在所有文件的所有序列之间共享，实现更好的负载均衡
            if hasattr(self.processor, 'process_multiple_files'):
                self.processor.process_multiple_files(self.sequence_files)
            else:
                # 降级处理：逐个文件处理（旧逻辑）
                for sequence_file in self.sequence_files:
                    if self.isInterruptionRequested():
                        break
                    self.processor.process_sequences_from_file(sequence_file)

        except Exception as e:
            logger.error(f"MultiSequenceProcessingThread error: {e}")
            logger.debug(traceback.format_exc())
            self.processing_error.emit(str(e))
        finally:
            self.finished.emit()
