"""
详细信息组件模块
负责显示详细信息的GUI组件
"""

from pathlib import Path

from Bio.Blast import NCBIXML
from PyQt6.QtWidgets import (QGroupBox, QVBoxLayout, QTextEdit)

# 导入生物学翻译模块
from src.utils.biology_translator import get_biology_translator


class DetailViewerWidget(QGroupBox):
    """详细信息组件类"""
    
    def __init__(self):
        super().__init__("详细信息")
        self._setup_ui()
        # 初始化翻译器
        self.translator = get_biology_translator()
    
    def _setup_ui(self):
        """设置界面"""
        layout = QVBoxLayout()
        
        self.detail_text = QTextEdit()
        self.detail_text.setReadOnly(True)
        self.detail_text.setMaximumHeight(150)
        layout.addWidget(self.detail_text)
        
        self.setLayout(layout)
    
    def show_details(self, file_name, results, selected_alignment=None):
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
                    
                    # 读取并解析结果文件以获取详细信息
                    result_file = result["result_file"]
                    try:
                        with open(result_file, 'r') as f:
                            handle = NCBIXML.read(f)
                            details += self._get_detailed_info(handle, selected_alignment)
                    except Exception as e:
                        details += f"加载结果失败: {str(e)}"
                
                self.detail_text.setPlainText(details)
                break
        else:
            # 如果没有找到结果，显示基本信息
            self.detail_text.setPlainText(f"文件: {file_name}\n状态: 待处理\n")

    def _get_detailed_info(self, blast_record, selected_alignment=None):
        """获取详细的BLAST结果信息"""
        detailed_info = "\n详细信息:\n"
        
        if blast_record.alignments:
            if selected_alignment is None:
                detailed_info += f"找到 {len(blast_record.alignments)} 个匹配:\n"
                for i, alignment in enumerate(blast_record.alignments):
                    title = alignment.title[:100] + "..." if len(alignment.title) > 100 else alignment.title
                    detailed_info += f"\n匹配 {i+1}: {title}\n"
                    
                    # 翻译物种名字
                    translated_title = self._translate_species_name(title)
                    detailed_info += f"翻译: {translated_title}\n"
                    
                    for hsp in alignment.hsps:
                        identity_pct = (hsp.identities / hsp.align_length * 100) if hsp.align_length > 0 else 0
                        detailed_info += f"  - 长度: {alignment.length}\n"
                        detailed_info += f"  - E值: {hsp.expect:.2e}\n"
                        detailed_info += f"  - 相似度: {identity_pct:.2f}%\n"
                        detailed_info += f"  - 比对序列:\n{hsp.query}\n{hsp.match}\n{hsp.sbjct}\n"
            else:
                title = selected_alignment.title[:100] + "..." if len(selected_alignment.title) > 100 else selected_alignment.title
                detailed_info += f"匹配: {title}\n"
                
                # 翻译物种名字
                translated_title = self._translate_species_name(title)
                detailed_info += f"翻译: {translated_title}\n"
                
                for hsp in selected_alignment.hsps:
                    identity_pct = (hsp.identities / hsp.align_length * 100) if hsp.align_length > 0 else 0
                    detailed_info += f"  - 长度: {selected_alignment.length}\n"
                    detailed_info += f"  - E값: {hsp.expect:.2e}\n"
                    detailed_info += f"  - 相似度: {identity_pct:.2f}%\n"
                    detailed_info += f"  - 比对序列:\n{hsp.query}\n{hsp.match}\n{hsp.sbjct}\n"
        else:
            detailed_info += "没有找到匹配结果\n"
        
        return detailed_info

    def _translate_species_name(self, title):
        """翻译物种名字"""
        # 提取标题中的物种名称部分进行翻译
        # 标题格式通常为 "gi|...|...|物种名称..."
        try:
            # 尝试从NCBI标题中提取物种名称部分
            if "|" in title:
                # 找到最后一个"|"之后的部分
                species_part = title.split("|")[-1].strip()
                # 如果包含空格，可能是物种名称
                if " " in species_part:
                    translated = self.translator.translate_text(species_part)
                    return translated
            
            # 如果没有成功提取物种名称部分，则直接翻译整个标题
            translated = self.translator.translate_text(title)
            return translated
        except Exception as e:
            # 如果翻译过程中出现任何错误，返回原始标题
            return title