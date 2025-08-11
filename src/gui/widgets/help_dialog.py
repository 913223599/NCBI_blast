"""
帮助文档对话框模块
负责提供关于工具的详细信息和使用说明
"""

import sys
import os
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QTextEdit, QPushButton, 
                             QHBoxLayout, QWidget, QLabel, QTabWidget)
from PyQt6.QtCore import Qt

# 添加项目根目录到Python路径
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if project_root not in sys.path:
    sys.path.insert(0, project_root)


class HelpDialog(QDialog):
    """帮助文档对话框类"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("帮助")
        self.setGeometry(200, 200, 600, 500)
        self._setup_ui()
    
    def _setup_ui(self):
        """设置界面"""
        layout = QVBoxLayout()
        
        # 创建标签页控件
        tab_widget = QTabWidget()
        
        # 添加关于标签页
        about_tab = self._create_about_tab()
        tab_widget.addTab(about_tab, "关于")
        
        # 添加使用说明标签页
        usage_tab = self._create_usage_tab()
        tab_widget.addTab(usage_tab, "使用说明")
        
        # 添加功能说明标签页
        features_tab = self._create_features_tab()
        tab_widget.addTab(features_tab, "功能说明")
        
        layout.addWidget(tab_widget)
        
        # 添加关闭按钮
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        close_button = QPushButton("关闭")
        close_button.clicked.connect(self.accept)
        button_layout.addWidget(close_button)
        layout.addLayout(button_layout)
        
        self.setLayout(layout)
    
    def _create_about_tab(self):
        """创建关于标签页"""
        widget = QWidget()
        layout = QVBoxLayout()
        
        about_text = """
<h2>NCBI BLAST 查询工具</h2>

<p>版本: 1.0.0</p>

<h3>简介</h3>
<p>这是一个用于执行 NCBI BLAST 搜索的工具，支持对 DNA 序列进行比对分析。该工具专为生物信息学研究人员和DNA序列分析人员设计，提供快速、高效的本地或远程 BLAST 搜索功能。</p>

<h3>主要特性</h3>
<ul>
<li>执行本地 BLAST 搜索</li>
<li>执行远程 BLAST 搜索</li>
<li>批量处理多个序列文件</li>
<li>多线程处理避免程序卡死</li>
<li>结果缓存避免重复查询</li>
<li>图形界面展示处理结果</li>
<li>支持取消正在进行的任务</li>
<li>提供性能优化方案</li>
</ul>

<h3>开发者信息</h3>
<p>该工具基于 Python 和 BioPython 开发，使用 PyQt6 构建图形界面。</p>
"""
        
        label = QLabel(about_text)
        label.setWordWrap(True)
        label.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(label)
        widget.setLayout(layout)
        
        return widget
    
    def _create_usage_tab(self):
        """创建使用说明标签页"""
        widget = QWidget()
        layout = QVBoxLayout()
        
        usage_text = """
<h3>基本使用流程</h3>
<ol>
<li><b>选择序列文件</b>：点击"选择文件"按钮，选择要进行 BLAST 搜索的序列文件</li>
<li><b>设置参数</b>：根据需要调整线程数和高级参数设置</li>
<li><b>开始处理</b>：点击"开始处理"按钮开始 BLAST 搜索</li>
<li><b>查看结果</b>：在结果查看器中浏览搜索结果</li>
</ol>

<h3>参数设置说明</h3>
<ul>
<li><b>线程数</b>：设置并发处理的线程数量（1-10）</li>
<li><b>结果数量</b>：设置返回的匹配结果数量</li>
<li><b>词大小</b>：设置匹配时使用的词大小</li>
<li><b>期望值</b>：设置统计显著性的阈值</li>
<li><b>打分矩阵</b>：设置序列比对的打分矩阵</li>
<li><b>过滤器</b>：设置序列过滤选项</li>
</ul>

<h3>混合模式参数</h3>
<ul>
<li><b>优先使用本地BLAST</b>：优先使用本地数据库进行搜索</li>
<li><b>本地不可用时回退到远程</b>：当本地数据库不可用时自动切换到远程搜索</li>
<li><b>使用缓存</b>：启用结果缓存以避免重复查询</li>
</ul>
"""
        
        label = QLabel(usage_text)
        label.setWordWrap(True)
        label.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(label)
        widget.setLayout(layout)
        
        return widget
    
    def _create_features_tab(self):
        """创建功能说明标签页"""
        widget = QWidget()
        layout = QVBoxLayout()
        
        features_text = """
<h3>核心功能</h3>
<ul>
<li><b>本地BLAST搜索</b>：支持在本地数据库上执行BLAST搜索，提供更快的查询速度</li>
<li><b>远程BLAST搜索</b>：通过NCBI服务器执行BLAST搜索，访问最新的数据库</li>
<li><b>混合模式</b>：智能结合本地和远程搜索的优势</li>
<li><b>批量处理</b>：支持同时处理多个序列文件</li>
<li><b>多线程</b>：利用多线程技术提高处理效率</li>
<li><b>结果缓存</b>：缓存查询结果以避免重复查询，提升效率</li>
<li><b>中文翻译</b>：对搜索结果中的生物学术语进行中文翻译</li>
<li><b>AI翻译</b>：使用通义千问AI模型提供高质量的翻译服务</li>
</ul>

<h3>高级功能</h3>
<ul>
<li><b>重试机制</b>：对失败的查询可以单独重试</li>
<li><b>进度监控</b>：实时显示处理进度</li>
<li><b>结果统计</b>：提供处理结果的统计信息</li>
<li><b>详细视图</b>：提供详细的查询结果展示</li>
<li><b>翻译调试</b>：通过"工具"菜单中的"翻译调试器"测试翻译功能</li>
</ul>

<h3>注意事项</h3>
<ul>
<li>使用远程BLAST需要网络连接</li>
<li>使用本地BLAST需要预先安装本地数据库</li>
<li>AI翻译功能需要配置通义百炼API密钥</li>
<li>处理大量文件时建议适当调整线程数</li>
</ul>
"""
        
        label = QLabel(features_text)
        label.setWordWrap(True)
        label.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(label)
        widget.setLayout(layout)
        
        return widget