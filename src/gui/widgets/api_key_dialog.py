"""
API密钥设置对话框模块
负责提供API密钥的设置和管理界面
"""

import sys
import os
import json
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QPushButton, 
                             QLabel, QLineEdit, QMessageBox)
from PyQt6.QtCore import Qt

# 添加项目根目录到Python路径
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from src.utils.config_manager import get_config_manager


class ApiKeyDialog(QDialog):
    """API密钥设置对话框类"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("API密钥设置")
        self.setFixedSize(400, 150)
        self.config_manager = get_config_manager()
        self._setup_ui()
        self._load_api_key()
    
    def _setup_ui(self):
        """设置界面"""
        layout = QVBoxLayout()
        
        # 说明标签
        instruction_label = QLabel("请输入通义百炼API密钥（DashScope）:")
        layout.addWidget(instruction_label)
        
        # API密钥输入框
        self.api_key_input = QLineEdit()
        self.api_key_input.setEchoMode(QLineEdit.EchoMode.Password)  # 密码模式显示
        self.api_key_input.setPlaceholderText("输入您的API密钥")
        layout.addWidget(self.api_key_input)
        
        # 按钮布局
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        
        # 保存按钮
        self.save_button = QPushButton("保存")
        self.save_button.clicked.connect(self._save_api_key)
        button_layout.addWidget(self.save_button)
        
        # 取消按钮
        self.cancel_button = QPushButton("取消")
        self.cancel_button.clicked.connect(self.reject)
        button_layout.addWidget(self.cancel_button)
        
        layout.addLayout(button_layout)
        self.setLayout(layout)
    
    def _load_api_key(self):
        """加载现有的API密钥"""
        try:
            api_key = self.config_manager.get_api_key('dashscope')
            if api_key:
                self.api_key_input.setText(api_key)
        except Exception as e:
            print(f"加载API密钥时出错: {e}")
    
    def _save_api_key(self):
        """保存API密钥"""
        api_key = self.api_key_input.text().strip()
        
        if not api_key:
            QMessageBox.warning(self, "输入错误", "API密钥不能为空")
            return
        
        try:
            # 保存API密钥到配置文件
            self.config_manager.set_api_key('dashscope', api_key)
            QMessageBox.information(self, "保存成功", "API密钥已成功保存")
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, "保存失败", f"保存API密钥时出错:\n{str(e)}")