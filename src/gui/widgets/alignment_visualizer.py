"""
序列比对可视化组件
使用 Matplotlib 绘制 BLAST 比对结果的覆盖度图
"""

import matplotlib
matplotlib.use('QtAgg')  # 必须在导入 pyplot 之前设置

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.backends.backend_qtagg import NavigationToolbar2QT as NavigationToolbar
from matplotlib.figure import Figure
from matplotlib import patches
import matplotlib.pyplot as plt

from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
                             QComboBox, QWidget, QMessageBox, QProgressBar, QScrollArea)
from PyQt6.QtCore import Qt, QThread, pyqtSignal

from Bio.Blast import NCBIXML
import os

class VisualizationWorker(QThread):
    """后台解析和绘图数据准备线程"""
    finished = pyqtSignal(object) # 发送解析后的数据
    error = pyqtSignal(str)

    def __init__(self, xml_file):
        super().__init__()
        self.xml_file = xml_file

    def run(self):
        try:
            if not os.path.exists(self.xml_file):
                raise FileNotFoundError(f"结果文件不存在: {self.xml_file}")

            data = []
            with open(self.xml_file, 'r') as f:
                blast_records = list(NCBIXML.parse(f))
                
            if not blast_records:
                raise ValueError("未找到有效的 BLAST 记录")

            # 目前只处理第一个查询序列的结果
            record = blast_records[0]
            query_len = record.query_length
            query_name = record.query

            hits = []
            for alignment in record.alignments:
                hit_info = {
                    'title': alignment.title,
                    'length': alignment.length,
                    'hsps': []
                }
                for hsp in alignment.hsps:
                    hit_info['hsps'].append({
                        'query_start': hsp.query_start,
                        'query_end': hsp.query_end,
                        'score': hsp.score,
                        'evalue': hsp.expect,
                        'identity': hsp.identities / hsp.align_length if hsp.align_length > 0 else 0
                    })
                hits.append(hit_info)

            result_data = {
                'query_name': query_name,
                'query_length': query_len,
                'hits': hits
            }
            self.finished.emit(result_data)

        except Exception as e:
            self.error.emit(str(e))

