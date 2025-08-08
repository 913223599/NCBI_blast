"""
参数设置组件模块
负责参数设置相关的GUI组件
"""

from PyQt6.QtWidgets import (QGroupBox, QHBoxLayout, QLabel, QSpinBox)


class ParameterSettingsWidget(QGroupBox):
    """参数设置组件类"""
    
    def __init__(self):
        super().__init__("参数设置")
        self._setup_ui()
    
    def _setup_ui(self):
        """设置界面"""
        layout = QHBoxLayout()
        
        layout.addWidget(QLabel("线程数:"))
        
        self.thread_count_spinbox = QSpinBox()
        self.thread_count_spinbox.setRange(1, 10)
        self.thread_count_spinbox.setValue(3)
        self.thread_count_spinbox.setFixedWidth(60)
        layout.addWidget(self.thread_count_spinbox)
        
        layout.addStretch()
        
        self.setLayout(layout)
    
    def get_thread_count(self):
        """获取线程数设置"""
        return self.thread_count_spinbox.value()
    
    def set_thread_count(self, count):
        """设置线程数"""
        self.thread_count_spinbox.setValue(count)