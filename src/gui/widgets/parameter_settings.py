"""
参数设置组件模块 - 现代化 UI 重构版
负责参数设置相关的GUI组件
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QCheckBox, QSpinBox, QComboBox, QLineEdit,
    QLabel, QPushButton, QDialog, QTabWidget,
    QFrame, QScrollArea
)
from PyQt6.QtCore import pyqtSignal, Qt

# =============================================================================
#  高级参数设置对话框 (现代化 Tab 布局)
# =============================================================================

class AdvancedSettingsDialog(QDialog):
    """高级参数设置对话框 - 现代化 Tab 风格"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("高级参数配置")
        self.setModal(True)
        self.resize(700, 500) # 稍微加大尺寸以适应 Tab

        # 应用对话框专属样式
        self._apply_styles()
        self._setup_ui()

    def _apply_styles(self):
        self.setStyleSheet("""
            QDialog {
                background-color: #ffffff;
            }
            QTabWidget::pane {
                border: 1px solid #e0e0e0;
                border-radius: 6px;
                background: #fff;
                margin-top: -1px;
            }
            QTabWidget::tab-bar {
                left: 10px;
            }
            QTabBar::tab {
                background: #f5f6f7;
                border: 1px solid #e0e0e0;
                border-bottom-color: #e0e0e0;
                border-top-left-radius: 4px;
                border-top-right-radius: 4px;
                padding: 8px 20px;
                margin-right: 4px;
                color: #606266;
            }
            QTabBar::tab:selected {
                background: #fff;
                border-bottom-color: #fff;
                color: #409eff;
                font-weight: bold;
            }
            QLabel {
                font-size: 13px;
                color: #333;
            }
            QGroupBox {
                border: 1px solid #e0e0e0;
                border-radius: 6px;
                margin-top: 10px;
                padding-top: 15px;
                font-weight: bold;
            }
            QLineEdit, QComboBox {
                border: 1px solid #dcdfe6;
                border-radius: 4px;
                padding: 5px;
                background-color: #fff;
                selection-background-color: #409eff;
            }
            QLineEdit:disabled, QSpinBox:disabled, QComboBox:disabled {
                background-color: #f5f7fa;
                color: #c0c4cc;
            }
            QLineEdit:focus, QSpinBox:focus, QComboBox:focus {
                border-color: #409eff;
            }
            
            /* 底部按钮栏 */
            #ButtonBox {
                background-color: #f9fafc;
                border-top: 1px solid #e0e0e0;
            }
        """)

    def _setup_ui(self):
        """设置界面布局"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 1. 主要内容区域 - 使用 TabWidget
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True) # 更加扁平的风格

        # 初始化各个 Tab 页面的容器
        self._init_controls() # 先初始化控件

        self.tabs.addTab(self._create_search_tab(), "搜索参数")
        self.tabs.addTab(self._create_database_tab(), "数据库与输出")
        self.tabs.addTab(self._create_system_tab(), "系统与混合模式")

        # Tab 内容区域加一点内边距
        content_wrapper = QWidget()
        content_layout = QVBoxLayout(content_wrapper)
        content_layout.setContentsMargins(20, 20, 20, 20)
        content_layout.addWidget(self.tabs)
        layout.addWidget(content_wrapper)

        # 2. 底部按钮区域
        button_container = QWidget()
        button_container.setObjectName("ButtonBox")
        button_layout = QHBoxLayout(button_container)
        button_layout.setContentsMargins(20, 15, 20, 15)

        button_layout.addStretch()

        self.cancel_button = QPushButton("取消")
        self.cancel_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.cancel_button.setStyleSheet("""
            QPushButton { background: #fff; border: 1px solid #dcdfe6; padding: 6px 15px; border-radius: 4px; }
            QPushButton:hover { color: #409eff; border-color: #c6e2ff; background-color: #ecf5ff; }
        """)

        self.ok_button = QPushButton("确定保存")
        self.ok_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.ok_button.setStyleSheet("""
            QPushButton { background: #409eff; border: 1px solid #409eff; color: white; padding: 6px 20px; border-radius: 4px; font-weight: bold; }
            QPushButton:hover { background: #66b1ff; border-color: #66b1ff; }
            QPushButton:pressed { background: #3a8ee6; border-color: #3a8ee6; }
        """)

        button_layout.addWidget(self.cancel_button)
        button_layout.addWidget(self.ok_button)

        layout.addWidget(button_container)

        # 连接信号
        self.ok_button.clicked.connect(self.accept)
        self.cancel_button.clicked.connect(self.reject)

    def _init_controls(self):
        """初始化所有控件对象 (逻辑保持不变，只是分离了创建过程)"""
        # --- 搜索参数 ---
        self.hitlist_size_enabled = QCheckBox()
        self.hitlist_size_spinbox = QSpinBox()
        self.hitlist_size_spinbox.setRange(1, 1000)
        self.hitlist_size_spinbox.setValue(10)

        self.word_size_enabled = QCheckBox()
        self.word_size_spinbox = QSpinBox()
        self.word_size_spinbox.setRange(1, 100)
        self.word_size_spinbox.setValue(28)

        self.evalue_enabled = QCheckBox()
        self.evalue_input = QLineEdit("0.1")

        self.matrix_name_enabled = QCheckBox()
        self.matrix_name_combo = QComboBox()
        self.matrix_name_combo.addItems(["BLOSUM62", "BLOSUM45", "BLOSUM80", "PAM30", "PAM70"])
        self.matrix_name_combo.setCurrentText("BLOSUM62")

        self.filter_enabled = QCheckBox()
        self.filter_input = QLineEdit("none")

        # --- 输出参数 ---
        self.alignments_enabled = QCheckBox()
        self.alignments_spinbox = QSpinBox()
        self.alignments_spinbox.setRange(0, 5000)
        self.alignments_spinbox.setValue(500)

        self.descriptions_enabled = QCheckBox()
        self.descriptions_spinbox = QSpinBox()
        self.descriptions_spinbox.setRange(0, 5000)
        self.descriptions_spinbox.setValue(500)

        # --- 数据库参数 ---
        self.nucleotide_db_enabled = QCheckBox()
        self.nucleotide_db_combo = QComboBox()
        self.nucleotide_db_combo.addItems(["nt", "refseq_rna", "refseq_genomic", "nr", "swissprot"])
        self.nucleotide_db_combo.setCurrentText("nt")

        self.protein_db_enabled = QCheckBox()
        self.protein_db_combo = QComboBox()
        self.protein_db_combo.addItems(["nr", "refseq_protein", "swissprot", "pdb", "env_nr"])
        self.protein_db_combo.setCurrentText("nr")

        # --- 本地/系统参数 ---
        self.local_num_threads_enabled = QCheckBox()
        self.local_num_threads_spinbox = QSpinBox()
        self.local_num_threads_spinbox.setRange(1, 32)
        self.local_num_threads_spinbox.setValue(4)

        self.prefer_local_checkbox = QCheckBox("优先使用本地 BLAST 引擎 (若可用)")
        self.prefer_local_checkbox.setChecked(True)

        self.fallback_to_remote_checkbox = QCheckBox("本地不可用时自动回退到远程 NCBI")
        self.fallback_to_remote_checkbox.setChecked(True)

        self.use_cache_checkbox = QCheckBox("启用结果缓存 (减少重复计算)")
        self.use_cache_checkbox.setChecked(True)

        # 初始化联动逻辑 (默认禁用)
        self._setup_toggles()

    def _setup_toggles(self):
        """设置复选框与控件的联动"""
        pairs = [
            (self.hitlist_size_enabled, self.hitlist_size_spinbox),
            (self.word_size_enabled, self.word_size_spinbox),
            (self.evalue_enabled, self.evalue_input),
            (self.matrix_name_enabled, self.matrix_name_combo),
            (self.filter_enabled, self.filter_input),
            (self.alignments_enabled, self.alignments_spinbox),
            (self.descriptions_enabled, self.descriptions_spinbox),
            (self.nucleotide_db_enabled, self.nucleotide_db_combo),
            (self.protein_db_enabled, self.protein_db_combo),
            (self.local_num_threads_enabled, self.local_num_threads_spinbox)
        ]
        for chk, widget in pairs:
            widget.setEnabled(chk.isChecked()) # 初始化状态
            chk.toggled.connect(widget.setEnabled)

    def _create_param_row(self, label_text, checkbox, widget, tooltip=""):
        """辅助函数：创建统一的参数行布局"""
        row_widget = QWidget()
        row_layout = QHBoxLayout(row_widget)
        row_layout.setContentsMargins(0, 5, 0, 5)

        # 左侧标签 + 复选框
        left_layout = QHBoxLayout()
        checkbox.setToolTip("启用此参数")
        left_layout.addWidget(checkbox)

        lbl = QLabel(label_text)
        if tooltip:
            lbl.setToolTip(tooltip)
        left_layout.addWidget(lbl)
        left_layout.addStretch()

        # 右侧控件
        widget.setMinimumWidth(200)

        row_layout.addLayout(left_layout, 1) # 标签占1份
        row_layout.addWidget(widget, 1)      # 控件占1份

        return row_widget

    def _create_search_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(10)

        layout.addWidget(QLabel("<b>核心搜索参数</b> (影响比对灵敏度与速度)"))

        # 添加分隔线
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        line.setStyleSheet("background-color: #f0f0f0;")
        layout.addWidget(line)

        layout.addWidget(self._create_param_row("结果数量 (Hitlist Size)", self.hitlist_size_enabled, self.hitlist_size_spinbox))
        layout.addWidget(self._create_param_row("期望值 (E-Value)", self.evalue_enabled, self.evalue_input, "统计显著性阈值"))
        layout.addWidget(self._create_param_row("词大小 (Word Size)", self.word_size_enabled, self.word_size_spinbox, "初始匹配的片段长度"))
        layout.addWidget(self._create_param_row("打分矩阵 (Matrix)", self.matrix_name_enabled, self.matrix_name_combo, "用于蛋白质比对的打分矩阵"))
        layout.addWidget(self._create_param_row("低复杂度过滤 (Filter)", self.filter_enabled, self.filter_input, "过滤低复杂度区域，例如 'L' 或 'm'"))

        layout.addStretch()
        return tab

    def _create_database_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(10)

        layout.addWidget(QLabel("<b>数据库选择</b>"))
        layout.addWidget(self._create_param_row("核苷酸数据库 (Blastn)", self.nucleotide_db_enabled, self.nucleotide_db_combo))
        layout.addWidget(self._create_param_row("蛋白质数据库 (Blastp)", self.protein_db_enabled, self.protein_db_combo))

        layout.addSpacing(15)
        layout.addWidget(QLabel("<b>结果输出限制</b>"))
        layout.addWidget(self._create_param_row("比对数量 (Alignments)", self.alignments_enabled, self.alignments_spinbox))
        layout.addWidget(self._create_param_row("描述数量 (Descriptions)", self.descriptions_enabled, self.descriptions_spinbox))

        layout.addStretch()
        return tab

    def _create_system_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(15)

        # 性能部分
        perf_group = QWidget()
        perf_layout = QVBoxLayout(perf_group)
        perf_layout.setContentsMargins(0,0,0,0)
        perf_layout.addWidget(QLabel("<b>本地计算性能</b>"))
        perf_layout.addWidget(self._create_param_row("本地线程数 (Threads)", self.local_num_threads_enabled, self.local_num_threads_spinbox))
        layout.addWidget(perf_group)

        layout.addSpacing(10)

        # 策略部分
        strategy_group = QWidget()
        strategy_layout = QVBoxLayout(strategy_group)
        strategy_layout.setContentsMargins(0,0,0,0)
        strategy_layout.addWidget(QLabel("<b>执行策略</b>"))

        # 复选框样式稍微调整
        chk_style = "QCheckBox { padding: 5px; spacing: 8px; }"
        self.prefer_local_checkbox.setStyleSheet(chk_style)
        self.fallback_to_remote_checkbox.setStyleSheet(chk_style)
        self.use_cache_checkbox.setStyleSheet(chk_style)

        strategy_layout.addWidget(self.prefer_local_checkbox)
        strategy_layout.addWidget(self.fallback_to_remote_checkbox)
        strategy_layout.addWidget(self.use_cache_checkbox)

        layout.addWidget(strategy_group)
        layout.addStretch()
        return tab

    def get_settings(self):
        """获取高级参数设置 (逻辑保持不变)"""
        settings = {
            'hitlist_size': self.hitlist_size_spinbox.value() if self.hitlist_size_enabled.isChecked() else None,
            'word_size': self.word_size_spinbox.value() if self.word_size_enabled.isChecked() else None,
            'evalue': float(self.evalue_input.text()) if self.evalue_enabled.isChecked() and self.evalue_input.text() else None,
            'matrix_name': self.matrix_name_combo.currentText() if self.matrix_name_enabled.isChecked() else None,
            'filter': self.filter_input.text() if self.filter_enabled.isChecked() and self.filter_input.text() else None,
            'alignments': self.alignments_spinbox.value() if self.alignments_enabled.isChecked() else None,
            'descriptions': self.descriptions_spinbox.value() if self.descriptions_enabled.isChecked() else None,
            'local_num_threads': self.local_num_threads_spinbox.value() if self.local_num_threads_enabled.isChecked() else None,
            'nucleotide_database': self.nucleotide_db_combo.currentText() if self.nucleotide_db_enabled.isChecked() else 'nt',
            'protein_database': self.protein_db_combo.currentText() if self.protein_db_enabled.isChecked() else 'nr',
            'prefer_local': self.prefer_local_checkbox.isChecked(),
            'fallback_to_remote': self.fallback_to_remote_checkbox.isChecked(),
            'use_cache': self.use_cache_checkbox.isChecked(),
        }
        return settings

    def set_settings(self, settings):
        """设置高级参数 (逻辑保持不变)"""
        # --- 映射逻辑 ---
        # 辅助函数：设置 checkbox 和 widget 值
        def _set_val(chk, widget, key):
            if key in settings and settings[key] is not None:
                chk.setChecked(True)
                if isinstance(widget, QSpinBox):
                    widget.setValue(int(settings[key]))
                elif isinstance(widget, QLineEdit):
                    widget.setText(str(settings[key]))
                elif isinstance(widget, QComboBox):
                    idx = widget.findText(str(settings[key]))
                    if idx >= 0: widget.setCurrentIndex(idx)
            else:
                chk.setChecked(False)

        _set_val(self.hitlist_size_enabled, self.hitlist_size_spinbox, 'hitlist_size')
        _set_val(self.word_size_enabled, self.word_size_spinbox, 'word_size')
        _set_val(self.evalue_enabled, self.evalue_input, 'evalue')
        _set_val(self.matrix_name_enabled, self.matrix_name_combo, 'matrix_name')
        _set_val(self.filter_enabled, self.filter_input, 'filter')
        _set_val(self.alignments_enabled, self.alignments_spinbox, 'alignments')
        _set_val(self.descriptions_enabled, self.descriptions_spinbox, 'descriptions')
        _set_val(self.local_num_threads_enabled, self.local_num_threads_spinbox, 'local_num_threads')
        _set_val(self.nucleotide_db_enabled, self.nucleotide_db_combo, 'nucleotide_database')
        _set_val(self.protein_db_enabled, self.protein_db_combo, 'protein_database')

        if 'prefer_local' in settings: self.prefer_local_checkbox.setChecked(settings['prefer_local'])
        if 'fallback_to_remote' in settings: self.fallback_to_remote_checkbox.setChecked(settings['fallback_to_remote'])
        if 'use_cache' in settings: self.use_cache_checkbox.setChecked(settings['use_cache'])


# =============================================================================
#  参数设置组件 Widget (侧边栏嵌入版)
# =============================================================================

class ParameterSettingsWidget(QWidget):
    """
    参数设置组件类 - 侧边栏简化版
    不再使用 QGroupBox 边框，而是作为侧边栏卡片的一部分
    """

    settings_changed = pyqtSignal(dict)  # 参数设置改变信号

    def __init__(self):
        super().__init__()
        # 默认高级参数
        self.advanced_settings = {}
        self._init_default_settings()
        self._setup_ui()
        self._connect_signals()

    def _init_default_settings(self):
        self.advanced_settings = {
            'hitlist_size': 20, 'word_size': None, 'evalue': None, 'matrix_name': None,
            'filter': None, 'alignments': None, 'descriptions': None, 'local_num_threads': None,
            'nucleotide_database': 'nt', 'protein_database': 'nr',
            'prefer_local': True, 'fallback_to_remote': True, 'use_cache': True,
            'use_ai_translation': True, 'ai_translation_model': 'deepseek-r1'
        }

    def _setup_ui(self):
        """设置简洁的垂直布局"""
        layout = QVBoxLayout(self)
        
        # [关键修改] 增加内边距
        # 原来是 (5, 5, 5, 5)，现在改为 (15, 20, 15, 20)
        # 顺序是 (左, 上, 右, 下)
        layout.setContentsMargins(15, 20, 15, 20) 
        
        layout.setSpacing(15) # 保持间距
        
        # 标题
        title_label = QLabel("参数配置")
        # [可选] 稍微调大一点标题字号
        title_label.setStyleSheet("font-weight: bold; color: #409eff; font-size: 15px; margin-bottom: 5px;")
        layout.addWidget(title_label)
        
        # 1. 线程数设置行
        thread_container = QWidget()
        thread_layout = QHBoxLayout(thread_container)
        # 这里必须设为 0，否则会产生双重边距
        thread_layout.setContentsMargins(0, 0, 0, 0) 
        
        lbl_thread = QLabel("处理线程数:")
        lbl_thread.setToolTip("并行处理文件的线程数量")
        lbl_thread.setStyleSheet("color: #606266; font-size: 13px;") # 统一字号
        
        self.thread_count_spinbox = QSpinBox()
        self.thread_count_spinbox.setRange(1, 50)
        self.thread_count_spinbox.setValue(2)
        # [关键修改] 稍微加宽输入框，避免数字被按钮遮挡
        self.thread_count_spinbox.setFixedWidth(90) 
        # 这里不需要单独写 StyleSheet 了，因为我们在 MainWindow 里设置了全局样式
        
        thread_layout.addWidget(lbl_thread)
        thread_layout.addStretch()
        thread_layout.addWidget(self.thread_count_spinbox)
        layout.addWidget(thread_container)
        
        # 2. 高级设置按钮
        self.advanced_settings_button = QPushButton("配置高级参数 / 数据库")
        self.advanced_settings_button.setCursor(Qt.CursorShape.PointingHandCursor)
        # 增加 padding 看起来更舒服
        self.advanced_settings_button.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                border: 1px dashed #b0b3b8;
                border-radius: 4px;
                color: #606266;
                padding: 10px;  /* 增加按钮内部空间 */
                text-align: center;
                font-size: 13px;
            }
            QPushButton:hover {
                border-color: #409eff;
                color: #409eff;
                background-color: #f0f9eb;
            }
        """)
        layout.addWidget(self.advanced_settings_button)
        
        # 底部填充
        layout.addStretch()

    def _connect_signals(self):
        self.thread_count_spinbox.valueChanged.connect(self._on_settings_changed)
        self.advanced_settings_button.clicked.connect(self._show_advanced_settings)

    def _show_advanced_settings(self):
        dialog = AdvancedSettingsDialog(self)
        dialog.set_settings(self.advanced_settings)

        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.advanced_settings = dialog.get_settings()
            self._on_settings_changed()

    def _on_settings_changed(self):
        settings = self.get_advanced_settings()
        settings['thread_count'] = self.get_thread_count()
        self.settings_changed.emit(settings)

    def get_thread_count(self):
        return self.thread_count_spinbox.value()

    def set_thread_count(self, count):
        self.thread_count_spinbox.setValue(count)

    def get_advanced_settings(self):
        # 简单的合并逻辑
        default_settings = {
            'hitlist_size': 10, 'word_size': None, 'evalue': 0.1, 'matrix_name': 'BLOSUM62',
            'filter': 'none', 'alignments': 100, 'descriptions': 100, 'local_num_threads': 4,
            'nucleotide_database': 'nt', 'protein_database': 'nr',
            'prefer_local': True, 'fallback_to_remote': True, 'use_cache': True,
            'use_ai_translation': True, 'ai_translation_model': 'deepseek-r1'
        }
        if not self.advanced_settings:
            return default_settings.copy()

        settings = default_settings.copy()
        settings.update(self.advanced_settings)
        return settings

    def set_advanced_settings(self, settings):
        # 过滤并保存
        valid_keys = [
            'hitlist_size', 'word_size', 'evalue', 'matrix_name', 'filter',
            'alignments', 'descriptions', 'local_num_threads', 'nucleotide_database',
            'protein_database', 'prefer_local', 'fallback_to_remote', 'use_cache'
        ]
        self.advanced_settings = {k: v for k, v in settings.items() if k in valid_keys}