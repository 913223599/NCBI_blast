# -*- coding: utf-8 -*-
"""
Prodigal 极速 CDS 预测引擎 (ProdigalEngine)
利用非监督机器学习与核糖体结合位点识别算法进行高精度原核/病毒 CDS 定位
"""
import os
import shutil
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple, Callable
from Bio import SeqIO

from .base import BaseAnnotationEngine
from ..types import FeatureItem, AnnotationRunRequest
from ..builtin_annotator import BuiltinAnnotator

logger = logging.getLogger("analysis.annotation.engines.prodigal")


class ProdigalEngine(BaseAnnotationEngine):
    """Prodigal CDS 预测引擎"""

    def __init__(self):
        super().__init__(name="Prodigal")

    async def is_available(self) -> bool:
        from ....assembly.engine.runner import CommandRunner
        runner = CommandRunner(step_name="ProdigalCheck", logger=logger, is_wsl=True)
        return (await runner.run_command(["which", "prodigal"], silence_errors=True)) == 0

    async def run(
        self,
        input_fasta: Path,
        work_dir: Path,
        req: AnnotationRunRequest,
        threads: int,
        prefix: str,
        on_progress: Optional[Callable[[int, str, Optional[str]], None]] = None
    ) -> Tuple[List[FeatureItem], Dict[str, str]]:
        from ....assembly.env.wsl_manager import WSLManager
        from ....assembly.engine.runner import CommandRunner

        runner = CommandRunner(step_name="Prodigal", logger=logger, is_wsl=True)
        out_gff = work_dir / f"{prefix}_prodigal.gff"
        out_faa = work_dir / f"{prefix}.faa"
        out_ffn = work_dir / f"{prefix}.ffn"

        wsl_fasta = WSLManager.to_wsl_path(str(input_fasta))
        wsl_gff = WSLManager.to_wsl_path(str(out_gff))
        wsl_faa = WSLManager.to_wsl_path(str(out_faa))
        wsl_ffn = WSLManager.to_wsl_path(str(out_ffn))

        mode = "meta" if req.sample_type.upper() in ["VIRUS", "PHAGE"] else "single"
        cmd = [
            "prodigal",
            "-i", wsl_fasta,
            "-o", wsl_gff,
            "-f", "gff",
            "-a", wsl_faa,
            "-d", wsl_ffn,
            "-g", str(req.genetic_code),
            "-p", mode
        ]

        if on_progress:
            on_progress(20, f"Prodigal 正在运行基因位点预测 (模式: {mode})...", " ".join(cmd))

        ret = await runner.run_command(cmd, cwd=work_dir)
        if ret != 0 or not out_gff.exists():
            raise RuntimeError(f"Prodigal 执行返回异常退出码: {ret}")

        # 解析 Prodigal FAA 与 GFF
        faa_map: Dict[str, str] = {}
        if out_faa.exists():
            with open(out_faa, "r", encoding="utf-8", errors="ignore") as f:
                for rec in SeqIO.parse(f, "fasta"):
                    faa_map[rec.id] = str(rec.seq)

        features: List[FeatureItem] = []
        idx = 1
        with open(out_gff, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                if line.startswith("#") or not line.strip():
                    continue
                parts = line.strip().split("\t")
                if len(parts) < 9:
                    continue
                seq_id, source, ftype, start_s, end_s, score_s, strand, phase, attr_str = parts[:9]
                if ftype != "CDS":
                    continue

                start = int(start_s)
                end = int(end_s)
                length_bp = end - start + 1
                locus_tag = f"{prefix}_{idx:05d}"
                idx += 1

                # 匹配蛋白序列
                trans = ""
                for k, v in faa_map.items():
                    if f"_{idx-1}" in k or f"ID={idx-1}" in attr_str:
                        trans = v
                        break
                if not trans and f"{seq_id}_{idx-1}" in faa_map:
                    trans = faa_map[f"{seq_id}_{idx-1}"]

                mw = BuiltinAnnotator.calculate_molecular_weight(trans) if trans else 0.0

                features.append(FeatureItem(
                    id=locus_tag,
                    locus_tag=locus_tag,
                    contig_id=seq_id,
                    feature_type="CDS",
                    start=start,
                    end=end,
                    strand=strand,
                    length_bp=length_bp,
                    product="hypothetical protein",
                    protein_id=locus_tag,
                    protein_length_aa=len(trans) if trans else 0,
                    molecular_weight_kda=mw,
                    translation=trans if trans else None,
                    source_engine="Prodigal",
                    evidence_sources=["[Prodigal] Machine Learning CDS Model"]
                ))

        files = {
            "gff": str(out_gff.resolve()),
            "faa": str(out_faa.resolve()) if out_faa.exists() else "",
            "ffn": str(out_ffn.resolve()) if out_ffn.exists() else ""
        }
        return features, files
