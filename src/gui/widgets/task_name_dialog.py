"""
任务命名对话框
在开始处理前让用户输入任务名称
"""

from datetime import datetime

from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                             QLineEdit, QPushButton)


class TaskNameDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("新建任务")
        self.resize(400, 150)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        
        layout.addWidget(QLabel("请为本次任务命名:"))
        
        self.name_edit = QLineEdit()
        # 默认名称
        default_name = f"Task_{datetime.now().strftime('%Y%m%d_%H%M')}"
        self.name_edit.setText(default_name)
        self.name_edit.setPlaceholderText("任务名称将作为结果文件夹名")
        self.name_edit.selectAll() # 方便用户直接修改
        layout.addWidget(self.name_edit)
        
        layout.addStretch()
        
        btn_layout = QHBoxLayout()
        self.btn_cancel = QPushButton("取消")
        self.btn_cancel.clicked.connect(self.reject)
        
        self.btn_ok = QPushButton("开始")
        self.btn_ok.setStyleSheet("background-color: #409eff; color: white; font-weight: bold;")
        self.btn_ok.clicked.connect(self.accept)
        # 设置默认按钮
        self.btn_ok.setDefault(True)
        
        btn_layout.addStretch()
        btn_layout.addWidget(self.btn_cancel)
        btn_layout.addWidget(self.btn_ok)
        
        layout.addLayout(btn_layout)

    def get_task_name(self):
        return self.name_edit.text().strip()
