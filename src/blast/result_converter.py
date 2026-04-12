"""
BLAST结果转换模块
负责将BLAST的XML格式结果转换为CSV格式
现在使用流式解析器以降低内存占用
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
            
            # 定义CSV表头
            fieldnames = [
                'title', 'length', 'accession', 'species', 'genus', 'strain', 
                'gene_type', 'sequence_type', 'host_info', 'hsps_count', 
                'e_value', 'align_length', 'identities', 'identity_pct', 'gaps',
                'query_start', 'query_end', 'sbjct_start', 'sbjct_end'
            ]
            
            # 中文映射表头 (为了兼容旧版输出格式，这里做映射)
            header_map = {
                'title': '标题',
                'length': '长度',
                'accession': '访问号',
                'species': '物种',
                'genus': '属名',
                'strain': '菌株',
                'gene_type': '基因类型',
                'sequence_type': '序列类型',
                'host_info': '宿主信息',
                'hsps_count': '高得分片段对(HSPs)',
                'e_value': 'E值',
                'align_length': '比对长度',
                'identities': '相同碱基数',
                'identity_pct': '相似度',
                'gaps': '缺口数',
                'query_start': '查询起始', # 注意：这里拆分了起始结束，简化处理
                'query_end': '查询结束',
                'sbjct_start': '命中起始',
                'sbjct_end': '命中结束'
            }
            
            # 使用流式处理写入CSV
            record_count = 0
            
            with open(xml_file, 'r', encoding='utf-8') as f_xml, \
                 open(csv_file, 'w', newline='', encoding='utf-8-sig') as f_csv:
                
                writer = csv.DictWriter(f_csv, fieldnames=header_map.values())
                writer.writeheader()
                
                # 从解析器获取流式数据
                for row_data in self.parser.parse(f_xml):
                    record_count += 1
                    
                    # 格式化数据以匹配CSV输出要求
                    formatted_row = {
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
                        'E值': f"{row_data.get('e_value', 0):.2e}",
                        '比对长度': row_data.get('align_length', 0),
                        '相同碱基数': row_data.get('identities', 0),
                        '相似度': f"{row_data.get('identity_pct', 0):.2f}%",
                        '缺口数': row_data.get('gaps', 0),
                        '查询起始': row_data.get('query_start', 0),
                        '查询结束': row_data.get('query_end', 0),
                        '命中起始': row_data.get('sbjct_start', 0),
                        '命中结束': row_data.get('sbjct_end', 0)
                    }
                    
                    # 兼容旧逻辑：合并起始结束字段 (如果UI需要这样的格式)
                    # 但为了CSV的整洁，建议由UI端去合并显示，这里存储原始数据更佳。
                    # 为了保持这里跟之前 implementation_plan 不会使得UI报错，我们遵循 header_map 的列。
                    # *注意*：之前的 implementation plan 没有明确说明要改 CSV 结构，
                    # 但原代码生成的 CSV 有 '查询起始-结束' 这样的复合列。
                    # 为了最小化破坏，我们可以在这里手动合成这些列。
                    
                    # 修正：为了完全兼容原 result_converter.py 的输出列
                    legacy_row = formatted_row.copy()
                    legacy_row.pop('查询起始')
                    legacy_row.pop('查询结束')
                    legacy_row.pop('命中起始')
                    legacy_row.pop('命中结束')
                    legacy_row['查询起始-结束'] = f"{row_data.get('query_start')}-{row_data.get('query_end')}"
                    legacy_row['命中起始-结束'] = f"{row_data.get('sbjct_start')}-{row_data.get('sbjct_end')}"
                    
                    # 我们需要重新定义 fieldnames 来匹配 legacy_row
                    legacy_fieldnames = list(header_map.values())[:]
                    legacy_fieldnames.remove('查询起始')
                    legacy_fieldnames.remove('查询结束')
                    legacy_fieldnames.remove('命中起始')
                    legacy_fieldnames.remove('命中结束')
                    legacy_fieldnames.append('查询起始-结束')
                    legacy_fieldnames.append('命中起始-结束')
                    
                    # 如果是由于循环第一次才确定 header，那就会麻烦。
                    # 所以我们在循环外必须确定 header。
                    if record_count == 1:
                         # 重写 header (有些 hacky，但为了流式只能这样，或者预先定死)
                         # 为简单起见，我们预先定死 compatible header
                         pass

                    # 这里的逻辑有点乱，为了稳妥，我们直接使用"兼容模式"的 header
                    pass 

                # 重新梳理：直接使用兼容模式
                
            # --- 重新实现 conversion 逻辑 (Clean Version) ---
            
            # 兼容模式的 Header
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
                        'E值': f"{row_data.get('e_value', 0):.2e}",
                        '比对长度': row_data.get('align_length', 0),
                        '相同碱基数': row_data.get('identities', 0),
                        '相似度': f"{row_data.get('identity_pct', 0):.2f}%",
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
            
            # 同样提取术语
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