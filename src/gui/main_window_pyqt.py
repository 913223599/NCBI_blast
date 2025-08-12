"""
PyQt主窗口模块
负责创建和管理主窗口界面
"""

import os
import sys
from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSlot
from PyQt6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QMessageBox,
                             QPushButton, QHBoxLayout, QMenuBar, QMenu, QStatusBar, QSplitter)
from PyQt6.QtGui import QAction

# 添加项目根目录到Python路径
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# 导入自定义组件
from src.gui.widgets.file_selector import FileSelectorWidget
from src.gui.widgets.parameter_settings import ParameterSettingsWidget
from src.gui.widgets.control_panel import ControlPanelWidget
from src.gui.widgets.result_viewer import ResultViewerWidget
from src.gui.widgets.summary_panel import SummaryPanelWidget
from src.gui.widgets.translation_debugger import TranslationDebuggerDialog
from src.gui.widgets.help_dialog import HelpDialog
from src.gui.widgets.api_key_dialog import ApiKeyDialog
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
        self.translation_debugger = None  # 翻译调试器实例
        self.help_dialog = None  # 帮助文档对话框实例
        self.api_key_dialog = None  # API密钥设置对话框实例
        
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
        self.summary_panel = SummaryPanelWidget()
    
    def _setup_ui(self):
        """
        初始化用户界面
        """
        # 创建菜单栏
        self._create_menu_bar()
        
        # 创建中央部件
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # 创建主布局
        main_layout = QVBoxLayout(central_widget)
        
        # 创建水平分割器
        splitter = QSplitter(Qt.Orientation.Horizontal)
        
        # 左侧面板（文件选择和结果查看）
        left_panel = QWidget()
        left_layout = QVBoxLayout()
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_panel.setLayout(left_layout)
        left_layout.addWidget(self.file_selector)
        left_layout.addWidget(self.parameter_settings)
        left_layout.addWidget(self.control_panel)
        left_layout.addWidget(self.result_viewer)
        
        # 右侧面板（统计）
        self.right_panel = QWidget()
        right_layout = QVBoxLayout()
        self.right_panel.setLayout(right_layout)
        right_layout.addWidget(self.summary_panel)

        # 默认隐藏右侧面板
        self.right_panel.hide()
        self.control_panel.toggle_detail_button.setText("显示统计信息")
        
        # 添加面板到分割器
        splitter.addWidget(left_panel)
        splitter.addWidget(self.right_panel)
        splitter.setSizes([400, 200])  # 调整初始大小，因为不需要显示详细信息
        
        # 将分割器添加到主布局
        main_layout.addWidget(splitter)
        
        # 创建状态栏
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("就绪")
    
    def _create_menu_bar(self):
        """创建菜单栏"""
        menu_bar = QMenuBar(self)
        self.setMenuBar(menu_bar)
        
        # 文件菜单
        file_menu = QMenu("文件", self)
        menu_bar.addMenu(file_menu)
        
        # 设置菜单
        settings_menu = QMenu("设置", self)
        menu_bar.addMenu(settings_menu)
        
        # 帮助菜单
        help_menu = QMenu("帮助", self)
        menu_bar.addMenu(help_menu)
        
        # 添加菜单项
        open_translation_debugger_action = QAction("翻译调试器", self)
        open_translation_debugger_action.triggered.connect(self._open_translation_debugger)
        settings_menu.addAction(open_translation_debugger_action)
        
        open_settings_dialog_action = QAction("设置", self)
        open_settings_dialog_action.triggered.connect(self._open_settings_dialog)
        settings_menu.addAction(open_settings_dialog_action)
        
        open_help_dialog_action = QAction("帮助", self)
        open_help_dialog_action.triggered.connect(self._open_help_dialog)
        help_menu.addAction(open_help_dialog_action)
        
        open_api_key_dialog_action = QAction("API密钥", self)
        open_api_key_dialog_action.triggered.connect(self._open_api_key_dialog)
        help_menu.addAction(open_api_key_dialog_action)
    
    def _connect_signals(self):
        """连接信号"""
        # 文件选择器信号
        self.file_selector.files_selected.connect(self._on_files_selected)
        
        # 控制面板信号
        self.control_panel.start_button.clicked.connect(self._start_processing)
        self.control_panel.stop_button.clicked.connect(self._stop_processing)
        self.control_panel.toggle_detail_button.clicked.connect(self._toggle_detail_panel)  # 连接切换按钮信号
        
        # 结果查看器信号
        self.result_viewer.signals.item_selected.connect(self._on_item_selected)
        self.result_viewer.signals.retry_blast.connect(self._retry_blast)  # 连接重试BLAST信号
        
        # 处理线程信号
        if self.processing_thread:
            self.processing_thread.task_started.connect(self._on_task_start)
            self.processing_thread.progress_updated.connect(self.control_panel.update_progress)  # 确保这里正确连接
            self.processing_thread.result_received.connect(self._on_result_received)
            self.processing_thread.all_tasks_completed.connect(self._on_all_tasks_complete)
            self.processing_thread.processing_error.connect(self._on_processing_error)
            self.processing_thread.finished.connect(self._on_thread_finished)
    
    def _toggle_detail_panel(self):
        """切换统计信息面板显示/隐藏"""
        if self.right_panel.isVisible():
            self.right_panel.hide()
            self.control_panel.toggle_detail_button.setText("显示统计信息")
        else:
            self.right_panel.show()
            self.control_panel.toggle_detail_button.setText("隐藏统计信息")
    
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
        
        # 如果是通过文件选择器触发的开始处理，则清空之前的错误状态
        for file in self.sequence_files:
            self.result_viewer.update_file_status({
                "file": file,
                "status": "pending"
            })
        
        try:
            max_workers = self.parameter_settings.get_thread_count()
            if max_workers < 1 or max_workers > 10:
                raise ValueError("线程数必须在1-10之间")
        except ValueError as e:
            QMessageBox.critical(self, "错误", f"线程数设置错误: {e}")
            return
        
        # 获取高级参数设置
        advanced_settings = self.parameter_settings.get_advanced_settings()
        
        # 设置生物学翻译器参数
        translation_settings = {
            'use_ai': advanced_settings.get('use_ai_translation', True),
            'translator_type': advanced_settings.get('translator_type', 'default')  # 可以是 'default', 'ai_basic', 'ai_advanced' 等
        }
        
        # 获取API密钥（如果需要）
        api_key = None
        try:
            from src.utils.config_manager import get_config_manager
            config_manager = get_config_manager()
            api_key = config_manager.get_api_key('dashscope')
        except Exception as e:
            print(f"获取API密钥失败: {e}")
        
        # 设置结果查看器的翻译配置
        self.result_viewer.set_translation_settings(translation_settings, api_key)
        
        # 更新界面状态
        self.is_processing = True
        self.control_panel.enable_start_button(False)
        self.control_panel.enable_stop_button(True)
        self.control_panel.update_progress(0)
        
        # 清空之前的结果
        self.results = []
        
        # 创建并启动处理线程，传递高级参数
        self.batch_processor = BatchProcessor(
            max_workers=max_workers,
            advanced_settings=advanced_settings
        )
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
    
    @pyqtSlot()
    def _stop_processing(self):
        """停止处理"""
        if self.is_processing and self.batch_processor:
            # 设置取消标志
            self.batch_processor.cancel_processing()
            self.control_panel.set_status("正在取消处理...")
            self.control_panel.enable_stop_button(False)
            self.statusBar().showMessage("正在取消处理...")
    
    def _on_task_start(self, sequence_file):
        """处理任务开始事件"""
        file_name = Path(sequence_file).name
        self.control_panel.set_status(f"正在处理: {file_name}")
        self.statusBar().showMessage(f"正在处理: {file_name}")
    
    def _on_progress_update(self, completed, total):
        """处理进度更新事件"""
        if total > 0:
            progress = int((completed / total) * 100)
            self.control_panel.update_progress(progress, 100)
        else:
            self.control_panel.update_progress(0, 100)
    
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
        self.statusBar().showMessage("处理完成")
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
        self.statusBar().showMessage("处理出错")
    
    def _on_thread_finished(self):
        """处理线程结束事件"""
        # 更新界面状态
        self.is_processing = False
        self.control_panel.enable_start_button(True)
        self.control_panel.enable_stop_button(False)
        self.control_panel.update_progress(100, 100)
        
        # 显示完成消息
        successful = sum(1 for r in self.results if r["status"] == "success")
        self.control_panel.set_status(f"处理完成: 成功 {successful} 个文件")
        self.statusBar().showMessage(f"处理完成: 成功 {successful} 个文件")
    
    @pyqtSlot(str)
    def _on_item_selected(self, file_name):
        """处理项目选择事件（现在不执行任何操作，因为detail_viewer已被移除）"""
        pass

    @pyqtSlot(str)
    def _retry_blast(self, file_name):
        """重试BLAST搜索"""
        if self.is_processing:
            QMessageBox.warning(self, "警告", "正在处理中，请等待完成")
            return
        
        # 查找对应的文件路径
        file_path = None
        for result in self.results:
            result_file_name = Path(result.get("file", "")).name
            if result_file_name == file_name:
                file_path = result.get("file")
                break
        
        if not file_path:
            QMessageBox.warning(self, "重试失败", f"未找到文件 {file_name} 的路径信息")
            return
        
        try:
            max_workers = self.parameter_settings.get_thread_count()
            if max_workers < 1 or max_workers > 10:
                raise ValueError("线程数必须在1-10之间")
        except ValueError as e:
            QMessageBox.critical(self, "错误", f"线程数设置错误: {e}")
            return
        
        # 获取高级参数设置
        advanced_settings = self.parameter_settings.get_advanced_settings()
        
        # 获取API密钥（如果需要）
        api_key = None
        try:
            from src.utils.config_manager import get_config_manager
            config_manager = get_config_manager()
            api_key = config_manager.get_api_key('dashscope')
        except Exception as e:
            print(f"获取API密钥失败: {e}")
        
        # 更新界面状态
        self.is_processing = True
        self.control_panel.enable_start_button(False)
        self.control_panel.enable_stop_button(True)
        self.control_panel.update_progress(0)
        self.control_panel.set_status(f"正在重试: {file_name}")
        self.statusBar().showMessage(f"正在重试: {file_name}")
        
        # 设置结果查看器的翻译配置
        self.result_viewer.set_translation_settings(translation_settings, api_key)
        
        # 创建并启动处理线程，传递高级参数
        self.batch_processor = BatchProcessor(
            max_workers=max_workers,
            advanced_settings=advanced_settings
        )
        
        # 只处理需要重试的单个文件
        self.processing_thread = ProcessingThread(self.batch_processor, [file_path])
        
        # 连接线程信号
        self.processing_thread.task_started.connect(self._on_task_start)
        self.processing_thread.progress_updated.connect(self._on_progress_update)
        self.processing_thread.result_received.connect(self._on_result_received)
        self.processing_thread.all_tasks_completed.connect(self._on_all_tasks_complete)
        self.processing_thread.processing_error.connect(self._on_processing_error)
        self.processing_thread.finished.connect(self._on_thread_finished)
        
        # 启动线程
        self.processing_thread.start()

    def _open_translation_debugger(self):
        """打开翻译调试器"""
        if not self.translation_debugger:
            self.translation_debugger = TranslationDebuggerDialog()
        self.translation_debugger.show()
        self.translation_debugger.raise_()
        self.translation_debugger.activateWindow()
        
    def _open_settings_dialog(self):
        """打开设置对话框"""
        # TODO: 实现设置对话框
        pass
    
    def _open_help_dialog(self):
        """打开帮助文档对话框"""
        if not self.help_dialog:
            self.help_dialog = HelpDialog()
        self.help_dialog.show()
        self.help_dialog.raise_()
        self.help_dialog.activateWindow()
    
    def _open_api_key_dialog(self):
        """打开API密钥设置对话框"""
        if not self.api_key_dialog:
            self.api_key_dialog = ApiKeyDialog()
        self.api_key_dialog.show()
        self.api_key_dialog.raise_()
        self.api_key_dialog.activateWindow()
    
    def closeEvent(self, event):
        """处理窗口关闭事件"""
        # 如果有正在运行的工作线程，询问用户是否确定关闭
        if self.is_processing:
            reply = QMessageBox.question(
                self,
                "确认退出",
                "有处理任务正在运行，确定要退出吗？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
                
            if reply == QMessageBox.StandardButton.Yes:
                # 终止工作线程
                if self.processing_thread:
                    self.processing_thread.terminate()
                    self.processing_thread.wait()
                event.accept()
            else:
                event.ignore()
        else:
            event.accept()