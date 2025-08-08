"""
详细信息组件模块
负责显示详细信息的GUI组件
"""

from pathlib import Path
from PyQt6.QtWidgets import (QGroupBox, QVBoxLayout, QTextEdit)


class DetailViewerWidget(QGroupBox):
    """详细信息组件类"""
    
    def __init__(self):
        super().__init__("详细信息")
        self._setup_ui()
    
    def _setup_ui(self):
        """设置界面"""
        layout = QVBoxLayout()
        
        self.detail_text = QTextEdit()
        self.detail_text.setReadOnly(True)
        self.detail_text.setMaximumHeight(150)
        layout.addWidget(self.detail_text)
        
        self.setLayout(layout)
    
    def show_details(self, file_name, results):
        """显示文件详细信息"""
        # 清空详细信息
        self.detail_text.clear()
        
        # 查找对应的结果
        for result in results:
            result_file_name = Path(result.get("file", "")).name
            if result_file_name == file_name:
                # 显示详细信息
                details = f"文件: {file_name}\n"
                details += f"状态: {'成功' if result.get('status') == 'success' else '失败'}\n"
                
                if "elapsed_time" in result:
                    details += f"耗时: {result['elapsed_time']:.2f} 秒\n"
                
                if result.get("status") == "error":
                    details += f"错误信息: {result.get('error', '未知错误')}\n"
                
                if "result_file" in result:
                    details += f"结果文件: {result['result_file']}\n"
                
                self.detail_text.setPlainText(details)
                break
        else:
            # 如果没有找到结果，显示基本信息
            self.detail_text.setPlainText(f"文件: {file_name}\n状态: 待处理\n")