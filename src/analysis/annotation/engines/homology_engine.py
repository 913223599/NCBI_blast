# -*- coding: utf-8 -*-
"""
权威同源数据库多核打捞引擎 (HomologyEngine)
利用 PhageScope 105万权威参考蛋白库 (RefSeq, GenBank, PhagesDB) 执行 BLASTP 深度同源推断与功能赋予
"""
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple, Callable

from .base import BaseAnnotationEngine
from ..types import FeatureItem, AnnotationRunRequest
from ..functional_assigner import FunctionalAssigner
from ..fuser import AnnotationFuser

logger = logging.getLogger("analysis.annotation.engines.homology")


class HomologyEngine(BaseAnnotationEngine):
    """PhageScope 权威同源打捞引擎"""

    def __init__(self):
        super().__init__(name="PhageScope Homology")

    async def is_available(self) -> bool:
        assigner = FunctionalAssigner()
        return assigner.phagescope_dir.exists()

    async def run(
        self,
        input_fasta: Path,
        work_dir: Path,
        req: AnnotationRunRequest,
        threads: int,
        prefix: str,
        on_progress: Optional[Callable[[int, str, Optional[str]], None]] = None
    ) -> Tuple[List[FeatureItem], Dict[str, str]]:
        """同源引擎主要作为互补阶段调用，但亦可实现通用接口"""
        return [], {}

    def complement_features(
        self,
        features: List[FeatureItem],
        query_faa: Path,
        work_dir: Path,
        threads: int,
        on_progress: Optional[Callable[[int, str, Optional[str]], None]] = None
    ) -> int:
        """
        对已有的 features 进行针对性同源打捞与属性补全
        返回补全更新的基因数量
        """
        if not query_faa.exists() or query_faa.stat().st_size == 0:
            return 0

        # 筛选需要打捞的特征（优先打捞未注释的，或者全量增强）
        unannotated_count = sum(1 for f in features if f.feature_type == "CDS" and AnnotationFuser.is_unannotated(f.product))
        if unannotated_count == 0:
            logger.info("所有 CDS 均已具有明确生物学功能，跳过基础同源打捞")
            return 0

        if on_progress:
            on_progress(10, f"正在比对权威同源数据库 (PhageScope 105万参考蛋白库，待打捞 {unannotated_count} 个基因)...", None)

        assigner = FunctionalAssigner()
        hits_map = assigner.run_blastp_annotation(
            query_faa=query_faa,
            work_dir=work_dir,
            threads=threads,
            on_progress=on_progress
        )

        if not hits_map:
            return 0

        updated_count = 0
        for feat in features:
            if feat.feature_type != "CDS":
                continue

            hit = hits_map.get(feat.id) or hits_map.get(feat.locus_tag) or hits_map.get(feat.protein_id)
            if not hit:
                continue

            source_name = hit.get("source_db") or "PhageScope"
            method_desc = "RPS-BLAST" if "CDD" in source_name or "Pfam" in source_name else "BLASTP"
            cand_data = {
                "product": hit.get("product"),
                "gene_name": hit.get("gene_name"),
                "evidence": f"{method_desc} to {hit.get('target_id', 'Reference')} (Identity: {hit.get('identity', 100)}%, E-value: {hit.get('evalue', '1e-5')})"
            }

            if AnnotationFuser.complement_single_feature(feat, cand_data, engine_name=source_name):
                updated_count += 1

        if on_progress:
            on_progress(100, f"权威同源库成功赋予并更新 {updated_count} 个基因的生物学功能 (剩余 {unannotated_count - updated_count} 个待补充)...", None)

        return updated_count
