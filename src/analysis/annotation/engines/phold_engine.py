# -*- coding: utf-8 -*-
"""
Phold AI 蛋白质三维结构感知与折叠增强引擎 (PholdEngine)
结合 ESMFold 深度学习空间折叠与 Foldseek 结构域比对，专司破解未知与假定蛋白 (hypothetical protein)
"""
import os
import gc
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple, Callable
from Bio import SeqIO

from .base import BaseAnnotationEngine
from ..types import FeatureItem, AnnotationRunRequest
from ..fuser import AnnotationFuser
from ..builtin_annotator import BuiltinAnnotator

logger = logging.getLogger("analysis.annotation.engines.phold")


class PholdEngine(BaseAnnotationEngine):
    """Phold 3D 结构深度增强引擎"""

    def __init__(self):
        super().__init__(name="Phold AI")

    async def is_available(self) -> bool:
        from ....assembly.engine.runner import CommandRunner
        runner = CommandRunner(step_name="PholdCheck", logger=logger, is_wsl=True)
        return (await runner.run_command(["which", "phold"], silence_errors=True)) == 0

    def _cleanup_gpu_memory(self):
        """显存红线保护与垃圾回收"""
        try:
            import importlib
            torch = importlib.import_module("torch")
            if hasattr(torch, "cuda") and torch.cuda.is_available():
                torch.cuda.empty_cache()
                torch.cuda.ipc_collect()
        except Exception:
            pass
        gc.collect()

    async def run(
        self,
        input_fasta: Path,
        work_dir: Path,
        req: AnnotationRunRequest,
        threads: int,
        prefix: str,
        on_progress: Optional[Callable[[int, str, Optional[str]], None]] = None
    ) -> Tuple[List[FeatureItem], Dict[str, str]]:
        """基础运行接口"""
        return [], {}

    async def complement_from_gbk(
        self,
        features: List[FeatureItem],
        input_gbk: Path,
        work_dir: Path,
        threads: int,
        on_progress: Optional[Callable[[int, str, Optional[str]], None]] = None
    ) -> int:
        """
        以中间 GenBank 为输入调度 Phold 进行 3D 结构折叠与 Foldseek 补漏
        返回成功识别补全的未知蛋白数量
        """
        if not input_gbk.exists() or input_gbk.stat().st_size == 0:
            return 0

        unannotated_count = sum(1 for f in features if f.feature_type == "CDS" and AnnotationFuser.is_unannotated(f.product))
        if unannotated_count == 0:
            logger.info("所有蛋白均已有确切功能，跳过 Phold 3D 补漏")
            return 0

        from ....assembly.engine.runner import CommandRunner
        from ....assembly.env.wsl_manager import WSLManager

        runner = CommandRunner(step_name="Phold", logger=logger, is_wsl=True)
        out_dir = work_dir / "phold_out"
        out_dir.mkdir(parents=True, exist_ok=True)

        if on_progress:
            on_progress(70, f"正在调度 Phold AI 蛋白质三维结构折叠与空间感知增强 (针对 {unannotated_count} 个假定蛋白)...", None)

        # 构建安全路径
        await runner.run_command(["bash", "-c", "ln -sfT '/mnt/f/NCBI blast' /tmp/ncbi_blast_tmp"], silence_errors=True)
        
        # 将路径转换为 WSL 路径
        wsl_gbk = WSLManager.to_wsl_path(str(input_gbk))
        wsl_out = WSLManager.to_wsl_path(str(out_dir))

        cmd = [
            "bash", "-c",
            f"export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 && phold run -i \"{wsl_gbk}\" -o \"{wsl_out}\" -d /opt/phold_db -t {threads} -f"
        ]

        current_phold_pct = 5
        def on_phold_output(line: str):
            nonlocal current_phold_pct
            if not on_progress or not line:
                return
            clean_l = line.strip()
            if "createdb" in clean_l or "Foldseek createdb" in clean_l:
                current_phold_pct = max(current_phold_pct, 25)
                on_progress(current_phold_pct, "Phold AI [1/4]: 正在构建蛋白质空间特征数据库 (Foldseek)...", clean_l)
            elif "easy-search" in clean_l or "structure match" in clean_l or "searching" in clean_l.lower():
                current_phold_pct = max(current_phold_pct, 50)
                on_progress(current_phold_pct, "Phold AI [2/4]: 正在执行 Foldseek 三维构象空间比对...", clean_l)
            elif "predict" in clean_l or "ESM" in clean_l or "prostt5" in clean_l or "embedding" in clean_l.lower():
                current_phold_pct = max(current_phold_pct, 75)
                on_progress(current_phold_pct, "Phold AI [3/4]: 正在执行深度学习 3D 结构折叠空间感知...", clean_l)
            elif "topfunction" in clean_l or "merge" in clean_l or "filter" in clean_l.lower():
                current_phold_pct = max(current_phold_pct, 95)
                on_progress(current_phold_pct, "Phold AI [4/4]: 正在筛选最优结构预测并生成增强模型...", clean_l)
            else:
                on_progress(current_phold_pct, f"Phold AI 正在运行: {clean_l[:55]}...", clean_l)

        ret = await runner.run_command(cmd, cwd=work_dir, on_output=on_phold_output)
        
        # 强制显存垃圾清理
        self._cleanup_gpu_memory()

        phold_gbk = out_dir / "phold.gbk"
        if ret != 0 or not phold_gbk.exists() or phold_gbk.stat().st_size == 0:
            logger.warning("Phold 执行未能产出 phold.gbk，保留已有注释")
            return 0

        # 解析 Phold 增强产物
        phold_candidates: List[FeatureItem] = []
        with open(phold_gbk, "r", encoding="utf-8", errors="ignore") as f:
            for rec in SeqIO.parse(f, "genbank"):
                for feat in rec.features:
                    if feat.type in ["source", "gene"]:
                        continue
                    q = feat.qualifiers
                    lt = q.get("locus_tag", [""])[0]
                    prod = q.get("product", ["hypothetical protein"])[0]
                    trans = q.get("translation", [""])[0]
                    gene_name = q.get("gene", [None])[0]
                    phold_func = q.get("function", q.get("phold_annotation", q.get("note", [None])))[0]

                    f_start = int(feat.location.start) + 1
                    f_end = int(feat.location.end)
                    f_strand = "+" if feat.location.strand >= 0 else "-"

                    item = FeatureItem(
                        id=lt,
                        locus_tag=lt,
                        contig_id=rec.id,
                        feature_type=feat.type,
                        start=f_start,
                        end=f_end,
                        strand=f_strand,
                        length_bp=f_end - f_start + 1,
                        gene_name=gene_name,
                        product=prod,
                        translation=trans if trans else None,
                        notes=f"Phold Structure: {phold_func}" if phold_func else None
                    )
                    phold_candidates.append(item)

        # 流式互补
        features, updated_count = AnnotationFuser.merge_by_coordinates(
            base_features=features,
            incoming_features=phold_candidates,
            engine_name="Phold AI",
            overlap_threshold=0.8
        )

        if on_progress:
            on_progress(82, f"Phold AI 结构感知成功额外识别出 {updated_count} 个结构功能蛋白 (剩余 {unannotated_count - updated_count} 个未知)...", None)

        return updated_count
