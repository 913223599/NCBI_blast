"""
PyQt主窗口模块
负责创建和管理主窗口界面
"""

import os
import sys
from pathlib import Path
import shutil

from PyQt6.QtCore import Qt, pyqtSlot
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import (QMainWindow, QMenuBar, QMenu, QWidget, QVBoxLayout, QSplitter,
                             QStatusBar, QMessageBox, QDialog, QApplication, QHBoxLayout, QFrame)
from src.utils.config_manager import get_config_manager
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
from src.gui.threads.processing_thread import ProcessingThread
from src.blast.batch_processor import BatchProcessor, MultiSequenceBatchProcessor


def ensure_results_folders():
    """
    确保results文件夹存在
    根据项目规范，确保项目根目录和src目录下的results文件夹存在
    """
    try:
        # 确保项目根目录下的results文件夹存在
        root_results_path = Path(project_root) / "results"
        if not root_results_path.exists():
            root_results_path.mkdir(parents=True, exist_ok=True)
            print(f"已创建项目根目录results文件夹: {root_results_path}")
        else:
            print(f"项目根目录results文件夹已存在: {root_results_path}")
            
        # 确保src目录下的results文件夹存在
        src_results_path = Path(project_root) / "src" / "results"
        if not src_results_path.exists():
            src_results_path.mkdir(parents=True, exist_ok=True)
            print(f"已创建src目录results文件夹: {src_results_path}")
        else:
            print(f"src目录results文件夹已存在: {src_results_path}")
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
        self.processing_thread = None
        self.batch_processor = None
        self.translation_debugger = None
        self.help_dialog = None
        self.api_key_dialog = None
        
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
                show-decoration-controls: 1;
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
        control_card.setFixedHeight(100) # 限制高度，使其像个工具栏
        
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
    
    def _start_processing(self):
        """开始处理文件"""
        # 从文件选择器组件直接获取文件列表，确保是最新的状态
        current_files = self.file_selector.get_selected_files()
        print(f"开始处理时检测到的文件数量: {len(current_files)}, 文件列表: {[Path(f).name for f in current_files]}")
        
        # 更新实例变量以确保一致性
        self.sequence_files = current_files
        
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
                "status": "processing",  # 更改为processing状态
                "elapsed_time": 0
            })
        
        # 强制刷新UI
        self.result_viewer.update()
        try:
            QApplication.processEvents()  # 强制处理UI事件
        except:
            pass  # 如果QApplication不可用，忽略这个调用
        
        try:
            max_workers = self.parameter_settings.get_thread_count()
            if max_workers < 1 or max_workers > 50:
                raise ValueError("线程数必须在1-50之间")
        except ValueError as e:
            QMessageBox.critical(self, "错误", f"线程数设置错误: {e}")
            return
        
        # 设置高级参数设置
        advanced_settings = self.parameter_settings.get_advanced_settings()
        
        # 设置生物学翻译器参数，现在由右键菜单控制，但初始化时启用AI翻译器
        translation_settings = {
            'use_ai': advanced_settings.get('use_ai_translation', True),  # 使用高级设置中的AI翻译开关
            'translator_type': advanced_settings.get('translator_type', 'default'),  # 可以是 'default', 'ai_basic', 'ai_advanced' 等
            'ai_model': advanced_settings.get('ai_translation_model', 'deepseek-r1')  # 添加AI模型参数
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
        
        try:
            max_workers = self.parameter_settings.get_thread_count()
            if max_workers < 1 or max_workers > 50:
                raise ValueError("线程数必须在1-50之间")
        except ValueError as e:
            QMessageBox.critical(self, "错误", f"线程数设置错误: {e}")
            return
        
        # 检查是否有文件包含多条序列
        has_multi_sequence_files = False
        for file_path in self.sequence_files:
            try:
                from src.utils.file_handler import FileHandler
                file_handler = FileHandler()
                sequences = file_handler.read_fasta_file(file_path)
                if len(sequences) > 1:
                    has_multi_sequence_files = True
                    break
            except Exception as e:
                print(f"检查文件 {file_path} 时出错: {e}")
    
        # 根据文件类型选择处理器
        if has_multi_sequence_files:
            # 使用多序列处理器
            self.batch_processor = MultiSequenceBatchProcessor(
                max_workers=max_workers,
                advanced_settings=advanced_settings
            )
            # 对于多序列处理，我们处理每个文件中的多条序列
            # 但需要修改线程以支持多序列处理
            from src.gui.threads.processing_thread import MultiSequenceProcessingThread
            self.processing_thread = MultiSequenceProcessingThread(self.batch_processor, self.sequence_files)
        else:
            # 使用普通处理器
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
        

    
    def _on_all_tasks_complete(self, total_tasks):
        """处理所有任务完成事件"""
        self.control_panel.set_status("处理完成")
        self.statusBar().showMessage("处理完成")

    
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
            if max_workers < 1 or max_workers > 50:
                raise ValueError("线程数必须在1-50之间")
        except ValueError as e:
            QMessageBox.critical(self, "错误", f"线程数设置错误: {e}")
            return
        
        # 获取高级参数设置
        advanced_settings = self.parameter_settings.get_advanced_settings()
        
        # 设置生物学翻译器参数，现在由右键菜单控制，但初始化时启用AI翻译器
        translation_settings = {
            'use_ai': advanced_settings.get('use_ai_translation', True),  # 使用高级设置中的AI翻译开关
            'translator_type': advanced_settings.get('translator_type', 'default'),  # 可以是 'default', 'ai_basic', 'ai_advanced' 等
            'ai_model': advanced_settings.get('ai_translation_model', 'deepseek-r1')  # 添加AI模型参数
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
        self.control_panel.set_status(f"正在重试: {file_name}")
        self.statusBar().showMessage(f"正在重试: {file_name}")
        
        # 创建并启动处理线程，传递高级参数
        # 检查文件是否包含多条序列
        try:
            from src.utils.file_handler import FileHandler
            file_handler = FileHandler()
            sequences = file_handler.read_fasta_file(file_path)
            if len(sequences) > 1:
                # 使用多序列处理器
                self.batch_processor = MultiSequenceBatchProcessor(
                    max_workers=max_workers,
                    advanced_settings=advanced_settings
                )
                from src.gui.threads.processing_thread import MultiSequenceProcessingThread
                self.processing_thread = MultiSequenceProcessingThread(self.batch_processor, [file_path])
            else:
                # 使用普通处理器
                self.batch_processor = BatchProcessor(
                    max_workers=max_workers,
                    advanced_settings=advanced_settings
                )
                self.processing_thread = ProcessingThread(self.batch_processor, [file_path])
        except Exception as e:
            print(f"检查文件 {file_path} 时出错: {e}")
            # 如果检查失败，使用普通处理器
            self.batch_processor = BatchProcessor(
                max_workers=max_workers,
                advanced_settings=advanced_settings
            )
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