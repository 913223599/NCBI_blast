"""
历史记录对话框
用于查看和管理BLAST任务历史记录
"""

import json
import os
from pathlib import Path
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem, 
    QPushButton, QHeaderView, QMessageBox, QLabel, QAbstractItemView
)

from src.utils.history_manager import HistoryManager

class HistoryDialog(QDialog):
    # 信号：当用户选择加载某条记录时触发，传递结果目录
    load_history_signal = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("任务历史记录")
        self.resize(900, 600)
        self.history_manager = HistoryManager()
        
        self._setup_ui()
        self._load_data()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        
        # 标题和说明
        header_layout = QHBoxLayout()
        title = QLabel("<b>BLAST 任务历史</b>")
        title.setStyleSheet("font-size: 16px; color: #333;")
        header_layout.addWidget(title)
        header_layout.addStretch()
        layout.addLayout(header_layout)
        
        # 表格
        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(["ID", "任务名称", "时间", "文件数", "状态"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents) # ID列自适应
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents) # 时间列自适应
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers) # 不可编辑
        self.table.doubleClicked.connect(self._on_load_clicked) # 双击加载
        layout.addWidget(self.table)
        
        # 按钮栏
        btn_layout = QHBoxLayout()
        
        self.btn_delete = QPushButton("删除选中")
        self.btn_delete.clicked.connect(self._on_delete_clicked)
        
        self.btn_clear = QPushButton("清空所有")
        self.btn_clear.clicked.connect(self._on_clear_clicked)
        
        self.btn_load = QPushButton("加载任务")
        self.btn_load.setStyleSheet("background-color: #409eff; color: white; font-weight: bold;")
        self.btn_load.clicked.connect(self._on_load_clicked)
        
        self.btn_close = QPushButton("关闭")
        self.btn_close.clicked.connect(self.accept)
        
        btn_layout.addWidget(self.btn_delete)
        btn_layout.addWidget(self.btn_clear)
        btn_layout.addStretch()
        btn_layout.addWidget(self.btn_load)
        btn_layout.addWidget(self.btn_close)
        
        layout.addLayout(btn_layout)

    def _load_data(self):
        """从数据库加载数据到表格"""
        self.table.setRowCount(0)
        records = self.history_manager.get_all_tasks()
        
        self.records_map = {} # 用于存储行号到完整记录的映射
        
        for row_idx, record in enumerate(records):
            self.table.insertRow(row_idx)
            
            # 存储完整记录以便后续使用
            self.records_map[row_idx] = record
            
            # 设置单元格内容
            self.table.setItem(row_idx, 0, QTableWidgetItem(str(record['id'])))
            self.table.setItem(row_idx, 1, QTableWidgetItem(record['task_name']))
            self.table.setItem(row_idx, 2, QTableWidgetItem(record['timestamp']))
            self.table.setItem(row_idx, 3, QTableWidgetItem(str(record['file_count'])))
            
            status_item = QTableWidgetItem(record['status'])
            if record['status'] == 'completed':
                status_item.setForeground(Qt.GlobalColor.green)
            elif record['status'] == 'failed':
                status_item.setForeground(Qt.GlobalColor.red)
            else:
                status_item.setForeground(Qt.GlobalColor.blue)
            self.table.setItem(row_idx, 4, status_item)

    def _get_selected_record(self):
        """获取当前选中的记录"""
        current_row = self.table.currentRow()
        if current_row >= 0 and current_row in self.records_map:
            return self.records_map[current_row]
        return None

    def _on_load_clicked(self):
        """加载选中记录的结果"""
        record = self._get_selected_record()
        if not record:
            QMessageBox.warning(self, "提示", "请先选择一条记录")
            return
            
        result_dir = record['result_dir']
        if not os.path.exists(result_dir):
            QMessageBox.critical(self, "错误", f"任务目录不存在: {result_dir}\n可能已被删除或移动。")
            return
            
        # 发送信号通知主窗口加载
        self.load_history_signal.emit(result_dir)
        self.accept() # 关闭对话框

    def _on_delete_clicked(self):
        """删除选中记录"""
        record = self._get_selected_record()
        if not record:
            return
            
        reply = QMessageBox.question(self, "确认", f"确定要删除任务 '{record['task_name']}' 吗？\n(不会删除实际的结果文件)", 
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            if self.history_manager.delete_task(record['id']):
                self._load_data() # 刷新表格

    def _on_clear_clicked(self):
        """清空所有记录"""
        reply = QMessageBox.question(self, "确认", "确定要清空所有历史记录吗？", 
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            if self.history_manager.clear_history():
                self._load_data()
