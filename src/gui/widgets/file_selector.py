"""
文件选择组件模块
负责文件选择相关的GUI组件
"""

from PyQt6.QtWidgets import (QGroupBox, QHBoxLayout, QPushButton, QLabel)
from PyQt6.QtCore import pyqtSignal, QObject


class FileSelectorSignals(QObject):
    """文件选择器信号类"""
    files_selected = pyqtSignal(list)  # 信号：文件已选择


class FileSelectorWidget(QGroupBox):
    """文件选择组件类"""
    
    def __init__(self):
        super().__init__("文件选择")
        self.signals = FileSelectorSignals()
        self.selected_files = []
        self._setup_ui()
        self._connect_signals()
    
    def _setup_ui(self):
        """设置界面"""
        layout = QHBoxLayout()
        
        self.select_button = QPushButton("选择序列文件")
        layout.addWidget(self.select_button)
        
        self.file_count_label = QLabel("未选择文件")
        layout.addWidget(self.file_count_label)
        layout.addStretch()
        
        self.setLayout(layout)
    
    def _connect_signals(self):
        """连接信号"""
        self.select_button.clicked.connect(self._on_select_files)
    
    def _on_select_files(self):
        """处理文件选择事件"""
        from PyQt6.QtWidgets import QFileDialog
        file_paths, _ = QFileDialog.getOpenFileNames(
            self,
            "选择序列文件",
            "",
            "Sequence files (*.seq);;FASTA files (*.fasta *.fa);;All files (*.*)"
        )
        
        if file_paths:
            self.selected_files = list(file_paths)
            self.file_count_label.setText(f"已选择 {len(self.selected_files)} 个文件")
            self.signals.files_selected.emit(self.selected_files)
    
    def get_selected_files(self):
        """获取已选择的文件列表"""
        return self.selected_files
    
    def clear_selection(self):
        """清空文件选择"""
        self.selected_files = []
        self.file_count_label.setText("未选择文件")
