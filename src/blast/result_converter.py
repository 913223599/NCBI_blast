"""
BLAST结果转换模块
负责将BLAST的XML格式结果转换为CSV格式
使用流式解析器以降低内存占用
"""

import csv
from pathlib import Path
from typing import Iterator, Dict, Any

from src.blast.parser import BlastXmlParser


class BlastResultConverter:
    """
    BLAST结果转换器
    负责将BLAST的XML格式结果转换为CSV格式，并生成描述文件
    """
    
    def __init__(self):
        """
        初始化结果转换器
        """
        self.parser = BlastXmlParser()
    
    def convert_xml_to_csv(self, xml_file: str, csv_file: str):
        """
        将BLAST XML结果文件转换为CSV格式 (流式处理)
        
        Args:
            xml_file (str): 输入的XML文件路径
            csv_file (str): 输出的CSV文件路径
        """
        try:
            # 确保输出目录存在
            Path(csv_file).parent.mkdir(parents=True, exist_ok=True)
            
            final_headers = [
                '标题', '长度', '访问号', '物种', '属名', '菌株', '基因类型', '序列类型',
                '宿主信息', '高得分片段对(HSPs)', 'E值', '比对长度', '相同碱基数', '相似度', '缺口数',
                '查询起始-结束', '命中起始-结束'
            ]
            
            with open(xml_file, 'r', encoding='utf-8') as f_xml, \
                 open(csv_file, 'w', newline='', encoding='utf-8-sig') as f_csv:
                 
                writer = csv.DictWriter(f_csv, fieldnames=final_headers)
                writer.writeheader()
                
                has_records = False
                for row_data in self.parser.parse(f_xml):
                    has_records = True
                    csv_row = {
                        '标题': row_data.get('title', ''),
                        '长度': row_data.get('length', 0),
                        '访问号': row_data.get('accession', ''),
                        '物种': row_data.get('species', ''),
                        '属名': row_data.get('genus', ''),
                        '菌株': row_data.get('strain', ''),
                        '基因类型': row_data.get('gene_type', ''),
                        '序列类型': row_data.get('sequence_type', ''),
                        '宿主信息': row_data.get('host_info', ''),
                        '高得分片段对(HSPs)': row_data.get('hsps_count', 1),
                        'E值': f"{row_data.get('e_value', 0):.2e}" if isinstance(row_data.get('e_value'), (int, float)) else row_data.get('e_value', ''),
                        '比对长度': row_data.get('align_length', 0),
                        '相同碱基数': row_data.get('identities', 0),
                        '相似度': f"{row_data.get('identity_pct', 0):.2f}%" if isinstance(row_data.get('identity_pct'), (int, float)) else row_data.get('identity_pct', ''),
                        '缺口数': row_data.get('gaps', 0),
                        '查询起始-结束': f"{row_data.get('query_start')}-{row_data.get('query_end')}",
                        '命中起始-结束': f"{row_data.get('sbjct_start')}-{row_data.get('sbjct_end')}"
                    }
                    writer.writerow(csv_row)
                    
                if has_records:
                    print(f"成功转换XML到CSV (流式): {csv_file}")
                    # 提取并保存术语到预定义术语文件
                    self._extract_and_save_terms(csv_file)
                else:
                    print(f"没有找到比对结果，创建了空的CSV文件: {csv_file}")
                
        except Exception as e:
            print(f"转换过程中出错: {e}")
            raise

    def save_parsed_to_csv(self, parsed_rows: Iterator[Dict[str, Any]], output_file: str):
        """
        将已解析的行序列直接保存为 CSV (用于批处理加速)
        """
        try:
            Path(output_file).parent.mkdir(parents=True, exist_ok=True)
            final_headers = [
                '标题', '长度', '访问号', '物种', '属名', '菌株', '基因类型', '序列类型',
                '宿主信息', '高得分片段对(HSPs)', 'E值', '比对长度', '相同碱基数', '相似度', '缺口数',
                '查询起始-结束', '命中起始-结束'
            ]
            
            with open(output_file, 'w', newline='', encoding='utf-8-sig') as f_csv:
                writer = csv.DictWriter(f_csv, fieldnames=final_headers)
                writer.writeheader()
                for row_data in parsed_rows:
                    csv_row = {
                        '标题': row_data.get('title', ''),
                        '长度': row_data.get('length', 0),
                        '访问号': row_data.get('accession', ''),
                        '物种': row_data.get('species', ''),
                        '属名': row_data.get('genus', ''),
                        '菌株': row_data.get('strain', ''),
                        '基因类型': row_data.get('gene_type', ''),
                        '序列类型': row_data.get('sequence_type', ''),
                        '宿主信息': row_data.get('host_info', ''),
                        '高得分片段对(HSPs)': row_data.get('hsps_count', 1),
                        'E值': f"{row_data.get('e_value', 0):.2e}" if isinstance(row_data.get('e_value'), (int, float)) else row_data.get('e_value'),
                        '比对长度': row_data.get('align_length', 0),
                        '相同碱基数': row_data.get('identities', 0),
                        '相似度': f"{row_data.get('identity_pct', 0):.2f}%" if isinstance(row_data.get('identity_pct'), (int, float)) else row_data.get('identity_pct'),
                        '缺口数': row_data.get('gaps', 0),
                        '查询起始-结束': f"{row_data.get('query_start')}-{row_data.get('query_end')}",
                        '命中起始-结束': f"{row_data.get('sbjct_start')}-{row_data.get('sbjct_end')}"
                    }
                    writer.writerow(csv_row)
            
            # 提取术语
            self._extract_and_save_terms(output_file)
        except Exception as e:
            print(f"保存 CSV 过程中出错: {e}")
            raise
    

    def _extract_and_save_terms(self, csv_file_path: str):
        """
        提取并保存术语到预定义术语文件
        
        Args:
            csv_file_path (str): CSV文件路径
        """
        try:
            from src.utils.translation.term_extractor import TermExtractor
            # 不传递translation_data_manager，避免多线程冲突
            term_extractor = TermExtractor()
            term_extractor.extract_blast_result_terms(csv_file_path)
        except Exception as e:
            print(f"提取术语时出错: {e}")
            import traceback
            traceback.print_exc()


def get_blast_result_converter() -> BlastResultConverter:
    """
    获取BLAST结果转换器实例
    
    Returns:
        BlastResultConverter: 结果转换器实例
    """
    return BlastResultConverter()