"""
PyQt主窗口模块
负责创建和管理主窗口界面
"""

import os
import sys
import json
from pathlib import Path

from PyQt6.QtCore import pyqtSlot, QTimer
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import (QMainWindow, QMenuBar, QMenu, QWidget, QVBoxLayout, QStatusBar, QMessageBox, QDialog,
                             QApplication, QHBoxLayout, QFrame)

# 添加项目根目录到Python路径
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# 导入自定义组件
from src.gui.widgets.file_selector import FileSelectorWidget
from src.gui.widgets.parameter_settings import ParameterSettingsWidget
from src.gui.widgets.control_panel import ControlPanelWidget
from src.gui.widgets.result_viewer import ResultViewerWidget
from src.gui.widgets.translation_debugger import TranslationDebuggerDialog
from src.gui.widgets.help_dialog import HelpDialog
from src.gui.widgets.api_key_dialog import ApiKeyDialog
from src.gui.widgets.history_dialog import HistoryDialog  # 导入历史记录对话框
from src.gui.widgets.database_manager_dialog import DatabaseManagerDialog # 导入数据库管理对话框
from src.gui.widgets.task_name_dialog import TaskNameDialog # 导入任务命名对话框
from src.gui.threads.processing_thread import ProcessingThread, MultiSequenceProcessingThread
from src.blast.batch_processor import BatchProcessor, MultiSequenceBatchProcessor


def ensure_results_folders():
    """
    确保results文件夹存在
    只在项目根目录下创建results文件夹
    """
    try:
        # 确保项目根目录下的results文件夹存在
        root_results_path = Path(project_root) / "results"
        if not root_results_path.exists():
            root_results_path.mkdir(parents=True, exist_ok=True)
            print(f"已创建项目根目录results文件夹: {root_results_path}")
        else:
            print(f"项目根目录results文件夹已存在: {root_results_path}")
            
    except Exception as e:
        print(f"确保results文件夹存在时出错: {e}")


