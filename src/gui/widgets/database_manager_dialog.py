"""
数据库管理对话框
用于创建和管理本地BLAST数据库
"""

import os

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QPushButton, QLabel, QFileDialog, QComboBox, QLineEdit, QMessageBox,
    QGroupBox, QProgressBar
)

from src.blast.database_manager import DatabaseManager


class CreateDbThread(QThread):
    """后台创建数据库线程"""
    finished = pyqtSignal(bool, str)

    def __init__(self, manager, input_file, db_type, title, out_name):
        super().__init__()
        self.manager = manager
        self.input_file = input_file
        self.db_type = db_type
        self.title = title
        self.out_name = out_name

    def run(self):
        success, msg = self.manager.make_blast_db(
            self.input_file, self.db_type, self.title, self.out_name
        )
        self.finished.emit(success, msg)

class DatabaseManagerDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("本地数据库管理")
        self.resize(800, 600)
        self.db_manager = DatabaseManager()
        
        self._setup_ui()
        self._refresh_db_list()

    def _setup_ui(self):
        layout = QHBoxLayout(self)
        
        # 左侧：现有数据库列表
        left_panel = QGroupBox("现有数据库")
        left_layout = QVBoxLayout(left_panel)
        
        self.db_list = QListWidget()
        left_layout.addWidget(self.db_list)
        
        btn_layout = QHBoxLayout()
        self.btn_refresh = QPushButton("刷新")
        self.btn_refresh.clicked.connect(self._refresh_db_list)
        self.btn_delete = QPushButton("删除选中")
        self.btn_delete.clicked.connect(self._delete_selected_db)
        
        btn_layout.addWidget(self.btn_refresh)
        btn_layout.addWidget(self.btn_delete)
        left_layout.addLayout(btn_layout)
        
        layout.addWidget(left_panel, 1)
        
        # 右侧：创建新数据库
        right_panel = QGroupBox("创建新数据库")
        right_layout = QVBoxLayout(right_panel)
        
        # 输入文件
        right_layout.addWidget(QLabel("输入 FASTA 文件:"))
        file_layout = QHBoxLayout()
        self.input_file_edit = QLineEdit()
        self.input_file_edit.setReadOnly(True)
        self.btn_browse = QPushButton("浏览...")
        self.btn_browse.clicked.connect(self._browse_file)
        file_layout.addWidget(self.input_file_edit)
        file_layout.addWidget(self.btn_browse)
        right_layout.addLayout(file_layout)
        
        # 数据库类型
        right_layout.addWidget(QLabel("数据库类型:"))
        self.type_combo = QComboBox()
        self.type_combo.addItems(["核酸 (nucl)", "蛋白质 (prot)"])
        right_layout.addWidget(self.type_combo)
        
        # 标题
        right_layout.addWidget(QLabel("数据库标题:"))
        self.title_edit = QLineEdit()
        right_layout.addWidget(self.title_edit)
        
        # 输出名称
        right_layout.addWidget(QLabel("文件名 (英文, 无空格):"))
        self.out_name_edit = QLineEdit()
        right_layout.addWidget(self.out_name_edit)
        
        right_layout.addStretch()
        
        # 进度条
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        right_layout.addWidget(self.progress_bar)
        
        # 创建按钮
        self.btn_create = QPushButton("创建数据库")
        self.btn_create.setStyleSheet("background-color: #409eff; color: white; font-weight: bold; padding: 8px;")
        self.btn_create.clicked.connect(self._create_database)
        right_layout.addWidget(self.btn_create)
        
        layout.addWidget(right_panel, 1)

    def _browse_file(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "选择 FASTA 文件", "", "FASTA Files (*.fasta *.fa *.fas *.txt);;All Files (*)"
        )
        if file_path:
            self.input_file_edit.setText(file_path)
            # 自动填充标题和文件名
            base_name = os.path.splitext(os.path.basename(file_path))[0]
            if not self.title_edit.text():
                self.title_edit.setText(base_name)
            if not self.out_name_edit.text():
                # 简单的清理文件名
                clean_name = "".join([c if c.isalnum() else "_" for c in base_name])
                self.out_name_edit.setText(clean_name)

    def _refresh_db_list(self):
        self.db_list.clear()
        dbs = self.db_manager.list_local_databases()
        for db in dbs:
            type_str = "核酸" if db['type'] == 'nucl' else "蛋白"
            item_text = f"{db['name']} [{type_str}]"
            item = QListWidgetItem(item_text)
            item.setData(Qt.ItemDataRole.UserRole, db)
            self.db_list.addItem(item)

    def _delete_selected_db(self):
        item = self.db_list.currentItem()
        if not item:
            return
            
        db_info = item.data(Qt.ItemDataRole.UserRole)
        reply = QMessageBox.question(
            self, "确认删除", 
            f"确定要删除数据库 '{db_info['name']}' 吗？\n此操作不可恢复。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            if self.db_manager.delete_database(db_info['name']):
                self._refresh_db_list()
                QMessageBox.information(self, "成功", "数据库已删除")
            else:
                QMessageBox.warning(self, "失败", "删除数据库失败，可能文件被占用或权限不足。")

    def _create_database(self):
        input_file = self.input_file_edit.text()
        if not input_file:
            QMessageBox.warning(self, "提示", "请先选择输入文件")
            return
            
        title = self.title_edit.text()
        out_name = self.out_name_edit.text()
        if not title or not out_name:
            QMessageBox.warning(self, "提示", "请填写标题和文件名")
            return
            
        db_type = "nucl" if self.type_combo.currentIndex() == 0 else "prot"
        
        # 禁用界面
        self.btn_create.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0) # 忙碌状态
        
        # 启动后台线程
        self.thread = CreateDbThread(self.db_manager, input_file, db_type, title, out_name)
        self.thread.finished.connect(self._on_create_finished)
        self.thread.start()

    def _on_create_finished(self, success, msg):
        self.btn_create.setEnabled(True)
        self.progress_bar.setVisible(False)
        
        if success:
            QMessageBox.information(self, "成功", msg)
            self._refresh_db_list()
            # 清空输入
            self.input_file_edit.clear()
            self.title_edit.clear()
            self.out_name_edit.clear()
        else:
            QMessageBox.critical(self, "错误", msg)
