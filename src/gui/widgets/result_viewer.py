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
        print(f"[DEBUG] TranslationWorker 初始化完成，文件: {csv_file}")
    
    def stop(self):
        """停止翻译工作"""
        print("[DEBUG] TranslationWorker 收到停止信号")
        self._is_running = False
    
    def process_csv(self):
        """处理CSV文件并翻译内容"""
        try:
            print(f"[DEBUG] 开始处理CSV文件: {self.csv_file}")
            translated_rows = []
            
            with open(self.csv_file, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                rows = list(reader)
                print(f"[DEBUG] 读取到 {len(rows)} 行数据")
                
                if rows:
                    for i, row in enumerate(rows):
                        if not self._is_running:
                            print("[DEBUG] 翻译工作中断")
                            break
                            
                        # 发送进度更新信号
                        self.progress.emit(f"正在翻译第 {i+1} 条记录...")
                        print(f"[DEBUG] 正在翻译第 {i+1} 条记录")
                        
                        # 获取各个字段
                        species = row.get('物种', '')
                        genus = row.get('属名', '')
                        strain = row.get('菌株', '')
                        gene_type = row.get('基因类型', '')
                        sequence_type = row.get('序列类型', '')
                        similarity = row.get('相似度', '')
                        e_value = row.get('E값', '')
                        print(f"[DEBUG] 第{i+1}行数据 - 物种: {species}, 属名: {genus}")
                        
                        # 使用生物学翻译器翻译物种和属名
                        if species and self.biology_translator:
                            try:
                                print(f"[DEBUG] 开始翻译物种: {species}")
                                translated_species = self.biology_translator.translate_text(species)
                                print(f"[DEBUG] 物种翻译结果: {translated_species}")
                                # 处理翻译结果，去除标识符如[AI]或[本地]
                                if translated_species:
                                    if translated_species.startswith(('[AI]', '[本地]')):
                                        species = translated_species[4:].strip()
                                    else:
                                        species = translated_species
                            except Exception as e:
                                print(f"翻译物种时出错: {e}")
                                import traceback
                                traceback.print_exc()
                        
                        if genus and self.biology_translator:
                            try:
                                print(f"[DEBUG] 开始翻译属名: {genus}")
                                translated_genus = self.biology_translator.translate_text(genus)
                                print(f"[DEBUG] 属名翻译结果: {translated_genus}")
                                # 处理翻译结果，去除标识符如[AI]或[本地]
                                if translated_genus and translated_genus != genus:
                                    if translated_genus.startswith(('[AI]', '[本地]')):
                                        genus = translated_genus[4:].strip()
                                    else:
                                        genus = translated_genus
                            except Exception as e:
                                print(f"翻译属名时出错: {e}")
                                import traceback
                                traceback.print_exc()
                        
                        # 使用生物学翻译器翻译基因类型和序列类型
                        if gene_type and self.biology_translator:
                            try:
                                print(f"[DEBUG] 开始翻译基因类型: {gene_type}")
                                translated_gene = self.biology_translator.translate_text(gene_type)
                                print(f"[DEBUG] 基因类型翻译结果: {translated_gene}")
                                # 处理翻译结果，去除标识符如[AI]或[本地]
                                if translated_gene and translated_gene != gene_type:
                                    if translated_gene.startswith(('[AI]', '[本地]')):
                                        gene_type = translated_gene[4:].strip()
                                    else:
                                        gene_type = translated_gene
                            except Exception as e:
                                print(f"翻译基因类型时出错: {e}")
                                import traceback
                                traceback.print_exc()
                        
                        if sequence_type and self.biology_translator:
                            try:
                                print(f"[DEBUG] 开始翻译序列类型: {sequence_type}")
                                translated_sequence = self.biology_translator.translate_text(sequence_type)
                                print(f"[DEBUG] 序列类型翻译结果: {translated_sequence}")
                                # 处理翻译结果，去除标识符如[AI]或[本地]
                                if translated_sequence and translated_sequence != sequence_type:
                                    if translated_sequence.startswith(('[AI]', '[本地]')):
                                        sequence_type = translated_sequence[4:].strip()
                                    else:
                                        sequence_type = translated_sequence
                            except Exception as e:
                                print(f"翻译序列类型时出错: {e}")
                                import traceback
                                traceback.print_exc()
                        
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
                
                print(f"[DEBUG] 翻译完成，共处理 {len(translated_rows)} 行数据")
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
        # 为每个文件维护独立的翻译线程和工作对象
        self.translation_threads = {}  # 存储每个文件的翻译线程
        self.translation_workers = {}  # 存储每个文件的翻译工作对象
    
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
    
    def closeEvent(self, event):
        """处理窗口关闭事件"""
        print("[DEBUG] closeEvent 开始执行")
        # 停止所有正在运行的翻译线程
        for file_key, thread in self.translation_threads.items():
            if thread.isRunning():
                print(f"[DEBUG] 停止线程: {file_key}")
                if file_key in self.translation_workers:
                    self.translation_workers[file_key].stop()
                thread.quit()
                thread.wait()
        
        # 清空线程字典
        self.translation_threads.clear()
        self.translation_workers.clear()
        
        print("[DEBUG] closeEvent 执行完成")
        event.accept()
    
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
        print(f"[DEBUG] set_translation_settings 开始执行")
        print(f"[DEBUG] 翻译设置: {translation_settings}")
        print(f"[DEBUG] API密钥: {'已提供' if api_key else '未提供'}")
        self.translation_settings = translation_settings or {}
        self.api_key = api_key
        
        # 只有在需要使用AI翻译时才初始化生物学翻译器
        if self.translation_settings.get('use_ai', True):
            print("[DEBUG] 需要使用AI翻译，初始化生物学翻译器")
            try:
                from src.utils.translation import get_biology_translator
                # 确保使用项目根目录下的translation_data.csv文件
                from pathlib import Path
                project_root = Path(__file__).parent.parent.parent.parent
                csv_file = str(project_root / "translation_data.csv")
                print(f"[DEBUG] 使用翻译数据文件: {csv_file}")
                
                # 获取AI模型参数
                ai_model = self.translation_settings.get('ai_model', 'deepseek-r1')
                print(f"[DEBUG] 使用AI模型: {ai_model}")
                
                # 初始化生物学翻译器，传递AI模型参数
                self.biology_translator = get_biology_translator(
                    data_file=csv_file, 
                    use_ai=True, 
                    ai_api_key=api_key,
                    ai_model=ai_model  # 传递AI模型参数
                )
                print("[DEBUG] 生物学翻译器初始化完成")
            except Exception as e:
                print(f"初始化生物学翻译器失败: {e}")
                import traceback
                traceback.print_exc()
                self.biology_translator = None
        else:
            print("[DEBUG] 不使用AI翻译")
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
        print(f"[DEBUG] _on_item_clicked 开始执行，项目: {item.text(0)}, 列: {column}")
        # 如果点击的是父节点（文件节点）
        if item.parent() is None:
            file_name = item.text(0)
            print(f"[DEBUG] 点击的是文件节点: {file_name}")
            self.item_selected.emit(file_name)
            
            # 切换展开/折叠状态
            is_expanded = not item.isExpanded()
            print(f"[DEBUG] 切换展开状态为: {is_expanded}")
            item.setExpanded(is_expanded)
            
            # 如果是展开状态且还没有加载详细信息，则加载详细信息
            if is_expanded and item.childCount() > 0:
                try:
                    child = item.child(0)
                    # 检查是否已加载详细信息（通过检查子节点的列数）
                    # 同时检查子节点的文本是否为空或正在翻译的提示
                    if (child.columnCount() == 3 and 
                        (child.text(0) == '' or child.text(0).startswith('正在加载') or child.text(0).startswith('正在翻译'))):
                        # 显示正在加载的提示
                        print("[DEBUG] 需要加载详细信息")
                        child.setText(0, "正在加载详细信息...")
                        # 处理事件队列，确保UI更新
                        QApplication.processEvents()
                        # 加载并显示详细信息
                        self._load_detail_info(item, file_name)
                    else:
                        print("[DEBUG] 详细信息已加载或不需要加载")
                except Exception as e:
                    print(f"[ERROR] 处理项目点击事件时出现异常: {e}")
                    # 出现异常时，显示错误信息而不是闪退
                    if item.childCount() > 0:
                        child = item.child(0)
                        child.setText(0, f"加载结果失败: {str(e)}")
        else:
            print("[DEBUG] 点击的是子节点，不执行特殊处理")
    
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
        print(f"[DEBUG] _load_detail_info 开始执行，文件名: {file_name}")
        # 显示正在加载的提示
        if parent_item.childCount() > 0:
            child = parent_item.child(0)
            child.setText(0, "正在加载详细信息...")
            # 处理事件队列，确保UI更新
            try:
                QApplication.processEvents()
            except:
                pass  # 如果QApplication不可用，忽略这个调用
        
        # 查找对应的结果数据
        result_data = None
        for data in self.results_data.values():
            if Path(data.get("file", "")).name == file_name:
                result_data = data
                break
        
        if result_data:
            print(f"[DEBUG] 找到结果数据，状态: {result_data.get('status')}")
            if result_data.get("status") == "success":
                # 读取CSV结果文件
                csv_file = result_data.get("csv_file") or result_data.get("result_file").replace(".xml", ".csv")
                print(f"[DEBUG] 准备加载CSV文件: {csv_file}")
                try:
                    self._display_csv_results_async(parent_item, csv_file)
                except Exception as e:
                    print(f"[ERROR] 加载CSV结果时出现异常: {e}")
                    # 清空子节点并显示错误信息
                    if parent_item.childCount() > 0:
                        child = parent_item.child(0)
                        child.setText(0, f"加载结果失败: {str(e)}")
                    # 触发翻译完成的错误处理
                    self._on_translation_error(parent_item, str(e))
            elif result_data.get("status") == "error":
                # 显示错误信息
                if parent_item.childCount() > 0:
                    child = parent_item.child(0)
                    child.setText(0, f"处理失败: {result_data.get('error', '未知错误')}")
                print(f"[DEBUG] 处理失败，错误信息: {result_data.get('error', '未知错误')}")
            else:
                print(f"[DEBUG] 未知状态: {result_data.get('status')}")
        else:
            print(f"[DEBUG] 未找到结果数据")
    
    def _display_csv_results_async(self, parent_item, csv_file):
        """异步显示CSV结果"""
        print(f"[DEBUG] _display_csv_results_async 开始执行，文件: {csv_file}")
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
        print(f"[DEBUG] 使用文件键: {file_key} 管理线程")
        
        # 如果该文件已有线程在运行，先清理旧的线程
        if file_key in self.translation_threads and self.translation_threads[file_key].isRunning():
            print(f"[DEBUG] 停止已存在的线程: {file_key}")
            if file_key in self.translation_workers:
                self.translation_workers[file_key].stop()
            self.translation_threads[file_key].quit()
            self.translation_threads[file_key].wait()
        
        # 创建新的线程和工作对象
        print("[DEBUG] 创建新的翻译线程和工作对象")
        translation_thread = QThread()
        translation_worker = TranslationWorker(csv_file, self.biology_translator)
        
        # 保存线程和工作对象的引用
        self.translation_threads[file_key] = translation_thread
        self.translation_workers[file_key] = translation_worker
        
        # 将工作对象移动到线程中
        print("[DEBUG] 将工作对象移动到线程中")
        translation_worker.moveToThread(translation_thread)
        
        # 连接信号和槽
        print("[DEBUG] 连接信号和槽")
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
        print("[DEBUG] 启动翻译线程")
        translation_thread.start()
        print("[DEBUG] 翻译线程启动完成")
    
    def _on_translation_progress(self, parent_item, message):
        """处理翻译进度更新"""
        if parent_item.childCount() > 0:
            child = parent_item.child(0)
            child.setText(0, message)
            try:
                QApplication.processEvents()
            except:
                pass  # 如果QApplication不可用，忽略这个调用
    
    def _cleanup_thread_reference(self, file_key):
        """清理线程引用"""
        print(f"[DEBUG] 清理线程引用: {file_key}")
        if file_key in self.translation_threads:
            del self.translation_threads[file_key]
        if file_key in self.translation_workers:
            del self.translation_workers[file_key]
    
    def _on_translation_finished(self, parent_item, translated_rows, file_key):
        """处理翻译完成"""
        print(f"[DEBUG] _on_translation_finished 开始执行，接收到 {len(translated_rows)} 行翻译数据，文件: {file_key}")
        # 清空现有子节点
        if parent_item.childCount() > 0:
            for i in range(parent_item.childCount()):
                parent_item.removeChild(parent_item.child(0))
        
        # 显示翻译结果
        if translated_rows:
            print(f"[DEBUG] 开始显示 {len(translated_rows)} 行翻译结果")
            for i, row_data in enumerate(translated_rows):
                species = row_data['species']
                genus = row_data['genus']
                strain = row_data['strain']
                gene_type = row_data['gene_type']
                sequence_type = row_data['sequence_type']
                similarity = row_data['similarity']
                e_value = row_data['e_value']
                print(f"[DEBUG] 处理第{i+1}行数据: 物种={species}, 属名={genus}")
                
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
                print(f"[DEBUG] 第{i+1}行主要信息: {main_info}")
                item = QTreeWidgetItem(parent_item, [f"{i+1}. {main_info}", '', ''])
                
                # 详细信息行
                detail_parts = []
                if similarity:
                    detail_parts.append(f"相似度: {similarity}")
                if e_value:
                    detail_parts.append(f"E값: {e_value}")
                
                if detail_parts:
                    detail_text = ", ".join(detail_parts)
                    print(f"[DEBUG] 第{i+1}行详细信息: {detail_text}")
                    QTreeWidgetItem(item, [detail_text, '', ''])
            print("[DEBUG] 所有翻译结果显示完成")
        else:
            print("[DEBUG] 没有翻译结果，显示提示信息")
            QTreeWidgetItem(parent_item, ["没有找到匹配结果", '', ''])

        # 翻译完成后，确保界面更新
        print("[DEBUG] 处理翻译完成后的界面更新")
        try:
            QApplication.processEvents()
        except:
            pass  # 如果QApplication不可用，忽略这个调用
        print("[DEBUG] _on_translation_finished 执行完成")
    
    def _on_translation_error(self, parent_item, error, file_key=None):
        """处理翻译错误"""
        print(f"[DEBUG] _on_translation_error 开始执行，错误: {error}，文件: {file_key}")
        if parent_item.childCount() > 0:
            child = parent_item.child(0)
            child.setText(0, f"翻译失败: {error}")
        # 清理线程引用
        if file_key:
            self._cleanup_thread_reference(file_key)
    
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