class AlignmentVisualizerDialog(QDialog):
    def __init__(self, xml_file, parent=None):
        super().__init__(parent)
        self.setWindowTitle("序列比对可视化")
        self.resize(1000, 700)
        self.xml_file = xml_file
        
        self._setup_ui()
        self._load_data()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        # 顶部控制栏
        ctrl_layout = QHBoxLayout()
        ctrl_layout.addWidget(QLabel("排序方式:"))
        self.sort_combo = QComboBox()
        self.sort_combo.addItems(["按 E-value", "按 Score", "按起始位置"])
        self.sort_combo.currentIndexChanged.connect(self._update_plot)
        ctrl_layout.addWidget(self.sort_combo)
        ctrl_layout.addStretch()
        layout.addLayout(ctrl_layout)

        # 滚动区域配置
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        
        # 绘图容器 (放入滚动区域)
        self.plot_widget = QWidget()
        self.plot_layout = QVBoxLayout(self.plot_widget)
        
        self.figure = Figure(figsize=(10, 6), dpi=100)
        self.canvas = FigureCanvas(self.figure)
        # 初始最小高度，后续会动态调整
        self.canvas.setMinimumHeight(600) 
        
        self.plot_layout.addWidget(self.canvas)
        self.scroll_area.setWidget(self.plot_widget)
        
        # 工具栏
        self.toolbar = NavigationToolbar(self.canvas, self)
        
        layout.addWidget(self.toolbar)
        layout.addWidget(self.scroll_area)

        # 进度条
        self.progress = QProgressBar()
        self.progress.setRange(0, 0) # 忙碌模式
        self.progress.hide()
        layout.addWidget(self.progress)
        
        # 状态信息
        self.status_label = QLabel("准备就绪")
        layout.addWidget(self.status_label)

    def _load_data(self):
        self.progress.show()
        self.status_label.setText("正在解析 BLAST 结果...")
        
        self.worker = VisualizationWorker(self.xml_file)
        self.worker.finished.connect(self._on_data_loaded)
        self.worker.error.connect(self._on_error)
        self.worker.start()

    def _on_data_loaded(self, data):
        self.progress.hide()
        self.data = data
        self.status_label.setText(f"解析完成: Query长度 {data['query_length']}, 找到 {len(data['hits'])} 个匹配")
        self._update_plot()

    def _on_error(self, msg):
        self.progress.hide()
        self.status_label.setText("加载失败")
        QMessageBox.critical(self, "错误", f"无法加载可视化数据:\n{msg}")

    def _update_plot(self):
        if not hasattr(self, 'data'):
            return

        self.figure.clear()
        ax = self.figure.add_subplot(111)

        # 获取排序方式
        sort_mode = self.sort_combo.currentText()
        hits = self.data['hits'] # 原始数据
        
        # 限制显示数量，避免太拥挤
        max_display = 100 # 增加显示上限，配合滚动条
        
        # 使用 sorted 生成新列表，不修改原数据
        if sort_mode == "按 E-value":
            # E-value 越小越好
            display_hits = sorted(hits, key=lambda x: min([h['evalue'] for h in x['hsps']] + [1.0]))
        elif sort_mode == "按 Score":
            # Score 越大越好
            display_hits = sorted(hits, key=lambda x: max([h['score'] for h in x['hsps']] + [0]), reverse=True)
        elif sort_mode == "按起始位置":
            # 起始位置越小越靠前
            display_hits = sorted(hits, key=lambda x: min([h['query_start'] for h in x['hsps']] + [999999]))
        else:
            display_hits = list(hits)

        display_hits = display_hits[:max_display]

        # 动态调整 Canvas 高度
        # 基础高度 100 + 每个 Hit 30 像素
        required_height = 100 + len(display_hits) * 30
        # 限制最小高度为 500，防止太小
        final_height = max(500, required_height)
        self.canvas.setMinimumHeight(final_height)
        self.plot_widget.setMinimumHeight(final_height) # 确保容器也调整

        # 绘图参数
        query_len = self.data['query_length']
        bar_height = 0.6 # 稍微调细一点
        
        # 绘制 Query 标尺 (最上方)
        # Y轴坐标：len(display_hits) + 1
        query_y = len(display_hits) + 1
        ax.add_patch(patches.Rectangle((1, query_y), query_len, bar_height, 
                                     facecolor='#409eff', alpha=0.3, edgecolor='none'))
        ax.text(query_len/2, query_y + bar_height/2, f"Query: {self.data['query_name']}", 
                ha='center', va='center', fontweight='bold')

        # 绘制 Hits
        yticks = []
        yticklabels = []
        
        for i, hit in enumerate(display_hits):
            # 倒序排列，排名第一的在最上面 (紧挨着 Query)
            y = len(display_hits) - i - 1 
            
            # 简化标题
            title = hit['title']
            if len(title) > 50: title = title[:47] + "..."
            
            yticks.append(y + bar_height/2)
            yticklabels.append(f"{i+1}. {title}")
            
            # 绘制背景条
            ax.hlines(y + bar_height/2, 1, query_len, colors='#eeeeee', linewidth=1)

            # 绘制 HSPs
            for hsp in hit['hsps']:
                start = hsp['query_start']
                width = hsp['query_end'] - start
                
                # 颜色根据 Identity 变化
                identity = hsp['identity']
                if identity >= 0.9: color = '#d62728' # Red (High)
                elif identity >= 0.7: color = '#ff7f0e' # Orange
                elif identity >= 0.5: color = '#2ca02c' # Green
                else: color = '#1f77b4' # Blue (Low)
                
                rect = patches.Rectangle((start, y), width, bar_height, 
                                       facecolor=color, edgecolor='black', linewidth=0.5)
                ax.add_patch(rect)

        # 设置坐标轴
        ax.set_xlim(0, query_len * 1.05)
        ax.set_ylim(-1, len(display_hits) + 2)
        ax.set_xlabel("Sequence Position (bp)")
        ax.set_yticks(yticks)
        ax.set_yticklabels(yticklabels, fontsize=9)
        
        # 将 Y 轴标签放在右侧，避免遮挡左侧内容，或者增加左侧边距
        # 这里我们保持在左侧，但通过 figure.subplots_adjust 调整边距
        self.figure.subplots_adjust(left=0.3, right=0.95, top=0.95, bottom=0.1)
        
        ax.set_title(f"Alignment Overview (Top {len(display_hits)} Hits)")
        ax.grid(True, axis='x', linestyle='--', alpha=0.5)
        
        # 图例
        legend_patches = [
            patches.Patch(color='#d62728', label='Iden >= 90%'),
            patches.Patch(color='#ff7f0e', label='70% <= Iden < 90%'),
            patches.Patch(color='#2ca02c', label='50% <= Iden < 70%'),
            patches.Patch(color='#1f77b4', label='Iden < 50%'),
        ]
        ax.legend(handles=legend_patches, loc='upper right', fontsize='small')

        self.canvas.draw()
