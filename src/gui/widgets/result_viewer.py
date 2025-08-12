"""
结果展示组件模块
"""

import csv
import shutil
from pathlib import Path
from PyQt6.QtWidgets import (QGroupBox, QVBoxLayout, QTreeWidget, QTreeWidgetItem, 
                             QHBoxLayout, QPushButton, QMenu, QMessageBox, QFileDialog, 
                             QHeaderView)
from PyQt6.QtCore import Qt, pyqtSignal, QObject
from PyQt6.QtGui import QAction

from src.utils.translation import get_blast_result_translator


class ResultViewerSignals(QObject):
    """结果查看器信号类"""
    
    item_selected = pyqtSignal(str)
    retry_blast = pyqtSignal(str)


class ResultViewerWidget(QGroupBox):
    """结果展示组件类"""
    
    # 定义信号
    item_selected = pyqtSignal(str)
    retry_blast = pyqtSignal(str)
    
    def __init__(self):
        super().__init__("结果查看")
        self.signals = ResultViewerSignals()
        self._setup_ui()
        self._connect_signals()
        self.results_data = {}  # 存储结果数据
        self.current_file_item = None  # 当前右键点击的文件项
        self.translator = get_blast_result_translator()  # 使用BLAST结果翻译器
        self.biology_translator = None  # 延迟初始化生物学翻译器
        self.translation_settings = {}  # 翻译设置
        self.api_key = None  # API密钥

    def _setup_ui(self):
        """设置界面"""
        layout = QVBoxLayout()
        
        # 创建结果树
        self.result_tree = QTreeWidget()
        self.result_tree.setHeaderLabels(["文件名/结果", "状态", "耗时"])
        self.result_tree.setAlternatingRowColors(True)
        self.result_tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)  # 启用自定义上下文菜单
        self.result_tree.customContextMenuRequested.connect(self._show_context_menu)   # 连接上下文菜单信号
        
        # 禁用鼠标悬停和选择高亮
        self.result_tree.setMouseTracking(False)
        self.result_tree.setSelectionMode(QTreeWidget.SelectionMode.NoSelection)
        
        # 设置列宽，允许用户自由调整列宽
        header = self.result_tree.header()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.result_tree.setHeaderHidden(False)
        
        layout.addWidget(self.result_tree)
        
        # 创建按钮布局
        button_layout = QHBoxLayout()
        
        self.export_button = QPushButton("导出结果")
        self.export_button.clicked.connect(self._export_results)
        button_layout.addWidget(self.export_button)
        
        self.clear_button = QPushButton("清空结果")
        self.clear_button.clicked.connect(self._clear_results)
        button_layout.addWidget(self.clear_button)
        
        layout.addLayout(button_layout)
        self.setLayout(layout)
    
    def _connect_signals(self):
        """连接信号"""
        # 只连接itemPressed信号，避免重复触发
        self.result_tree.itemPressed.connect(self._on_item_clicked)
        # self.result_tree.itemSelectionChanged.connect(self._on_item_selected)  # 移除选择变化信号连接
    
    def set_translation_settings(self, translation_settings: dict, api_key: str = None):
        """
        设置翻译设置
        
        Args:
            translation_settings (dict): 翻译设置
            api_key (str): AI翻译API密钥
        """
        self.translation_settings = translation_settings or {}
        self.api_key = api_key
        
        # 只有在需要使用AI翻译时才初始化生物学翻译器
        if self.translation_settings.get('use_ai', True):
            try:
                from src.utils.translation import get_biology_translator
                # 确保使用项目根目录下的translation_data.csv文件
                from pathlib import Path
                project_root = Path(__file__).parent.parent.parent.parent
                csv_file = str(project_root / "translation_data.csv")
                self.biology_translator = get_biology_translator(data_file=csv_file, use_ai=True, ai_api_key=api_key)
            except Exception as e:
                print(f"初始化生物学翻译器失败: {e}")
                self.biology_translator = None
        else:
            self.biology_translator = None
    
    def _export_results(self):
        """导出所有结果"""
        if not self.results_data:
            QMessageBox.information(self, "导出结果", "没有结果可以导出")
            return
        
        # 选择保存目录
        save_dir = QFileDialog.getExistingDirectory(self, "选择导出目录")
        if not save_dir:
            return
        
        try:
            exported_count = 0
            for file_name, result_data in self.results_data.items():
                if result_data.get("status") == "success":
                    # 获取结果文件路径
                    result_file_path = result_data.get("csv_file") or result_data.get("result_file")
                    if result_file_path and Path(result_file_path).exists():
                        # 构造目标文件路径
                        target_path = Path(save_dir) / f"{file_name}_results.csv"
                        # 复制文件
                        shutil.copy2(result_file_path, target_path)
                        exported_count += 1
            
            QMessageBox.information(
                self, 
                "导出完成", 
                f"成功导出 {exported_count} 个结果文件到:\n{save_dir}"
            )
        except Exception as e:
            QMessageBox.critical(self, "导出失败", f"导出过程中发生错误:\n{str(e)}")
    
    def _clear_results(self):
        """清空结果"""
        reply = QMessageBox.question(
            self, 
            "确认清空", 
            "确定要清空所有结果吗？", 
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            # 清空结果数据
            self.results_data.clear()
            # 清空结果树
            self.result_tree.clear()
            # 发送清空信号（如果需要）
    
    def _on_item_clicked(self, item, column):
        """处理项目点击事件"""
        # 如果点击的是父节点（文件节点）
        if item.parent() is None:
            file_name = item.text(0)
            self.item_selected.emit(file_name)
            
            # 切换展开/折叠状态
            is_expanded = not item.isExpanded()
            item.setExpanded(is_expanded)
            
            # 如果是展开状态且还没有加载详细信息，则加载详细信息
            if is_expanded and item.childCount() > 0:
                try:
                    child = item.child(0)
                    # 检查是否已加载详细信息（通过检查子节点的列数）
                    # 同时检查子节点的文本是否为空或正在翻译的提示
                    if (child.columnCount() == 3 and 
                        (child.text(0) == '' or child.text(0).startswith('正在加载'))):
                        # 加载并显示详细信息
                        self._load_detail_info(item, file_name)
                except Exception as e:
                    # 出现异常时，显示错误信息而不是闪退
                    if item.childCount() > 0:
                        child = item.child(0)
                        child.setText(0, f"加载结果失败: {str(e)}")
    
    def _show_context_menu(self, position):
        """显示上下文菜单"""
        # 获取右键点击的项
        item = self.result_tree.itemAt(position)
        if item and item.parent() is None:  # 确保是文件节点（父节点）
            self.current_file_item = item
            file_name = item.text(0)
            
            # 创建上下文菜单
            context_menu = QMenu(self)
            
            # 添加重试菜单项
            retry_action = QAction("重试比对", self)
            retry_action.triggered.connect(lambda: self._retry_blast(file_name))
            context_menu.addAction(retry_action)
            
            # 添加导出菜单项
            export_action = QAction("导出查询信息", self)
            export_action.triggered.connect(lambda: self._export_query_info(file_name))
            context_menu.addAction(export_action)
            
            # 显示菜单
            context_menu.exec(self.result_tree.mapToGlobal(position))
    
    def _retry_blast(self, file_name):
        """重试BLAST搜索"""
        # 发送重试信号
        self.retry_blast.emit(file_name)
    
    def _export_query_info(self, file_name):
        """导出查询信息"""
        # 查找对应的结果数据
        result_data = self.results_data.get(file_name)
        if not result_data:
            QMessageBox.warning(self, "导出失败", f"未找到文件 {file_name} 的结果数据")
            return
        
        # 选择保存位置
        save_path, _ = QFileDialog.getSaveFileName(
            self, 
            f"导出 {file_name} 的查询信息", 
            f"{file_name}_blast_results.csv", 
            "CSV Files (*.csv);;All Files (*)"
        )
        
        if save_path:
            try:
                # 检查结果文件是否存在
                result_file_path = result_data.get("csv_file") or result_data.get("result_file")
                if not result_file_path or not Path(result_file_path).exists():
                    QMessageBox.warning(self, "导出失败", f"结果文件不存在: {result_file_path}")
                    return
                
                # 复制结果文件到指定位置
                shutil.copy2(result_file_path, save_path)
                QMessageBox.information(self, "导出成功", f"查询信息已导出到:\n{save_path}")
            except Exception as e:
                QMessageBox.critical(self, "导出失败", f"导出过程中发生错误:\n{str(e)}")
    
    def _load_detail_info(self, parent_item, file_name):
        """加载并显示详细信息"""
        # 查找对应的结果数据
        result_data = None
        for data in self.results_data.values():
            if Path(data.get("file", "")).name == file_name:
                result_data = data
                break
        
        if result_data and result_data.get("status") == "success":
            # 读取CSV结果文件
            csv_file = result_data.get("csv_file") or result_data.get("result_file").replace(".xml", ".csv")
            try:
                self._display_csv_results(parent_item, csv_file)
            except Exception as e:
                # 清空子节点并显示错误信息
                if parent_item.childCount() > 0:
                    child = parent_item.child(0)
                    child.setText(0, f"加载结果失败: {str(e)}")
        elif result_data and result_data.get("status") == "error":
            # 显示错误信息
            if parent_item.childCount() > 0:
                child = parent_item.child(0)
                child.setText(0, f"处理失败: {result_data.get('error', '未知错误')}")
    
    def _display_csv_results(self, parent_item, csv_file):
        """显示CSV结果"""
        if parent_item.childCount() > 0:
            # 清空现有子节点
            for i in range(parent_item.childCount()):
                parent_item.removeChild(parent_item.child(0))
        
        try:
            with open(csv_file, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                rows = list(reader)
                
                if rows:
                    for i, row in enumerate(rows):
                        # 获取各个字段
                        species = row.get('物种', '')
                        genus = row.get('属名', '')
                        strain = row.get('菌株', '')
                        gene_type = row.get('基因类型', '')
                        sequence_type = row.get('序列类型', '')
                        similarity = row.get('相似度', '')
                        e_value = row.get('E值', '')
                        
                        # 使用生物学翻译器翻译物种和属名
                        if species and self.biology_translator:
                            try:
                                translated_species = self.biology_translator.translate_text(species)
                                if translated_species and translated_species != species:
                                    # 提取翻译结果，去除标识符如[AI]或[本地]
                                    if translated_species.startswith('[AI]'):
                                        species = translated_species[4:]  # 去掉前缀[AI]
                                    elif translated_species.startswith('[本地]'):
                                        species = translated_species[4:]  # 去掉前缀[本地]
                                    else:
                                        species = translated_species
                            except Exception as e:
                                print(f"翻译物种时出错: {e}")
                        
                        if genus and self.biology_translator:
                            try:
                                translated_genus = self.biology_translator.translate_text(genus)
                                if translated_genus and translated_genus != genus:
                                    # 提取翻译结果，去除标识符如[AI]或[本地]
                                    if translated_genus.startswith('[AI]'):
                                        genus = translated_genus[4:]  # 去掉前缀[AI]
                                    elif translated_genus.startswith('[本地]'):
                                        genus = translated_genus[4:]  # 去掉前缀[本地]
                                    else:
                                        genus = translated_genus
                            except Exception as e:
                                print(f"翻译属名时出错: {e}")
                        
                        
                        # 使用AI增强的生物学翻译器翻译基因类型和序列类型
                        if gene_type and self.biology_translator:
                            try:
                                translated_gene = self.biology_translator.translate_text(gene_type)
                                if translated_gene and translated_gene != gene_type:
                                    # 提取翻译结果，去除标识符如[AI]或[本地]
                                    if translated_gene.startswith('[AI]'):
                                        gene_type = translated_gene[4:]  # 去掉前缀[AI]
                                    elif translated_gene.startswith('[本地]'):
                                        gene_type = translated_gene[4:]  # 去掉前缀[本地]
                                    else:
                                        gene_type = translated_gene
                            except Exception as e:
                                print(f"翻译基因类型时出错: {e}")
                        
                        if sequence_type and self.biology_translator:
                            try:
                                translated_sequence = self.biology_translator.translate_text(sequence_type)
                                if translated_sequence and translated_sequence != sequence_type:
                                    # 提取翻译结果，去除标识符如[AI]或[本地]
                                    if translated_sequence.startswith('[AI]'):
                                        sequence_type = translated_sequence[4:]  # 去掉前缀[AI]
                                    elif translated_sequence.startswith('[本地]'):
                                        sequence_type = translated_sequence[4:]  # 去掉前缀[本地]
                                    else:
                                        sequence_type = translated_sequence
                            except Exception as e:
                                print(f"翻译序列类型时出错: {e}")
                        
                        # 构建显示文本
                        info_parts = []
                        if species:
                            info_parts.append(species)
                        if genus and genus != species:
                            info_parts.append(genus)
                        if strain:
                            info_parts.append(strain)
                        if gene_type:
                            info_parts.append(gene_type)
                        if sequence_type:
                            info_parts.append(sequence_type)
                        
                        # 主要信息行
                        main_info = " ".join(info_parts) if info_parts else "未命名条目"
                        item = QTreeWidgetItem(parent_item, [f"{i+1}. {main_info}", '', ''])
                        
                        # 详细信息行
                        detail_parts = []
                        if similarity:
                            detail_parts.append(f"相似度: {similarity}")
                        if e_value:
                            detail_parts.append(f"E值: {e_value}")
                        
                        if detail_parts:
                            detail_text = ", ".join(detail_parts)
                            QTreeWidgetItem(item, [detail_text, '', ''])
                else:
                    QTreeWidgetItem(parent_item, ["没有找到匹配结果", '', ''])
        except Exception as e:
            QTreeWidgetItem(parent_item, [f"加载结果失败: {str(e)}", '', ''])
    
    def update_result_tree(self, sequence_files):
        """更新结果树显示"""
        # 清空现有内容
        self.result_tree.clear()
        
        # 添加文件列表
        for seq_file in sequence_files:
            file_name = Path(seq_file).name
            
            # 添加父节点（文件）
            item = QTreeWidgetItem(self.result_tree, [file_name, '待处理', ''])
            item.setExpanded(False)
            
            # 添加子节点（详细信息占位符）
            QTreeWidgetItem(item, ['', '', ''])
    
    def update_file_status(self, result):
        """更新文件状态"""
        file_path = result.get("file", "")
        file_name = Path(file_path).name
        status = "成功" if result.get("status") == "success" else "失败"
        elapsed_time = f"{result.get('elapsed_time', 0):.2f}秒" if "elapsed_time" in result else "N/A"
        
        # 保存结果数据
        self.results_data[file_name] = result
        
        # 查找对应的树节点并更新
        root = self.result_tree.invisibleRootItem()
        for i in range(root.childCount()):
            item = root.child(i)
            if item.text(0) == file_name:
                # 只有当状态不是"待处理"时才更新状态显示
                if result.get("status") != "pending":
                    # 更新父节点的值
                    item.setText(1, status)
                    item.setText(2, elapsed_time)
                break