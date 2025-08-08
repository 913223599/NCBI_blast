"""
控制面板组件模块
负责控制按钮相关的GUI组件
"""

from PyQt6.QtWidgets import (QGroupBox, QHBoxLayout, QPushButton, QProgressBar, QLabel)


class ControlPanelWidget(QGroupBox):
    """控制面板组件类"""
    
    def __init__(self):
        super().__init__("控制")
        self._setup_ui()
    
    def _setup_ui(self):
        """设置界面"""
        layout = QHBoxLayout()
        
        self.start_button = QPushButton("开始处理")
        layout.addWidget(self.start_button)
        
        self.stop_button = QPushButton("停止处理")
        self.stop_button.setEnabled(False)
        layout.addWidget(self.stop_button)
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)
        
        self.status_label = QLabel("就绪")
        layout.addWidget(self.status_label)
        
        self.setLayout(layout)
    
    def set_status(self, message):
        """设置状态信息"""
        self.status_label.setText(message)
    
    def update_progress(self, value, maximum=100):
        """更新进度条"""
        self.progress_bar.setMaximum(maximum)
        self.progress_bar.setValue(value)
    
    def enable_start_button(self, enabled=True):
        """启用/禁用开始按钮"""
        self.start_button.setEnabled(enabled)
    
    def enable_stop_button(self, enabled=True):
        """启用/禁用停止按钮"""
        self.stop_button.setEnabled(enabled)
