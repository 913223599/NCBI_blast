"""
进化树分析服务
职责：封装NCBI tree-tool工具，提供MDS分析能力

注：ncbi_tree_tool.py 是独立的进化树程序逻辑，保持原样不修改
"""

import logging
from typing import Dict, Any, Optional

from ..core.base import BaseService
from ..ncbi_tree_tool import NcbiTreeToolWrapper

logger = logging.getLogger(__name__)


class TreeService(BaseService):
    """
    进化树服务
    职责：封装MDS分析、距离矩阵处理等进化树相关功能
    """
    
    def __init__(self, tools_dir: Optional[str] = None):
        """
        初始化服务
        :param tools_dir: NCBI tree-tool工具目录
        """
        self.wrapper = NcbiTreeToolWrapper(tools_dir)
    
    def is_available(self) -> bool:
        """检查tree-tool是否可用"""
        return self.wrapper.is_available()
    
    def execute_mds(
        self,
        distance_matrix,
        names,
        **kwargs
    ) -> Dict[str, Any]:
        """
        执行MDS分析
        :param distance_matrix: 距离矩阵（numpy array或list of lists）
        :param names: 序列名称列表
        :return: MDS结果
        """
        try:
            if not self.is_available():
                return {
                    "success": False,
                    "error": "NCBI tree-tool不可用，请先编译tree-tool"
                }
            
            df = self.wrapper.run_mds(distance_matrix, names)
            
            return {
                "success": True,
                "data": df.to_dict('records'),
                "message": "MDS分析完成"
            }
            
        except Exception as e:
            logger.error(f"MDS分析失败: {e}")
            return {
                "success": False,
                "error": f"MDS分析异常: {e}"
            }
    
    def execute(
        self,
        analysis_type: str = "mds",
        **kwargs
    ) -> Dict[str, Any]:
        """
        执行树分析
        :param analysis_type: 分析类型（mds, tree等）
        :param kwargs: 分析参数
        :return: 分析结果
        """
        if analysis_type == "mds":
            return self.execute_mds(**kwargs)
        else:
            return {
                "success": False,
                "error": f"不支持的分析类型: {analysis_type}"
            }
