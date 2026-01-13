# -*- coding: utf-8 -*-
"""
结果展示组件模块 - 优化版
"""

import csv
import shutil
import traceback
from pathlib import Path

from PyQt6.QtCore import pyqtSignal, QObject, Qt, QThread
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (QVBoxLayout, QPushButton, QTreeWidget,
                             QTreeWidgetItem, QFileDialog, QMessageBox, QHeaderView, QMenu, QHBoxLayout, QGroupBox)

from src.utils.translation import get_blast_result_translator


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
                        }

                        # 批量翻译需要翻译的字段
                        if self.biology_translator:
                            for key in ['species', 'genus', 'gene_type', 'sequence_type']:
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
                            'strain': fields['strain'],  # strain 通常不需要翻译，保持原样
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

        self._setup_ui()
        self._connect_signals()

    def _setup_ui(self):
        """设置界面 - 优化布局参数"""
        layout = QVBoxLayout()
        layout.setContentsMargins(10, 15, 10, 10)  # 优化边距

        # 创建结果树
        self.result_tree = QTreeWidget()
        self.result_tree.setHeaderLabels(["文件名/序列/结果", "状态", "耗时"])
        self.result_tree.setAlternatingRowColors(True)
        self.result_tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.result_tree.customContextMenuRequested.connect(self._show_context_menu)

        # 性能优化：统一行高，提升大量数据时的渲染性能
        self.result_tree.setUniformRowHeights(True)
        # 禁用不需要的交互
        self.result_tree.setMouseTracking(False)
        self.result_tree.setSelectionMode(QTreeWidget.SelectionMode.SingleSelection)  # 改为单选更符合直觉

        # 设置列宽为用户可调
        header = self.result_tree.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)  # 第一列可手动调整
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)  # 耗时列固定
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)  # 耗时列固定
        header.resizeSection(0, 500)
        header.resizeSection(1, 80)
        header.resizeSection(2, 80)

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
        # 使用 itemClicked 而不是 itemPressed，体验更好
        self.result_tree.itemClicked.connect(self._on_item_clicked)

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

    def _rebuild_result_tree(self, sequence_files):
        """完全重建结果树"""
        self.result_tree.clear()
        self.file_items.clear()
        self.sequence_items.clear()
        self.result_items.clear()
        self.file_data.clear()

        items_to_add = []
        for seq_file in sequence_files:
            file_name = Path(seq_file).name

            # 预先创建数据结构
            self.file_data[file_name] = {
                'file_path': seq_file,
                'sequences': {},
                'status': '待处理',
                'elapsed_time': '',
                'expanded': False
            }

            item = QTreeWidgetItem([file_name, '待处理', ''])
            self.file_items[file_name] = item

            # 初始化翻译状态
            file_item_key = f"file#{file_name}"
            self.translation_states[file_item_key] = False

            items_to_add.append(item)

        self.result_tree.addTopLevelItems(items_to_add)

    def update_file_status(self, result):
        """更新文件状态"""
        # 统一逻辑入口
        if 'sequence_id' in result:
            self._update_multi_sequence_result(result)
        else:
            self._update_single_sequence_result(result)

    def _update_common_logic(self, file_name, file_path, status, elapsed_time):
        """辅助方法：更新文件节点的通用逻辑"""
        # 确保数据结构存在
        if file_name not in self.file_data:
            self.file_data[file_name] = {
                'file_path': file_path,
                'sequences': {},
                'status': '待处理',
                'elapsed_time': '',
                'expanded': False
            }

        # 获取节点并更新UI
        file_item = self._ensure_file_item_exists(file_name, file_path)

        # 只有在单序列模式或多序列汇总状态下才直接更新文件节点
        if status != "待处理":
            file_item.setText(1, status)
            file_item.setText(2, elapsed_time)

        # 设置颜色提示状态
        if status == "成功":
            file_item.setForeground(1, QColor("#67C23A"))  # 绿色
        elif status == "失败":
            file_item.setForeground(1, QColor("#F56C6C"))  # 红色
        elif status == "处理中":
            file_item.setForeground(1, QColor("#409EFF"))  # 蓝色

        return file_item

    def _update_multi_sequence_result(self, result):
        """更新多序列处理结果"""
        file_path = result.get("file", "")
        file_name = Path(file_path).name
        sequence_id = result.get("sequence_id", "")

        status_code = result.get("status")
        status_text = "成功" if status_code == "success" else "失败"
        elapsed_time = f"{result.get('elapsed_time', 0):.2f}s" if "elapsed_time" in result else "-"

        # 更新内部数据
        if file_name not in self.file_data:
            self._update_common_logic(file_name, file_path, "处理中", "")

        self.file_data[file_name]['sequences'][sequence_id] = {
            'status': status_text,
            'elapsed_time': elapsed_time,
            'result': result
        }

        # 计算总体状态
        all_seqs = self.file_data[file_name]['sequences']
        success_count = sum(1 for s in all_seqs.values() if s['status'] == '成功')
        total_count = len(all_seqs)

        overall_status = "处理中"
        if total_count > 0:
            if success_count == total_count:
                overall_status = "成功"
            elif success_count == 0 and len(all_seqs) > 0:  # 简化逻辑，实际可能需要总序列数
                overall_status = "失败"  # 暂时简化
            else:
                overall_status = f"完成({success_count}/{total_count})"

        self.file_data[file_name]['status'] = overall_status

        # 更新UI
        file_item = self._update_common_logic(file_name, file_path, overall_status, "")
        sequence_item = self._ensure_sequence_item_exists(file_item, file_name, sequence_id)

        sequence_item.setText(1, status_text)
        sequence_item.setText(2, elapsed_time)

        if status_code == "success":
            sequence_item.setForeground(1, QColor("#67C23A"))

        # 缓存结果
        self.results_data[f"{file_name}#{sequence_id}"] = result

        if result.get("csv_file"):
            self._display_top_results(sequence_item, result.get("csv_file"))

    def _update_single_sequence_result(self, result):
        """更新单序列处理结果"""
        file_path = result.get("file", "")
        file_name = Path(file_path).name
        result_status = result.get("status", "")

        status_map = {
            "processing": ("处理中", "#409EFF"),
            "success": ("成功", "#67C23A"),
            "error": ("失败", "#F56C6C")
        }

        status_text, color_code = status_map.get(result_status, ("未知", "#909399"))
        elapsed_time = f"{result.get('elapsed_time', 0):.2f}s" if "elapsed_time" in result and result_status != "processing" else ""

        self.results_data[file_name] = result

        # 更新数据和UI
        self.file_data[file_name] = self.file_data.get(file_name, {})
        self.file_data[file_name].update({
            'status': status_text,
            'elapsed_time': elapsed_time
        })

        file_item = self._update_common_logic(file_name, file_path, status_text, elapsed_time)

        # 处理序列子节点
        sequences = self._parse_sequences_from_file(file_path)
        if sequences:
            seq_id = sequences[0]
            # 初始化或更新序列数据
            if 'sequences' not in self.file_data[file_name]:
                self.file_data[file_name]['sequences'] = {}

            self.file_data[file_name]['sequences'][seq_id] = {
                'status': status_text,
                'elapsed_time': elapsed_time,
                'result': result
            }

            seq_item = self._ensure_sequence_item_exists(file_item, file_name, seq_id)
            seq_item.setText(1, status_text)
            seq_item.setText(2, elapsed_time)
            seq_item.setForeground(1, QColor(color_code))

            if result.get("csv_file"):
                self._display_top_results(seq_item, result.get("csv_file"))

    def _ensure_file_item_exists(self, file_name, file_path):
        if file_name in self.file_items:
            return self.file_items[file_name]

        item = QTreeWidgetItem(self.result_tree, [file_name, '待处理', ''])
        self.file_items[file_name] = item
        # 保持数据结构同步
        if file_name not in self.file_data:
            self.file_data[file_name] = {'file_path': file_path, 'sequences': {}, 'status': '待处理'}
        return item

    def _ensure_sequence_item_exists(self, file_item, file_name, sequence_id):
        key = f"{file_name}#{sequence_id}"
        if key in self.sequence_items:
            return self.sequence_items[key]

        # 双重检查：防止重复添加
        for i in range(file_item.childCount()):
            child = file_item.child(i)
            if child.text(0) == sequence_id:
                self.sequence_items[key] = child
                return child

        item = QTreeWidgetItem(file_item, [sequence_id, '待处理', ''])
        self.sequence_items[key] = item
        return item

    def _display_top_results(self, parent_item, csv_file):
        """显示前 5 个比对结果 - [优化版]"""
        self._clear_result_children(parent_item)

        if not Path(csv_file).exists():
            return

        try:
            with open(csv_file, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)

                # [优化点] 使用 enumerate + break，避免读取整个文件到内存
                # 原代码: rows = list(reader) -> top_results = rows[:5] (内存杀手)
                for i, row in enumerate(reader):
                    if i >= 5:  # 只读前5行
                        break

                    species = row.get('物种', 'N/A')
                    similarity = row.get('相似度', 'N/A')
                    e_value = row.get('E值', 'N/A')

                    # 简化显示文本
                    result_text = f"{i + 1}. {species} | 相似度: {similarity} | E值: {e_value}"
                    result_item = QTreeWidgetItem(parent_item, [result_text, '', ''])

                    # 设置淡灰色背景，增加层次感
                    for c in range(3):
                        result_item.setBackground(c, QColor("#FAFAFA"))
                        result_item.setForeground(c, QColor("#606266"))

        except Exception as e:
            QTreeWidgetItem(parent_item, [f"读取失败: {str(e)}", '', ''])

    def _clear_result_children(self, parent_item):
        for i in range(parent_item.childCount() - 1, -1, -1):
            child = parent_item.child(i)
            if self._is_result_node(child):
                parent_item.takeChild(i)

    def _is_result_node(self, item):
        text = item.text(0)
        # 简单的启发式判断
        return text[0:2].isdigit() and '.' in text[:3] or text.startswith('读取失败')

    def _on_item_clicked(self, item, column):
        """处理点击逻辑"""
        parent = item.parent()

        # 切换展开/折叠 (UX优化: 单击即可切换)
        item.setExpanded(not item.isExpanded())

        if parent is None:  # 文件节点
            self.signals.item_selected.emit(item.text(0))
            if item.isExpanded():
                # 展开时尝试预加载序列节点
                file_name = item.text(0)
                if file_name in self.file_data:
                    path = self.file_data[file_name]['file_path']
                    seqs = self._parse_sequences_from_file(path)
                    for seq_id in seqs:
                        self._ensure_sequence_item_exists(item, file_name, seq_id)

        elif parent.parent() is None:  # 序列节点
            if item.isExpanded():
                self._load_sequence_details(item, parent.text(0), item.text(0))

    def _load_sequence_details(self, item, file_name, sequence_id):
        """加载序列详细结果"""
        if file_name in self.file_data:
            seqs_data = self.file_data[file_name]['sequences']
            if sequence_id in seqs_data:
                result = seqs_data[sequence_id].get('result')
                if result and result.get('csv_file'):
                    self._display_csv_results_async(item, result['csv_file'])

    def _parse_sequences_from_file(self, file_path):
        """解析序列ID"""
        sequences = []
        try:
            path = Path(file_path)
            if path.suffix.lower() in ['.fasta', '.fas', '.fa']:
                with open(path, 'r', encoding='utf-8') as f:
                    for line in f:
                        if line.startswith('>'):
                            seq_id = line[1:].strip().split()[0]
                            sequences.append(seq_id)
            else:
                sequences.append(path.stem)
        except (IOError, OSError, UnicodeDecodeError):
            sequences = ["sequence_1"]  # Fallback
        return sequences

    def _display_csv_results_async(self, parent_item, csv_file):
        """异步加载详情"""
        if parent_item.childCount() > 0:
            parent_item.child(0).setText(0, "正在加载详情...")

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
        if parent_item.childCount() > 0:
            parent_item.child(0).setText(0, text)

    def _on_translation_finished(self, parent_item, translated_rows, file_key):
        # 移除旧节点
        for i in range(parent_item.childCount() - 1, -1, -1):
            parent_item.takeChild(0)

        if not translated_rows:
            QTreeWidgetItem(parent_item, ["无详细结果", '', ''])
            return

        for i, row in enumerate(translated_rows):
            # 构建主要信息
            parts = [row['species']]
            if row['genus'] and row['genus'] != row['species']: parts.append(row['genus'])
            if row['strain']: parts.append(row['strain'])
            if row['host_info']: parts.append(f"[宿主: {row['host_info']}]")

            main_text = f"{i + 1}. {' '.join(filter(None, parts))}"
            item = QTreeWidgetItem(parent_item, [main_text, '', ''])

            # 构建次要信息
            sub_parts = []
            if row['similarity']: sub_parts.append(f"相似度: {row['similarity']}")
            if row['e_value']: sub_parts.append(f"E值: {row['e_value']}")
            if row['gene_type']: sub_parts.append(f"基因: {row['gene_type']}")

            if sub_parts:
                sub_item = QTreeWidgetItem(item, [", ".join(sub_parts), '', ''])
                sub_item.setForeground(0, QColor("#909399"))

    def _on_translation_error(self, parent_item, error, file_key):
        if parent_item.childCount() > 0:
            parent_item.child(0).setText(0, f"加载错误: {error}")
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

    # --- 菜单和导出逻辑保持不变，仅做代码风格清理 ---

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
            self.results_data.clear()
            self.result_tree.clear()
            self.file_data.clear()
            self.file_items.clear()
            self.sequence_items.clear()
            self.translation_states.clear()

    def _show_context_menu(self, pos):
        item = self.result_tree.itemAt(pos)
        if not item: return

        menu = QMenu(self)
        parent = item.parent()

        if parent is None:  # File
            menu.addAction("重试比对", lambda: self.signals.retry_blast.emit(item.text(0)))
            menu.addAction("导出查询信息", lambda: self._export_query_info(item.text(0)))
            menu.addAction("翻译此文件结果", lambda: self._translate_item_node(item))

        elif parent.parent() is None:  # Sequence
            menu.addAction("翻译此序列结果", lambda: self._translate_item_node(item))

        else:  # Result Leaf
            pass  # 不显示任何右键菜单项

        menu.exec(self.result_tree.mapToGlobal(pos))

    def _get_item_key(self, item):
        # 简单的唯一键生成
        return str(id(item))

    def _translate_item_node(self, item):
        # 触发该节点下所有子项的翻译（简化逻辑：只展开触发异步加载即可，异步加载会自动翻译）
        if not item.isExpanded():
            item.setExpanded(True)
        # 实际的翻译逻辑由异步loader处理，这里留空或添加特定逻辑

    def _translate_single_text(self, item, key):
        if not self.biology_translator:
            QMessageBox.warning(self, "提示", "翻译器未就绪")
            return

        text = item.text(0)
        self.original_texts[key] = text
        try:
            trans = self.biology_translator.translate_text(text)
            if trans.startswith(('[AI]', '[本地]')): trans = trans[4:].strip()

            item.setText(0, trans)
            self.translation_states[key] = True
        except Exception as e:
            print(f"翻译错: {e}")

    def _toggle_translation(self, item, key, show_trans):
        if not show_trans and key in self.original_texts:
            item.setText(0, self.original_texts[key])
            self.translation_states[key] = False

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
