"""
详细信息查看组件模块（PyQt6版本）
"""

import csv
from pathlib import Path
from PyQt6.QtWidgets import (QGroupBox, QVBoxLayout, QTextEdit, QFileDialog, 
                             QMessageBox)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QTextOption

from src.utils.translation import get_blast_result_translator


class DetailViewerWidget(QGroupBox):
    """详细信息查看组件类"""
    
    def __init__(self):
        super().__init__("详细信息")
        self._setup_ui()
        self.translator = get_blast_result_translator()
        self.biology_translator = None  # 延迟初始化生物学翻译器
        self.current_result = None
        self.api_key = None  # API密钥
    
    def _setup_ui(self):
        """设置界面"""
        layout = QVBoxLayout()
        
        # 创建文本显示区域
        self.text_display = QTextEdit()
        self.text_display.setReadOnly(True)
        self.text_display.setWordWrapMode(QTextOption.WrapMode.NoWrap)
        layout.addWidget(self.text_display)
        
        self.setLayout(layout)
    
    def set_api_key(self, api_key):
        """
        设置API密钥并初始化生物学翻译器
        
        Args:
            api_key (str): API密钥
        """
        self.api_key = api_key
        if api_key:
            try:
                from src.utils.translation import get_biology_translator
                # 确保使用项目根目录下的translation_data.csv文件
                from pathlib import Path
                project_root = Path(__file__).parent.parent.parent.parent
                csv_file = str(project_root / "translation_data.csv")
                self.biology_translator = get_biology_translator(data_file=csv_file, use_ai=True, ai_api_key=api_key)
            except Exception as e:
                print(f"初始化生物学翻译器失败: {e}")
                self.biology_translator = None
        else:
            self.biology_translator = None
    
    def show_details(self, file_name, results):
        """
        显示文件详细信息 (为兼容主窗口调用而添加)
        
        Args:
            file_name (str): 文件名
            results (list): 结果数据列表
        """
        # 查找对应的结果数据
        result_data = None
        for result in results:
            if Path(result.get("file", "")).name == file_name:
                result_data = result
                break
        
        if result_data:
            self.display_result(result_data)
        else:
            self.clear_display()
    
    def display_result(self, result_data):
        """显示结果详细信息"""
        self.current_result = result_data
        
        # 构建显示文本
        try:
            display_text = self._build_display_text(result_data)
            self.text_display.setPlainText(display_text)
        except Exception as e:
            error_text = f"显示详细信息时出错:\n{str(e)}"
            self.text_display.setPlainText(error_text)
    
    def _build_display_text(self, result_data):
        """构建显示文本"""
        lines = []
        
        # 基本信息
        lines.append("BLAST结果详细信息")
        lines.append("=" * 50)
        lines.append(f"文件名: {Path(result_data.get('file', '')).name}")
        lines.append(f"状态: {'成功' if result_data.get('status') == 'success' else '失败'}")
        
        if "elapsed_time" in result_data:
            lines.append(f"耗时: {result_data['elapsed_time']:.2f}秒")
        
        if result_data.get("status") == "error":
            lines.append(f"错误信息: {result_data.get('error', '未知错误')}")
            return "\n".join(lines)
        
        # 添加结果文件信息
        if result_data.get("result_file"):
            lines.append(f"结果文件: {result_data['result_file']}")
        
        if result_data.get("csv_file"):
            lines.append(f"CSV文件: {result_data['csv_file']}")
        
        if result_data.get("desc_file"):
            lines.append(f"描述文件: {result_data['desc_file']}")
        
        # 读取并显示CSV内容
        csv_file = result_data.get("csv_file")
        if csv_file and Path(csv_file).exists():
            lines.append("\n匹配结果:")
            lines.append("-" * 30)
            
            try:
                with open(csv_file, 'r', encoding='utf-8') as f:
                    reader = csv.DictReader(f)
                    for i, row in enumerate(reader):
                        # 获取各个字段
                        species = row.get('物种', '')
                        genus = row.get('属名', '')
                        strain = row.get('菌株', '')
                        gene_type = row.get('基因类型', '')
                        sequence_type = row.get('序列类型', '')
                        similarity = row.get('相似度', '')
                        e_value = row.get('E值', '')
                        
                        # 使用生物学翻译器翻译物种和属名
                        if species and self.biology_translator:
                            try:
                                translated_species = self.biology_translator.translate_text(species)
                                if translated_species and translated_species != species:
                                    # 提取翻译结果，去除标识符如[AI]或[本地]
                                    if translated_species.startswith('[AI]'):
                                        species = translated_species[4:]  # 去掉前缀[AI]
                                    elif translated_species.startswith('[本地]'):
                                        species = translated_species[4:]  # 去掉前缀[本地]
                                    else:
                                        species = translated_species
                            except Exception as e:
                                print(f"翻译物种时出错: {e}")
                        
                        if genus and self.biology_translator:
                            try:
                                translated_genus = self.biology_translator.translate_text(genus)
                                if translated_genus and translated_genus != genus:
                                    # 提取翻译结果，去除标识符如[AI]或[本地]
                                    if translated_genus.startswith('[AI]'):
                                        genus = translated_genus[4:]  # 去掉前缀[AI]
                                    elif translated_genus.startswith('[本地]'):
                                        genus = translated_genus[4:]  # 去掉前缀[本地]
                                    else:
                                        genus = translated_genus
                            except Exception as e:
                                print(f"翻译属名时出错: {e}")
                        
                        
                        # 使用AI增强的生物学翻译器翻译基因类型和序列类型
                        if gene_type and self.biology_translator:
                            try:
                                translated_gene = self.biology_translator.translate_text(gene_type)
                                if translated_gene and translated_gene != gene_type:
                                    # 提取翻译结果，去除标识符如[AI]或[本地]
                                    if translated_gene.startswith('[AI]'):
                                        gene_type = translated_gene[4:]  # 去掉前缀[AI]
                                    elif translated_gene.startswith('[本地]'):
                                        gene_type = translated_gene[4:]  # 去掉前缀[本地]
                                    else:
                                        gene_type = translated_gene
                            except Exception as e:
                                print(f"翻译基因类型时出错: {e}")
                        
                        if sequence_type and self.biology_translator:
                            try:
                                translated_sequence = self.biology_translator.translate_text(sequence_type)
                                if translated_sequence and translated_sequence != sequence_type:
                                    # 提取翻译结果，去除标识符如[AI]或[本地]
                                    if translated_sequence.startswith('[AI]'):
                                        sequence_type = translated_sequence[4:]  # 去掉前缀[AI]
                                    elif translated_sequence.startswith('[本地]'):
                                        sequence_type = translated_sequence[4:]  # 去掉前缀[本地]
                                    else:
                                        sequence_type = translated_sequence
                            except Exception as e:
                                print(f"翻译序列类型时出错: {e}")
                        
                        # 构建显示文本
                        info_parts = []
                        if species:
                            info_parts.append(species)
                        if genus and genus != species:
                            info_parts.append(genus)
                        if strain:
                            info_parts.append(strain)
                        if gene_type:
                            info_parts.append(gene_type)
                        if sequence_type:
                            info_parts.append(sequence_type)
                        
                        main_info = " ".join(info_parts) if info_parts else "未命名条目"
                        lines.append(f"{i+1}. {main_info}")
                        
                        # 添加详细信息
                        detail_parts = []
                        if similarity:
                            detail_parts.append(f"相似度: {similarity}")
                        if e_value:
                            detail_parts.append(f"E值: {e_value}")
                        
                        if detail_parts:
                            detail_text = ", ".join(detail_parts)
                            lines.append(f"   {detail_text}")
                        
                        lines.append("")
                        
            except Exception as e:
                lines.append(f"读取CSV文件时出错: {e}")
        else:
            lines.append("\n未找到匹配结果")
        
        return "\n".join(lines)
    
    def clear_display(self):
        """清空显示内容"""
        self.text_display.clear()
    
    def export_display(self):
        """导出显示内容到文件"""
        try:
            file_path, _ = QFileDialog.getSaveFileName(
                self, 
                "导出详细信息", 
                "", 
                "Text Files (*.txt);;All Files (*)"
            )
            
            if file_path:
                content = self.text_display.toPlainText()
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(content)
                QMessageBox.information(self, "成功", f"详细信息已导出到:\n{file_path}")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"导出失败:\n{str(e)}")
