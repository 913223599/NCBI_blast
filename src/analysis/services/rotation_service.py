"""
旋转检测服务
职责：协调序列处理器、比对引擎和解析器，执行完整的旋转检测流程
"""

import logging
import os
from typing import Dict, Any, List
from pathlib import Path

from ..core.base import BaseService
from ..core.sequence import SequenceProcessor
from ..engines.minimap2_engine import Minimap2Engine
from ..parsers.paf_parser import PAFParser

logger = logging.getLogger(__name__)


class RotationService(BaseService):
    """
    旋转检测服务
    职责：编排序列倍增、Minimap2比对、PAF解析的完整流程
    """
    
    def __init__(self):
        self.engine = Minimap2Engine(preset="asm5", enable_cs=True)
        self.parser = PAFParser()
    
    def execute(
        self,
        seq1_path: str,
        seq2_path: str,
        output_dir: str
    ) -> Dict[str, Any]:
        """
        执行旋转检测
        :param seq1_path: 序列1路径
        :param seq2_path: 序列2路径
        :param output_dir: 输出目录
        :return: 检测结果
        """
        try:
            # 1. 准备输出目录
            Path(output_dir).mkdir(parents=True, exist_ok=True)
            
            # 2. 序列倍增
            doubled_fasta = os.path.join(output_dir, "seq1_doubled.fasta")
            target_len = SequenceProcessor.prepare_doubled_fasta(seq1_path, doubled_fasta)
            
            # 3. 执行比对
            paf_out = os.path.join(output_dir, "alignment.paf")
            align_result = self.engine.execute(
                target_path=doubled_fasta,
                query_path=seq2_path,
                output_path=paf_out
            )
            
            if not align_result['success']:
                return {
                    "success": False,
                    "error": align_result.get('error', '比对失败')
                }
            
            # 4. 解析结果
            result = self.parser.parse(paf_out, target_len)
            result['success'] = True
            
            return result
            
        except Exception as e:
            logger.error(f"旋转检测失败: {e}")
            return {
                "success": False,
                "error": f"旋转检测异常: {e}"
            }


class AnalysisManager:
    """
    组装分析管理器
    职责：提供多种比对模式的高级封装
    """
    
    @staticmethod
    def run_pairwise_mode(target_path: str, query_path: str, task_dir: str) -> Dict[str, Any]:
        """
        模式1：经典两两比对
        :param target_path: 目标序列路径
        :param query_path: 查询序列路径
        :param task_dir: 任务输出目录
        :return: 检测结果
        """
        service = RotationService()
        return service.execute(target_path, query_path, task_dir)
    
    @staticmethod
    def run_reference_mode(
        ref_path: str,
        other_paths: List[str],
        base_dir: str
    ) -> List[Dict[str, Any]]:
        """
        模式2：参考基因组模式 (1 vs N)
        :param ref_path: 参考序列路径
        :param other_paths: 其他序列路径列表
        :param base_dir: 基础输出目录
        :return: 检测结果列表
        """
        service = RotationService()
        results = []
        
        for i, query in enumerate(other_paths):
            if ref_path == query:
                continue
            
            task_id = f"REF_Q{i+1}"
            task_dir = os.path.join(base_dir, task_id)
            
            res = service.execute(ref_path, query, task_dir)
            res["query_name"] = os.path.basename(query)
            res["target_name"] = os.path.basename(ref_path)
            results.append(res)
        
        return results
    
    @staticmethod
    def run_cross_mode(paths: List[str], base_dir: str) -> List[Dict[str, Any]]:
        """
        模式3：全交叉矩阵模式 (N vs N)
        :param paths: 序列路径列表
        :param base_dir: 基础输出目录
        :return: 检测结果列表
        """
        service = RotationService()
        results = []
        
        for i in range(len(paths)):
            for j in range(i + 1, len(paths)):
                p1, p2 = paths[i], paths[j]
                task_id = f"CROSS_{i}_{j}"
                task_dir = os.path.join(base_dir, task_id)
                
                res = service.execute(p1, p2, task_dir)
                res["query_name"] = os.path.basename(p2)
                res["target_name"] = os.path.basename(p1)
                results.append(res)
        
        return results
