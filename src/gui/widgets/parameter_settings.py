"""
参数设置组件模块
负责参数设置相关的GUI组件
"""

from PyQt6.QtWidgets import (QGroupBox, QHBoxLayout, QLabel, QSpinBox, QVBoxLayout, 
                             QCheckBox, QLineEdit, QPushButton, QWidget, QFormLayout, QComboBox, QGridLayout)


class ParameterSettingsWidget(QGroupBox):
    """参数设置组件类"""
    
    def __init__(self):
        super().__init__("参数设置")
        self.advanced_settings_visible = False
        self._setup_ui()
    
    def _setup_ui(self):
        """设置界面"""
        main_layout = QVBoxLayout()
        
        # 基本设置
        basic_layout = QHBoxLayout()
        basic_layout.addWidget(QLabel("线程数:"))
        
        # 创建线程数设置控件
        self.thread_count_spinbox = QSpinBox()
        self.thread_count_spinbox.setRange(1, 10)  # 设置线程数范围为1-10
        self.thread_count_spinbox.setValue(3)      # 默认线程数设为3
        self.thread_count_spinbox.setFixedWidth(60)  # 设置控件宽度
        basic_layout.addWidget(self.thread_count_spinbox)
        
        # 添加展开/收起高级设置按钮
        self.toggle_advanced_button = QPushButton("显示高级设置")
        self.toggle_advanced_button.setCheckable(True)
        self.toggle_advanced_button.clicked.connect(self._toggle_advanced_settings)
        basic_layout.addWidget(self.toggle_advanced_button)
        
        basic_layout.addStretch()
        main_layout.addLayout(basic_layout)
        
        # 高级设置区域（默认隐藏）
        self.advanced_settings_widget = QWidget()
        self.advanced_settings_widget.setVisible(False)
        
        # 使用网格布局实现双栏显示
        advanced_layout = QGridLayout(self.advanced_settings_widget)
        
        # 左栏
        left_layout = QFormLayout()
        # 远程BLAST参数
        left_layout.addRow(QLabel("远程BLAST参数:"))
        
        # 结果数量设置 (HITLIST_SIZE)
        hitlist_size_layout = QHBoxLayout()
        self.hitlist_size_enabled = QCheckBox()
        self.hitlist_size_enabled.setChecked(True)
        self.hitlist_size_spinbox = QSpinBox()
        self.hitlist_size_spinbox.setRange(1, 1000)  # 设置结果数量范围为1-1000
        self.hitlist_size_spinbox.setValue(20)       # 默认结果数量设为20
        self.hitlist_size_spinbox.setEnabled(True)  # 默认启用
        self.hitlist_size_enabled.toggled.connect(self.hitlist_size_spinbox.setEnabled)
        hitlist_size_layout.addWidget(self.hitlist_size_enabled)
        hitlist_size_layout.addWidget(self.hitlist_size_spinbox)
        left_layout.addRow("结果数量 (HITLIST_SIZE):", hitlist_size_layout)
        
        # 词大小设置 (WORD_SIZE)
        word_size_layout = QHBoxLayout()
        self.word_size_enabled = QCheckBox()
        self.word_size_enabled.setChecked(False)
        self.word_size_spinbox = QSpinBox()
        self.word_size_spinbox.setRange(1, 100)     # 设置词大小范围为1-100
        self.word_size_spinbox.setValue(28)         # 默认词大小设为28
        self.word_size_spinbox.setEnabled(False)    # 默认禁用，需要勾选复选框启用
        self.word_size_enabled.toggled.connect(self.word_size_spinbox.setEnabled)
        word_size_layout.addWidget(self.word_size_enabled)
        word_size_layout.addWidget(self.word_size_spinbox)
        left_layout.addRow("词大小 (WORD_SIZE):", word_size_layout)
        
        # 期望值设置 (EXPECT)
        evalue_layout = QHBoxLayout()
        self.evalue_enabled = QCheckBox()
        self.evalue_enabled.setChecked(False)
        self.evalue_input = QLineEdit("10.0")      # 默认期望值设为10.0
        self.evalue_input.setEnabled(False)        # 默认禁用，需要勾选复选框启用
        self.evalue_enabled.toggled.connect(self.evalue_input.setEnabled)
        evalue_layout.addWidget(self.evalue_enabled)
        evalue_layout.addWidget(self.evalue_input)
        left_layout.addRow("期望值 (EXPECT):", evalue_layout)
        
        # 打分矩阵设置 (MATRIX_NAME)
        matrix_layout = QHBoxLayout()
        self.matrix_name_enabled = QCheckBox()
        self.matrix_name_enabled.setChecked(False)
        self.matrix_name_combo = QComboBox()
        self.matrix_name_combo.addItems(["BLOSUM62", "BLOSUM45", "BLOSUM80", "PAM30", "PAM70"])  # 可选的打分矩阵
        self.matrix_name_combo.setCurrentText("BLOSUM62")  # 默认打分矩阵设为BLOSUM62
        self.matrix_name_combo.setEnabled(False)           # 默认禁用，需要勾选复选框启用
        self.matrix_name_enabled.toggled.connect(self.matrix_name_combo.setEnabled)
        matrix_layout.addWidget(self.matrix_name_enabled)
        matrix_layout.addWidget(self.matrix_name_combo)
        left_layout.addRow("打分矩阵 (MATRIX_NAME):", matrix_layout)
        
        # 过滤器设置 (FILTER)
        filter_layout = QHBoxLayout()
        self.filter_enabled = QCheckBox()
        self.filter_enabled.setChecked(False)
        self.filter_input = QLineEdit("none")      # 默认过滤器设为"none"(不过滤)
        self.filter_input.setEnabled(False)        # 默认禁用，需要勾选复选框启用
        self.filter_enabled.toggled.connect(self.filter_input.setEnabled)
        filter_layout.addWidget(self.filter_enabled)
        filter_layout.addWidget(self.filter_input)
        left_layout.addRow("过滤器 (FILTER):", filter_layout)
        
        # 本地BLAST参数
        left_layout.addRow(QLabel("本地BLAST参数:"))
        local_threads_layout = QHBoxLayout()
        self.local_num_threads_enabled = QCheckBox()
        self.local_num_threads_enabled.setChecked(False)
        self.local_num_threads_spinbox = QSpinBox()
        self.local_num_threads_spinbox.setRange(1, 16)   # 设置本地线程数范围为1-16
        self.local_num_threads_spinbox.setValue(4)       # 默认本地线程数设为4
        self.local_num_threads_spinbox.setEnabled(False) # 默认禁用，需要勾选复选框启用
        self.local_num_threads_enabled.toggled.connect(self.local_num_threads_spinbox.setEnabled)
        local_threads_layout.addWidget(self.local_num_threads_enabled)
        local_threads_layout.addWidget(self.local_num_threads_spinbox)
        left_layout.addRow("本地线程数:", local_threads_layout)
        
        # 右栏
        right_layout = QFormLayout()
        
        # 比对数量设置 (ALIGNMENTS)
        alignments_layout = QHBoxLayout()
        self.alignments_enabled = QCheckBox()
        self.alignments_enabled.setChecked(False)
        self.alignments_spinbox = QSpinBox()
        self.alignments_spinbox.setRange(0, 5000)    # 设置比对数量范围为0-5000
        self.alignments_spinbox.setValue(500)        # 默认比对数量设为500
        self.alignments_spinbox.setEnabled(False)    # 默认禁用，需要勾选复选框启用
        self.alignments_enabled.toggled.connect(self.alignments_spinbox.setEnabled)
        alignments_layout.addWidget(self.alignments_enabled)
        alignments_layout.addWidget(self.alignments_spinbox)
        right_layout.addRow("比对数量 (ALIGNMENTS):", alignments_layout)
        
        # 描述数量设置 (DESCRIPTIONS)
        descriptions_layout = QHBoxLayout()
        self.descriptions_enabled = QCheckBox()
        self.descriptions_enabled.setChecked(False)
        self.descriptions_spinbox = QSpinBox()
        self.descriptions_spinbox.setRange(0, 5000)   # 设置描述数量范围为0-5000
        self.descriptions_spinbox.setValue(500)       # 默认描述数量设为500
        self.descriptions_spinbox.setEnabled(False)   # 默认禁用，需要勾选复选框启用
        self.descriptions_enabled.toggled.connect(self.descriptions_spinbox.setEnabled)
        descriptions_layout.addWidget(self.descriptions_enabled)
        descriptions_layout.addWidget(self.descriptions_spinbox)
        right_layout.addRow("描述数量 (DESCRIPTIONS):", descriptions_layout)
        
        # 混合模式参数
        right_layout.addRow(QLabel("混合模式参数:"))
        self.prefer_local_checkbox = QCheckBox("优先使用本地BLAST")
        self.prefer_local_checkbox.setChecked(True)      # 默认优先使用本地BLAST
        right_layout.addRow("", self.prefer_local_checkbox)
        
        self.fallback_to_remote_checkbox = QCheckBox("本地不可用时回退到远程")
        self.fallback_to_remote_checkbox.setChecked(True) # 默认启用回退到远程
        right_layout.addRow("", self.fallback_to_remote_checkbox)
        
        self.use_cache_checkbox = QCheckBox("使用缓存")
        self.use_cache_checkbox.setChecked(True)          # 默认启用缓存
        right_layout.addRow("", self.use_cache_checkbox)
        
        # 添加AI翻译功能开关
        right_layout.addRow(QLabel("翻译功能设置:"))
        self.ai_translation_checkbox = QCheckBox("使用AI翻译")
        self.ai_translation_checkbox.setChecked(True)     # 默认启用AI翻译
        right_layout.addRow("", self.ai_translation_checkbox)
        
        # 将左右两栏添加到网格布局中
        advanced_layout.addLayout(left_layout, 0, 0)
        advanced_layout.addLayout(right_layout, 0, 1)
        
        main_layout.addWidget(self.advanced_settings_widget)
        self.setLayout(main_layout)
    
    def _toggle_advanced_settings(self):
        """切换高级设置显示状态"""
        self.advanced_settings_visible = not self.advanced_settings_visible
        self.advanced_settings_widget.setVisible(self.advanced_settings_visible)
        self.toggle_advanced_button.setText("隐藏高级设置" if self.advanced_settings_visible else "显示高级设置")
    
    def get_thread_count(self):
        """获取线程数设置"""
        return self.thread_count_spinbox.value()
    
    def set_thread_count(self, count):
        """设置线程数"""
        self.thread_count_spinbox.setValue(count)
    
    def get_advanced_settings(self):
        """
        获取高级设置参数
        
        Returns:
            dict: 包含所有启用的高级参数设置的字典
                  只有用户勾选启用的参数才会包含在返回字典中
        """
        settings = {}
        
        # 只添加启用的参数
        if self.hitlist_size_enabled.isChecked():
            settings['hitlist_size'] = self.hitlist_size_spinbox.value()
        
        if self.word_size_enabled.isChecked():
            settings['word_size'] = self.word_size_spinbox.value()
            
        if self.evalue_enabled.isChecked():
            settings['evalue'] = float(self.evalue_input.text())
            
        if self.matrix_name_enabled.isChecked():
            settings['matrix_name'] = self.matrix_name_combo.currentText()
            
        if self.filter_enabled.isChecked():
            settings['filter'] = self.filter_input.text()
            
        if self.alignments_enabled.isChecked():
            settings['alignments'] = self.alignments_spinbox.value()
            
        if self.descriptions_enabled.isChecked():
            settings['descriptions'] = self.descriptions_spinbox.value()
            
        # 'max_hsps' 参数被移除，因为qblast不支持该参数
        
        if self.local_num_threads_enabled.isChecked():
            settings['local_num_threads'] = self.local_num_threads_spinbox.value()
            
        # 混合模式参数始终包含
        settings['prefer_local'] = self.prefer_local_checkbox.isChecked()
        settings['fallback_to_remote'] = self.fallback_to_remote_checkbox.isChecked()
        settings['use_cache'] = self.use_cache_checkbox.isChecked()
        
        # AI翻译功能开关
        settings['use_ai_translation'] = self.ai_translation_checkbox.isChecked()
        
        return settings
    
    def set_advanced_settings(self, settings):
        """
        设置高级参数
        
        Args:
            settings (dict): 包含参数设置的字典
                            会根据字典中的键值对设置对应的参数控件值和启用状态
        """
        # 设置参数值和启用状态
        if 'hitlist_size' in settings:
            self.hitlist_size_enabled.setChecked(True)
            self.hitlist_size_spinbox.setValue(settings['hitlist_size'])
            
        if 'word_size' in settings:
            self.word_size_enabled.setChecked(True)
            self.word_size_spinbox.setValue(settings['word_size'])
            
        if 'evalue' in settings:
            self.evalue_enabled.setChecked(True)
            self.evalue_input.setText(str(settings['evalue']))
            
        if 'matrix_name' in settings:
            self.matrix_name_enabled.setChecked(True)
            index = self.matrix_name_combo.findText(settings['matrix_name'])
            if index >= 0:
                self.matrix_name_combo.setCurrentIndex(index)
                
        if 'filter' in settings:
            self.filter_enabled.setChecked(True)
            self.filter_input.setText(settings['filter'])
            
        if 'alignments' in settings:
            self.alignments_enabled.setChecked(True)
            self.alignments_spinbox.setValue(settings['alignments'])
            
        if 'descriptions' in settings:
            self.descriptions_enabled.setChecked(True)
            self.descriptions_spinbox.setValue(settings['descriptions'])
            
        # max_hsps 参数被移除，因为qblast不支持该参数
        
        if 'local_num_threads' in settings:
            self.local_num_threads_enabled.setChecked(True)
            self.local_num_threads_spinbox.setValue(settings['local_num_threads'])
            
        if 'prefer_local' in settings:
            self.prefer_local_checkbox.setChecked(settings['prefer_local'])
            
        if 'fallback_to_remote' in settings:
            self.fallback_to_remote_checkbox.setChecked(settings['fallback_to_remote'])
            
        if 'use_cache' in settings:
            self.use_cache_checkbox.setChecked(settings['use_cache'])
            
        # AI翻译功能开关设置
        if 'use_ai_translation' in settings:
            self.ai_translation_checkbox.setChecked(settings['use_ai_translation'])
