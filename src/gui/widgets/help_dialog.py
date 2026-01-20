"""
帮助对话框模块（PyQt6版本）
"""

import os
import sys

from PyQt6.QtGui import QTextOption
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QPushButton,
                             QTextEdit)

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
        self.setWindowTitle("帮助与使用指南")
        self.setModal(True)
        self.resize(800, 600)
        
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
        <style>
            h2 { color: #2c3e50; }
            h3 { color: #3498db; margin-top: 20px; }
            li { margin-bottom: 5px; }
            .note { background-color: #f9f9f9; border-left: 5px solid #f1c40f; padding: 10px; margin: 10px 0; }
            .tip { background-color: #e8f8f5; border-left: 5px solid #2ecc71; padding: 10px; margin: 10px 0; }
        </style>
        
        <h2>NCBI BLAST Pro 使用指南</h2>
        
        <div class="tip">
        <b>快速入门：</b> 拖拽 FASTA 文件到左侧列表 -> 点击"开始处理" -> 等待结果显示。
        </div>

        <h3>1. 文件导入</h3>
        <ul>
            <li><b>支持格式</b>：FASTA (.fasta, .fa, .fna), 纯文本序列 (.seq, .txt)</li>
            <li><b>批量处理</b>：支持一次性导入多个文件，或包含多条序列的单个 FASTA 文件。</li>
            <li><b>操作方式</b>：点击"添加文件"按钮，或直接将文件拖入左侧列表区域。</li>
        </ul>

        <h3>2. 参数配置</h3>
        <ul>
            <li><b>基础设置</b>：在左侧面板可快速调整线程数和 AI 翻译开关。</li>
            <li><b>高级设置</b>：点击"配置高级参数"可设置：
                <ul>
                    <li><b>BLAST 程序</b>：手动指定 blastn, blastp, blastx 等，或留空自动检测。</li>
                    <li><b>数据库</b>：选择 nt (核酸), nr (蛋白) 等标准数据库。</li>
                    <li><b>搜索参数</b>：E-value, Word Size, Hitlist Size 等。</li>
                    <li><b>本地/远程</b>：配置本地 BLAST+ 路径及优先策略。</li>
                </ul>
            </li>
        </ul>

        <h3>3. 结果查看与分析</h3>
        <ul>
            <li><b>实时状态</b>：处理过程中，文件状态会实时更新（处理中/成功/失败）。</li>
            <li><b>详细结果</b>：点击文件节点展开，查看每条序列的最佳匹配结果（物种、相似度、E值）。</li>
            <li><b>可视化</b>：右键点击结果，选择"可视化比对"查看图形化比对视图。</li>
            <li><b>AI 翻译</b>：启用 AI 翻译后，结果中的物种名、基因功能等将自动翻译为中文，并提供简要解释。</li>
        </ul>

        <h3>4. 历史记录与缓存</h3>
        <ul>
            <li><b>任务历史</b>：通过"文件" -> "任务历史记录"查看过往任务，支持重新加载结果。</li>
            <li><b>智能缓存</b>：系统会自动缓存相同序列的查询结果（默认 24 小时），避免重复消耗时间和流量。</li>
        </ul>

        <h3>5. 常见问题</h3>
        <div class="note">
        <b>Q: 处理速度慢？</b><br>
        A: 远程 BLAST 受网络和 NCBI 服务器负载影响。建议：
        1. 减少并发线程数（默认 3）；
        2. 启用本地 BLAST+（需自行安装并下载数据库）；
        3. 检查网络连接。
        </div>
        
        <div class="note">
        <b>Q: 内存占用高？</b><br>
        A: 处理超大 FASTA 文件时，系统会自动优化读取方式。但建议将超大文件（>500MB）分割后处理。
        </div>

        <h3>技术支持</h3>
        <p>如遇程序错误或有功能建议，请联系开发团队。</p>
        """