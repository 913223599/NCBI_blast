# -*- coding: utf-8 -*-
"""
注释引擎抽象基类 (BaseAnnotationEngine)
"""
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple, Callable
from ..types import FeatureItem, AnnotationRunRequest


class BaseAnnotationEngine(ABC):
    """注释引擎通用基类"""

    def __init__(self, name: str):
        self.name = name

    @abstractmethod
    async def is_available(self) -> bool:
        """检查当前运行环境中该引擎是否就绪可用"""
        pass

    @abstractmethod
    async def run(
        self,
        input_fasta: Path,
        work_dir: Path,
        req: AnnotationRunRequest,
        threads: int,
        prefix: str,
        on_progress: Optional[Callable[[int, str, Optional[str]], None]] = None
    ) -> Tuple[List[FeatureItem], Dict[str, str]]:
        """
        执行引擎分析
        返回: (features, generated_files_dict)
        """
        pass
