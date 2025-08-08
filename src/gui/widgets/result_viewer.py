"""
结果展示组件模块
负责结果展示相关的GUI组件
"""

from pathlib import Path
from PyQt6.QtWidgets import (QGroupBox, QVBoxLayout, QTreeWidget, QTreeWidgetItem, QTextEdit)
from PyQt6.QtCore import pyqtSignal, QObject


class ResultViewerSignals(QObject):
    """结果查看器信号类"""
    item_selected = pyqtSignal(str)  # 信号：项目已选择
    item_double_clicked = pyqtSignal(object, int)  # 信号：项目被双击


class ResultViewerWidget(QGroupBox):
    """结果展示组件类"""
    
    def __init__(self):
        super().__init__("处理结果")
        self.signals = ResultViewerSignals()
        self._setup_ui()
        self._connect_signals()
    
    def _setup_ui(self):
        """设置界面"""
        layout = QVBoxLayout()
        
        self.result_tree = QTreeWidget()
        self.result_tree.setHeaderLabels(['文件名', '状态', '耗时'])
        layout.addWidget(self.result_tree)
        
        self.setLayout(layout)
    
    def _connect_signals(self):
        """连接信号"""
        self.result_tree.itemSelectionChanged.connect(self._on_item_selected)
        self.result_tree.itemDoubleClicked.connect(self._on_item_double_clicked)
    
    def _on_item_selected(self):
        """处理项目选择事件"""
        selected_items = self.result_tree.selectedItems()
        if selected_items:
            item = selected_items[0]
            # 如果选择的是父节点（文件节点）
            if item.parent() is None:
                file_name = item.text(0)
                self.signals.item_selected.emit(file_name)
    
    def _on_item_double_clicked(self, item, column):
        """处理项目双击事件"""
        self.signals.item_double_clicked.emit(item, column)
    
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
        
        # 查找对应的树节点并更新
        root = self.result_tree.invisibleRootItem()
        for i in range(root.childCount()):
            item = root.child(i)
            if item.text(0) == file_name:
                # 更新父节点的值
                item.setText(1, status)
                item.setText(2, elapsed_time)
                break
