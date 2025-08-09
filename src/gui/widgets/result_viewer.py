"""
结果展示组件模块
负责结果展示相关的GUI组件
"""

from pathlib import Path
import shutil
import os
import threading
import time

from Bio.Blast import NCBIXML
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtCore import pyqtSignal, QObject
from PyQt6.QtWidgets import (QGroupBox, QVBoxLayout, QTreeWidget, QTreeWidgetItem, QMenu, QMessageBox, QFileDialog)

# 导入生物学翻译模块
from src.utils.biology_translator import get_biology_translator


class ResultViewerSignals(QObject):
    """结果查看器信号类"""
    item_selected = pyqtSignal(str)  # 信号：项目已选择
    retry_blast = pyqtSignal(str)    # 信号：重试BLAST搜索
    translation_complete = pyqtSignal(object, str, str)  # 翻译完成信号：item, 原文, 译文


class ResultViewerWidget(QGroupBox):
    """结果展示组件类"""
    
    def __init__(self):
        super().__init__("处理结果")
        self.signals = ResultViewerSignals()
        self._setup_ui()
        self._connect_signals()
        self.results_data = {}  # 存储结果数据
        self.current_file_item = None  # 当前右键点击的文件项
        self.translating_items = {}  # 正在翻译的项目
        # 初始化翻译器，启用AI翻译功能，并从配置文件获取API密钥
        try:
            from src.utils.config_manager import get_config_manager
            config_manager = get_config_manager()
            api_key = config_manager.get_api_key('dashscope')
        except Exception:
            api_key = None
        
        self.translator = get_biology_translator(use_ai=True, ai_api_key=api_key)
    
    def _setup_ui(self):
        """设置界面"""
        layout = QVBoxLayout()
        
        self.result_tree = QTreeWidget()
        self.result_tree.setHeaderLabels(['文件名', '状态', '耗时'])
        self.result_tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)  # 启用自定义上下文菜单
        self.result_tree.customContextMenuRequested.connect(self._show_context_menu)   # 连接上下文菜单信号
        layout.addWidget(self.result_tree)
        
        self.setLayout(layout)
    
    def _connect_signals(self):
        """连接信号"""
        self.result_tree.itemClicked.connect(self._on_item_clicked)
        self.signals.translation_complete.connect(self._on_translation_complete)
        # self.result_tree.itemSelectionChanged.connect(self._on_item_selected)  # 移除选择变化信号连接
    
    def _on_item_clicked(self, item, column):
        """处理项目点击事件"""
        # 如果点击的是父节点（文件节点）
        if item.parent() is None:
            file_name = item.text(0)
            self.signals.item_selected.emit(file_name)
            
            # 切换展开/折叠状态
            is_expanded = not item.isExpanded()
            item.setExpanded(is_expanded)
            
            # 如果是展开状态且还没有加载详细信息，则加载详细信息
            if is_expanded and item.childCount() > 0:
                child = item.child(0)
                # 检查是否已加载详细信息（通过检查子节点的列数）
                if child.columnCount() == 3 and child.text(0) == '':
                    # 加载并显示详细信息
                    self._load_detail_info(item, file_name)
    
    def _show_context_menu(self, position):
        """显示上下文菜单"""
        # 获取右键点击的项
        item = self.result_tree.itemAt(position)
        if item and item.parent() is None:  # 确保是文件节点（父节点）
            self.current_file_item = item
            file_name = item.text(0)
            
            # 创建上下文菜单
            context_menu = QMenu(self)
            
            # 添加重试菜单项
            retry_action = context_menu.addAction("重试比对")
            retry_action.triggered.connect(lambda: self._retry_blast(file_name))
            
            # 添加导出菜单项
            export_action = context_menu.addAction("导出查询信息")
            export_action.triggered.connect(lambda: self._export_query_info(file_name))
            
            # 显示菜单
            context_menu.exec(self.result_tree.mapToGlobal(position))
    
    def _retry_blast(self, file_name):
        """重试BLAST搜索"""
        # 发送重试信号
        self.signals.retry_blast.emit(file_name)
    
    def _export_query_info(self, file_name):
        """导出查询信息"""
        # 查找对应的结果数据
        result_data = self.results_data.get(file_name)
        if not result_data:
            QMessageBox.warning(self, "导出失败", f"未找到文件 {file_name} 的结果数据")
            return
        
        # 选择保存位置
        save_path, _ = QFileDialog.getSaveFileName(
            self, 
            f"导出 {file_name} 的查询信息", 
            f"{file_name}_blast_results.xml", 
            "XML Files (*.xml);;All Files (*)"
        )
        
        if save_path:
            try:
                # 检查结果文件是否存在
                result_file_path = result_data.get("result_file")
                if not result_file_path or not Path(result_file_path).exists():
                    QMessageBox.warning(self, "导出失败", f"结果文件不存在: {result_file_path}")
                    return
                
                # 复制结果文件到指定位置
                shutil.copy2(result_file_path, save_path)
                QMessageBox.information(self, "导出成功", f"查询信息已导出到:\n{save_path}")
            except Exception as e:
                QMessageBox.critical(self, "导出失败", f"导出过程中发生错误:\n{str(e)}")
    
    def _load_detail_info(self, parent_item, file_name):
        """加载并显示详细信息"""
        # 查找对应的结果数据
        result_data = None
        for data in self.results_data.values():
            if Path(data.get("file", "")).name == file_name:
                result_data = data
                break
        
        if result_data and result_data.get("status") == "success":
            # 读取结果文件
            result_file = result_data.get("result_file")
            try:
                with open(result_file, 'r') as f:
                    handle = NCBIXML.read(f)
                    self._display_blast_results(parent_item, handle)
            except Exception as e:
                # 清空子节点并显示错误信息
                if parent_item.childCount() > 0:
                    child = parent_item.child(0)
                    child.setText(0, f"加载结果失败: {str(e)}")
        elif result_data and result_data.get("status") == "error":
            # 显示错误信息
            if parent_item.childCount() > 0:
                child = parent_item.child(0)
                child.setText(0, f"处理失败: {result_data.get('error', '未知错误')}")
    
    def _display_blast_results(self, parent_item, blast_record):
        """显示BLAST结果"""
        if parent_item.childCount() > 0:
            # 清空现有子节点
            for i in range(parent_item.childCount()):
                parent_item.removeChild(parent_item.child(0))
        
        if blast_record.alignments:
            for alignment in blast_record.alignments:
                # 获取原始标题（移除"gi|...|"部分）
                original_title = alignment.title.split(" ", 1)[1] if " " in alignment.title else alignment.title
                
                # 创建树节点
                item = QTreeWidgetItem(parent_item, ["", '', ''])
                item.setData(0, Qt.ItemDataRole.UserRole, alignment)
                
                # 启动翻译过程（在后台线程中）
                self._start_translation(item, original_title)
        else:
            QTreeWidgetItem(parent_item, ["没有找到匹配结果", '', ''])
    
    def _start_translation(self, item, original_title):
        """启动翻译过程"""
        # 显示正在翻译的提示
        item.setText(0, f"正在翻译，请稍后... ({original_title})")
        
        # 记录正在翻译的项目
        self.translating_items[id(item)] = original_title
        
        # 在后台线程中执行翻译
        def translate_task():
            try:
                translated_title = self.translator.translate_text(original_title)
                # 发送翻译完成信号
                self.signals.translation_complete.emit(item, original_title, translated_title)
            except Exception as e:
                print(f"翻译失败: {e}")
                # 发送翻译失败信号
                self.signals.translation_complete.emit(item, original_title, original_title)
        
        # 启动翻译线程
        thread = threading.Thread(target=translate_task, daemon=True)
        thread.start()
    
    def _on_translation_complete(self, item, original_title, translated_title):
        """处理翻译完成事件"""
        # 检查项目是否仍在翻译列表中
        if id(item) in self.translating_items:
            del self.translating_items[id(item)]
        
        # 更新显示
        if translated_title and translated_title != original_title:
            display_title = f"{translated_title} ({original_title})"
        else:
            # 翻译失败或与原文相同则只显示原文
            display_title = original_title
        
        item.setText(0, display_title)
    
    def update_result_tree(self, sequence_files):
        """更新结果树显示"""
        # 清空现有内容
        self.result_tree.clear()
        
        # 添加文件列表
        for seq_file in sequence_files:
            file_name = Path(seq_file).name
            
            # 添加父节点（文件）
            item = QTreeWidgetItem(self.result_tree, [file_name, '待处理', ''])
            item.setExpanded(False)
            
            # 添加子节点（详细信息占位符）
            QTreeWidgetItem(item, ['', '', ''])
    
    def update_file_status(self, result):
        """更新文件状态"""
        file_path = result.get("file", "")
        file_name = Path(file_path).name
        status = "成功" if result.get("status") == "success" else "失败"
        elapsed_time = f"{result.get('elapsed_time', 0):.2f}秒" if "elapsed_time" in result else "N/A"
        
        # 保存结果数据
        self.results_data[file_name] = result
        
        # 查找对应的树节点并更新
        root = self.result_tree.invisibleRootItem()
        for i in range(root.childCount()):
            item = root.child(i)
            if item.text(0) == file_name:
                # 更新父节点的值
                item.setText(1, status)
                item.setText(2, elapsed_time)
                break