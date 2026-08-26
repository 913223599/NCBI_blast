# -*- coding: utf-8 -*-
"""
Prokka 标准全特征注释引擎 (ProkkaEngine)
"""
import os
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple, Callable
from Bio import SeqIO

from .base import BaseAnnotationEngine
from ..types import FeatureItem, AnnotationRunRequest
from ..builtin_annotator import BuiltinAnnotator

logger = logging.getLogger("analysis.annotation.engines.prokka")


class ProkkaEngine(BaseAnnotationEngine):
    """Prokka 微生物全特征注释引擎"""

    def __init__(self):
        super().__init__(name="Prokka")

    async def is_available(self) -> bool:
        from ....assembly.engine.runner import CommandRunner
        runner = CommandRunner(step_name="ProkkaCheck", logger=logger, is_wsl=True)
        return (await runner.run_command(["which", "prokka"], silence_errors=True)) == 0

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

        runner = CommandRunner(step_name="Prokka", logger=logger, is_wsl=True)
        out_dir = work_dir / "prokka_out"
        out_dir.mkdir(parents=True, exist_ok=True)

        wsl_out = WSLManager.to_wsl_path(str(out_dir))
        wsl_fasta = WSLManager.to_wsl_path(str(input_fasta))

        cmd = [
            "prokka",
            "--outdir", wsl_out,
            "--prefix", prefix,
            "--cpus", str(threads),
            "--mincontiglen", "0",
            "--force"
        ]

        if req.sample_type.upper() in ["PHAGE", "VIRUS"]:
            cmd.extend(["--kingdom", "Viruses"])
        
        cmd.append(wsl_fasta)

        if on_progress:
            on_progress(25, "正在调度 Prokka 工具链执行特征注释...", " ".join(cmd))

        def on_output_line(line: str):
            if "Running: " in line and on_progress:
                tool = line.split("Running: ")[-1].split()[0]
                on_progress(35, f"Prokka 正在运行子工具: {tool}...", line)

        ret = await runner.run_command(cmd, cwd=work_dir, on_output=on_output_line)
        if ret != 0:
            raise RuntimeError(f"Prokka 执行返回非零状态码: {ret}")

        gbk_file = out_dir / f"{prefix}.gbk"
        tsv_file = out_dir / f"{prefix}.tsv"
        gff_file = out_dir / f"{prefix}.gff"
        faa_file = out_dir / f"{prefix}.faa"
        ffn_file = out_dir / f"{prefix}.ffn"

        if not gbk_file.exists():
            raise RuntimeError("Prokka 未能生成预期的 GenBank 输出文件")

        features: List[FeatureItem] = []
        with open(gbk_file, "r", encoding="utf-8", errors="ignore") as f:
            for rec in SeqIO.parse(f, "genbank"):
                for feat in rec.features:
                    if feat.type in ["source", "gene"]:
                        continue
                    q = feat.qualifiers
                    lt = q.get("locus_tag", [f"{prefix}_unknown"])[0]
                    prod = q.get("product", ["hypothetical protein"])[0]
                    trans = q.get("translation", [""])[0]
                    prot_id = q.get("protein_id", [None])[0]
                    gene_name = q.get("gene", [None])[0]
                    ec_num = q.get("EC_number", [None])[0]
                    
                    f_start = int(feat.location.start) + 1
                    f_end = int(feat.location.end)
                    f_len = f_end - f_start + 1
                    f_strand = "+" if feat.location.strand >= 0 else "-"
                    mw = BuiltinAnnotator.calculate_molecular_weight(trans) if trans else 0.0

                    item = FeatureItem(
                        id=lt,
                        locus_tag=lt,
                        contig_id=rec.id,
                        feature_type=feat.type,
                        start=f_start,
                        end=f_end,
                        strand=f_strand,
                        length_bp=f_len,
                        gene_name=gene_name,
                        product=prod,
                        protein_id=prot_id,
                        protein_length_aa=len(trans) if trans else 0,
                        molecular_weight_kda=mw,
                        translation=trans if trans else None,
                        ec_number=ec_num,
                        source_engine="Prokka",
                        evidence_sources=[f"[Prokka] Model {feat.type}"]
                    )
                    features.append(item)

        files = {
            "gbk": str(gbk_file.resolve()),
            "tsv": str(tsv_file.resolve()) if tsv_file.exists() else "",
            "gff": str(gff_file.resolve()) if gff_file.exists() else "",
            "faa": str(faa_file.resolve()) if faa_file.exists() else "",
            "ffn": str(ffn_file.resolve()) if ffn_file.exists() else ""
        }
        return features, files
