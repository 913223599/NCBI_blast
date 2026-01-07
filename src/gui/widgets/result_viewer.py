# -*- coding: utf-8 -*-
"""
结果展示组件模块
"""

import csv
import shutil
from pathlib import Path
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QPushButton, QTreeWidget,
                             QTreeWidgetItem, QFileDialog, QMessageBox, QHeaderView, QMenu, QHBoxLayout, QGroupBox)
from PyQt6.QtCore import pyqtSignal, QObject, Qt, QThread, pyqtSlot
from PyQt6.QtGui import QColor, QAction
from PyQt6.QtWidgets import QApplication

from src.utils.translation import get_blast_result_translator


class TranslationWorker(QObject):
    """翻译工作线程类"""
    # 定义信号
    finished = pyqtSignal(list)  # 翻译完成信号，传递翻译结果
    progress = pyqtSignal(str)   # 进度更新信号，传递进度信息
    error = pyqtSignal(str)      # 错误信号，传递错误信息
    
    def __init__(self, csv_file, biology_translator):
        super().__init__()
        self.csv_file = csv_file
        self.biology_translator = biology_translator
        self._is_running = True
    
    def stop(self):
        """停止翻译工作"""
        self._is_running = False
    
    def process_csv(self):
        """处理CSV文件并翻译内容"""
        try:
            translated_rows = []
            
            with open(self.csv_file, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                rows = list(reader)
                
                if rows:
                    for i, row in enumerate(rows):
                        if not self._is_running:
                            break
                            
                        # 发送进度更新信号
                        self.progress.emit(f"正在翻译第 {i+1} 条记录...")
                        
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
                                # 处理翻译结果，去除标识符如[AI]或[本地]
                                if translated_species:
                                    if translated_species.startswith(('[AI]', '[本地]')):
                                        species = translated_species[4:].strip()
                                    else:
                                        species = translated_species
                            except Exception as e:
                                print(f"翻译物种时出错: {e}")
                        
                        if genus and self.biology_translator:
                            try:
                                translated_genus = self.biology_translator.translate_text(genus)
                                # 处理翻译结果，去除标识符如[AI]或[本地]
                                if translated_genus and translated_genus != genus:
                                    if translated_genus.startswith(('[AI]', '[本地]')):
                                        genus = translated_genus[4:].strip()
                                    else:
                                        genus = translated_genus
                            except Exception as e:
                                print(f"翻译属名时出错: {e}")
                        
                        # 使用生物学翻译器翻译基因类型和序列类型
                        if gene_type and self.biology_translator:
                            try:
                                translated_gene = self.biology_translator.translate_text(gene_type)
                                # 处理翻译结果，去除标识符如[AI]或[本地]
                                if translated_gene and translated_gene != gene_type:
                                    if translated_gene.startswith(('[AI]', '[本地]')):
                                        gene_type = translated_gene[4:].strip()
                                    else:
                                        gene_type = translated_gene
                            except Exception as e:
                                print(f"翻译基因类型时出错: {e}")
                        
                        if sequence_type and self.biology_translator:
                            try:
                                translated_sequence = self.biology_translator.translate_text(sequence_type)
                                # 处理翻译结果，去除标识符如[AI]或[本地]
                                if translated_sequence and translated_sequence != sequence_type:
                                    if translated_sequence.startswith(('[AI]', '[本地]')):
                                        sequence_type = translated_sequence[4:].strip()
                                    else:
                                        sequence_type = translated_sequence
                            except Exception as e:
                                print(f"翻译序列类型时出错: {e}")
                        
                        # 构建翻译后的行数据
                        translated_row = {
                            'species': species,
                            'genus': genus,
                            'strain': strain,
                            'gene_type': gene_type,
                            'sequence_type': sequence_type,
                            'similarity': similarity,
                            'e_value': e_value,
                            'original_row': row
                        }
                        
                        translated_rows.append(translated_row)
                
                # 发送完成信号
                self.finished.emit(translated_rows)
        except Exception as e:
            # 发送错误信号
            print(f"[ERROR] 处理CSV文件时发生异常: {e}")
            import traceback
            traceback.print_exc()
            self.error.emit(str(e))


class ResultViewerSignals(QObject):
    """结果查看器信号类"""
    
    item_selected = pyqtSignal(str)
    retry_blast = pyqtSignal(str)


class ResultViewerWidget(QGroupBox):
    """结果展示组件类 - 完全重构的树形结构逻辑"""
    
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
        # 为每个文件维护独立的翻译线程和工作对象
        self.translation_threads = {}  # 存储每个文件的翻译线程
        self.translation_workers = {}  # 存储每个文件的翻译工作对象
        self.all_sequence_files = []  # 存储所有序列文件列表
        
        # 完全重构的数据结构
        self.file_data = {}  # 存储每个文件的完整信息
        self.file_items = {}  # 存储文件名到QTreeWidgetItem的映射
        self.sequence_items = {}  # 存储文件名+序列ID到序列QTreeWidgetItem的映射
        self.result_items = {}  # 存储文件名+序列ID+结果ID到结果QTreeWidgetItem的映射
    
    def _setup_ui(self):
        """设置界面"""
        layout = QVBoxLayout()
        
        # 创建结果树
        self.result_tree = QTreeWidget()
        self.result_tree.setHeaderLabels(["文件名/序列/结果", "状态", "耗时"])
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
                
                # 获取AI模型参数
                ai_model = self.translation_settings.get('ai_model', 'deepseek-r1')
                
                # 初始化生物学翻译器，传递AI模型参数
                self.biology_translator = get_biology_translator(
                    data_file=csv_file, 
                    use_ai=True, 
                    ai_api_key=api_key,
                    ai_model=ai_model  # 传递AI模型参数
                )
            except Exception as e:
                print(f"初始化生物学翻译器失败: {e}")
                import traceback
                traceback.print_exc()
                self.biology_translator = None
        else:
            self.biology_translator = None

    def update_sequence_files(self, sequence_files):
        """更新序列文件列表 - 重构版本"""
        self.all_sequence_files = sequence_files
        print(f"更新序列文件列表，文件数量: {len(sequence_files)}")
        
        # 重构：重新构建整个结果树
        self._rebuild_result_tree(sequence_files)
        
        # 强制更新UI显示
        self.result_tree.update()
        try:
            QApplication.processEvents()  # 强制处理UI事件
        except:
            pass  # 如果QApplication不可用，忽略这个调用
    
    def _rebuild_result_tree(self, sequence_files):
        """完全重建结果树 - 重构核心逻辑"""
        # 清空现有内容和内部数据结构
        self.result_tree.clear()
        self.file_items.clear()
        self.sequence_items.clear()
        self.result_items.clear()
        self.file_data.clear()

        # 为每个文件创建初始数据结构
        for seq_file in sequence_files:
            file_name = Path(seq_file).name
            
            # 创建文件节点
            file_item = QTreeWidgetItem(self.result_tree, [file_name, '待处理', ''])
            file_item.setExpanded(False)
            
            # 初始化该文件的完整数据结构
            self.file_data[file_name] = {
                'file_path': seq_file,
                'sequences': {},  # 存储每个序列的信息
                'status': '待处理',
                'elapsed_time': '',
                'expanded': False
            }
            
            # 保存文件项的引用
            self.file_items[file_name] = file_item

    def update_file_status(self, result):
        """更新文件状态 - 重构版本"""
        # 检查是否是多序列处理结果
        if 'sequence_id' in result:
            # 这是一个多序列处理结果
            self._update_multi_sequence_result(result)
        else:
            # 这是一个单序列处理结果
            self._update_single_sequence_result(result)

    def _update_multi_sequence_result(self, result):
        """更新多序列处理结果 - 重构版本"""
        file_path = result.get("file", "")
        file_name = Path(file_path).name
        sequence_id = result.get("sequence_id", "")

        status = "成功" if result.get("status") == "success" else "失败"
        elapsed_time = f"{result.get('elapsed_time', 0):.2f}秒" if "elapsed_time" in result else "N/A"

        # 确保文件数据结构存在
        if file_name not in self.file_data:
            self.file_data[file_name] = {
                'file_path': file_path,
                'sequences': {},
                'status': '待处理',
                'elapsed_time': '',
                'expanded': False
            }
        
        # 更新序列信息
        self.file_data[file_name]['sequences'][sequence_id] = {
            'status': status,
            'elapsed_time': elapsed_time,
            'result': result
        }
        
        # 计算文件总体状态
        all_seqs = self.file_data[file_name]['sequences']
        success_count = sum(1 for seq in all_seqs.values() if seq['status'] == '成功')
        total_count = len(all_seqs)
        
        if success_count == total_count:
            overall_status = '成功'
        elif success_count == 0:
            overall_status = '失败'
        else:
            overall_status = f'部分完成({success_count}/{total_count})'
        
        self.file_data[file_name]['status'] = overall_status

        # 保存结果数据
        combined_key = f"{file_name}#{sequence_id}"
        self.results_data[combined_key] = result

        # 获取或创建文件节点
        file_item = self._ensure_file_item_exists(file_name, file_path)

        # 更新文件节点状态
        file_item.setText(1, self.file_data[file_name]['status'])
        file_item.setText(2, self.file_data[file_name].get('elapsed_time', ''))

        # 获取或创建序列节点
        sequence_item = self._ensure_sequence_item_exists(file_item, file_name, sequence_id)

        # 更新序列节点状态
        sequence_item.setText(1, status)
        sequence_item.setText(2, elapsed_time)

        # 显示前3个比对结果
        if result.get("csv_file"):
            self._display_top_results(sequence_item, result.get("csv_file"))

        # 强制更新UI显示
        self.result_tree.update()
        print(f"多序列结果 - 文件 {file_name}, 序列 {sequence_id} 状态已更新为: {status}")

    def _update_single_sequence_result(self, result):
        """更新单序列处理结果 - 重构版本"""
        file_path = result.get("file", "")
        file_name = Path(file_path).name
        result_status = result.get("status", "")

        # 根据不同的状态设置显示文本
        if result_status == "processing":
            status = "处理中"
            elapsed_time = ""  # 处理中时不显示时间
        elif result_status == "success":
            status = "成功"
            elapsed_time = f"{result.get('elapsed_time', 0):.2f}秒" if "elapsed_time" in result else "N/A"
        elif result_status == "error":
            status = "失败"
            elapsed_time = f"{result.get('elapsed_time', 0):.2f}秒" if "elapsed_time" in result else "N/A"
        else:
            status = "失败"  # 默认为失败状态
            elapsed_time = "N/A"

        # 保存结果数据
        self.results_data[file_name] = result

        # 更新文件数据结构
        if file_name not in self.file_data:
            self.file_data[file_name] = {
                'file_path': file_path,
                'sequences': {},
                'status': '待处理',
                'elapsed_time': '',
                'expanded': False
            }
        
        self.file_data[file_name]['status'] = status
        self.file_data[file_name]['elapsed_time'] = elapsed_time

        # 获取或创建文件节点并更新
        file_item = self._ensure_file_item_exists(file_name, file_path)
        file_item.setText(1, status)
        file_item.setText(2, elapsed_time)

        # 强制更新UI显示
        self.result_tree.update()
        print(f"文件 {file_name} 状态已更新为: {status}, 当前项目数量: {self.result_tree.topLevelItemCount()}")

    def _ensure_file_item_exists(self, file_name, file_path):
        """确保文件节点存在 - 重构版本"""
        if file_name in self.file_items:
            return self.file_items[file_name]
        
        # 如果文件节点不存在，创建它
        file_item = QTreeWidgetItem(self.result_tree, [file_name, '待处理', ''])
        file_item.setExpanded(False)
        
        # 初始化该文件的完整数据结构（如果不存在）
        if file_name not in self.file_data:
            self.file_data[file_name] = {
                'file_path': file_path,
                'sequences': {},
                'status': '待处理',
                'elapsed_time': '',
                'expanded': False
            }
        
        # 保存文件项的引用
        self.file_items[file_name] = file_item
        return file_item

    def _ensure_sequence_item_exists(self, file_item, file_name, sequence_id):
        """确保序列节点存在 - 重构版本"""
        key = f"{file_name}#{sequence_id}"
        if key in self.sequence_items:
            return self.sequence_items[key]
        
        # 搜索子节点中是否已存在该序列
        for i in range(file_item.childCount()):
            child = file_item.child(i)
            if child.text(0) == sequence_id:
                self.sequence_items[key] = child
                return child
        
        # 如果序列节点不存在，创建它
        sequence_item = QTreeWidgetItem(file_item, [sequence_id, '待处理', ''])
        sequence_item.setExpanded(False)
        
        # 保存序列项的引用
        self.sequence_items[key] = sequence_item
        return sequence_item

    def _display_top_results(self, parent_item, csv_file):
        """显示前3个比对结果 - 重构版本"""
        # 清空现有的结果子节点
        self._clear_result_children(parent_item)

        if not Path(csv_file).exists():
            return

        # 读取CSV文件并获取前3个结果
        try:
            with open(csv_file, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                rows = list(reader)
                # 只取前3个结果
                top_results = rows[:3] if len(rows) > 3 else rows

                for i, row in enumerate(top_results):
                    species = row.get('物种', 'N/A')
                    similarity = row.get('相似度', 'N/A')
                    e_value = row.get('E值', 'N/A')

                    result_text = f"{i+1}. {species} (相似度: {similarity}, E值: {e_value})"
                    result_item = QTreeWidgetItem(parent_item, [result_text, '', ''])

                    # 为结果节点设置不同的背景色以区分层次
                    for col in range(3):
                        result_item.setBackground(col, QColor(245, 245, 245))
        except Exception as e:
            result_item = QTreeWidgetItem(parent_item, [f"读取结果失败: {str(e)}", '', ''])

    def _clear_result_children(self, parent_item):
        """清除结果子节点 - 重构版本"""
        # 从后往前删除，避免索引变化问题
        for i in range(parent_item.childCount() - 1, -1, -1):
            child = parent_item.child(i)
            # 检查是否为结果节点（以数字开头）
            if self._is_result_node(child):
                parent_item.takeChild(i)

    def _is_result_node(self, item):
        """判断是否为结果节点 - 重构版本"""
        text = item.text(0)
        return text.startswith(('1.', '2.', '3.', '4.', '5.', '6.', '7.', '8.', '9.', '0.')) or \
               text.startswith('读取结果失败:')

    def _on_item_clicked(self, item, column):
        """处理项目点击事件 - 重构版本"""
        # 获取父节点判断层级
        parent = item.parent()
        
        if parent is None:
            # 点击的是顶级文件节点
            file_name = item.text(0)
            self.signals.item_selected.emit(file_name)

            # 切换展开/折叠状态
            is_expanded = not item.isExpanded()
            item.setExpanded(is_expanded)
            
            # 更新文件数据中的展开状态
            if file_name in self.file_data:
                self.file_data[file_name]['expanded'] = is_expanded

            # 如果是展开状态，确保所有序列节点都已创建（即使还没有处理结果）
            if is_expanded:
                # 直接使用file_data中存储的文件路径
                if file_name in self.file_data:
                    target_file_path = self.file_data[file_name]['file_path']
                    
                    # 检查文件中包含哪些序列（如果是FASTA文件）
                    sequences_in_file = self._parse_sequences_from_file(target_file_path)
                    
                    # 确保所有序列节点都已创建
                    for sequence_id in sequences_in_file:
                        # 检查是否已经在file_data中存在此序列信息
                        if sequence_id not in self.file_data[file_name]['sequences']:
                            # 为尚未处理的序列初始化状态
                            self.file_data[file_name]['sequences'][sequence_id] = {
                                'status': '待处理',
                                'elapsed_time': '',
                                'result': None
                            }
                        
                        # 确保序列节点存在
                        self._ensure_sequence_item_exists(item, file_name, sequence_id)
                
        else:
            # 点击的是序列节点
            sequence_id = item.text(0)
            file_item = parent
            file_name = file_item.text(0)
            
            # 切换展开/折叠状态
            is_expanded = not item.isExpanded()
            item.setExpanded(is_expanded)
            
            # 加载序列的详细结果信息
            if is_expanded and file_name in self.file_data:
                file_info = self.file_data[file_name]
                if sequence_id in file_info['sequences']:
                    seq_info = file_info['sequences'][sequence_id]
                    result = seq_info['result']
                    
                    # 获取CSV文件路径
                    if result and result.get('csv_file'):
                        csv_file = result.get('csv_file')
                        if csv_file and Path(csv_file).exists():
                            # 异步加载和翻译CSV结果
                            self._display_csv_results_async(item, csv_file)

        # 强制更新UI显示
        item.treeWidget().update()

    def _parse_sequences_from_file(self, file_path):
        """从FASTA文件中解析序列ID列表"""
        sequences = []
        try:
            file_path = Path(file_path)
            if file_path.suffix.lower() in ['.fasta', '.fas', '.fa']:
                with open(file_path, 'r', encoding='utf-8') as f:
                    for line in f:
                        if line.startswith('>'):
                            # 提取序列ID（标题行去掉>符号）
                            header = line[1:].strip()
                            # 取第一部分作为序列ID（通常是空格前的部分）
                            seq_id = header.split()[0] if header.split() else f"sequence_{len(sequences)+1}"
                            sequences.append(seq_id)
        except Exception as e:
            print(f"解析序列文件失败: {e}")
            # 如果解析失败，返回一个默认序列ID
            sequences = [f"sequence_{i+1}" for i in range(1)]  # 至少有一个
        
        return sequences

    def _display_csv_results_async(self, parent_item, csv_file):
        """异步显示CSV结果 - 重构版本"""
        # 显示正在翻译的提示
        if parent_item.childCount() > 0:
            child = parent_item.child(0)
            child.setText(0, "正在翻译详细信息...")
            # 处理事件队列，确保UI更新
            try:
                QApplication.processEvents()
            except:
                pass  # 如果QApplication不可用，忽略这个调用
        
        # 使用文件名作为键来管理独立的线程
        file_key = Path(csv_file).name
        
        # 如果该文件已有线程在运行，先清理旧的线程
        if file_key in self.translation_threads and self.translation_threads[file_key].isRunning():
            if file_key in self.translation_workers:
                self.translation_workers[file_key].stop()
            self.translation_threads[file_key].quit()
            self.translation_threads[file_key].wait()
        
        # 创建新的线程和工作对象
        translation_thread = QThread()
        translation_worker = TranslationWorker(csv_file, self.biology_translator)
        
        # 保存线程和工作对象的引用
        self.translation_threads[file_key] = translation_thread
        self.translation_workers[file_key] = translation_worker
        
        # 将工作对象移动到线程中
        translation_worker.moveToThread(translation_thread)
        
        # 连接信号和槽
        translation_thread.started.connect(translation_worker.process_csv)
        translation_worker.finished.connect(lambda rows: self._on_translation_finished(parent_item, rows, file_key))
        translation_worker.progress.connect(lambda msg: self._on_translation_progress(parent_item, msg))
        translation_worker.error.connect(lambda error: self._on_translation_error(parent_item, error, file_key))
        
        # 确保线程和工作对象在任务完成后被正确释放
        translation_worker.finished.connect(translation_thread.quit)
        translation_worker.finished.connect(translation_worker.deleteLater)
        translation_thread.finished.connect(translation_thread.deleteLater)
        
        # 清理线程引用
        translation_thread.finished.connect(lambda: self._cleanup_thread_reference(file_key))
        
        # 启动线程
        translation_thread.start()

    def _on_translation_finished(self, parent_item, translated_rows, file_key):
        """处理翻译完成 - 重构版本"""
        # 清空现有子节点
        for i in range(parent_item.childCount() - 1, -1, -1):
            parent_item.takeChild(0)
        
        # 显示翻译结果
        if translated_rows:
            for i, row_data in enumerate(translated_rows):
                species = row_data['species']
                genus = row_data['genus']
                strain = row_data['strain']
                gene_type = row_data['gene_type']
                sequence_type = row_data['sequence_type']
                similarity = row_data['similarity']
                e_value = row_data['e_value']
                
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

        # 翻译完成后，确保界面更新
        try:
            QApplication.processEvents()
        except:
            pass  # 如果QApplication不可用，忽略这个调用
        
        # 强制更新UI显示
        parent_item.treeWidget().update()
    
    def _on_translation_progress(self, parent_item, message):
        """处理翻译进度更新 - 重构版本"""
        if parent_item.childCount() > 0:
            child = parent_item.child(0)
            child.setText(0, message)
            try:
                QApplication.processEvents()
            except:
                pass  # 如果QApplication不可用，忽略这个调用
        
        # 强制更新UI显示
        parent_item.treeWidget().update()
    
    def _cleanup_thread_reference(self, file_key):
        """清理线程引用 - 重构版本"""
        if file_key in self.translation_threads:
            del self.translation_threads[file_key]
        if file_key in self.translation_workers:
            del self.translation_workers[file_key]
    
    def _on_translation_error(self, parent_item, error, file_key=None):
        """处理翻译错误 - 重构版本"""
        if parent_item.childCount() > 0:
            child = parent_item.child(0)
            child.setText(0, f"翻译失败: {error}")
        # 清理线程引用
        if file_key:
            self._cleanup_thread_reference(file_key)
        
        # 强制更新UI显示
        parent_item.treeWidget().update()
    
    def closeEvent(self, event):
        """处理窗口关闭事件"""
        # 停止所有正在运行的翻译线程
        for file_key, thread in self.translation_threads.items():
            if thread.isRunning():
                if file_key in self.translation_workers:
                    self.translation_workers[file_key].stop()
                thread.quit()
                thread.wait()
        
        # 清空线程字典
        self.translation_threads.clear()
        self.translation_workers.clear()
        
        event.accept()

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
            # 清空内部数据结构
            self.file_data.clear()
            self.file_items.clear()
            self.sequence_items.clear()
            self.result_items.clear()
            # 发送清空信号（如果需要）
    
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