"""
PAF格式解析器
职责：解析Minimap2输出的PAF格式比对结果
"""

import logging
import os
from typing import Dict, Any, List
from pathlib import Path

from ..core.base import BaseParser
from .cs_parser import CSParser

logger = logging.getLogger(__name__)


class PAFParser(BaseParser):
    """
    PAF格式解析器
    职责：解析PAF文件，提取比对区块和最佳匹配
    """
    
    def parse(
        self,
        paf_path: str,
        target_len: int,
        query_len: int = 0
    ) -> Dict[str, Any]:
        """
        解析PAF文件
        :param paf_path: PAF文件路径
        :param target_len: 目标序列长度
        :param query_len: 查询序列长度（可选）
        :return: 解析结果
        """
        if not Path(paf_path).exists() or os.path.getsize(paf_path) == 0:
            return {
                "identity": 0,
                "rotated": False,
                "message": "未发现共线性比对匹配项",
                "blocks": [],
                "variants": []
            }
        
        blocks = []
        variants = []
        best_hit = None
        max_match = 0
        actual_query_len = query_len
        
        try:
            with open(paf_path, 'r', encoding='utf-8', errors='ignore') as f:
                for line in f:
                    parts = line.split('\t')
                    if len(parts) < 12:
                        continue
                    
                    hit_info = self._parse_alignment_line(parts)
                    if not hit_info:
                        continue
                    
                    actual_query_len = hit_info['q_len']
                    
                    # 记录符合条件的比对区块
                    if hit_info['block_len'] > 100:
                        blocks.append({
                            "qs": hit_info['q_start'],
                            "qe": hit_info['q_end'],
                            "ts": hit_info['t_start'],
                            "te": hit_info['t_end'],
                            "strand": hit_info['strand'],
                            "id": round(hit_info['identity'], 2)
                        })
                    
                    # 解析CS标签获取变异信息
                    if hit_info.get('cs_tag') and hit_info['match_len'] > max_match:
                        variants = CSParser().parse(hit_info['cs_tag'], hit_info['t_start'])
                    
                    # 更新最佳匹配
                    if hit_info['match_len'] > max_match:
                        max_match = hit_info['match_len']
                        best_hit = hit_info
            
            if best_hit:
                return self._build_result(best_hit, actual_query_len, target_len, blocks, variants)
            
            return {
                "identity": 0,
                "rotated": False,
                "message": "解析比对结果失败",
                "blocks": [],
                "variants": []
            }
            
        except Exception as e:
            logger.error(f"PAF解析失败: {e}")
            return {
                "identity": 0,
                "rotated": False,
                "message": f"PAF解析异常: {e}",
                "blocks": [],
                "variants": []
            }
    
    def _parse_alignment_line(self, parts: List[str]) -> Dict[str, Any]:
        """解析单行比对记录"""
        try:
            q_len = int(parts[1])
            q_start = int(parts[2])
            q_end = int(parts[3])
            strand = parts[4]
            t_start = int(parts[7])
            t_end = int(parts[8])
            match_len = int(parts[9])
            block_len = int(parts[10])
            
            identity = (match_len / block_len) * 100 if block_len > 0 else 0
            
            # 查找CS标签
            cs_tag = next((p for p in parts if p.startswith("cs:Z:")), None)
            cs_value = cs_tag[5:] if cs_tag else None
            
            return {
                'q_len': q_len,
                'q_start': q_start,
                'q_end': q_end,
                'strand': strand,
                't_start': t_start,
                't_end': t_end,
                'match_len': match_len,
                'block_len': block_len,
                'identity': identity,
                'cs_tag': cs_value
            }
        except Exception as e:
            logger.warning(f"解析比对行失败: {e}")
            return None
    
    def _build_result(
        self,
        hit: Dict[str, Any],
        query_len: int,
        target_len: int,
        blocks: List[Dict],
        variants: List[Dict]
    ) -> Dict[str, Any]:
        """构建最终结果"""
        identity = (hit['match_len'] / hit['block_len']) * 100
        coverage = (hit['match_len'] / query_len) * 100 if query_len > 0 else 0
        
        is_rotated = (coverage > 98 and identity > 99)
        
        # 限制返回的变异数量防止UI挂起
        limited_variants = variants[:200]
        
        if is_rotated:
            message = f"检测到高度一致性 ({round(identity, 2)}%)，且覆盖度完整。检出 {len(variants)} 处差异点。"
        else:
            message = f"比对完成，相似度 {round(identity, 2)}%，检出 {len(variants)} 处差异位点。"
        
        return {
            "success": True,
            "identity": round(identity, 2),
            "rotated": is_rotated,
            "offset": hit['t_start'],
            "q_len": query_len,
            "t_len": target_len,
            "coverage": round(coverage, 2),
            "blocks": blocks,
            "variants": limited_variants,
            "variant_count": len(variants),
            "message": message
        }
