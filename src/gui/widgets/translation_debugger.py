"""
翻译调试器组件模块
负责提供一个独立的界面用于调试AI翻译功能
"""

import sys
import os
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton, 
                             QTextEdit, QLabel, QMessageBox, QGroupBox, QFormLayout)
from PyQt6.QtCore import pyqtSignal

# 添加项目根目录到Python路径
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from src.utils.translation.qwen_translator import get_qwen_translator


class TranslationDebuggerWidget(QWidget):
    """翻译调试器组件类"""
    
    def __init__(self):
        super().__init__()
        self.translator = None
        self._setup_ui()
        self._setup_translator()
    
    def _setup_ui(self):
        """设置界面"""
        layout = QVBoxLayout()
        
        # 创建说明标签
        instruction_label = QLabel("在此窗口中可以测试AI翻译功能，输入英文文本后点击'翻译'按钮查看结果")
        instruction_label.setWordWrap(True)
        layout.addWidget(instruction_label)
        
        # 创建输入区域
        input_group = QGroupBox("输入文本")
        input_layout = QVBoxLayout()
        self.input_text_edit = QTextEdit()
        self.input_text_edit.setPlaceholderText("请输入需要翻译的英文文本...")
        self.input_text_edit.setMinimumHeight(100)
        input_layout.addWidget(self.input_text_edit)
        input_group.setLayout(input_layout)
        layout.addWidget(input_group)
        
        # 创建按钮区域
        button_layout = QHBoxLayout()
        self.translate_button = QPushButton("翻译")
        self.translate_button.clicked.connect(self._translate_text)
        self.clear_button = QPushButton("清空")
        self.clear_button.clicked.connect(self._clear_all)
        button_layout.addWidget(self.translate_button)
        button_layout.addWidget(self.clear_button)
        button_layout.addStretch()
        layout.addLayout(button_layout)
        
        # 创建输出区域
        output_group = QGroupBox("翻译结果")
        output_layout = QVBoxLayout()
        self.output_text_edit = QTextEdit()
        self.output_text_edit.setPlaceholderText("翻译结果将显示在这里...")
        self.output_text_edit.setMinimumHeight(100)
        self.output_text_edit.setReadOnly(True)  # 设置为只读
        output_layout.addWidget(self.output_text_edit)
        output_group.setLayout(output_layout)
        layout.addWidget(output_group)
        
        self.setLayout(layout)
    
    def _setup_translator(self):
        """设置翻译器"""
        try:
            self.translator = get_qwen_translator()
        except Exception as e:
            QMessageBox.warning(self, "翻译器初始化失败", 
                              f"无法初始化翻译器: {str(e)}\n"
                              "请检查API密钥配置是否正确。")
    
    def _translate_text(self):
        """翻译文本"""
        if not self.translator:
            QMessageBox.warning(self, "翻译器未就绪", "翻译器未正确初始化，请检查配置。")
            return
        
        # 获取输入文本
        input_text = self.input_text_edit.toPlainText().strip()
        if not input_text:
            QMessageBox.warning(self, "输入为空", "请输入需要翻译的文本。")
            return
        
        try:
            # 执行翻译
            translated_text = self.translator.translate_text(input_text)
            
            # 显示翻译结果
            self.output_text_edit.setPlainText(translated_text)
        except Exception as e:
            QMessageBox.critical(self, "翻译失败", f"翻译过程中发生错误:\n{str(e)}")
    
    def _clear_all(self):
        """清空所有内容"""
        self.input_text_edit.clear()
        self.output_text_edit.clear()


class TranslationDebuggerDialog(QWidget):
    """翻译调试器对话框类"""
    
    def __init__(self):
        super().__init__()
        self.setWindowTitle("翻译调试器")
        self.resize(600, 500)
        self._setup_ui()
    
    def _setup_ui(self):
        """设置界面"""
        layout = QVBoxLayout()
        self.translation_debugger = TranslationDebuggerWidget()
        layout.addWidget(self.translation_debugger)
        self.setLayout(layout)