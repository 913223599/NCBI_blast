"""
通用帮助查看器
用于显示 Markdown 格式的帮助文档
"""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QTextBrowser, QPushButton, QHBoxLayout,
    QListWidget, QSplitter, QListWidgetItem
)

from src.utils.help_manager import get_help_manager


class HelpViewerDialog(QDialog):
    """
    帮助文档查看器对话框
    支持左侧目录（可选）和右侧内容显示
    """
    
    def __init__(self, parent=None, initial_topic=None):
        super().__init__(parent)
        self.setWindowTitle("帮助文档")
        self.resize(900, 600)
        self.help_manager = get_help_manager()
        self.initial_topic = initial_topic
        
        self._setup_ui()
        self._load_topics()
        
        # 加载初始主题
        if initial_topic:
            self._select_topic(initial_topic)
        else:
            # 默认选中第一个非标题项
            for i in range(self.topic_list.count()):
                item = self.topic_list.item(i)
                # 检查是否是可点击的主题项（有 UserRole 数据）
                if item.data(Qt.ItemDataRole.UserRole):
                    self.topic_list.setCurrentItem(item)
                    break

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        
        # 分割器
        splitter = QSplitter(Qt.Orientation.Horizontal)
        
        # 左侧：主题列表
        self.topic_list = QListWidget()
        self.topic_list.setFixedWidth(200)
        self.topic_list.currentItemChanged.connect(self._on_topic_changed)
        splitter.addWidget(self.topic_list)
        
        # 右侧：内容显示
        self.content_browser = QTextBrowser()
        self.content_browser.setOpenExternalLinks(True) # 允许打开外部链接
        splitter.addWidget(self.content_browser)
        
        # 设置分割比例
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 4)
        
        layout.addWidget(splitter)
        
        # 底部按钮
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        
        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(self.accept)
        btn_layout.addWidget(close_btn)
        
        layout.addLayout(btn_layout)

    def _load_topics(self):
        """加载并分类显示所有可用主题"""
        available_topics = set(self.help_manager.get_help_topics())
        
        # 定义分类结构
        structure = [
            ("入门指南", [
                ("quick_start", "快速入门"),
            ]),
            ("核心功能", [
                ("local_blast", "本地 BLAST"),
                ("elastic_blast", "Elastic BLAST 云服务"),
                ("database_manager", "数据库管理"),
                ("history", "任务历史"),
            ]),
            ("高级设置", [
                ("settings", "参数设置"),
                ("translation_debugger", "翻译调试器"),
            ])
        ]
        
        # 记录已处理的主题，以便最后添加未分类的主题
        processed_topics = set()
        
        for category, items in structure:
            # 添加分类标题
            category_item = QListWidgetItem(category)
            category_item.setFlags(Qt.ItemFlag.NoItemFlags) # 不可选中
            category_item.setForeground(QColor("#409eff")) # 蓝色高亮
            font = category_item.font()
            font.setBold(True)
            category_item.setFont(font)
            self.topic_list.addItem(category_item)
            
            # 添加该分类下的主题
            for topic_id, display_name in items:
                if topic_id in available_topics:
                    item = QListWidgetItem(f"  {display_name}") # 缩进
                    item.setData(Qt.ItemDataRole.UserRole, topic_id)
                    self.topic_list.addItem(item)
                    processed_topics.add(topic_id)
            
            # 添加一点间距（空行）
            # empty_item = QListWidgetItem("")
            # empty_item.setFlags(Qt.ItemFlag.NoItemFlags)
            # self.topic_list.addItem(empty_item)

        # 处理未分类的主题
        remaining_topics = available_topics - processed_topics
        if remaining_topics:
            other_category = QListWidgetItem("其他")
            other_category.setFlags(Qt.ItemFlag.NoItemFlags)
            other_category.setForeground(QColor("#409eff"))
            font = other_category.font()
            font.setBold(True)
            other_category.setFont(font)
            self.topic_list.addItem(other_category)
            
            for topic_id in sorted(remaining_topics):
                display_name = topic_id.replace("_", " ").title()
                item = QListWidgetItem(f"  {display_name}")
                item.setData(Qt.ItemDataRole.UserRole, topic_id)
                self.topic_list.addItem(item)

    def _select_topic(self, topic_id):
        """选中指定的主题"""
        for i in range(self.topic_list.count()):
            item = self.topic_list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == topic_id:
                self.topic_list.setCurrentItem(item)
                self._load_content(topic_id)
                return

    def _on_topic_changed(self, current, previous):
        if not current:
            return
        
        topic_id = current.data(Qt.ItemDataRole.UserRole)
        if topic_id:
            self._load_content(topic_id)

    def _load_content(self, topic_id):
        """加载并渲染 Markdown 内容"""
        content = self.help_manager.get_help_content(topic_id)
        self.content_browser.setMarkdown(content)

    @staticmethod
    def show_topic(parent, topic_id):
        """静态便捷方法"""
        dialog = HelpViewerDialog(parent, initial_topic=topic_id)
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()
        return dialog
