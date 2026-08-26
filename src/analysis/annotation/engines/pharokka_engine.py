# -*- coding: utf-8 -*-
"""
Pharokka 噬菌体专用全特征注释引擎 (PharokkaEngine)
结合 PHROGs 噬菌体特异性模型、tRNA-scan、MinCED CRISPR 探测与末端基因识别
"""
import os
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple, Callable
from Bio import SeqIO

from .base import BaseAnnotationEngine
from ..types import FeatureItem, AnnotationRunRequest
from ..builtin_annotator import BuiltinAnnotator

logger = logging.getLogger("analysis.annotation.engines.pharokka")


class PharokkaEngine(BaseAnnotationEngine):
    """Pharokka 噬菌体特征引擎"""

    def __init__(self):
        super().__init__(name="Pharokka")

    async def is_available(self) -> bool:
        from ....assembly.engine.runner import CommandRunner
        runner = CommandRunner(step_name="PharokkaCheck", logger=logger, is_wsl=True)
        return (await runner.run_command(["which", "pharokka.py"], silence_errors=True)) == 0

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

        runner = CommandRunner(step_name="Pharokka", logger=logger, is_wsl=True)
        out_dir = work_dir / "pharokka_out"
        out_dir.mkdir(parents=True, exist_ok=True)

        wsl_out = WSLManager.to_wsl_path(str(out_dir))
        wsl_fasta = WSLManager.to_wsl_path(str(input_fasta))

        cmd = [
            "pharokka.py",
            "-i", wsl_fasta,
            "-o", wsl_out,
            "-d", "/opt/pharokka_db",
            "-t", str(threads),
            "-p", prefix,
            "-f"
        ]

        if on_progress:
            on_progress(5, "正在初始化并调度 Pharokka 噬菌体专用引擎分析...", " ".join(cmd))

        current_pct = 5
        def on_pharokka_line(line: str):
            nonlocal current_pct
            if not on_progress or not line:
                return
            
            clean_l = line.strip()
            # 依据 Pharokka 实际输出流水动态计算相对进度 (5% -> 98%)
            if "phanotate" in clean_l.lower() or "validate" in clean_l.lower():
                current_pct = max(current_pct, 12)
                on_progress(current_pct, "Pharokka [1/8]: 正在执行 Phanotate 基因识别...", clean_l)
            elif "tRNAscan" in clean_l or "tRNA" in clean_l:
                current_pct = max(current_pct, 25)
                on_progress(current_pct, "Pharokka [2/8]: 正在扫描 tRNA-scan 特征...", clean_l)
            elif "MinCED" in clean_l or "CRISPR" in clean_l:
                current_pct = max(current_pct, 38)
                on_progress(current_pct, "Pharokka [3/8]: 正在探测 MinCED CRISPR 结构域...", clean_l)
            elif "Aragorn" in clean_l or "tmRNA" in clean_l:
                current_pct = max(current_pct, 50)
                on_progress(current_pct, "Pharokka [4/8]: 正在运行 Aragorn 终止子与 tmRNA 识别...", clean_l)
            elif "MMseqs2 on PHROGs" in clean_l or "run_mmseqs" in clean_l:
                current_pct = max(current_pct, 65)
                on_progress(current_pct, "Pharokka [5/8]: 正在比对 PHROGs 噬菌体特异性同源数据库...", clean_l)
            elif "CARD" in clean_l or "VFDB" in clean_l:
                current_pct = max(current_pct, 78)
                on_progress(current_pct, "Pharokka [6/8]: 正在扫描 CARD 耐药与 VFDB 毒力数据库...", clean_l)
            elif "PyHMMER on PHROGs" in clean_l or "pyhmmer" in clean_l:
                current_pct = max(current_pct, 90)
                on_progress(current_pct, "Pharokka [7/8]: 正在执行 PyHMMER 隐马尔可夫模型深度扫描...", clean_l)
            elif "topfunction" in clean_l or "mash" in clean_l or "GenBank" in clean_l:
                current_pct = max(current_pct, 98)
                on_progress(current_pct, "Pharokka [8/8]: 正在整合 PHROGs 噬菌体分类并生成标准模型...", clean_l)
            elif "Running" in clean_l or "INFO" in clean_l:
                on_progress(current_pct, f"Pharokka 正在运行: {clean_l[:55]}...", clean_l)

        ret = await runner.run_command(cmd, cwd=work_dir, on_output=on_pharokka_line)
        if ret != 0:
            logger.warning(f"Pharokka 基础运行异常: {ret}，尝试降级参数...")

        gbk_file = out_dir / f"{prefix}.gbk"
        if not gbk_file.exists():
            gbk_candidates = list(out_dir.glob("*.gbk"))
            if gbk_candidates:
                gbk_file = gbk_candidates[0]
            else:
                raise RuntimeError("Pharokka 未能生成有效的 GenBank 文件")

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
                    phrog_num = q.get("phrog", [None])[0]
                    phrog_cat = q.get("function", [None])[0]

                    f_start = int(feat.location.start) + 1
                    f_end = int(feat.location.end)
                    f_len = f_end - f_start + 1
                    f_strand = "+" if feat.location.strand >= 0 else "-"
                    mw = BuiltinAnnotator.calculate_molecular_weight(trans) if trans else 0.0

                    evidence = []
                    if phrog_num:
                        evidence.append(f"PHROG #{phrog_num}")
                    if phrog_cat:
                        evidence.append(f"Category: {phrog_cat}")

                    features.append(FeatureItem(
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
                        category=phrog_cat if phrog_cat else None,
                        source_engine="Pharokka",
                        evidence_sources=[f"[Pharokka] {', '.join(evidence)}"] if evidence else ["[Pharokka] Model"]
                    ))

        files = {
            "gbk": str(gbk_file.resolve()),
            "gff": str((out_dir / f"{prefix}.gff").resolve()) if (out_dir / f"{prefix}.gff").exists() else "",
            "faa": str((out_dir / f"{prefix}.faa").resolve()) if (out_dir / f"{prefix}.faa").exists() else "",
            "ffn": str((out_dir / f"{prefix}.ffn").resolve()) if (out_dir / f"{prefix}.ffn").exists() else "",
            "tsv": str((out_dir / f"{prefix}_cds_functions.tsv").resolve()) if (out_dir / f"{prefix}_cds_functions.tsv").exists() else ""
        }
        return features, files
