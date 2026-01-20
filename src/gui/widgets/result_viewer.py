# -*- coding: utf-8 -*-
"""
结果展示组件模块 - Model/View 重构版
"""

import csv
import shutil
import traceback
import os
from pathlib import Path

from PyQt6.QtCore import pyqtSignal, QObject, Qt, QThread, QModelIndex
from PyQt6.QtGui import QColor, QAction, QStandardItemModel, QStandardItem, QBrush
from PyQt6.QtWidgets import (QVBoxLayout, QPushButton, QTreeView,
                             QFileDialog, QMessageBox, QHeaderView, QMenu, QHBoxLayout, QGroupBox, QAbstractItemView)

from src.utils.translation import get_blast_result_translator
from src.gui.widgets.alignment_visualizer import AlignmentVisualizerDialog
from src.utils.file_handler import FileHandler


class TranslationWorker(QObject):
    """翻译工作线程类"""
    # 定义信号
    finished = pyqtSignal(list)  # 翻译完成信号，传递翻译结果
    progress = pyqtSignal(str)  # 进度更新信号，传递进度信息
    error = pyqtSignal(str)  # 错误信号，传递错误信息

    def __init__(self, csv_file, biology_translator):
        super().__init__()
        self.csv_file = csv_file
        self.biology_translator = biology_translator
        self._is_running = True

    def stop(self):
        """停止翻译工作"""
        self._is_running = False

    def _clean_translated_text(self, original, translated):
        """辅助方法：清理翻译文本中的标识符"""
        if not translated:
            return original

        cleaned = translated
        # 去除常见标识符
        if cleaned.startswith(('[AI]', '[本地]')):
            cleaned = cleaned[4:].strip()

        # 如果清理后的文本为空，或者只包含空格，返回原文
        return cleaned if cleaned else original

    def process_csv(self):
        """处理CSV文件并翻译内容"""
        try:
            translated_rows = []

            if not Path(self.csv_file).exists():
                raise FileNotFoundError(f"结果文件不存在: {self.csv_file}")

            with open(self.csv_file, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                rows = list(reader)

                # 只处理前5个结果
                top_rows = rows[:5] if len(rows) > 5 else rows

                if top_rows:
                    for i, row in enumerate(top_rows):
                        if not self._is_running:
                            break

                        self.progress.emit(f"正在翻译第 {i + 1} 条记录...")

                        # 获取原始字段
                        fields = {
                            'species': row.get('物种', ''),
                            'genus': row.get('属名', ''),
                            'strain': row.get('菌株', ''),
                            'gene_type': row.get('基因类型', ''),
                            'sequence_type': row.get('序列类型', ''),
                            'host_info': row.get('宿主信息', ''),  # 添加宿主信息字段
                        }

                        # 批量翻译需要翻译的字段
                        if self.biology_translator:
                            for key in ['species', 'genus', 'gene_type', 'sequence_type', 'host_info']:
                                original_text = fields[key]
                                if original_text:
                                    try:
                                        trans_text = self.biology_translator.translate_text(original_text)
                                        fields[key] = self._clean_translated_text(original_text, trans_text)
                                    except Exception as e:
                                        print(f"翻译 {key} 时出错: {e}")

                        # 构建结果
                        translated_row = {
                            **fields,  # 解包翻译后的字段
                            'similarity': row.get('相似度', ''),
                            'e_value': row.get('E值', ''),
                            'original_row': row
                        }

                        translated_rows.append(translated_row)

                self.finished.emit(translated_rows)

        except Exception as e:
            print(f"[ERROR] 处理CSV文件时发生异常: {e}")
            traceback.print_exc()
            self.error.emit(str(e))


class ResultViewerSignals(QObject):
    """结果查看器信号类"""
    item_selected = pyqtSignal(str)
    retry_blast = pyqtSignal(str)


class ResultViewerWidget(QGroupBox):
    """结果展示组件类"""

    def __init__(self):
        super().__init__("结果查看")
        self.signals = ResultViewerSignals()

        # 数据存储初始化
        self.results_data = {}
        self.file_data = {}
        self.file_items = {}
        self.sequence_items = {}
        self.result_items = {}

        self.translation_states = {}
        self.original_texts = {}
        self.translated_texts = {}

        self.translation_threads = {}
        self.translation_workers = {}
        self.all_sequence_files = []

        self.current_file_item = None
        self.translator = get_blast_result_translator()
        self.biology_translator = None
        self.translation_settings = {}
        self.api_key = None

        # Model 初始化
        self.model = QStandardItemModel()
        self.model.setHorizontalHeaderLabels(["文件名/序列/结果", "状态", "耗时"])

        self._setup_ui()
        self._connect_signals()

    def _setup_ui(self):
        """设置界面 - 优化布局参数"""
        layout = QVBoxLayout()
        layout.setContentsMargins(10, 15, 10, 10)  # 优化边距

        # 创建结果树 (QTreeView)
        self.result_tree = QTreeView()
        self.result_tree.setModel(self.model)
        self.result_tree.setAlternatingRowColors(True)
        self.result_tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.result_tree.customContextMenuRequested.connect(self._show_context_menu)
        self.result_tree.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)

        # 性能优化：统一行高，提升大量数据时的渲染性能
        self.result_tree.setUniformRowHeights(True)
        # 禁用不需要的交互
        self.result_tree.setMouseTracking(False)
        self.result_tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)

        # 设置列宽为用户可调
        header = self.result_tree.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)  # 第一列可手动调整
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)  # 第二列自适应内容
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)  # 耗时列固定
        self.result_tree.setColumnWidth(0, 500)
        self.result_tree.setColumnWidth(2, 80)

        layout.addWidget(self.result_tree)

        # 按钮布局
        button_layout = QHBoxLayout()
        button_layout.addStretch()  # 按钮靠右

        self.export_button = QPushButton("导出结果")
        self.export_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.export_button.clicked.connect(self._export_results)
        button_layout.addWidget(self.export_button)

        self.clear_button = QPushButton("清空结果")
        self.clear_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clear_button.clicked.connect(self._clear_results)
        button_layout.addWidget(self.clear_button)

        layout.addLayout(button_layout)
        self.setLayout(layout)

    def _connect_signals(self):
        self.result_tree.clicked.connect(self._on_item_clicked)

    def set_translation_settings(self, translation_settings: dict, api_key: str = None):
        """设置翻译设置"""
        self.translation_settings = translation_settings or {}
        self.api_key = api_key

        if self.translation_settings.get('use_ai', True):
            try:
                from src.utils.translation import get_biology_translator
                from pathlib import Path
                # 优化路径获取方式，更稳健
                project_root = Path(__file__).resolve().parents[3]
                csv_file = str(project_root / "translation_data.csv")

                ai_model = self.translation_settings.get('ai_model', 'deepseek-r1')

                self.biology_translator = get_biology_translator(
                    data_file=csv_file,
                    use_ai=True,
                    ai_api_key=api_key,
                    ai_model=ai_model
                )
            except Exception as e:
                print(f"初始化生物学翻译器失败: {e}")
                self.biology_translator = None
        else:
            self.biology_translator = None

    def update_sequence_files(self, sequence_files):
        """更新序列文件列表"""
        self.all_sequence_files = sequence_files
        self._rebuild_result_tree(sequence_files)
        # 不需要 processEvents，正常 update 即可
        self.result_tree.update()

    def _normalize_path(self, path_str):
        """统一路径格式，解决路径不一致导致的重复节点问题"""
        if not path_str:
            return ""
        try:
            # [增强] 使用 resolve() 获取绝对路径，解决符号链接和相对路径问题
            p = Path(path_str).resolve()
            return os.path.normcase(str(p))
        except Exception:
            # 降级处理
            try:
                return os.path.normcase(os.path.normpath(os.path.abspath(path_str)))
            except Exception:
                return path_str

    def _normalize_seq_id(self, raw_id):
        """
        统一序列ID格式，确保与 BatchProcessor 中的处理逻辑一致
        BatchProcessor: seq_id = sequence_info['id'].replace('|', '_').replace(' ', '_')
        """
        if not raw_id:
            return "unknown_seq"
        return raw_id.replace('|', '_').replace(' ', '_')

    def _rebuild_result_tree(self, sequence_files):
        """完全重建结果树"""
        self.model.removeRows(0, self.model.rowCount())
        self.file_items.clear()
        self.sequence_items.clear()
        self.result_items.clear()
        self.file_data.clear()
        self.results_data.clear()

        seen_paths = set() # [新增] 用于去重

        for seq_file in sequence_files:
            # [修复] 使用统一的路径格式
            file_path = self._normalize_path(str(seq_file))
            
            # [新增] 防止重复添加相同文件
            if file_path in seen_paths:
                continue
            seen_paths.add(file_path)

            file_name = Path(seq_file).name

            # 预先创建数据结构
            self.file_data[file_path] = {
                'file_path': file_path,
                'sequences': {},
                'status': '待处理',
                'elapsed_time': '',
                'expanded': False
            }

            item0 = QStandardItem(file_name)
            item1 = QStandardItem('待处理')
            item2 = QStandardItem('')
            self.model.appendRow([item0, item1, item2])
            
            self.file_items[file_path] = item0

            # 初始化翻译状态
            file_item_key = f"file#{file_path}"
            self.translation_states[file_item_key] = False
            
            # 预解析序列
            sequences = self._parse_sequences_from_file(seq_file)
            
            # [修改] 如果只有一个序列，不需要预先创建子节点
            if len(sequences) > 1:
                # [关键修复] 明确标记为多序列模式，防止后续被误判为单序列
                item0.setData("multi_sequence", Qt.ItemDataRole.UserRole)
                
                for seq_id in sequences:
                    # [修改] 使用小写键存储，解决大小写不一致导致的重复节点
                    key = seq_id.lower()
                    self.file_data[file_path]['sequences'][key] = {'status': '待处理', 'original_id': seq_id}
                    # 预先创建序列节点
                    self._ensure_sequence_item_exists(item0, file_path, seq_id)
            elif len(sequences) == 1:
                # 单序列，初始化数据但不创建子节点
                seq_id = sequences[0]
                key = seq_id.lower()
                self.file_data[file_path]['sequences'][key] = {'status': '待处理', 'original_id': seq_id}
                # [关键修复] 明确标记为单序列模式
                item0.setData("single_sequence", Qt.ItemDataRole.UserRole)
                item0.setData(seq_id, Qt.ItemDataRole.UserRole + 1)

    def update_file_status(self, result):
        """更新文件状态"""
        # 统一逻辑入口
        if 'sequence_id' in result:
            self._update_multi_sequence_result(result)
        else:
            self._update_single_sequence_result(result)

    def _calculate_overall_status(self, sequences_data):
        """计算总体状态"""
        total_count = len(sequences_data)
        if total_count == 0:
            return "待处理"

        # 统计非"待处理"的数量（即已完成或失败的）
        completed_count = sum(1 for s in sequences_data.values() if s.get('status') != '待处理')
        success_count = sum(1 for s in sequences_data.values() if s.get('status') == '成功')
        
        if completed_count == 0:
            return "待处理"
        
        if completed_count == total_count:
            if success_count == total_count:
                return "成功"
            elif success_count == 0:
                return "失败"
            else:
                return f"完成({success_count}/{total_count})"
        else:
            return f"处理中 ({completed_count}/{total_count})"

    def _update_common_logic(self, file_path, file_name, status, elapsed_time):
        """辅助方法：更新文件节点的通用逻辑"""
        # 确保数据结构存在
        if file_path not in self.file_data:
            self.file_data[file_path] = {
                'file_path': file_path,
                'sequences': {},
                'status': '待处理',
                'elapsed_time': '',
                'expanded': False
            }

        # 获取节点并更新UI
        file_item = self._ensure_file_item_exists(file_name, file_path)

        # 更新文件节点状态
        self._set_item_text(file_item, 1, status)
        if elapsed_time:
            self._set_item_text(file_item, 2, elapsed_time)

        # 设置颜色提示状态
        color = None
        if status == "成功":
            color = QColor("#67C23A")  # 绿色
        elif status == "失败":
            color = QColor("#F56C6C")  # 红色
        elif "处理中" in status:
            color = QColor("#409EFF")  # 蓝色
        
        if color:
            self._set_item_foreground(file_item, 1, color)

        return file_item

    def _update_multi_sequence_result(self, result):
        """更新多序列处理结果"""
        # [修复] 使用统一的路径格式
        file_path = self._normalize_path(result.get("file", ""))
        if not file_path:
            return

        file_name = Path(file_path).name
        sequence_id = result.get("sequence_id", "")
        seq_key = sequence_id.lower() # [修改] 使用小写键

        status_code = result.get("status")
        status_text = "成功" if status_code == "success" else "失败"
        elapsed_time = f"{result.get('elapsed_time', 0):.2f}s" if "elapsed_time" in result else "-"

        # 1. 确保文件级数据存在
        if file_path not in self.file_data:
            # 如果是意外的新文件（未预解析），初始化它
            self.file_data[file_path] = {
                'file_path': file_path,
                'sequences': {},
                'status': '处理中',
                'elapsed_time': '',
                'expanded': False
            }

        # 2. 更新单条序列数据
        # 注意：这里直接更新字典中的项，如果 sequence_id 已存在（预解析的），则更新状态
        if 'sequences' not in self.file_data[file_path]:
            self.file_data[file_path]['sequences'] = {}
            
        self.file_data[file_path]['sequences'][seq_key] = {
            'status': status_text,
            'elapsed_time': elapsed_time,
            'result': result
        }
        
        # 获取文件节点以便检查状态
        file_item = self._ensure_file_item_exists(file_name, file_path)

        # 3. 计算并更新总体状态
        # [修改] 如果只有一个序列，直接更新文件状态
        if len(self.file_data[file_path]['sequences']) <= 1:
             self.file_data[file_path]['status'] = status_text
             self._update_common_logic(file_path, file_name, status_text, elapsed_time)
             
             # 缓存结果
             self.results_data[f"{file_path}#{seq_key}"] = result
             
             # 如果有CSV结果，直接挂载到文件节点下（如果展开）
             if result.get("csv_file"):
                 # 标记该文件节点为单序列模式，方便点击处理
                 file_item.setData("single_sequence", Qt.ItemDataRole.UserRole)
                 file_item.setData(sequence_id, Qt.ItemDataRole.UserRole + 1)
                 
                 # 如果已经展开，直接显示结果
                 if self.result_tree.isExpanded(file_item.index()):
                     self._display_top_results(file_item, result.get("csv_file"))
        else:
            # 多序列逻辑
            
            # [关键修复] 只有当文件节点被错误标记为单序列，且确实有多个子节点需要显示时才切换
            # 避免因为初始化时的标记导致清空已存在的子节点
            is_marked_single = file_item.data(Qt.ItemDataRole.UserRole) == "single_sequence"
            
            # 检查是否真的有子节点（预解析的）
            has_children = file_item.rowCount() > 0
            
            if is_marked_single and has_children:
                # 如果标记为单序列但有子节点，说明标记错了，直接修正标记，不清空子节点
                file_item.setData("multi_sequence", Qt.ItemDataRole.UserRole)
            elif is_marked_single and not has_children:
                # 确实是单序列模式转多序列（未预解析的情况），需要清空挂载的结果
                file_item.setData("multi_sequence", Qt.ItemDataRole.UserRole)
                self._clear_result_children(file_item)

            overall_status = self._calculate_overall_status(self.file_data[file_path]['sequences'])
            self.file_data[file_path]['status'] = overall_status

            # 4. 更新UI - 文件节点
            self._update_common_logic(file_path, file_name, overall_status, "")
            
            # 5. 更新UI - 序列节点
            sequence_item = self._ensure_sequence_item_exists(file_item, file_path, sequence_id)
            self._set_item_text(sequence_item, 1, status_text)
            self._set_item_text(sequence_item, 2, elapsed_time)

            if status_code == "success":
                self._set_item_foreground(sequence_item, 1, QColor("#67C23A"))
            elif status_code == "error":
                self._set_item_foreground(sequence_item, 1, QColor("#F56C6C"))

            # 6. 缓存结果
            self.results_data[f"{file_path}#{seq_key}"] = result

            if result.get("csv_file"):
                self._display_top_results(sequence_item, result.get("csv_file"))

    def _update_single_sequence_result(self, result):
        """更新单序列处理结果"""
        try:
            # [修复] 使用统一的路径格式
            file_path = self._normalize_path(result.get("file", ""))
            if not file_path:
                print("警告: 结果中没有文件路径")
                return

            # 如果是历史记录加载的，可能没有原始文件名，尝试从 display_name 获取
            if result.get("from_history"):
                file_name = result.get("display_name", Path(file_path).name)
            else:
                file_name = Path(file_path).name
                
            result_status = result.get("status", "")

            status_map = {
                "processing": ("处理中", "#409EFF"),
                "success": ("成功", "#67C23A"),
                "error": ("失败", "#F56C6C")
            }

            status_text, color_code = status_map.get(result_status, ("未知", "#909399"))
            elapsed_time = f"{result.get('elapsed_time', 0):.2f}s" if "elapsed_time" in result and result_status != "processing" else ""

            # 使用 file_path 作为键
            self.results_data[file_path] = result

            # 1. 确保文件级数据存在
            if file_path not in self.file_data:
                self.file_data[file_path] = {
                    'file_path': file_path,
                    'sequences': {},
                    'status': '待处理',
                    'elapsed_time': '',
                    'expanded': False
                }
            
            self.file_data[file_path].update({
                'status': status_text,
                'elapsed_time': elapsed_time
            })

            # 2. 更新UI - 文件节点
            file_item = self._update_common_logic(file_path, file_name, status_text, elapsed_time)
            
            # 3. 解析序列以确定是单序列还是多序列
            sequences = []
            if result.get("from_history"):
                if "sequence_id" in result:
                    sequences = [result["sequence_id"]]
                else:
                    seq_name = file_name.replace("_blast_result", "")
                    sequences = [seq_name]
            elif Path(file_path).exists():
                sequences = self._parse_sequences_from_file(file_path)
            
            if not sequences:
                sequences = ["sequence_1"]

            # [关键修改] 区分单序列和多序列的处理逻辑
            if len(sequences) > 1:
                # 多序列模式：不标记为single_sequence，不关联特定seq_id到文件节点
                if file_item.data(Qt.ItemDataRole.UserRole) == "single_sequence":
                    file_item.setData("multi_sequence", Qt.ItemDataRole.UserRole)
                
                # 如果是处理中状态，更新所有子节点
                if result_status == "processing":
                    for seq_id in sequences:
                        seq_key = seq_id.lower()
                        if 'sequences' not in self.file_data[file_path]:
                            self.file_data[file_path]['sequences'] = {}
                        
                        if seq_key not in self.file_data[file_path]['sequences']:
                             self.file_data[file_path]['sequences'][seq_key] = {}
                        
                        self.file_data[file_path]['sequences'][seq_key]['status'] = status_text
                        
                        seq_item = self._ensure_sequence_item_exists(file_item, file_path, seq_id)
                        self._set_item_text(seq_item, 1, status_text)
                        self._set_item_foreground(seq_item, 1, QColor(color_code))
            else:
                # 单序列模式
                file_item.setData("single_sequence", Qt.ItemDataRole.UserRole)
                
                seq_id = sequences[0]
                seq_key = seq_id.lower()
                if 'sequences' not in self.file_data[file_path]:
                    self.file_data[file_path]['sequences'] = {}

                self.file_data[file_path]['sequences'][seq_key] = {
                    'status': status_text,
                    'elapsed_time': elapsed_time,
                    'result': result
                }
                
                file_item.setData(seq_id, Qt.ItemDataRole.UserRole + 1)

                if result.get("csv_file"):
                    if self.result_tree.isExpanded(file_item.index()):
                        self._display_top_results(file_item, result.get("csv_file"))
                    
        except Exception as e:
            print(f"更新单序列结果时出错: {e}")
            traceback.print_exc()

    def _ensure_file_item_exists(self, file_name, file_path):
        # 使用 file_path 作为键
        if file_path in self.file_items:
            # 如果已存在，更新文件名（可能是历史记录加载的更友好的名字）
            item = self.file_items[file_path]
            if file_name and item.text() != file_name:
                if os.sep not in file_name and '/' not in file_name:
                     item.setText(file_name)
            return item

        # [新增] 防御性检查：通过文件名和 resolve 路径再次检查是否存在重复项
        # 这可以防止因路径字符串微小差异（如盘符大小写、分隔符）导致的重复
        for path, item in self.file_items.items():
            # 如果文件名相同，进一步检查路径是否指向同一文件
            if item.text() == file_name:
                try:
                    if Path(path).resolve() == Path(file_path).resolve():
                        # 发现是同一个文件，更新映射并返回现有项
                        self.file_items[file_path] = item
                        return item
                except Exception:
                    pass
        
        # [新增] 终极防御：如果文件名完全匹配，且我们没有找到其他匹配项，
        # 假设它是同一个文件（在单次运行上下文中，同名文件通常是同一个，或者用户意图如此）
        # 这解决了路径解析在某些极端情况下的不一致问题
        for path, item in self.file_items.items():
            if item.text() == file_name:
                # 更新映射
                self.file_items[file_path] = item
                return item

        item0 = QStandardItem(file_name)
        item1 = QStandardItem('待处理')
        item2 = QStandardItem('')
        self.model.appendRow([item0, item1, item2])
        
        self.file_items[file_path] = item0
        
        # 保持数据结构同步
        if file_path not in self.file_data:
            self.file_data[file_path] = {'file_path': file_path, 'sequences': {}, 'status': '待处理'}
        return item0

    def _ensure_sequence_item_exists(self, file_item, file_path, sequence_id):
        # [修改] 使用小写键
        key = f"{file_path}#{sequence_id.lower()}"
        if key in self.sequence_items:
            # 检查该 item 是否仍然在 model 中
            item = self.sequence_items[key]
            if item.model() is not None:
                return item
            else:
                # 如果 item 已经不在 model 中（可能被清除了），从缓存中移除
                del self.sequence_items[key]

        # [修改] 双重检查：防止重复添加 (大小写不敏感)
        for i in range(file_item.rowCount()):
            child = file_item.child(i, 0)
            if child.text().lower() == sequence_id.lower():
                self.sequence_items[key] = child
                return child

        item0 = QStandardItem(sequence_id)
        item1 = QStandardItem('待处理')
        item2 = QStandardItem('')
        file_item.appendRow([item0, item1, item2])
        
        self.sequence_items[key] = item0
        return item0

    def _set_item_text(self, item, column, text):
        """辅助方法：设置指定列的文本"""
        if column == 0:
            item.setText(text)
        else:
            sibling = self._get_sibling_item(item, column)
            if sibling:
                sibling.setText(text)

    def _set_item_foreground(self, item, column, color):
        """辅助方法：设置指定列的颜色"""
        brush = QBrush(color)
        if column == 0:
            item.setForeground(brush)
        else:
            sibling = self._get_sibling_item(item, column)
            if sibling:
                sibling.setForeground(brush)

    def _get_sibling_item(self, item, column):
        """辅助方法：获取同一行的其他列Item"""
        parent = item.parent()
        if parent:
            return parent.child(item.row(), column)
        else:
            return self.model.item(item.row(), column)

    def _display_top_results(self, parent_item, csv_file):
        """显示前 5 个比对结果 - [优化版]"""
        self._clear_result_children(parent_item)

        if not Path(csv_file).exists():
            return

        try:
            with open(csv_file, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)

                for i, row in enumerate(reader):
                    if i >= 5:  # 只读前5行
                        break

                    species = row.get('物种', 'N/A')
                    similarity = row.get('相似度', 'N/A')
                    e_value = row.get('E值', 'N/A')

                    result_text = f"{i + 1}. {species} | 相似度: {similarity} | E值: {e_value}"
                    
                    item0 = QStandardItem(result_text)
                    item1 = QStandardItem('')
                    item2 = QStandardItem('')

                    for item in [item0, item1, item2]:
                        item.setBackground(QBrush(QColor("#FAFAFA")))
                        item.setForeground(QBrush(QColor("#606266")))
                    
                    parent_item.appendRow([item0, item1, item2])

        except Exception as e:
            item0 = QStandardItem(f"读取失败: {str(e)}")
            parent_item.appendRow([item0, QStandardItem(''), QStandardItem('')])

    def _clear_result_children(self, parent_item):
        for i in range(parent_item.rowCount() - 1, -1, -1):
            child = parent_item.child(i, 0)
            if self._is_result_node(child):
                parent_item.removeRow(i)

    def _is_result_node(self, item):
        text = item.text()
        # 简单的启发式判断
        return text[0:2].isdigit() and '.' in text[:3] or text.startswith('读取失败') or text == "无详细结果"

    def _on_item_clicked(self, index):
        """处理点击逻辑"""
        try:
            item = self.model.itemFromIndex(index)
            # 确保获取的是第一列的 item，因为逻辑主要绑定在第一列
            if item.column() != 0:
                item = self._get_sibling_item(item, 0)

            parent = item.parent()

            # 切换展开/折叠 (UX优化: 单击即可切换)
            is_expanded = self.result_tree.isExpanded(item.index())
            self.result_tree.setExpanded(item.index(), not is_expanded)

            if parent is None:  # 文件节点
                self.signals.item_selected.emit(item.text())
                if not is_expanded: # 如果之前是折叠的，现在展开了
                    # [修改] 检查是否是单序列模式
                    is_single = item.data(Qt.ItemDataRole.UserRole) == "single_sequence"
                    
                    # 查找对应的 file_path
                    found_path = None
                    for path, f_item in self.file_items.items():
                        if f_item == item:
                            found_path = path
                            break
                    
                    if found_path and found_path in self.file_data:
                        path = found_path
                        
                        if is_single:
                            # 单序列模式：直接加载结果
                            seq_id = item.data(Qt.ItemDataRole.UserRole + 1)
                            if seq_id:
                                self._load_sequence_details(item, path, seq_id)
                            else:
                                # 尝试获取第一个序列
                                seqs = self.file_data[path].get('sequences', {})
                                if seqs:
                                    seq_id = list(seqs.keys())[0]
                                    # 注意：这里 seqs 的 key 已经是小写了，但 _load_sequence_details 会处理
                                    # 但我们需要 original_id 吗？
                                    # file_data 存储了 {'status':..., 'original_id':...}
                                    # 我们可以尝试获取 original_id
                                    original_id = seqs[seq_id].get('original_id', seq_id)
                                    self._load_sequence_details(item, path, original_id)
                        else:
                            # 多序列模式：加载序列列表
                            # [修复] 增加对文件不存在的处理
                            if Path(path).exists():
                                seqs = self._parse_sequences_from_file(path)
                                for seq_id in seqs:
                                    self._ensure_sequence_item_exists(item, path, seq_id)
                            else:
                                # 尝试从缓存恢复
                                if 'sequences' in self.file_data[path]:
                                    for seq_key in self.file_data[path]['sequences']:
                                        # 这里 seq_key 是小写的，我们需要 original_id
                                        original_id = self.file_data[path]['sequences'][seq_key].get('original_id', seq_key)
                                        self._ensure_sequence_item_exists(item, path, original_id)

            elif parent.parent() is None:  # 序列节点
                if not is_expanded:
                    # 同样需要找到 file_path
                    file_item = parent
                    found_path = None
                    for path, f_item in self.file_items.items():
                        if f_item == file_item:
                            found_path = path
                            break
                            
                    if found_path:
                        self._load_sequence_details(item, found_path, item.text())
        except Exception as e:
            print(f"点击项目时出错: {e}")
            traceback.print_exc()

    def _load_sequence_details(self, item, file_path, sequence_id):
        """加载序列详细结果"""
        if file_path in self.file_data:
            seqs_data = self.file_data[file_path]['sequences']
            key = sequence_id.lower() # [修改] 使用小写键
            if key in seqs_data:
                result = seqs_data[key].get('result')
                if result and result.get('csv_file'):
                    self._display_csv_results_async(item, result['csv_file'])

    def _parse_sequences_from_file(self, file_path):
        """解析序列ID - 使用 FileHandler 保持一致性"""
        sequences = []
        try:
            path = Path(file_path)
            # 使用 FileHandler 解析，确保与 Processor 逻辑一致
            handler = FileHandler()
            # 只读取 ID，不需要序列内容
            # read_fasta_file_iter 是生成器，我们只遍历它
            for seq_info in handler.read_fasta_file_iter(str(path)):
                raw_id = seq_info['id']
                # BatchProcessor 中做了替换: .replace('|', '_').replace(' ', '_')
                # FileHandler 返回的 id 已经是 str(record.id)
                # 我们需要应用相同的标准化
                seq_id = self._normalize_seq_id(raw_id)
                sequences.append(seq_id)
            
            if not sequences:
                sequences.append(path.stem)

        except Exception as e:
            print(f"解析序列失败: {e}")
            sequences = [Path(file_path).stem]  # Fallback

        return sequences

    def _display_csv_results_async(self, parent_item, csv_file):
        """异步加载详情"""
        if parent_item.rowCount() > 0:
            parent_item.child(0, 0).setText("正在加载详情...")
        else:
            parent_item.appendRow([QStandardItem("正在加载详情..."), QStandardItem(''), QStandardItem('')])

        file_key = Path(csv_file).name

        # 清理旧线程
        self._cleanup_thread(file_key)

        # 创建新线程
        thread = QThread()
        worker = TranslationWorker(csv_file, self.biology_translator)

        self.translation_threads[file_key] = thread
        self.translation_workers[file_key] = worker

        worker.moveToThread(thread)

        thread.started.connect(worker.process_csv)
        worker.finished.connect(lambda rows: self._on_translation_finished(parent_item, rows, file_key))
        worker.progress.connect(lambda msg: self._update_loading_text(parent_item, msg))
        worker.error.connect(lambda err: self._on_translation_error(parent_item, err, file_key))

        # 自动清理
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(lambda: self._cleanup_thread_reference(file_key))

        thread.start()

    def _update_loading_text(self, parent_item, text):
        if parent_item.rowCount() > 0:
            parent_item.child(0, 0).setText(text)

    def _on_translation_finished(self, parent_item, translated_rows, file_key):
        # 移除旧节点
        for i in range(parent_item.rowCount() - 1, -1, -1):
            parent_item.removeRow(i)

        if not translated_rows:
            parent_item.appendRow([QStandardItem("无详细结果"), QStandardItem(''), QStandardItem('')])
            return

        for i, row in enumerate(translated_rows):
            # 构建主要信息
            parts = [row.get('species', '')]
            genus = row.get('genus', '')
            if genus and genus != row.get('species', ''): parts.append(genus)
            strain = row.get('strain', '')
            if strain: parts.append(strain)
            host_info = row.get('host_info', '')
            if host_info: parts.append(f"[宿主: {host_info}]")

            main_text = f"{i + 1}. {' '.join(filter(None, parts))}"
            item0 = QStandardItem(main_text)
            item1 = QStandardItem('')
            item2 = QStandardItem('')
            parent_item.appendRow([item0, item1, item2])

            # 构建次要信息
            sub_parts = []
            similarity = row.get('similarity', '')
            if similarity: sub_parts.append(f"相似度: {similarity}")
            e_value = row.get('e_value', '')
            if e_value: sub_parts.append(f"E值: {e_value}")
            gene_type = row.get('gene_type', '')
            if gene_type: sub_parts.append(f"基因: {gene_type}")

            if sub_parts:
                sub_item0 = QStandardItem(", ".join(sub_parts))
                sub_item0.setForeground(QBrush(QColor("#909399")))
                item0.appendRow([sub_item0, QStandardItem(''), QStandardItem('')])

    def _on_translation_error(self, parent_item, error, file_key):
        if parent_item.rowCount() > 0:
            parent_item.child(0, 0).setText(f"加载错误: {error}")
        self._cleanup_thread_reference(file_key)

    def _cleanup_thread(self, key):
        if key in self.translation_threads and self.translation_threads[key].isRunning():
            if key in self.translation_workers:
                self.translation_workers[key].stop()
            self.translation_threads[key].quit()
            self.translation_threads[key].wait()

    def _cleanup_thread_reference(self, key):
        self.translation_threads.pop(key, None)
        self.translation_workers.pop(key, None)

    def closeEvent(self, event):
        for key in list(self.translation_threads.keys()):
            self._cleanup_thread(key)
        event.accept()

    def _export_results(self):
        if not self.results_data:
            QMessageBox.information(self, "提示", "暂无结果可导出")
            return

        save_dir = QFileDialog.getExistingDirectory(self, "选择导出目录")
        if not save_dir: return

        count = 0
        try:
            for fname, data in self.results_data.items():
                src = data.get("csv_file") or data.get("result_file")
                if src and Path(src).exists():
                    shutil.copy2(src, Path(save_dir) / f"{fname}_results.csv")
                    count += 1
            QMessageBox.information(self, "成功", f"已导出 {count} 个文件")
        except Exception as e:
            QMessageBox.critical(self, "错误", str(e))

    def _clear_results(self):
        if QMessageBox.question(self, "确认", "确定清空所有结果？") == QMessageBox.StandardButton.Yes:
            self._clear_results_internal()

    def _clear_results_internal(self):
        """内部清空结果方法"""
        self.results_data.clear()
        self.model.removeRows(0, self.model.rowCount())
        self.file_data.clear()
        self.file_items.clear()
        self.sequence_items.clear()
        self.translation_states.clear()

    def _show_context_menu(self, pos):
        index = self.result_tree.indexAt(pos)
        if not index.isValid(): return
        
        item = self.model.itemFromIndex(index)
        if item.column() != 0:
            item = self._get_sibling_item(item, 0)

        menu = QMenu(self)
        parent = item.parent()

        # 通用操作
        action_visualize = QAction("可视化比对", self)
        action_visualize.triggered.connect(lambda: self._open_visualizer(item))
        
        # 只有在有结果时才启用
        if self._get_result_data_for_item(item):
            menu.addAction(action_visualize)
            menu.addSeparator()

        if parent is None:  # File
            menu.addAction("重试比对", lambda: self.signals.retry_blast.emit(item.text()))
            menu.addAction("导出查询信息", lambda: self._export_query_info(item.text()))

        elif parent.parent() is None:  # Sequence
            pass

        else:  # Result Leaf
            pass  # 不显示任何右键菜单项

        menu.exec(self.result_tree.mapToGlobal(pos))

    def _get_result_data_for_item(self, item):
        """辅助函数：根据 Tree Item 获取其对应的结果数据"""
        parent = item.parent()
        
        # 1. 文件节点 (一级节点)
        if parent is None: 
            # 反向查找 file_path
            file_path = None
            for path, f_item in self.file_items.items():
                if f_item == item:
                    file_path = path
                    break
            
            if not file_path:
                return None

            # 检查是否标记为单序列模式
            is_single = item.data(Qt.ItemDataRole.UserRole) == "single_sequence"
            if is_single:
                # 获取关联的 sequence_id
                seq_id = item.data(Qt.ItemDataRole.UserRole + 1)
                if seq_id:
                    # 尝试组合键 (针对多序列文件但只有一条序列的情况)
                    key = f"{file_path}#{seq_id.lower()}" # [修改] 使用小写键
                    if key in self.results_data:
                        return self.results_data[key]
            
            # 默认尝试直接用 file_path (针对纯单序列文件)
            return self.results_data.get(file_path)

        # 2. 序列节点 (二级节点)
        elif parent.parent() is None: 
            # 找到父节点对应的 file_path
            file_path = None
            for path, f_item in self.file_items.items():
                if f_item == parent:
                    file_path = path
                    break
            
            if file_path:
                seq_id = item.text()
                key = f"{file_path}#{seq_id.lower()}" # [修改] 使用小写键
                return self.results_data.get(key)

        return None

    def _open_visualizer(self, item):
        """打开可视化对话框"""
        result_data = self._get_result_data_for_item(item)
        if not result_data or 'result_file' not in result_data:
            QMessageBox.warning(self, "提示", "未找到有效的 BLAST 结果文件 (XML)。")
            return
            
        xml_file = result_data['result_file']
        if not Path(xml_file).exists():
            QMessageBox.critical(self, "错误", f"结果文件不存在: {xml_file}")
            return

        # 创建并显示对话框
        dialog = AlignmentVisualizerDialog(xml_file, self)
        dialog.exec()

    def _export_query_info(self, file_name):
        # 保持原逻辑
        data = self.results_data.get(file_name)
        if not data: return

        path, _ = QFileDialog.getSaveFileName(self, "保存", f"{file_name}_query.csv", "CSV (*.csv)")
        if path:
            src = data.get("csv_file") or data.get("result_file")
            if src and Path(src).exists():
                shutil.copy2(src, path)
                QMessageBox.information(self, "成功", "导出成功")
