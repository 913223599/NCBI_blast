"""
设置对话框模块（PyQt6版本）
"""

from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QPushButton,
                             QGroupBox, QFormLayout, QComboBox, QLineEdit,
                             QCheckBox, QSpinBox, QMessageBox)
from PyQt6.QtCore import Qt


class SettingsDialog(QDialog):
    """设置对话框类"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()
        self._connect_signals()
        self._load_settings()
        
    def _setup_ui(self):
        """设置界面"""
        self.setWindowTitle("设置")
        self.setModal(True)
        self.resize(400, 300)
        
        layout = QVBoxLayout()
        
        # BLAST设置组
        blast_group = QGroupBox("BLAST设置")
        blast_layout = QFormLayout()
        
        # 数据库选择
        self.db_combo = QComboBox()
        self.db_combo.addItems(["nt", "nr", "refseq_rna", "refseq_genomic"])
        blast_layout.addRow("数据库:", self.db_combo)
        
        # 程序选择
        self.program_combo = QComboBox()
        self.program_combo.addItems(["blastn", "blastp", "blastx", "tblastn", "tblastx"])
        blast_layout.addRow("程序:", self.program_combo)
        
        # E值阈值
        self.evalue_spin = QSpinBox()
        self.evalue_spin.setRange(0, 1000)
        self.evalue_spin.setValue(10)
        blast_layout.addRow("E值阈值:", self.evalue_spin)
        
        # 最大匹配数
        self.max_matches_spin = QSpinBox()
        self.max_matches_spin.setRange(1, 10000)
        self.max_matches_spin.setValue(100)
        blast_layout.addRow("最大匹配数:", self.max_matches_spin)
        
        blast_group.setLayout(blast_layout)
        layout.addWidget(blast_group)
        
        # 翻译设置组
        translation_group = QGroupBox("翻译设置")
        translation_layout = QFormLayout()
        
        # AI翻译API密钥
        self.api_key_edit = QLineEdit()
        self.api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        translation_layout.addRow("API密钥:", self.api_key_edit)
        
        # 启用AI翻译
        self.ai_translate_check = QCheckBox("启用AI翻译")
        translation_layout.addRow("", self.ai_translate_check)
        
        translation_group.setLayout(translation_layout)
        layout.addWidget(translation_group)
        
        # 按钮布局
        button_layout = QHBoxLayout()
        
        self.ok_button = QPushButton("确定")
        self.cancel_button = QPushButton("取消")
        self.apply_button = QPushButton("应用")
        
        button_layout.addStretch()
        button_layout.addWidget(self.ok_button)
        button_layout.addWidget(self.cancel_button)
        button_layout.addWidget(self.apply_button)
        
        layout.addLayout(button_layout)
        self.setLayout(layout)
    
    def _connect_signals(self):
        """连接信号"""
        self.ok_button.clicked.connect(self._accept)
        self.cancel_button.clicked.connect(self.reject)
        self.apply_button.clicked.connect(self._apply_settings)
    
    def _load_settings(self):
        """加载设置"""
        # TODO: 从配置文件加载设置
        pass
    
    def _save_settings(self):
        """保存设置"""
        # TODO: 保存设置到配置文件
        pass
    
    def _apply_settings(self):
        """应用设置"""
        try:
            # 验证设置
            if not self.api_key_edit.text() and self.ai_translate_check.isChecked():
                QMessageBox.warning(self, "警告", "启用AI翻译需要提供API密钥")
                return
            
            # 保存设置
            self._save_settings()
            QMessageBox.information(self, "成功", "设置已保存")
            
        except Exception as e:
            QMessageBox.critical(self, "错误", f"保存设置时发生错误:\n{str(e)}")
    
    def _accept(self):
        """接受设置并关闭对话框"""
        try:
            # 应用设置
            self._apply_settings()
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, "错误", f"应用设置时发生错误:\n{str(e)}")