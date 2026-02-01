from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
                             QComboBox, QPushButton, QGroupBox, QFormLayout, QMessageBox)
from PyQt6.QtCore import Qt
from src.utils.config_manager import get_config_manager
from src.utils.ui_translation_manager import get_ui_translator

class GlobalSettingsDialog(QDialog):
    """
    Global System Settings Dialog
    Handles Language, Theme (future), and other system-wide preferences.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Global Settings / 全局设置")
        self.resize(500, 300)
        self.config_manager = get_config_manager()
        self.tr_mgr = get_ui_translator()
        
        self._init_ui()
        self._load_settings()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        
        # General Settings Group
        group = QGroupBox("General / 通用")
        form = QFormLayout(group)
        
        # Language
        self.lang_combo = QComboBox()
        self.lang_combo.addItems(["中文 (Chinese)", "English"])
        form.addRow("Language / 语言:", self.lang_combo)
        
        layout.addWidget(group)
        layout.addStretch()
        
        # Buttons
        btn_box = QHBoxLayout()
        btn_box.addStretch()
        
        save_btn = QPushButton("Save / 保存")
        save_btn.clicked.connect(self._save_and_close)
        cancel_btn = QPushButton("Cancel / 取消")
        cancel_btn.clicked.connect(self.reject)
        
        btn_box.addWidget(cancel_btn)
        btn_box.addWidget(save_btn)
        layout.addLayout(btn_box)

    def _load_settings(self):
        current_lang = self.tr_mgr.get_language()
        idx = 0 if current_lang == "zh_CN" else 1
        self.lang_combo.setCurrentIndex(idx)

    def _save_and_close(self):
        # Determine language code
        idx = self.lang_combo.currentIndex()
        code = "zh_CN" if idx == 0 else "en_US"
        
        # Save if changed
        if code != self.tr_mgr.get_language():
            self.tr_mgr.set_language(code)
            QMessageBox.information(self, "Restart Required", 
                                  "Language setting saved. Please restart the application for changes to take full effect.\n语言设置已保存，请重启应用以完全生效。")
        
        self.accept()
