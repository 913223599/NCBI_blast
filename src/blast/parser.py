"""
BLAST结果解析器模块
负责解析BLAST搜索结果
"""

from Bio.Blast import NCBIXML


class BlastResultParser:
    """
    BLAST结果解析器类
    负责解析和格式化BLAST搜索结果
    """
    
    def __init__(self):
        """
        初始化结果解析器
        """
        pass
    
    def parse_result(self, result_handle):
        """
        解析BLAST结果
        
        Args:
            result_handle: BLAST搜索结果句柄
            
        Returns:
            blast_record: 解析后的BLAST记录
        """
        try:
            blast_records = NCBIXML.parse(result_handle)
            blast_record = next(blast_records)
            return blast_record
        except Exception as e:
            print(f"解析BLAST结果时出错: {e}")
            raise e