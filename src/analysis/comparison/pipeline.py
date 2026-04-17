
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional
from .engines.mummer import MummerEngine
from .processors.orientator import SequenceOrientator
from .manager import get_comparison_manager

class ComparisonPipeline:
    """
    基因组比较分析管线 (Orchestrator)
    职责：协调极性校正、比对执行、变异提取的全流程。
    """
    def __init__(self, workspace: Path):
        self.workspace = workspace
        self.workspace.mkdir(parents=True, exist_ok=True)
        (self.workspace / "reports").mkdir(parents=True, exist_ok=True)
        (self.workspace / "xml_raw").mkdir(parents=True, exist_ok=True)
        
        self.logger = logging.getLogger("Analysis.Comparison.Pipeline")
        
        # 初始化组件
        self.orientator = SequenceOrientator()
        self.mummer = MummerEngine()

    async def execute(self, ref_file: str, query_file: str, options: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        主执行入口
        """
        options = options or {}
        ref_path = Path(ref_file)
        query_path = Path(query_file)
        
        # 1. 验证输入
        if not ref_path.exists() or not query_path.exists():
            raise FileNotFoundError("Reference or Query file not found")

        # 2. 极性检测与自动校正 (业内痛点解决)
        fixed_query_path, is_flipped = await self.orientator.detect_and_fix(
            ref_path, query_path, self.workspace
        )
        
        # 3. 执行核心比对 (MUMmer)
        result = await self.mummer.run_alignment(
            ref_path, fixed_query_path, self.workspace
        )
        
        # 4. 补充元数据
        result["metadata"] = {
            "ref_name": ref_path.name,
            "query_name": query_path.name,
            "was_flipped": is_flipped
        }
        
        self.logger.info(f"分析管线执行成功: {ref_path.name} vs {query_path.name}")
        
        # 记录到历史数据库
        get_comparison_manager().record_task(options.get('task_id', 'unknown'), result['metadata'], result['summary'])
        
        return result
