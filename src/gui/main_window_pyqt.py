"""
PyQt主窗口模块
负责创建和管理主窗口界面
"""

import os
import sys
from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QMessageBox)

# 添加项目根目录到Python路径
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# 导入自定义组件
from src.gui.widgets.file_selector import FileSelectorWidget
from src.gui.widgets.parameter_settings import ParameterSettingsWidget
from src.gui.widgets.control_panel import ControlPanelWidget
from src.gui.widgets.result_viewer import ResultViewerWidget
from src.gui.widgets.detail_viewer import DetailViewerWidget
from src.gui.widgets.summary_panel import SummaryPanelWidget
from src.gui.threads.processing_thread import ProcessingThread
from src.blast.batch_processor import BatchProcessor


class MainWindow(QMainWindow):
    """
    PyQt主窗口类
    负责创建和管理GUI界面
    """
    
    def __init__(self):
        """
        初始化主窗口
        """
        super().__init__()
        self.setWindowTitle("NCBI BLAST 查询工具")
        self.setGeometry(100, 100, 1000, 700)
        
        # 初始化变量
        self.sequence_files = []
        self.results = []
        self.is_processing = False
        self.processing_thread = None
        self.batch_processor = None
        
        # 创建界面组件
        self._create_widgets()
        
        # 创建界面
        self._setup_ui()
        
        # 连接信号
        self._connect_signals()
    
    def _create_widgets(self):
        """创建界面组件"""
        self.file_selector = FileSelectorWidget()
        self.parameter_settings = ParameterSettingsWidget()
        self.control_panel = ControlPanelWidget()
        self.result_viewer = ResultViewerWidget()
        self.detail_viewer = DetailViewerWidget()
        self.summary_panel = SummaryPanelWidget()
    
    def _setup_ui(self):
        """
        初始化用户界面
        """
        # 创建中央部件
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # 创建主布局
        main_layout = QVBoxLayout()
        central_widget.setLayout(main_layout)
        
        # 将各个区域添加到主布局
        main_layout.addWidget(self.file_selector)
        main_layout.addWidget(self.parameter_settings)
        main_layout.addWidget(self.control_panel)
        main_layout.addWidget(self.result_viewer)
        main_layout.addWidget(self.detail_viewer)
        main_layout.addWidget(self.summary_panel)
    
    def _connect_signals(self):
        """连接信号"""
        # 文件选择器信号
        self.file_selector.signals.files_selected.connect(self._on_files_selected)
        
        # 控制面板信号
        self.control_panel.start_button.clicked.connect(self._start_processing)
        self.control_panel.stop_button.clicked.connect(self._stop_processing)
        
        # 结果查看器信号
        self.result_viewer.signals.item_selected.connect(self._on_item_selected)
        self.result_viewer.signals.item_double_clicked.connect(self._on_item_double_clicked)
    
    def _on_files_selected(self, files):
        """处理文件选择事件"""
        self.sequence_files = files
        self.result_viewer.update_result_tree(files)
    
    def _start_processing(self):
        """开始处理文件"""
        if not self.sequence_files:
            QMessageBox.warning(self, "警告", "请先选择序列文件")
            return
        
        if self.is_processing:
            QMessageBox.warning(self, "警告", "正在处理中，请等待完成")
            return
        
        try:
            max_workers = self.parameter_settings.get_thread_count()
            if max_workers < 1 or max_workers > 10:
                raise ValueError("线程数必须在1-10之间")
        except ValueError as e:
            QMessageBox.critical(self, "错误", f"线程数设置错误: {e}")
            return
        
        # 更新界面状态
        self.is_processing = True
        self.control_panel.enable_start_button(False)
        self.control_panel.enable_stop_button(True)
        self.control_panel.update_progress(0)
        
        # 清空之前的结果
        self.results = []
        
        # 创建并启动处理线程
        self.batch_processor = BatchProcessor(max_workers=max_workers)
        self.processing_thread = ProcessingThread(self.batch_processor, self.sequence_files)
        
        # 连接线程信号
        self.processing_thread.task_started.connect(self._on_task_start)
        self.processing_thread.progress_updated.connect(self._on_progress_update)
        self.processing_thread.result_received.connect(self._on_result_received)
        self.processing_thread.all_tasks_completed.connect(self._on_all_tasks_complete)
        self.processing_thread.processing_error.connect(self._on_processing_error)
        self.processing_thread.finished.connect(self._on_thread_finished)
        
        # 启动线程
        self.processing_thread.start()
    
    def _stop_processing(self):
        """停止处理"""
        if self.is_processing and self.batch_processor:
            # 设置取消标志
            self.batch_processor.cancel_processing()
            self.control_panel.set_status("正在取消处理...")
            self.control_panel.enable_stop_button(False)
    
    def _on_task_start(self, sequence_file):
        """处理任务开始事件"""
        self.control_panel.set_status(f"正在处理: {Path(sequence_file).name}")
    
    def _on_progress_update(self, completed, total):
        """处理进度更新事件"""
        if total > 0:
            progress = int((completed / total) * 100)
            self.control_panel.update_progress(progress, 100)
    
    def _on_result_received(self, result):
        """处理结果接收事件"""
        # 将结果添加到结果列表中
        self.results.append(result)
        
        # 更新树形视图中的状态
        self.result_viewer.update_file_status(result)
        
        # 更新统计信息
        self.summary_panel.update_summary(self.results)
    
    def _on_all_tasks_complete(self, total_tasks):
        """处理所有任务完成事件"""
        self.control_panel.set_status("处理完成")
        self.summary_panel.update_summary(self.results)
    
    def _on_processing_error(self, error_message):
        """处理错误事件"""
        # 更新界面状态
        self.is_processing = False
        self.control_panel.enable_start_button(True)
        self.control_panel.enable_stop_button(False)
        
        # 显示错误消息
        QMessageBox.critical(self, "处理出错", f"处理过程中发生错误:\n{error_message}")
        self.control_panel.set_status("处理出错")
    
    def _on_thread_finished(self):
        """处理线程结束事件"""
        # 更新界面状态
        self.is_processing = False
        self.control_panel.enable_start_button(True)
        self.control_panel.enable_stop_button(False)
        self.control_panel.update_progress(100, 100)
        
        # 显示完成消息
        successful = sum(1 for r in self.results if r["status"] == "success")
        QMessageBox.information(self, "处理完成", f"处理完成!\n成功: {successful}个文件\n失败: {len(self.results) - successful}个文件")
        self.control_panel.set_status("处理完成")
    
    def _on_item_selected(self, file_name):
        """处理项目选择事件"""
        self.detail_viewer.show_details(file_name, self.results)
    
    def _on_item_double_clicked(self, item, column):
        """处理项目双击事件"""
        # 如果是父节点，展开/折叠
        if item.parent() is None:
            item.setExpanded(not item.isExpanded())
