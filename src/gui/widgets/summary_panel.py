"""
统计信息组件模块
负责显示统计信息的GUI组件
"""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QGroupBox, QVBoxLayout, QLabel)


class SummaryPanelWidget(QGroupBox):
    """统计信息组件类"""
    
    def __init__(self):
        super().__init__("统计信息")
        self._setup_ui()
    
    def _setup_ui(self):
        """设置界面"""
        layout = QVBoxLayout()
        
        self.summary_label = QLabel("总计: 0个文件, 成功: 0个, 失败: 0个")
        self.summary_label.setAlignment(Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(self.summary_label)
        
        self.setLayout(layout)
    
    def update_summary(self, results):
        """更新统计信息"""
        total = len(results)
        successful = sum(1 for r in results if r["status"] == "success")
        failed = total - successful
        
        self.summary_label.setText(f"总计: {total}个文件, 成功: {successful}个, 失败: {failed}个")
