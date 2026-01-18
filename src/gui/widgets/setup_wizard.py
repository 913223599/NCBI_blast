"""
首次启动配置向导
引导用户完成 BLAST+ 路径和 API Key 的配置
"""

import os
import shutil
from PyQt6.QtWidgets import (QWizard, QWizardPage, QVBoxLayout, QLabel, 
                             QLineEdit, QPushButton, QHBoxLayout, QFileDialog,
                             QMessageBox)
from PyQt6.QtCore import Qt

from src.utils.config_manager import get_config_manager

class IntroPage(QWizardPage):
    def __init__(self):
        super().__init__()
        self.setTitle("欢迎使用 NCBI BLAST Pro")
        self.setSubTitle("本向导将帮助您完成初始配置，以便软件能够正常运行。")
        
        layout = QVBoxLayout()
        label = QLabel("在开始之前，我们需要确认以下几点：\n\n"
                       "1. 您的电脑上已安装 NCBI BLAST+ 工具包。\n"
                       "2. (可选) 您拥有 DashScope API Key 以使用 AI 翻译功能。\n\n"
                       "点击“下一步”继续。")
        label.setWordWrap(True)
        layout.addWidget(label)
        self.setLayout(layout)

class BlastConfigPage(QWizardPage):
    def __init__(self):
        super().__init__()
        self.setTitle("BLAST+ 配置")
        self.setSubTitle("请指定 NCBI BLAST+ 可执行文件的位置。")
        
        layout = QVBoxLayout()
        
        self.status_label = QLabel()
        layout.addWidget(self.status_label)
        
        # 路径选择
        path_layout = QHBoxLayout()
        self.path_edit = QLineEdit()
        self.path_edit.setPlaceholderText("例如: C:/Program Files/NCBI/blast-2.13.0+/bin")
        self.btn_browse = QPushButton("浏览...")
        self.btn_browse.clicked.connect(self._browse_path)
        
        path_layout.addWidget(self.path_edit)
        path_layout.addWidget(self.btn_browse)
        layout.addLayout(path_layout)
        
        self.setLayout(layout)
        
        # 尝试自动检测
        self._auto_detect()

    def _auto_detect(self):
        blastn = shutil.which("blastn")
        if blastn:
            bin_dir = os.path.dirname(blastn)
            self.path_edit.setText(bin_dir)
            self.status_label.setText("✅ 已自动检测到 BLAST+ 安装路径")
            self.status_label.setStyleSheet("color: green")
        else:
            self.status_label.setText("⚠️ 未检测到 BLAST+，请手动指定 bin 目录")
            self.status_label.setStyleSheet("color: orange")

    def _browse_path(self):
        directory = QFileDialog.getExistingDirectory(self, "选择 BLAST+ bin 目录")
        if directory:
            self.path_edit.setText(directory)
            self._validate_path(directory)

    def _validate_path(self, path):
        blastn_path = os.path.join(path, "blastn.exe") if os.name == 'nt' else os.path.join(path, "blastn")
        if os.path.exists(blastn_path):
            self.status_label.setText("✅ 路径有效")
            self.status_label.setStyleSheet("color: green")
            return True
        else:
            self.status_label.setText("❌ 路径无效：未找到 blastn 可执行文件")
            self.status_label.setStyleSheet("color: red")
            return False

    def validatePage(self):
        path = self.path_edit.text()
        if not path:
            QMessageBox.warning(self, "提示", "请指定 BLAST+ 路径")
            return False
        return self._validate_path(path)

class ApiConfigPage(QWizardPage):
    def __init__(self):
        super().__init__()
        self.setTitle("AI 功能配置 (可选)")
        self.setSubTitle("配置 DashScope API Key 以启用 AI 翻译和解释功能。")
        
        layout = QVBoxLayout()
        
        layout.addWidget(QLabel("DashScope API Key:"))
        self.key_edit = QLineEdit()
        self.key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        layout.addWidget(self.key_edit)
        
        layout.addWidget(QLabel("\n如果您还没有 API Key，可以跳过此步骤，稍后在设置中配置。"))
        
        self.setLayout(layout)

class SetupWizard(QWizard):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("初始配置向导")
        self.setWizardStyle(QWizard.WizardStyle.ModernStyle)
        
        self.addPage(IntroPage())
        self.blast_page = BlastConfigPage()
        self.addPage(self.blast_page)
        self.api_page = ApiConfigPage()
        self.addPage(self.api_page)
        
        self.config_manager = get_config_manager()

    def accept(self):
        # 保存配置
        blast_path = self.blast_page.path_edit.text()
        api_key = self.api_page.key_edit.text()
        
        # 将 BLAST 路径添加到 PATH (临时，实际应持久化到配置)
        # 这里我们假设 ConfigManager 有能力保存这个路径，或者我们将其添加到系统 PATH
        # 由于修改系统 PATH 比较复杂，我们这里只保存到配置文件，并在程序启动时添加到 os.environ
        
        # 保存 API Key
        if api_key:
            self.config_manager.set_api_key('dashscope', api_key)
            
        # 标记向导已完成
        self.config_manager.set_config_value('setup_completed', True)
        self.config_manager.set_config_value('blast_bin_path', blast_path)
        
        super().accept()
