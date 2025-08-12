"""
帮助对话框模块（PyQt6版本）
"""

import sys
import os
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QPushButton,
                             QTextEdit, QLabel)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QTextOption

# 添加项目根目录到Python路径
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if project_root not in sys.path:
    sys.path.insert(0, project_root)


class HelpDialog(QDialog):
    """帮助对话框类"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()
        
    def _setup_ui(self):
        """设置界面"""
        self.setWindowTitle("帮助")
        self.setModal(True)
        self.resize(600, 400)
        
        layout = QVBoxLayout()
        
        # 创建帮助文本显示区域
        self.text_display = QTextEdit()
        self.text_display.setReadOnly(True)
        self.text_display.setWordWrapMode(QTextOption.WrapMode.WordWrap)
        self.text_display.setHtml(self._get_help_content())
        layout.addWidget(self.text_display)
        
        # 按钮布局
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        
        self.close_button = QPushButton("关闭")
        self.close_button.clicked.connect(self.accept)
        button_layout.addWidget(self.close_button)
        
        layout.addLayout(button_layout)
        self.setLayout(layout)
    
    def _get_help_content(self):
        """获取帮助内容"""
        return """
        <h2>NCBI BLAST工具使用帮助</h2>
        
        <h3>功能简介</h3>
        <p>本工具提供了一个图形界面，用于执行NCBI BLAST搜索并查看结果。主要功能包括：</p>
        <ul>
            <li>选择FASTA格式的序列文件</li>
            <li>配置BLAST参数</li>
            <li>执行BLAST搜索</li>
            <li>查看和导出结果</li>
            <li>结果翻译（中英文对照）</li>
        </ul>
        
        <h3>使用步骤</h3>
        <ol>
            <li><b>选择序列文件</b>：点击"添加文件"按钮选择一个或多个FASTA格式的序列文件</li>
            <li><b>配置参数</b>：通过"文件"->"设置"菜单配置BLAST参数，如数据库、程序类型等</li>
            <li><b>开始BLAST</b>：点击"开始BLAST"按钮执行搜索</li>
            <li><b>查看结果</b>：在结果区域查看搜索结果，点击文件名可查看详细信息</li>
            <li><b>导出结果</b>：右键点击结果文件可选择导出查询信息</li>
        </ol>
        
        <h3>结果说明</h3>
        <p>搜索结果包含以下信息：</p>
        <ul>
            <li><b>物种信息</b>：匹配序列的物种名称</li>
            <li><b>基因信息</b>：匹配的基因类型和序列类型</li>
            <li><b>相似度</b>：查询序列与匹配序列的相似度</li>
            <li><b>E值</b>：期望值，表示随机匹配的概率</li>
        </ul>
        
        <h3>翻译功能</h3>
        <p>工具支持中英文对照显示：</p>
        <ul>
            <li><b>本地翻译</b>：使用内置词典进行翻译</li>
            <li><b>AI翻译</b>：使用通义千问API进行翻译（需要配置API密钥）</li>
        </ul>
        
        <h3>注意事项</h3>
        <ul>
            <li>确保网络连接正常，以便访问NCBI BLAST服务</li>
            <li>较大的序列文件可能需要较长时间处理</li>
            <li>建议定期更新本地翻译数据库以获得更好的翻译效果</li>
        </ul>
        
        <h3>技术支持</h3>
        <p>如有问题，请联系技术支持。</p>
        """