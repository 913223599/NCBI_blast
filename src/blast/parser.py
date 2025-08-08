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
    
    def format_result_summary(self, blast_record, top_hits=5):
        """
        格式化结果摘要
        
        Args:
            blast_record: BLAST记录
            top_hits (int): 显示前几个匹配结果，默认为5
            
        Returns:
            list: 格式化的结果列表
        """
        summary = []
        for i, alignment in enumerate(blast_record.alignments[:top_hits]):
            hit_info = {
                'rank': i + 1,
                'title': alignment.title,
                'length': alignment.length,
                'hsps': []
            }
            
            for hsp in alignment.hsps[:1]:  # 只显示最好的HSP
                hsp_info = {
                    'e_value': hsp.expect,
                    'score': hsp.score,
                    'align_length': hsp.align_length,
                    'identity': hsp.identities / hsp.align_length * 100,
                    'gaps': hsp.gaps
                }
                hit_info['hsps'].append(hsp_info)
            
            summary.append(hit_info)
        
        return summary
    
    def display_result_summary(self, blast_record, top_hits=5):
        """
        显示结果摘要
        
        Args:
            blast_record: BLAST记录
            top_hits (int): 显示前几个匹配结果，默认为5
        """
        print(f"找到 {len(blast_record.alignments)} 个比对结果")
        if top_hits > 0:
            print(f"\n前{top_hits}个最佳比对:")
            print("=" * 80)
            
            for i, alignment in enumerate(blast_record.alignments[:top_hits]):
                print(f"匹配 {i+1}:")
                print(f"标题: {alignment.title}")
                print(f"长度: {alignment.length}")
                
                for hsp in alignment.hsps[:1]:  # 只显示最好的HSP
                    print(f"E值: {hsp.expect}")
                    print(f"得分: {hsp.score}")
                    print(f"比对长度: {hsp.align_length}")
                    print(f"相似度: {hsp.identities / hsp.align_length * 100:.2f}%")
                    print(f"缺口: {hsp.gaps}")
                
                print("=" * 80)