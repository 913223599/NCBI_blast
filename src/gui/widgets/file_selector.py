"""
文件选择组件模块（PyQt6版本）
"""

from pathlib import Path
from PyQt6.QtWidgets import (QGroupBox, QVBoxLayout, QHBoxLayout, QPushButton, 
                             QListWidget, QFileDialog, QMessageBox)
from PyQt6.QtCore import pyqtSignal, QObject


class FileSelectorWidget(QGroupBox):
    """文件选择组件类"""
    
    files_selected = pyqtSignal(list)
    
    def __init__(self):
        super().__init__("序列文件选择")
        self._setup_ui()
        self._connect_signals()
        self.selected_files = []
    
    def _setup_ui(self):
        """设置界面"""
        layout = QVBoxLayout()
        
        # 创建文件列表
        self.file_list = QListWidget()
        layout.addWidget(self.file_list)
        
        # 创建按钮布局
        button_layout = QHBoxLayout()
        
        self.add_button = QPushButton("添加文件")
        button_layout.addWidget(self.add_button)
        
        self.remove_button = QPushButton("移除选中")
        button_layout.addWidget(self.remove_button)
        
        self.clear_button = QPushButton("清空列表")
        button_layout.addWidget(self.clear_button)
        
        layout.addLayout(button_layout)
        self.setLayout(layout)
    
    def _connect_signals(self):
        """连接信号"""
        self.add_button.clicked.connect(self._add_files)
        self.remove_button.clicked.connect(self._remove_selected)
        self.clear_button.clicked.connect(self._clear_files)
        self.file_list.itemSelectionChanged.connect(self._on_selection_changed)
    
    def _add_files(self):
        """添加文件"""
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "选择序列文件",
            "",
            "Sequence Files (*.fasta *.fa *.fna *.seq *.fasta.gz);;All Files (*)"
        )
        
        if files:
            # 添加新文件到列表
            for file_path in files:
                if file_path not in self.selected_files:
                    self.selected_files.append(file_path)
                    self.file_list.addItem(Path(file_path).name)
            
            # 发出文件选择信号
            self.files_selected.emit(self.selected_files)
    
    def _remove_selected(self):
        """移除选中的文件"""
        selected_items = self.file_list.selectedItems()
        if not selected_items:
            QMessageBox.information(self, "提示", "请先选择要移除的文件")
            return
        
        # 从列表中移除选中的文件
        for item in selected_items:
            row = self.file_list.row(item)
            self.file_list.takeItem(row)
            if 0 <= row < len(self.selected_files):
                del self.selected_files[row]
        
        # 发出文件选择信号
        self.files_selected.emit(self.selected_files)
    
    def _clear_files(self):
        """清空文件列表"""
        self.file_list.clear()
        self.selected_files.clear()
        self.files_selected.emit(self.selected_files)
    
    def _on_selection_changed(self):
        """处理选择变化事件"""
        # 可以在这里添加选择变化的处理逻辑
        pass
    
    def get_selected_files(self):
        """获取选中的文件列表"""
        return self.selected_files[:]