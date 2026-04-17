"""
CS标签解析器
职责：解析Minimap2的CS标签，提取SNP/Indel变异信息
"""

import logging
import re
from typing import List, Dict, Any

from ..core.base import BaseParser

logger = logging.getLogger(__name__)


class CSParser(BaseParser):
    """
    CS标签解析器
    职责：解析Minimap2输出的cs:Z:标签，提取碱基级别的变异信息
    """
    
    # 转换类型定义
    TRANSITIONS = {('A', 'G'), ('G', 'A'), ('C', 'T'), ('T', 'C')}
    
    # CS标签正则
    CS_PATTERN = re.compile(r'(:[0-9]+|\*[a-z][a-z]|\+[a-z]+|-[a-z]+)')
    
    def parse(self, cs_string: str, start_pos: int) -> List[Dict[str, Any]]:
        """
        解析CS标签
        :param cs_string: CS标签字符串（不含前缀cs:Z:）
        :param start_pos: 起始参考位置
        :return: 变异位点列表
        """
        variants = []
        curr_ref_pos = start_pos
        
        try:
            tokens = self.CS_PATTERN.findall(cs_string)
            
            for token in tokens:
                op = token[0]
                
                if op == ':':
                    # 匹配区域
                    length = int(token[1:])
                    curr_ref_pos += length
                    
                elif op == '*':
                    # SNP
                    ref = token[1].upper()
                    alt = token[2].upper()
                    is_transition = (ref, alt) in self.TRANSITIONS
                    
                    variants.append({
                        "pos": curr_ref_pos,
                        "type": "SNP",
                        "ref": ref,
                        "alt": alt,
                        "assessment": "Transition" if is_transition else "Transversion",
                        "len": 1
                    })
                    curr_ref_pos += 1
                    
                elif op == '+':
                    # 插入
                    seq = token[1:].upper()
                    variants.append({
                        "pos": curr_ref_pos,
                        "type": "INS",
                        "ref": "-",
                        "alt": seq,
                        "assessment": f"Insertion ({len(seq)}bp)",
                        "len": len(seq)
                    })
                    
                elif op == '-':
                    # 缺失
                    seq = token[1:].upper()
                    variants.append({
                        "pos": curr_ref_pos,
                        "type": "DEL",
                        "ref": seq,
                        "alt": "-",
                        "assessment": f"Deletion ({len(seq)}bp)",
                        "len": len(seq)
                    })
                    curr_ref_pos += len(seq)
            
            return variants
            
        except Exception as e:
            logger.error(f"CS标签解析失败: {e}")
            return []
