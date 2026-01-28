"""
系统发育分析对话框
"""

import os
from pathlib import Path
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
                             QPushButton, QComboBox, QProgressBar, QMessageBox, QGroupBox)
from PyQt6.QtCore import Qt, QThread, pyqtSignal

from src.analysis.msa_engine import MSAEngine
from src.analysis.tree_builder import TreeBuilder
from src.analysis.tree_visualizer import TreeVisualizerWidget

class PhylogenyWorker(QThread):
    """后台分析线程"""
    finished = pyqtSignal(object) # 发送 Tree 对象
    error = pyqtSignal(str)
    progress = pyqtSignal(str)

    def __init__(self, input_file, msa_tool, tree_method):
        super().__init__()
        self.input_file = input_file
        self.msa_tool = msa_tool
        self.tree_method = tree_method

    def run(self):
        try:
            # 1. 多序列比对
            self.progress.emit("正在进行多序列比对...")
            msa_engine = MSAEngine(tool=self.msa_tool)
            aln_file = msa_engine.align_sequences(self.input_file)
            
            # 2. 读取比对结果
            self.progress.emit("正在解析比对结果...")
            alignment = msa_engine.read_alignment(aln_file)
            
            # 3. 构建树
            self.progress.emit(f"正在构建系统发育树 ({self.tree_method})...")
            builder = TreeBuilder(method=self.tree_method)
            tree = builder.build_tree(alignment)
            
            self.finished.emit(tree)
            
        except Exception as e:
            self.error.emit(str(e))

class PhylogenyDialog(QDialog):
    def __init__(self, input_file, parent=None):
        super().__init__(parent)
        self.setWindowTitle("系统发育分析")
        self.resize(900, 700)
        self.input_file = input_file
        
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        
        # 设置面板
        settings_group = QGroupBox("分析参数")
        settings_layout = QHBoxLayout(settings_group)
        
        settings_layout.addWidget(QLabel("比对工具:"))
        self.msa_combo = QComboBox()
        self.msa_combo.addItems(["muscle", "clustalw"])
        settings_layout.addWidget(self.msa_combo)
        
        settings_layout.addWidget(QLabel("建树方法:"))
        self.method_combo = QComboBox()
        self.method_combo.addItems(["nj", "upgma", "recursive_mds"]) # Added recursive_mds
        settings_layout.addWidget(self.method_combo)
        
        self.btn_run = QPushButton("开始分析")
        self.btn_run.clicked.connect(self._start_analysis)
        settings_layout.addWidget(self.btn_run)
        
        layout.addWidget(settings_group)
        
        # 可视化区域
        self.viz_container = QGroupBox("进化树可视化")
        self.viz_layout = QVBoxLayout(self.viz_container)
        layout.addWidget(self.viz_container, 1)
        
        # 状态栏
        self.progress_bar = QProgressBar()
        self.progress_bar.hide()
        layout.addWidget(self.progress_bar)
        
        self.status_label = QLabel("准备就绪")
        layout.addWidget(self.status_label)

    def _start_analysis(self):
        msa_tool = self.msa_combo.currentText()
        tree_method = self.method_combo.currentText()
        
        self.btn_run.setEnabled(False)
        self.progress_bar.show()
        self.progress_bar.setRange(0, 0) # 忙碌模式
        
        self.worker = PhylogenyWorker(self.input_file, msa_tool, tree_method)
        self.worker.progress.connect(self.status_label.setText)
        self.worker.finished.connect(self._on_finished)
        self.worker.error.connect(self._on_error)
        self.worker.start()

    def _on_finished(self, tree):
        self.progress_bar.hide()
        self.btn_run.setEnabled(True)
        self.status_label.setText("分析完成")
        
        # 清除旧的可视化组件
        if self.viz_layout.count() > 0:
            item = self.viz_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        
        # 添加新的可视化组件
        viz_widget = TreeVisualizerWidget(tree)
        self.viz_layout.addWidget(viz_widget)

    def _on_error(self, msg):
        self.progress_bar.hide()
        self.btn_run.setEnabled(True)
        self.status_label.setText("分析出错")
        QMessageBox.critical(self, "错误", f"分析过程中发生错误:\n{msg}")
