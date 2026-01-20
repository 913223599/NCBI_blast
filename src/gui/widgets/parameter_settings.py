"""
参数设置组件模块 - 现代化 UI 重构版
负责参数设置相关的GUI组件
"""

from PyQt6.QtCore import pyqtSignal, Qt
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QCheckBox, QSpinBox, QComboBox, QLineEdit,
    QLabel, QPushButton, QDialog, QTabWidget
)

from src.utils.config_manager import get_config_manager  # [关键修复] 导入配置管理器


# =============================================================================
#  高级参数设置对话框 (现代化 Tab 布局)
# =============================================================================

class AdvancedSettingsDialog(QDialog):
    """高级参数设置对话框 - 现代化 Tab 风格 (含 AI 设置)"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("高级参数配置")
        self.setModal(True)
        self.resize(700, 500)

        self._apply_styles()
        self._setup_ui()

    def _apply_styles(self):
        self.setStyleSheet("""
            QDialog { background-color: #ffffff; }
            QTabWidget::pane { border: 1px solid #e0e0e0; border-radius: 6px; background: #fff; margin-top: -1px; }
            QTabWidget::tab-bar { left: 10px; }
            QTabBar::tab { background: #f5f6f7; border: 1px solid #e0e0e0; border-bottom-color: #e0e0e0; 
                          border-top-left-radius: 4px; border-top-right-radius: 4px; padding: 8px 20px; margin-right: 4px; color: #606266; }
            QTabBar::tab:selected { background: #fff; border-bottom-color: #fff; color: #409eff; font-weight: bold; }
            QLabel { font-size: 13px; color: #333; }
            QLineEdit, QComboBox { border: 1px solid #dcdfe6; border-radius: 4px; padding: 5px; background-color: #fff; }
            QLineEdit:disabled, QComboBox:disabled { background-color: #f5f7fa; color: #c0c4cc; }
        """)

    def _setup_ui(self):
        """设置界面布局"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # 1. Tab Widget
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)

        self._init_controls()

        self.tabs.addTab(self._create_search_tab(), "搜索参数")
        self.tabs.addTab(self._create_database_tab(), "数据库与输出")
        self.tabs.addTab(self._create_system_tab(), "系统与混合模式")

        content_wrapper = QWidget()
        content_layout = QVBoxLayout(content_wrapper)
        content_layout.setContentsMargins(20, 20, 20, 20)
        content_layout.addWidget(self.tabs)
        layout.addWidget(content_wrapper)

        # 2. Buttons
        button_container = QWidget()
        button_layout = QHBoxLayout(button_container)
        button_layout.setContentsMargins(20, 15, 20, 15)
        button_layout.addStretch()

        self.cancel_button = QPushButton("取消")
        self.ok_button = QPushButton("确定保存")
        self.ok_button.setStyleSheet("background-color: #409eff; color: white; padding: 6px 20px; border-radius: 4px;")

        self.cancel_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.ok_button.setCursor(Qt.CursorShape.PointingHandCursor)

        button_layout.addWidget(self.cancel_button)
        button_layout.addWidget(self.ok_button)
        layout.addWidget(button_container)

        self.ok_button.clicked.connect(self.accept)
        self.cancel_button.clicked.connect(self.reject)

    def _init_controls(self):
        """初始化所有控件"""
        # --- 搜索参数 ---
        self.hitlist_size_enabled = QCheckBox()
        self.hitlist_size_spinbox = QSpinBox()
        self.hitlist_size_spinbox.setRange(1, 1000)

        self.word_size_enabled = QCheckBox()
        self.word_size_spinbox = QSpinBox()
        self.word_size_spinbox.setRange(1, 100)

        self.evalue_enabled = QCheckBox()
        self.evalue_input = QLineEdit("0.1")

        self.matrix_name_enabled = QCheckBox()
        self.matrix_name_combo = QComboBox()
        self.matrix_name_combo.addItems(["BLOSUM62", "BLOSUM45", "BLOSUM80", "PAM30", "PAM70"])

        self.filter_enabled = QCheckBox()
        self.filter_input = QLineEdit("none")
        
        # [新增] BLAST 程序选择
        self.program_enabled = QCheckBox()
        self.program_combo = QComboBox()
        self.program_combo.addItems(["blastn", "blastp", "blastx", "tblastn", "tblastx"])

        # --- 输出参数 ---
        self.alignments_enabled = QCheckBox()
        self.alignments_spinbox = QSpinBox()
        self.alignments_spinbox.setRange(0, 5000)

        self.descriptions_enabled = QCheckBox()
        self.descriptions_spinbox = QSpinBox()
        self.descriptions_spinbox.setRange(0, 5000)

        # --- 数据库参数 ---
        self.nucleotide_db_enabled = QCheckBox()
        self.nucleotide_db_combo = QComboBox()
        self.nucleotide_db_combo.addItems(["nt", "refseq_rna", "refseq_genomic", "nr", "swissprot"])

        self.protein_db_enabled = QCheckBox()
        self.protein_db_combo = QComboBox()
        self.protein_db_combo.addItems(["nr", "refseq_protein", "swissprot", "pdb", "env_nr"])

        # --- AI 参数 ---
        # 已移除，现在在主界面直接配置

        # --- 系统参数 ---
        self.local_num_threads_enabled = QCheckBox()
        self.local_num_threads_spinbox = QSpinBox()
        self.local_num_threads_spinbox.setRange(1, 32)

        self.prefer_local_checkbox = QCheckBox("优先使用本地 BLAST 引擎")
        self.fallback_to_remote_checkbox = QCheckBox("本地不可用时回退到远程")
        self.use_cache_checkbox = QCheckBox("启用结果缓存")

        # [新增] 请求超时设置
        self.request_timeout_enabled = QCheckBox()
        self.request_timeout_spinbox = QSpinBox()
        self.request_timeout_spinbox.setRange(1, 9) # 最大值上限设置为9分钟
        self.request_timeout_spinbox.setValue(6) # 默认6分钟

        self._setup_toggles()

    def _setup_toggles(self):
        # 保持原有的联动逻辑
        pairs = [
            (self.hitlist_size_enabled, self.hitlist_size_spinbox),
            (self.word_size_enabled, self.word_size_spinbox),
            (self.evalue_enabled, self.evalue_input),
            (self.matrix_name_enabled, self.matrix_name_combo),
            (self.filter_enabled, self.filter_input),
            (self.program_enabled, self.program_combo), # [新增]
            (self.alignments_enabled, self.alignments_spinbox),
            (self.descriptions_enabled, self.descriptions_spinbox),
            (self.nucleotide_db_enabled, self.nucleotide_db_combo),
            (self.protein_db_enabled, self.protein_db_combo),
            (self.local_num_threads_enabled, self.local_num_threads_spinbox),
            (self.request_timeout_enabled, self.request_timeout_spinbox) # [新增]
        ]
        for chk, widget in pairs:
            widget.setEnabled(chk.isChecked())
            chk.toggled.connect(widget.setEnabled)

    def _create_param_row(self, label, checkbox, widget, tooltip=""):
        # 辅助函数
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 5, 0, 5)

        left_layout = QHBoxLayout()
        left_layout.addWidget(checkbox)
        lbl = QLabel(label)
        if tooltip: lbl.setToolTip(tooltip)
        left_layout.addWidget(lbl)
        left_layout.addStretch()

        widget.setMinimumWidth(200)
        layout.addLayout(left_layout, 1)
        layout.addWidget(widget, 1)
        return row

    def _create_search_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.addWidget(self._create_param_row("BLAST 程序 (Program)", self.program_enabled, self.program_combo, "强制指定 BLAST 程序 (如 blastn, blastp)"))
        layout.addWidget(self._create_param_row("结果数量 (Hitlist Size)", self.hitlist_size_enabled, self.hitlist_size_spinbox))
        layout.addWidget(self._create_param_row("期望值 (E-Value)", self.evalue_enabled, self.evalue_input))
        layout.addWidget(self._create_param_row("词大小 (Word Size)", self.word_size_enabled, self.word_size_spinbox))
        layout.addWidget(self._create_param_row("打分矩阵 (Matrix)", self.matrix_name_enabled, self.matrix_name_combo))
        layout.addWidget(self._create_param_row("低复杂度过滤 (Filter)", self.filter_enabled, self.filter_input))
        layout.addStretch()
        return tab

    def _create_database_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.addWidget(QLabel("<b>数据库选择</b>"))
        layout.addWidget(self._create_param_row("核苷酸数据库", self.nucleotide_db_enabled, self.nucleotide_db_combo))
        layout.addWidget(self._create_param_row("蛋白质数据库", self.protein_db_enabled, self.protein_db_combo))
        layout.addSpacing(10)
        layout.addWidget(QLabel("<b>输出限制</b>"))
        layout.addWidget(self._create_param_row("比对数量", self.alignments_enabled, self.alignments_spinbox))
        layout.addWidget(self._create_param_row("描述数量", self.descriptions_enabled, self.descriptions_spinbox))
        layout.addStretch()
        return tab



    def _create_system_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.addWidget(QLabel("<b>本地计算性能</b>"))
        layout.addWidget(self._create_param_row("本地线程数", self.local_num_threads_enabled, self.local_num_threads_spinbox))
        layout.addSpacing(10)
        layout.addWidget(QLabel("<b>执行策略</b>"))
        layout.addWidget(self.prefer_local_checkbox)
        layout.addWidget(self.fallback_to_remote_checkbox)
        layout.addWidget(self.use_cache_checkbox)
        layout.addSpacing(10)
        layout.addWidget(QLabel("<b>网络请求</b>"))
        layout.addWidget(self._create_param_row("请求超时 (分钟)", self.request_timeout_enabled, self.request_timeout_spinbox, "BLAST请求的最大等待时间"))
        layout.addStretch()
        return tab

    def get_settings(self):
        """获取所有设置 (包含 AI 设置)"""
        settings = {
            'program': self.program_combo.currentText() if self.program_enabled.isChecked() else None, # [新增]
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
            'request_timeout': self.request_timeout_spinbox.value() if self.request_timeout_enabled.isChecked() else 4, # [新增]

            # AI 参数 - 从主界面获取
            'use_ai_translation': self.use_ai_checkbox.isChecked() if hasattr(self, 'use_ai_checkbox') else False,
            'ai_translation_model': self.ai_model_combo.currentText() if hasattr(self, 'ai_model_combo') else "qwen-mt-plus"
        }
        return settings

    def set_settings(self, settings):
        """设置界面值 (包含 AI 设置)"""

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

        _set_val(self.program_enabled, self.program_combo, 'program') # [新增]
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
        
        # [新增] 设置请求超时
        if 'request_timeout' in settings and settings['request_timeout'] is not None:
            self.request_timeout_enabled.setChecked(True)
            self.request_timeout_spinbox.setValue(int(settings['request_timeout']))
        else:
            self.request_timeout_enabled.setChecked(True) # 默认启用
            self.request_timeout_spinbox.setValue(4)

        if 'prefer_local' in settings: self.prefer_local_checkbox.setChecked(settings['prefer_local'])
        if 'fallback_to_remote' in settings: self.fallback_to_remote_checkbox.setChecked(settings['fallback_to_remote'])
        if 'use_cache' in settings: self.use_cache_checkbox.setChecked(settings['use_cache'])

        # 设置 AI 参数
        # AI翻译设置已移至主界面，此处不再处理

# =============================================================================
#  参数设置组件 Widget (侧边栏嵌入版)
# =============================================================================

class ParameterSettingsWidget(QWidget):
    """
    参数设置组件类 - 侧边栏简化版
    """

    settings_changed = pyqtSignal(dict)  # 参数设置改变信号

    def __init__(self):
        super().__init__()
        # [关键修复 1] 初始化时获取 ConfigManager
        self.config_manager = get_config_manager()

        # [关键修复 2] 直接从 ConfigManager 加载当前配置，而不是使用硬编码默认值
        # 这样程序启动时就能记住上次保存的 AI 设置等
        self.advanced_settings = self.config_manager.get_advanced_settings()

        self._setup_ui()
        self._connect_signals()
        
        # [新增] 根据配置初始化控件状态
        self._load_settings_from_config()

    def _load_settings_from_config(self):
        """从配置加载设置到界面"""
        # 设置AI翻译复选框状态
        use_ai = self.advanced_settings.get('use_ai_translation', True)
        self.use_ai_checkbox.setChecked(use_ai)
        
        # 设置AI模型下拉框
        ai_model = self.advanced_settings.get('ai_translation_model', 'qwen-mt-plus')
        # 如果模型不在下拉框中，添加它
        model_index = self.ai_model_combo.findText(ai_model)
        if model_index == -1:
            self.ai_model_combo.addItem(ai_model)
            model_index = self.ai_model_combo.findText(ai_model)
        self.ai_model_combo.setCurrentIndex(model_index)

        # [新增] 设置线程数
        thread_count = self.advanced_settings.get('thread_count', 3)
        self.thread_count_spinbox.setValue(int(thread_count))

    def _setup_ui(self):
        """设置简洁的垂直布局"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 20, 15, 20)
        layout.setSpacing(15)

        # 标题
        title_label = QLabel("参数配置")
        title_label.setStyleSheet("font-weight: bold; color: #409eff; font-size: 15px; margin-bottom: 5px;")
        layout.addWidget(title_label)

        # 1. 线程数设置行
        thread_container = QWidget()
        thread_layout = QHBoxLayout(thread_container)
        thread_layout.setContentsMargins(0, 0, 0, 0)

        lbl_thread = QLabel("处理线程数:")
        lbl_thread.setToolTip("并行处理文件的线程数量")
        lbl_thread.setStyleSheet("color: #606266; font-size: 13px;")

        self.thread_count_spinbox = QSpinBox()
        self.thread_count_spinbox.setRange(1, 50)
        # self.thread_count_spinbox.setValue(2) # [已移除] 移除硬编码默认值
        self.thread_count_spinbox.setFixedWidth(90)

        thread_layout.addWidget(lbl_thread)
        thread_layout.addStretch()
        thread_layout.addWidget(self.thread_count_spinbox)
        layout.addWidget(thread_container)

        # 2. AI翻译开关
        ai_container = QWidget()
        ai_layout = QHBoxLayout(ai_container)
        ai_layout.setContentsMargins(0, 0, 0, 0)

        self.use_ai_checkbox = QCheckBox("启用 AI 辅助翻译与解释")
        ai_layout.addWidget(self.use_ai_checkbox)
        ai_layout.addStretch()
        layout.addWidget(ai_container)

        # 3. AI模型选择下拉框
        ai_model_container = QWidget()
        ai_model_layout = QHBoxLayout(ai_model_container)
        ai_model_layout.setContentsMargins(0, 0, 0, 0)

        lbl_ai_model = QLabel("AI翻译模型:")
        lbl_ai_model.setToolTip("选择用于辅助翻译的AI模型")
        lbl_ai_model.setStyleSheet("color: #606266; font-size: 13px;")

        self.ai_model_combo = QComboBox()
        # 从配置文件获取支持的模型列表
        from src.utils.config_manager import get_config_manager
        config_manager = get_config_manager()
        supported_model_keys = config_manager.get_supported_model_keys()
        if not supported_model_keys:
            # 如果配置文件中没有定义，使用默认值
            from src.utils.translation.qwen_translator import QwenTranslator
            supported_model_keys = QwenTranslator().get_supported_models(return_keys_only=True)
        
        self.ai_model_combo.addItems(supported_model_keys)
        # 设置默认值为配置文件中的模型
        self.ai_model_combo.setFixedWidth(180)

        ai_model_layout.addWidget(lbl_ai_model)
        ai_model_layout.addStretch()
        ai_model_layout.addWidget(self.ai_model_combo)
        layout.addWidget(ai_model_container)

        # 4. 高级设置按钮
        self.advanced_settings_button = QPushButton("配置高级参数 / 数据库")
        self.advanced_settings_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.advanced_settings_button.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                border: 1px dashed #b0b3b8;
                border-radius: 4px;
                color: #606266;
                padding: 10px;
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

        layout.addStretch()

    def _connect_signals(self):
        self.thread_count_spinbox.valueChanged.connect(self._on_settings_changed)
        self.use_ai_checkbox.stateChanged.connect(self._on_settings_changed)
        self.ai_model_combo.currentTextChanged.connect(self._on_settings_changed)
        self.advanced_settings_button.clicked.connect(self._show_advanced_settings)

    def _show_advanced_settings(self):
        """显示高级设置对话框 (侧边栏按钮触发)"""
        dialog = AdvancedSettingsDialog(self)
        # 将当前的配置传给对话框显示
        dialog.set_settings(self.advanced_settings)

        if dialog.exec() == QDialog.DialogCode.Accepted:
            # 1. 获取新配置
            new_settings = dialog.get_settings()

            # 2. 更新内存变量
            self.advanced_settings = new_settings

            # 3. [关键修复 3] 立即保存到 config.json
            # 之前的代码这里缺失了保存步骤，导致只更新了内存
            try:
                if self.config_manager:
                    self.config_manager.set_advanced_settings(self.advanced_settings)
                    print(f"高级设置已保存到配置文件: {self.advanced_settings.get('ai_translation_model')}")
            except Exception as e:
                print(f"错误：无法保存配置: {e}")

            # 4. 通知其他组件
            self._on_settings_changed()

    def _on_settings_changed(self):
        # 获取当前设置
        settings = self.get_advanced_settings()
        
        # 更新线程数
        thread_count = self.get_thread_count()
        settings['thread_count'] = thread_count
        self.advanced_settings['thread_count'] = thread_count
        
        # 更新AI翻译设置
        use_ai = self.use_ai_checkbox.isChecked()
        settings['use_ai_translation'] = use_ai
        # 直接使用下拉框中的模型名，现在只显示模型键名
        ai_model = self.ai_model_combo.currentText()
        settings['ai_translation_model'] = ai_model
        
        # 立即更新配置文件中的AI翻译设置
        self.advanced_settings['use_ai_translation'] = use_ai
        self.advanced_settings['ai_translation_model'] = ai_model
        try:
            self.config_manager.set_advanced_settings(self.advanced_settings)
            print(f"配置已更新 - 线程: {thread_count}, AI启用: {use_ai}, 模型: {ai_model}")
        except Exception as e:
            print(f"错误：无法保存配置: {e}")
        
        # 发出信号
        self.settings_changed.emit(settings)

    def get_thread_count(self):
        return self.thread_count_spinbox.value()

    def set_thread_count(self, count):
        self.thread_count_spinbox.setValue(count)

    def get_advanced_settings(self):
        return self.advanced_settings.copy()

    def set_advanced_settings(self, settings):
        """外部调用更新设置 (如主窗口)"""
        valid_keys = [
            'program', # [新增]
            'hitlist_size', 'word_size', 'evalue', 'matrix_name', 'filter',
            'alignments', 'descriptions', 'local_num_threads', 'nucleotide_database',
            'protein_database', 'prefer_local', 'fallback_to_remote', 'use_cache',
            'use_ai_translation', 'ai_translation_model', 'thread_count', 'request_timeout'
        ]

        # 更新内存
        updated_subset = {k: v for k, v in settings.items() if k in valid_keys}
        self.advanced_settings.update(updated_subset)

        # 这里的保存逻辑是双保险，如果外部已经调用了 ConfigManager 保存，这里再保存一次也无妨
        if self.config_manager:
            try:
                self.config_manager.set_advanced_settings(self.advanced_settings)
            except Exception as e:
                print(f"警告: 保存高级设置到配置文件失败: {e}")
