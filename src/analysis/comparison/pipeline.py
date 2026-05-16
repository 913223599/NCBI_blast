"""
基因组比较分析管线 (Orchestrator)
职责：协调极性校正、引擎选择、比对执行、变异提取的全流程。
支持 MUMmer 和 Minimap2 引擎的动态路由。
"""

import logging
from pathlib import Path
from typing import Dict, Any

from .engines.mummer import MummerEngine
from .processors.orientator import SequenceOrientator
from .manager import get_comparison_manager
from src.analysis.engines.engine_base import AlignmentResult


class ComparisonPipeline:
    """
    基因组比较分析管线
    职责：协调极性校正、比对执行、变异提取的全流程。
    """

    def __init__(self, workspace: Path):
        self.workspace = workspace
        self.workspace.mkdir(parents=True, exist_ok=True)
        (self.workspace / "reports").mkdir(parents=True, exist_ok=True)

        self.logger = logging.getLogger("Analysis.Comparison.Pipeline")
        self.orientator = SequenceOrientator()

    async def execute(
        self, ref_file: str, query_file: str, options: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        """
        主执行入口
        :param ref_file: 参考序列文件路径
        :param query_file: 待测序列文件路径
        :param options: 配置选项（engine, autoOrientation, task_id 等）
        :return: 标准化比对结果字典
        """
        options = options or {}
        ref_path = Path(ref_file)
        query_path = Path(query_file)

        # 1. 验证输入
        if not ref_path.exists() or not query_path.exists():
            raise FileNotFoundError("Reference or Query file not found")

        # 2. 极性检测与自动校正（可通过选项关闭）
        is_flipped = False
        fixed_query_path = query_path
        if options.get("autoOrientation", True):
            fixed_query_path, is_flipped = await self.orientator.detect_and_fix(
                ref_path, query_path, self.workspace
            )

        # 3. 选择比对引擎
        engine_name = options.get("engine", "mummer")
        engine = self._create_engine(engine_name)

        # 4. 执行核心比对
        result: AlignmentResult = await engine.run_alignment(
            ref_path, fixed_query_path, self.workspace, options
        )

        # 5. 补充元数据
        result.metadata = {
            "ref_name": ref_path.name,
            "query_name": query_path.name,
            "was_flipped": is_flipped,
            "engine": engine_name
        }

        self.logger.info(f"分析管线执行成功: {ref_path.name} vs {query_path.name}")

        # 6. 持久化到历史数据库
        task_id = options.get("task_id", "unknown")
        get_comparison_manager().record_task(
            task_id=task_id,
            metadata=result.metadata,
            summary=result.summary,
            variant_count=len(result.variants)
        )

        return result.to_dict()

    def _create_engine(self, engine_name: str):
        """
        引擎工厂：根据名称创建比对引擎实例
        """
        if engine_name == "mummer":
            return MummerEngine()
        else:
            # 未来扩展点：添加 Minimap2Engine 等
            self.logger.warning(f"未知引擎 '{engine_name}'，降级使用 MUMmer")
            return MummerEngine()
