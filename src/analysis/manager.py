
import os
import logging
from typing import List, Dict, Any
from .sequence_utils import RotationChecker

logger = logging.getLogger("analysis.manager")

class AnalysisManager:
    """
    组装分析高度自动化管理器
    职责：负责不同比对策略的调度与任务编排
    """
    
    @staticmethod
    def run_pairwise_mode(target_path: str, query_path: str, task_dir: str) -> Dict[str, Any]:
        """模式1：经典两两比对"""
        return RotationChecker.check_rotation(target_path, query_path, task_dir)

    @staticmethod
    def run_reference_mode(ref_path: str, other_paths: List[str], base_dir: str) -> List[Dict[str, Any]]:
        """模式2：参考基因组模式 (1 vs N)"""
        results = []
        for i, query in enumerate(other_paths):
            if ref_path == query: continue
            
            task_id = f"REF_Q{i+1}"
            task_dir = os.path.join(base_dir, task_id)
            res = RotationChecker.check_rotation(ref_path, query, task_dir)
            res["query_name"] = os.path.basename(query)
            res["target_name"] = os.path.basename(ref_path)
            results.append(res)
        return results

    @staticmethod
    def run_cross_mode(paths: List[str], base_dir: str) -> List[Dict[str, Any]]:
        """模式3：全交叉矩阵模式 (N vs N)"""
        results = []
        for i in range(len(paths)):
            for j in range(i + 1, len(paths)):
                p1, p2 = paths[i], paths[j]
                task_id = f"CROSS_{i}_{j}"
                task_dir = os.path.join(base_dir, task_id)
                res = RotationChecker.check_rotation(p1, p2, task_dir)
                res["query_name"] = os.path.basename(p2)
                res["target_name"] = os.path.basename(p1)
                results.append(res)
        return results
