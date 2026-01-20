"""
文件选择组件模块（PyQt6版本）
"""

import re
from pathlib import Path

from PyQt6.QtCore import pyqtSignal, Qt
from PyQt6.QtWidgets import (QGroupBox, QVBoxLayout, QHBoxLayout, QPushButton,
                             QListWidget, QFileDialog, QMessageBox, QMenu)


class FileSelectorWidget(QGroupBox):
    """文件选择组件类"""
    
    files_selected = pyqtSignal(list)
    
    def __init__(self):
        super().__init__("序列文件选择")
        self.setAcceptDrops(True) # 启用拖拽功能
        self._setup_ui()
        self._connect_signals()
        self.selected_files = []
        self.is_processing = False # [新增] 处理状态标志
    
    def _setup_ui(self):
        """设置界面"""
        layout = QVBoxLayout()
        
        # 创建文件列表
        self.file_list = QListWidget()
        self.file_list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection) # 允许多选
        self.file_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu) # 启用右键菜单
        layout.addWidget(self.file_list)
        
        # 创建按钮布局
        button_layout = QHBoxLayout()
        
        self.add_button = QPushButton("添加文件")
        button_layout.addWidget(self.add_button)
        
        self.remove_button = QPushButton("移除选中")
        button_layout.addWidget(self.remove_button)
        
        self.clear_button = QPushButton("清空列表")
        button_layout.addWidget(self.clear_button)
        
        layout.addLayout(button_layout)
        self.setLayout(layout)
    
    def _connect_signals(self):
        """连接信号"""
        self.add_button.clicked.connect(self._add_files)
        self.remove_button.clicked.connect(self._remove_selected)
        self.clear_button.clicked.connect(self._clear_files)
        self.file_list.itemSelectionChanged.connect(self._on_selection_changed)
        self.file_list.customContextMenuRequested.connect(self._show_context_menu) # 连接右键菜单信号
    
    def set_processing_state(self, is_processing):
        """设置处理状态，用于控制按钮可用性"""
        self.is_processing = is_processing
        # 不再禁用按钮，而是通过点击时的提示来交互
        # self.add_button.setEnabled(not is_processing)
        # self.remove_button.setEnabled(not is_processing)
        # self.clear_button.setEnabled(not is_processing)

    def dragEnterEvent(self, event):
        """拖拽进入事件"""
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        """拖拽释放事件"""
        if self.is_processing:
            QMessageBox.warning(self, "操作受限", "任务正在进行中，请先停止任务或等待完成后再添加文件。")
            return

        files = []
        for url in event.mimeData().urls():
            file_path = url.toLocalFile()
            if file_path:
                path = Path(file_path)
                if path.is_file():
                    # 简单的后缀过滤，可选
                    suffix = path.suffix.lower()
                    if suffix in ['.fasta', '.fa', '.fna', '.seq', '.gz', '.txt']:
                        files.append(str(path))
                    else:
                        # 如果需要支持所有文件，可以去掉上面的if，或者询问用户
                        # 这里为了用户体验，默认接受所有文件，但在处理时可能会报错
                        files.append(str(path))
                elif path.is_dir():
                    # 简单的目录支持：添加目录下的所有fasta文件
                    for p in path.glob('*'):
                        if p.is_file() and p.suffix.lower() in ['.fasta', '.fa', '.fna', '.seq', '.gz']:
                            files.append(str(p))
        
        if files:
            self._add_files_internal(files)

    def _add_files_internal(self, files):
        """内部添加文件逻辑"""
        added_files = []
        duplicate_files = []
        
        for file_path in files:
            # 规范化路径以进行比较
            normalized_path = str(Path(file_path).resolve())
            
            # 检查是否已存在（使用规范化路径比较）
            is_duplicate = False
            for existing_file in self.selected_files:
                if str(Path(existing_file).resolve()) == normalized_path:
                    is_duplicate = True
                    break
            
            if not is_duplicate:
                self.selected_files.append(file_path)
                # 注意：这里不再直接 addItem，而是依赖最后的排序刷新
                added_files.append(file_path)
            else:
                duplicate_files.append(Path(file_path).name)
        
        if added_files:
            # 自动排序并刷新列表，同时发出信号
            self._sort_files_by_name()
            
        if duplicate_files:
            # 如果有重复文件，提示用户
            msg = f"以下 {len(duplicate_files)} 个文件已存在，已跳过：\n"
            if len(duplicate_files) > 5:
                msg += "\n".join(duplicate_files[:5]) + "\n..."
            else:
                msg += "\n".join(duplicate_files)
            QMessageBox.information(self, "重复文件", msg)

    def _add_files(self):
        """添加文件按钮点击事件"""
        if self.is_processing:
            QMessageBox.warning(self, "操作受限", "任务正在进行中，请先停止任务或等待完成后再添加文件。")
            return

        files, _ = QFileDialog.getOpenFileNames(
            self,
            "选择序列文件",
            "",
            "Sequence Files (*.fasta *.fa *.fna *.seq *.fasta.gz);;All Files (*)"
        )
        
        if files:
            self._add_files_internal(files)
    
    def _remove_selected(self):
        """移除选中的文件"""
        if self.is_processing:
            QMessageBox.warning(self, "操作受限", "任务正在进行中，请先停止任务或等待完成后再移除文件。")
            return

        selected_items = self.file_list.selectedItems()
        if not selected_items:
            QMessageBox.information(self, "提示", "请先选择要移除的文件")
            return
        
        # 获取所有选中项的行号，并按从大到小排序
        # 这样删除时不会影响前面元素的索引
        rows_to_remove = sorted([self.file_list.row(item) for item in selected_items], reverse=True)
        
        for row in rows_to_remove:
            # 从 UI 列表中移除
            self.file_list.takeItem(row)
            # 从数据列表中移除
            if 0 <= row < len(self.selected_files):
                del self.selected_files[row]
        
        # 发出文件选择信号
        self.files_selected.emit(self.selected_files)
    
    def _clear_files(self):
        """清空文件列表"""
        if self.is_processing:
            QMessageBox.warning(self, "操作受限", "任务正在进行中，请先停止任务或等待完成后再清空列表。")
            return

        self.file_list.clear()
        self.selected_files.clear()
        self.files_selected.emit(self.selected_files)
    
    def _on_selection_changed(self):
        """处理选择变化事件"""
        # 可以在这里添加选择变化的处理逻辑
        pass
    
    def get_selected_files(self):
        """获取选中的文件列表"""
        return self.selected_files[:]

    def _show_context_menu(self, pos):
        """显示右键菜单"""
        if self.is_processing:
            return

        menu = QMenu(self)
        
        sort_action = menu.addAction("按名称排序 (自然排序)")
        sort_action.triggered.connect(self._sort_files_by_name)
        
        menu.addSeparator()
        
        remove_action = menu.addAction("移除选中")
        remove_action.triggered.connect(self._remove_selected)
        
        clear_action = menu.addAction("清空列表")
        clear_action.triggered.connect(self._clear_files)
        
        menu.exec(self.file_list.mapToGlobal(pos))

    def _natural_sort_key(self, s):
        """
        自然排序键生成函数
        将字符串分割成数字和非数字部分，实现类似 Windows 文件管理器的排序
        例如：file2.txt 会排在 file10.txt 之前
        """
        return [int(text) if text.isdigit() else text.lower()
                for text in re.split('([0-9]+)', Path(s).name)]

    def _sort_files_by_name(self):
        """按文件名进行自然排序"""
        if not self.selected_files:
            return
            
        # 使用自然排序算法对 selected_files 进行排序
        self.selected_files.sort(key=self._natural_sort_key)
        
        # 重新填充列表
        self.file_list.clear()
        for file_path in self.selected_files:
            self.file_list.addItem(Path(file_path).name)
            
        # 发出信号
        self.files_selected.emit(self.selected_files)
