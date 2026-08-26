# -*- coding: utf-8 -*-
"""
纯 Python 高精度多核内置注释引擎 (BuiltinEngine)
提供 100% 宿主跨平台兼容、零外部环境依赖的基准 ORF/RNA 模型构建
"""
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple, Callable

from .base import BaseAnnotationEngine
from ..types import FeatureItem, AnnotationRunRequest
from ..builtin_annotator import BuiltinAnnotator

logger = logging.getLogger("analysis.annotation.engines.builtin")


class BuiltinEngine(BaseAnnotationEngine):
    """内置高性能特征预测引擎"""

    def __init__(self):
        super().__init__(name="Builtin")

    async def is_available(self) -> bool:
        return True

    async def run(
        self,
        input_fasta: Path,
        work_dir: Path,
        req: AnnotationRunRequest,
        threads: int,
        prefix: str,
        on_progress: Optional[Callable[[int, str, Optional[str]], None]] = None
    ) -> Tuple[List[FeatureItem], Dict[str, str]]:
        annotator = BuiltinAnnotator(
            genetic_code=req.genetic_code,
            min_orf_len_bp=req.min_contig_len,
            prefix=prefix
        )

        def prog_callback(pct: int, msg: str):
            if on_progress:
                on_progress(pct, f"[内置高精度引擎] {msg}", None)

        summary, features, files = annotator.annotate_fasta(
            fasta_file_path=input_fasta,
            output_dir=work_dir,
            on_progress=prog_callback
        )

        for feat in features:
            if not feat.source_engine:
                feat.source_engine = "Builtin"

        return features, files