class MainWindow(QMainWindow):
    """
    重构后的现代化 UI 主窗口
    采用 侧边栏(输入) + 主视图(输出) 的布局结构
    """
    
    def __init__(self):
        super().__init__()
        self.setWindowTitle("NCBI BLAST Pro | 生物序列分析工作站") # 稍微高大上一点的标题
        self.resize(1200, 800) #稍微加大初始尺寸以适应侧边栏
        
        ensure_results_folders()
        
        # 初始化变量 (保持不变)
        self.sequence_files = []
        self.results = []
        self.is_processing = False
        self.is_cancelling = False # [新增] 标记是否正在取消中
        self.processing_thread = None
        self.batch_processor = None
        self.translation_debugger = None
        self.help_dialog = None
        self.api_key_dialog = None
        self.history_dialog = None # 初始化历史记录对话框变量
        self.db_manager_dialog = None # 初始化数据库管理对话框变量
        
        # 1. 应用现代化皮肤
        self._apply_modern_theme()
        
        # 2. 创建组件 (保持不变，但稍后会被放入不同容器)
        self._create_widgets()
        
        # 3. 布局界面 (核心修改点)
        self._setup_modern_ui()
        
        # 4. 连接信号 (保持不变)
        self._connect_signals()

    def _apply_modern_theme(self):
        """应用全局 QSS 样式表 - 按钮背景图版"""
        self.setStyleSheet("""
            QMainWindow {
                background-color: #f0f2f5;
            }
            QWidget {
                font-family: 'Segoe UI', 'Microsoft YaHei', sans-serif;
                font-size: 14px;
                color: #2c3e50;
            }

            /* 卡片容器通用样式 */
            QFrame#Sidebar, QFrame#ContentArea {
                background-color: transparent;
                border: none;
            }
            QFrame#Card {
                background-color: #ffffff;
                border-radius: 10px;
                border: 1px solid #e0e0e0;
            }

            /* 分组框优化 */
            QGroupBox {
                border: 1px solid #dcdfe6;
                border-radius: 6px;
                margin-top: 12px;
                padding-top: 10px;
                font-weight: bold;
                background-color: white;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;
                padding: 0 5px;
                color: #409eff;
            }

            /* 按钮美化 */
            QPushButton {
                background-color: #ffffff;
                border: 1px solid #dcdfe6;
                border-radius: 4px;
                padding: 6px 15px;
                color: #606266;
            }
            QPushButton:hover {
                color: #409eff;
                border-color: #c6e2ff;
                background-color: #ecf5ff;
            }
            QPushButton:pressed {
                background-color: #dbeeff;
            }

            /* 状态栏 */
            QStatusBar {
                background-color: #ffffff;
                color: #909399;
                border-top: 1px solid #e4e7ed;
            }

            QSplitter::handle {
                background-color: #e4e7ed;
            }
            
            /* 树形控件样式 - 包括悬停和选择效果 */
            QTreeWidget {
                border: 1px solid #dcdfe6;
                background-color: #ffffff;
                alternate-background-color: #f9f9f9;
            }
            
            QTreeWidget::item {
                border: 1px solid transparent;
                padding: 4px;
            }
            
            QTreeWidget::item:hover {
                background-color: #e3f2fd; /* 淡蓝色悬停效果 */
                border: 1px solid #bbdefb;
                border-radius: 4px;
            }
            
            QTreeWidget::item:selected {
                background-color: #d0e7ff;
                color: #2c3e50;
            }
            
            QTreeWidget::item:selected:active {
                background-color: #bbdcff;
            }
            
            QTreeWidget::item:selected:!active {
                background-color: #d0e7ff;
            }
        """)
    def _create_widgets(self):
        """创建界面组件 (保持原有逻辑)"""
        self.file_selector = FileSelectorWidget()
        self.parameter_settings = ParameterSettingsWidget()
        self.control_panel = ControlPanelWidget()
        self.result_viewer = ResultViewerWidget()
        
        # 针对特定组件的样式微调 (可选)
        # 这里可以给特定组件设置 objectName 以便在 QSS 中单独控制
        self.file_selector.setObjectName("FileSelector")

    def _setup_modern_ui(self):
        """
        核心重构：构建 侧边栏 + 主内容区 的布局
        """
        self._create_menu_bar()
        
        # 主容器
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QHBoxLayout(central_widget) # 改为水平布局
        main_layout.setContentsMargins(15, 15, 15, 15)
        main_layout.setSpacing(15)
        
        # --- 左侧：侧边栏 (Sidebar) ---
        sidebar_frame = QFrame()
        sidebar_frame.setObjectName("Sidebar")
        sidebar_frame.setFixedWidth(380) # 固定宽度，显得整洁
        sidebar_layout = QVBoxLayout(sidebar_frame)
        sidebar_layout.setContentsMargins(0, 0, 0, 0)
        sidebar_layout.setSpacing(15)
        
        # 1. 文件选择卡片
        file_card = self._wrap_in_card(self.file_selector)
        # 2. 参数设置卡片
        param_card = self._wrap_in_card(self.parameter_settings)
        
        sidebar_layout.addWidget(file_card, 1) # 权重1，稍微占点空间
        sidebar_layout.addWidget(param_card, 2) # 权重2，参数通常比较长
        
        # --- 右侧：主工作区 (Content Area) ---
        content_frame = QFrame()
        content_frame.setObjectName("ContentArea")
        content_layout = QVBoxLayout(content_frame)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(15)
        
        # 1. 顶部控制栏卡片 (进度条、开始按钮)
        control_card = self._wrap_in_card(self.control_panel)
        control_card.setFixedHeight(100) # 恢复高度
        
        # 2. 核心结果区 (仅结果查看器)
        result_container = self._wrap_in_card(self.result_viewer)
        
        content_layout.addWidget(control_card)
        content_layout.addWidget(result_container)
        
        # 将左右两部分加入主布局
        main_layout.addWidget(sidebar_frame)
        main_layout.addWidget(content_frame)
        
        # 状态栏
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("系统就绪")

    def _wrap_in_card(self, widget):
        """辅助函数：将任何组件包裹在一个白色圆角卡片中"""
        card = QFrame()
        card.setObjectName("Card")
        
        # 添加阴影效果 (可选，稍微增加质感)
        from PyQt6.QtWidgets import QGraphicsDropShadowEffect
        from PyQt6.QtGui import QColor
        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(15)
        shadow.setColor(QColor(0, 0, 0, 20)) # 淡淡的黑色阴影
        shadow.setOffset(0, 2)
        card.setGraphicsEffect(shadow)
        
        layout = QVBoxLayout(card)
        layout.setContentsMargins(10, 10, 10, 10) # 卡片内边距
        layout.addWidget(widget)
        return card
    
    def _create_menu_bar(self):
        """创建菜单栏"""
        menu_bar = QMenuBar(self)
        self.setMenuBar(menu_bar)
        
        # 文件菜单
        file_menu = QMenu("文件", self)
        menu_bar.addMenu(file_menu)
        
        # 分析菜单
        analysis_menu = QMenu("分析", self)
        menu_bar.addMenu(analysis_menu)
        
        # 设置菜单
        settings_menu = QMenu("设置", self)
        menu_bar.addMenu(settings_menu)
        
        # 帮助菜单
        help_menu = QMenu("帮助", self)
        menu_bar.addMenu(help_menu)
        
        # 添加菜单项
        open_history_action = QAction("任务历史记录", self)
        open_history_action.triggered.connect(self._open_history_dialog)
        file_menu.addAction(open_history_action)

        open_db_manager_action = QAction("本地数据库管理", self)
        open_db_manager_action.triggered.connect(self._open_db_manager_dialog)
        settings_menu.addAction(open_db_manager_action)

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
    

    
    def _on_files_selected(self, files):
        """处理文件选择事件"""
        print(f"选择了 {len(files)} 个文件: {[Path(f).name for f in files]}")
        
        # 更新序列文件列表
        self.sequence_files = files
        
        # 更新结果树显示所有选中的文件
        self.result_viewer.update_sequence_files(files)  # 使用新的方法来显示所有文件
        
        # 更新状态栏
        self.status_bar.showMessage(f"已选择 {len(files)} 个序列文件", 3000)
        
        # 强制刷新UI
        self.result_viewer.update()  # 更新结果查看器
        self.update()  # 更新主窗口
    
    def _create_processor_and_thread(self, file_paths, task_name=None):
        """
        工厂方法：根据文件内容创建合适的处理器和线程
        统一了 _start_processing 和 _retry_blast 的逻辑
        """
        # 获取配置
        try:
            max_workers = self.parameter_settings.get_thread_count()
            if not (1 <= max_workers <= 50):
                raise ValueError("线程数必须在1-50之间")
        except ValueError as e:
            QMessageBox.critical(self, "错误", f"线程数设置错误: {e}")
            return None, None

        advanced_settings = self.parameter_settings.get_advanced_settings()

        # 检查是否需要多序列处理
        has_multi_sequence = False
        try:
            from src.utils.file_handler import FileHandler
            file_handler = FileHandler()
            for f in file_paths:
                seqs = file_handler.read_fasta_file(f)
                if len(seqs) > 1:
                    has_multi_sequence = True
                    break
        except Exception as e:
            print(f"文件检查警告: {e}")
            # 出错时默认使用普通处理或根据需求降级

        # 动态导入以避免循环依赖
        from src.blast.batch_processor import BatchProcessor, MultiSequenceBatchProcessor
        from src.gui.threads.processing_thread import ProcessingThread, MultiSequenceProcessingThread

        if has_multi_sequence:
            processor = MultiSequenceBatchProcessor(max_workers=max_workers, advanced_settings=advanced_settings, task_name=task_name)
            thread = MultiSequenceProcessingThread(processor, file_paths)
        else:
            processor = BatchProcessor(max_workers=max_workers, advanced_settings=advanced_settings, task_name=task_name)
            thread = ProcessingThread(processor, file_paths)
            
        return processor, thread

    def _start_processing(self):
        """优化后的开始处理"""
        current_files = self.file_selector.get_selected_files()
        self.sequence_files = current_files
        
        if not self.sequence_files:
            QMessageBox.warning(self, "警告", "请先选择序列文件")
            return
        
        if self.is_processing:
            QMessageBox.warning(self, "警告", "正在处理中，请等待完成")
            return

        # 弹出任务命名对话框
        task_dialog = TaskNameDialog(self)
        if task_dialog.exec() != QDialog.DialogCode.Accepted:
            return # 用户取消
            
        task_name = task_dialog.get_task_name()

        # 更新UI状态
        for file in self.sequence_files:
            self.result_viewer.update_file_status({
                "file": file, "status": "processing", "elapsed_time": 0
            })
        
        # 配置翻译设置 (保持原有逻辑)
        self._setup_translation_settings()

        # 创建处理器和线程
        self.batch_processor, self.processing_thread = self._create_processor_and_thread(self.sequence_files, task_name)
        
        if not self.batch_processor:
            return # 创建失败（如配置错误）

        # 设置UI控制状态
        self.is_processing = True
        self.is_cancelling = False # 重置取消状态
        self.control_panel.enable_start_button(False)
        self.control_panel.enable_stop_button(True)
        self.control_panel.set_stop_button_text("停止处理") # 恢复按钮文本
        self.control_panel.update_progress(0)
        
        # [新增] 设置文件选择器为处理状态
        self.file_selector.set_processing_state(True)
        
        self.results = []

        # 连接并启动
        self._connect_thread_signals()
        self.processing_thread.start()
    
    @pyqtSlot()
    def _stop_processing(self):
        """停止处理 - 两阶段逻辑"""
        if not self.is_processing:
            return

        # 第一阶段：请求取消
        if not self.is_cancelling:
            if self.batch_processor:
                # 设置取消标志
                self.batch_processor.cancel_processing()
                
            self.is_cancelling = True
            self.control_panel.set_status("正在取消处理... (再次点击强制终止)")
            self.statusBar().showMessage("正在取消处理... (再次点击强制终止)")
            self.control_panel.set_stop_button_text("强制终止")
            
        # 第二阶段：强制终止
        else:
            reply = QMessageBox.question(
                self,
                "强制终止",
                "确定要强制终止所有任务吗？\n这可能会导致当前正在进行的网络请求中断。",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            
            if reply == QMessageBox.StandardButton.Yes:
                self.control_panel.set_status("正在强制终止...")
                if self.processing_thread and self.processing_thread.isRunning():
                    # [关键修复] 断开信号，防止 terminate 后触发信号导致崩溃
                    try:
                        self.processing_thread.task_started.disconnect()
                        self.processing_thread.progress_updated.disconnect()
                        self.processing_thread.result_received.disconnect()
                        self.processing_thread.all_tasks_completed.disconnect()
                        self.processing_thread.processing_error.disconnect()
                        self.processing_thread.finished.disconnect()
                    except Exception as e:
                        print(f"断开信号时出错: {e}")

                    self.processing_thread.terminate()
                    self.processing_thread.wait()
                
                # 手动触发结束清理
                self._on_thread_finished()
                self.control_panel.set_status("已强制终止")
                self.statusBar().showMessage("已强制终止")
    
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
        

    
    def _on_all_tasks_complete(self, total_tasks):
        """处理所有任务完成事件"""
        self.control_panel.set_status("处理完成")
        self.statusBar().showMessage("处理完成")

    
    def _on_processing_error(self, error_message):
        """处理错误事件"""
        # 更新界面状态
        self.is_processing = False
        self.is_cancelling = False
        self.control_panel.enable_start_button(True)
        self.control_panel.enable_stop_button(False)
        self.control_panel.set_stop_button_text("停止处理")
        
        # [新增] 恢复文件选择器状态
        self.file_selector.set_processing_state(False)
        
        # 显示错误消息
        QMessageBox.critical(self, "处理出错", f"处理过程中发生错误:\n{error_message}")
        self.control_panel.set_status("处理出错")
        self.statusBar().showMessage("处理出错")
    
    def _on_thread_finished(self):
        """处理线程结束事件"""
        # 更新界面状态
        self.is_processing = False
        self.is_cancelling = False
        self.control_panel.enable_start_button(True)
        self.control_panel.enable_stop_button(False)
        self.control_panel.set_stop_button_text("停止处理")
        
        # [新增] 恢复文件选择器状态
        self.file_selector.set_processing_state(False)
        
        # 如果是取消状态，显示取消消息
        if self.batch_processor and self.batch_processor._cancel_flag:
            self.control_panel.set_status("处理已取消")
            self.statusBar().showMessage("处理已取消")
            self.control_panel.update_progress(0, 0) # 重置进度条
        else:
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
    def _setup_translation_settings(self):
        """辅助方法：配置翻译设置"""
        advanced_settings = self.parameter_settings.get_advanced_settings()
        translation_settings = {
            'use_ai': advanced_settings.get('use_ai_translation', True),
            'translator_type': advanced_settings.get('translator_type', 'default'),
            'ai_model': advanced_settings.get('ai_translation_model', 'deepseek-r1')
        }
        
        api_key = None
        try:
            from src.utils.config_manager import get_config_manager
            api_key = get_config_manager().get_api_key('dashscope')
        except Exception:
            pass
            
        self.result_viewer.set_translation_settings(translation_settings, api_key)

    def _connect_thread_signals(self):
        """辅助方法：连接线程信号"""
        if self.processing_thread:
            self.processing_thread.task_started.connect(self._on_task_start)
            self.processing_thread.progress_updated.connect(self._on_progress_update)
            self.processing_thread.result_received.connect(self._on_result_received)
            self.processing_thread.all_tasks_completed.connect(self._on_all_tasks_complete)
            self.processing_thread.processing_error.connect(self._on_processing_error)
            self.processing_thread.finished.connect(self._on_thread_finished)

    def _retry_blast(self, file_name):
        """优化后的重试逻辑"""
        if self.is_processing:
            return
            
        # 查找文件路径
        file_path = next((res.get("file") for res in self.results if Path(res.get("file", "")).name == file_name), None)
        if not file_path:
             QMessageBox.warning(self, "错误", "找不到原文件路径")
             return

        self._setup_translation_settings()
        
        # 复用工厂方法
        self.batch_processor, self.processing_thread = self._create_processor_and_thread([file_path])
        
        if not self.batch_processor:
            return

        self.is_processing = True
        self.is_cancelling = False
        self.control_panel.enable_start_button(False)
        self.control_panel.enable_stop_button(True)
        self.control_panel.set_stop_button_text("停止处理")
        self.control_panel.set_status(f"正在重试: {file_name}")
        
        # [新增] 设置文件选择器为处理状态
        self.file_selector.set_processing_state(True)
        
        self._connect_thread_signals()
        self.processing_thread.start()

    def _open_translation_debugger(self):
        """打开翻译调试器"""
        if not self.translation_debugger:
            self.translation_debugger = TranslationDebuggerDialog()
        self.translation_debugger.show()
        self.translation_debugger.raise_()
        self.translation_debugger.activateWindow()

    def _open_settings_dialog(self):
        """打开设置对话框 - 修复版"""
        from src.gui.widgets.parameter_settings import AdvancedSettingsDialog
        from src.utils.config_manager import get_config_manager

        dialog = AdvancedSettingsDialog(self)

        # 1. 获取当前所有高级设置
        # [关键修复] 不要过滤掉 AI 设置，否则弹窗无法显示当前状态
        current_settings = self.parameter_settings.get_advanced_settings()
        dialog.set_settings(current_settings)

        # 2. [关键修复] 只调用一次 exec()
        if dialog.exec() == QDialog.DialogCode.Accepted:
            # 3. 获取用户修改后的新设置
            new_settings = dialog.get_settings()

            # 4. 更新内存中的参数组件 (确保侧边栏等组件拿到最新值)
            self.parameter_settings.set_advanced_settings(new_settings)

            # 5. 保存到配置文件 config.json
            config_manager = get_config_manager()
            config_manager.set_advanced_settings(new_settings)

            # 6. 更新状态栏提示
            if hasattr(self, 'status_bar'):
                self.status_bar.showMessage("高级参数已保存", 3000)
            print(f"配置已更新并保存: {new_settings}")
    
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

    def _open_history_dialog(self):
        """打开历史记录对话框"""
        if not self.history_dialog:
            self.history_dialog = HistoryDialog(self)
            self.history_dialog.load_history_signal.connect(self._load_task_history)
        
        # 每次打开都刷新数据
        self.history_dialog._load_data()
        self.history_dialog.show()
        self.history_dialog.raise_()
        self.history_dialog.activateWindow()

    def _open_db_manager_dialog(self):
        """打开数据库管理对话框"""
        if not self.db_manager_dialog:
            self.db_manager_dialog = DatabaseManagerDialog(self)
        
        self.db_manager_dialog.show()
        self.db_manager_dialog.raise_()
        self.db_manager_dialog.activateWindow()

    def _load_task_history(self, result_dir):
        """加载任务历史记录"""
        print(f"加载任务历史: {result_dir}")
        QTimer.singleShot(100, lambda: self._do_load_task_history(result_dir))

    def _do_load_task_history(self, result_dir):
        """实际执行加载任务历史的操作"""
        try:
            result_path = Path(result_dir)
            if not result_path.exists():
                raise FileNotFoundError(f"任务目录不存在: {result_dir}")

            # [新增] 检查结果区是否已有数据
            if self.results:
                reply = QMessageBox.question(
                    self,
                    "加载历史任务",
                    "结果区已有数据，是否清空当前结果？\n\n点击'Yes'清空并加载，点击'No'附加到当前结果。",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No | QMessageBox.StandardButton.Cancel
                )
                
                if reply == QMessageBox.StandardButton.Cancel:
                    return
                elif reply == QMessageBox.StandardButton.Yes:
                    self.results = []
                    self.result_viewer._clear_results_internal() # 需要在 ResultViewer 中添加此方法或直接调用 clear

            # [新增] 尝试读取 task_info.json
            task_info_file = result_path / "task_info.json"
            if task_info_file.exists():
                try:
                    with open(task_info_file, 'r', encoding='utf-8') as f:
                        task_info = json.load(f)
                        
                    results_list = task_info.get("results", [])
                    if not results_list:
                        QMessageBox.warning(self, "提示", "任务记录中没有结果数据")
                        return

                    count = 0
                    for res in results_list:
                        # 补充必要字段
                        res["from_history"] = True
                        
                        # 确保 sequence_id 存在
                        if "sequence_id" not in res:
                             res["sequence_id"] = "Unknown"

                        # 修正 result_file 等路径为绝对路径（如果它们是相对路径）
                        for key in ["result_file", "csv_file", "desc_file"]:
                            path_str = res.get(key, "")
                            if path_str:
                                path = Path(path_str)
                                if not path.exists():
                                    # 尝试在当前任务目录下寻找
                                    local_path = result_path / path.name
                                    if local_path.exists():
                                        res[key] = str(local_path)
                        
                        self.results.append(res)
                        self.result_viewer.update_file_status(res)
                        count += 1
                        
                    self.status_bar.showMessage(f"已加载任务 '{result_path.name}'，共 {count} 个结果", 3000)
                    return # 成功加载，直接返回

                except Exception as e:
                    print(f"读取 task_info.json 失败: {e}，尝试扫描 XML 文件")

            # 扫描目录下的所有 XML 文件
            xml_files = list(result_path.glob("*_blast_result.xml"))
            if not xml_files:
                QMessageBox.warning(self, "提示", "该任务目录下没有找到结果文件")
                return

            count = 0
            for xml_file in xml_files:
                csv_file = xml_file.with_suffix('.csv')
                desc_file = xml_file.with_suffix('.desc')
                
                # 尝试从文件名恢复原始文件名
                # 假设格式为 {original_name}_{seq_id}_blast_result.xml
                # 或者 {original_name}_blast_result.xml
                # 这是一个简化的假设，实际情况可能更复杂
                file_stem = xml_file.stem.replace('_blast_result', '')
                
                # 构造结果对象
                result_info = {
                    "file": str(xml_file), # 使用结果文件作为唯一标识
                    "status": "success",
                    "result_file": str(xml_file),
                    "csv_file": str(csv_file),
                    "desc_file": str(desc_file),
                    "elapsed_time": 0,
                    "from_history": True,
                    "display_name": file_stem
                }
                
                # [修复] 尝试解析 sequence_id
                # 我们尝试方案 1，读取 XML 获取 query name
                try:
                    import xml.etree.ElementTree as ET
                    tree = ET.parse(xml_file)
                    root = tree.getroot()
                    # BLAST XML format: BlastOutput -> BlastOutput_query-def
                    query_def = root.find(".//BlastOutput_query-def")
                    if query_def is not None:
                        seq_id = query_def.text.split()[0] # 通常取第一个词作为 ID
                        result_info["sequence_id"] = seq_id
                        
                        # 尝试推断原始文件名
                        if seq_id in file_stem:
                            # 移除 seq_id 得到原始文件名
                            original_name = file_stem.replace(f"_{seq_id}", "").replace(seq_id, "")
                            if not original_name: original_name = "Unknown_Source"
                            # result_info["file"] = original_name # 之前被注释掉了
                        else:
                            # result_info["file"] = file_stem
                            pass
                            
                        # 修正：为了简单展示，我们可以把 file 设为 "历史任务加载" 或者基于目录名
                        result_info["file"] = result_path.name 
                except Exception:
                    pass

                self.results.append(result_info)
                self.result_viewer.update_file_status(result_info)
                count += 1
            
            self.status_bar.showMessage(f"已加载任务 '{result_path.name}'，共 {count} 个结果", 3000)
            
        except Exception as e:
            print(f"加载任务历史失败: {e}")
            QMessageBox.critical(self, "错误", f"加载任务历史失败: {e}")

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
                    # [关键修复] 断开信号，防止 terminate 后触发信号导致崩溃
                    try:
                        self.processing_thread.task_started.disconnect()
                        self.processing_thread.progress_updated.disconnect()
                        self.processing_thread.result_received.disconnect()
                        self.processing_thread.all_tasks_completed.disconnect()
                        self.processing_thread.processing_error.disconnect()
                        self.processing_thread.finished.disconnect()
                    except Exception as e:
                        print(f"断开信号时出错: {e}")

                    self.processing_thread.terminate()
                    self.processing_thread.wait()
                event.accept()
            else:
                event.ignore()
        else:
            event.accept()
