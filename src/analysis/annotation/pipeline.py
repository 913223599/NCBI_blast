# -*- coding: utf-8 -*-
"""
功能注释流水线 (AnnotationPipeline)
支持多引擎智能调度 (Prokka, Pharokka, Prodigal, 内置纯Python引擎)
"""
import os
import re
import json
import shutil
import asyncio
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
from Bio import SeqIO

from .types import AnnotationRunRequest, FeatureItem, AnnotationSummary
from .builtin_annotator import BuiltinAnnotator
from .db import annotation_db
from ...backend.broadcaster import broadcaster

logger = logging.getLogger("analysis.annotation.pipeline")


class AnnotationPipeline:
    """功能注释执行管线"""

    def __init__(self, task_id: str, work_dir: Path):
        self.task_id = task_id
        self.work_dir = Path(work_dir)
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self._is_cancelled = False

    def cancel(self):
        self._is_cancelled = True

    def _broadcast_progress(self, progress: int, step_desc: str, log_line: Optional[str] = None):
        """实时广播任务进度与控制台日志"""
        data = {
            "task_id": self.task_id,
            "progress": progress,
            "current_step": step_desc,
            "log": log_line
        }
        broadcaster.broadcast_sync("annotation_progress", data)
        annotation_db.update_progress(self.task_id, progress, step_desc)

    async def execute(self, req: AnnotationRunRequest) -> Dict[str, Any]:
        """执行全套注释流程"""
        try:
            self._broadcast_progress(5, "正在初始化注释工作区与输入序列...")
            
            # 1. 准备输入 FASTA 文件
            input_fasta = self._prepare_input_fasta(req)
            
            # 2. 计算系统可用多核线程 (保留核心防卡死)
            sys_cores = os.cpu_count() or 4
            allocated_threads = req.threads or max(1, sys_cores - 1)
            
            prefix = req.prefix or "ANNO"
            engine_to_use = req.engine.lower()
            
            summary: Optional[AnnotationSummary] = None
            features: List[FeatureItem] = []
            files: Dict[str, str] = {}

            # 3. 引擎决策与执行
            if engine_to_use in ["prokka", "pharokka", "auto"]:
                # 尝试通过外部生物信息工具链运行
                prokka_success = False
                if engine_to_use != "builtin":
                    try:
                        summary, features, files = await self._run_external_engine(
                            input_fasta=input_fasta,
                            req=req,
                            threads=allocated_threads,
                            prefix=prefix
                        )
                        prokka_success = True
                    except Exception as ext_err:
                        logger.warning(f"外部注释引擎执行异常或未安装，正在无缝切换至内置高精度引擎: {ext_err}")
                        self._broadcast_progress(20, "外部工具链未就绪，已切换至内置高性能注释引擎...", f"提示: {ext_err}")

                if not prokka_success:
                    # 降级至内置高性能引擎
                    annotator = BuiltinAnnotator(
                        genetic_code=req.genetic_code,
                        min_orf_len_bp=req.min_contig_len,
                        prefix=prefix
                    )
                    summary, features, files = annotator.annotate_fasta(
                        fasta_file_path=input_fasta,
                        output_dir=self.work_dir,
                        on_progress=lambda p, msg: self._broadcast_progress(p, msg)
                    )
            else:
                # 显式指定内置引擎
                annotator = BuiltinAnnotator(
                    genetic_code=req.genetic_code,
                    min_orf_len_bp=req.min_contig_len,
                    prefix=prefix
                )
                summary, features, files = annotator.annotate_fasta(
                    fasta_file_path=input_fasta,
                    output_dir=self.work_dir,
                    on_progress=lambda p, msg: self._broadcast_progress(p, msg)
                )

            if self._is_cancelled:
                annotation_db.mark_cancelled(self.task_id)
                self._broadcast_progress(0, "任务已被用户取消")
                return {"status": "cancelled"}

            # 4. 特征数据分片落盘与 JSON 存储
            features_file = self.work_dir / "features.json"
            features_dict = [f.dict() for f in features]
            with open(features_file, "w", encoding="utf-8") as f:
                json.dump(features_dict, f, ensure_ascii=False)
            files["features_json"] = str(features_file.resolve())

            # 5. 持久化至数据库
            summary_dict = summary.dict() if summary else {}
            annotation_db.mark_completed(self.task_id, summary_dict, files)
            
            # 广播完成事件
            final_res = {
                "task_id": self.task_id,
                "summary": summary_dict,
                "feature_count": len(features),
                "features_sample": [f.dict() for f in features[:100]],  # 首次返回前100条供轻量展示
                "files": files
            }
            broadcaster.broadcast_sync("annotation_completed", final_res)
            return final_res

        except Exception as e:
            logger.error(f"功能注释管线执行失败: {e}", exc_info=True)
            err_msg = str(e)
            annotation_db.mark_failed(self.task_id, err_msg)
            self._broadcast_progress(0, f"注释失败: {err_msg}", err_msg)
            raise

    def _prepare_input_fasta(self, req: AnnotationRunRequest) -> Path:
        """规范化并生成合法的输入 FASTA 文件"""
        target_fasta = self.work_dir / "input_sequence.fasta"

        if req.fasta_content and req.fasta_content.strip():
            raw_content = req.fasta_content.strip()
            # 如果用户未加 > 头部，自动补全
            if not raw_content.startswith(">"):
                raw_content = f">Sequence_1\n{raw_content}"
            
            with open(target_fasta, "w", encoding="utf-8") as f:
                f.write(raw_content)
                f.write("\n")
        elif req.fasta_path and Path(req.fasta_path).exists():
            src_path = Path(req.fasta_path)
            # 简化头部并复制
            with open(src_path, "r", encoding="utf-8", errors="ignore") as fin, \
                 open(target_fasta, "w", encoding="utf-8") as fout:
                for line in fin:
                    if line.startswith(">"):
                        header = line.split()[0]
                        fout.write(f"{header}\n")
                    else:
                        fout.write(line)
        else:
            raise ValueError("未提供有效的 FASTA 序列文本或文件路径")

        # 检查最小长度过滤
        records = list(SeqIO.parse(str(target_fasta), "fasta"))
        if not records:
            raise ValueError("解析 FASTA 失败，未检测到有效序列")

        # 如果用户指定了选定 Contig 集合，精准过滤
        if req.selected_contigs and len(req.selected_contigs) > 0:
            selected_set = set(req.selected_contigs)
            records = [r for r in records if r.id in selected_set]
            if not records:
                raise ValueError("未匹配到任何用户勾选的 Contig 序列")

        filtered = [r for r in records if len(r.seq) >= req.min_contig_len]
        if not filtered:
            # 若全部小于阈值，保留最长的一条
            longest = max(records, key=lambda x: len(x.seq))
            filtered = [longest]

        with open(target_fasta, "w", encoding="utf-8") as f:
            SeqIO.write(filtered, f, "fasta")

        return target_fasta

    async def _run_external_engine(self, input_fasta: Path, req: AnnotationRunRequest, 
                                  threads: int, prefix: str) -> Tuple[AnnotationSummary, List[FeatureItem], Dict[str, str]]:
        """调用 WSL / Linux 中的 Prokka 执行深度注释"""
        from ...assembly.env.wsl_manager import WSLManager
        from ...assembly.core.runner import StepRunner

        runner = StepRunner(logger)
        
        # 检查 Prokka 是否存在
        has_prokka = (await runner.run_command(["which", "prokka"], silence_errors=True)) == 0
        if not has_prokka:
            raise RuntimeError("宿主环境中未安装 Prokka 工具")

        out_dir = self.work_dir / "prokka_out"
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

        self._broadcast_progress(30, "正在调用 Prokka 深度预测特征...")
        
        def on_prokka_line(line: str):
            if "Running: " in line:
                tool = line.split("Running: ")[-1].split()[0]
                self._broadcast_progress(50, f"Prokka 正在运行: {tool}...", line)

        ret = await runner.run_command(cmd, cwd=self.work_dir, on_output=on_prokka_line)
        if ret != 0:
            raise RuntimeError(f"Prokka 执行返回非零退出码: {ret}")

        # 解析 Prokka 输出的 GenBank 和 TSV
        gbk_file = out_dir / f"{prefix}.gbk"
        tsv_file = out_dir / f"{prefix}.tsv"
        gff_file = out_dir / f"{prefix}.gff"
        faa_file = out_dir / f"{prefix}.faa"
        ffn_file = out_dir / f"{prefix}.ffn"

        if not gbk_file.exists():
            raise RuntimeError("Prokka 完成后未找到预期的 GBK 结果文件")

        features: List[FeatureItem] = []
        for rec in SeqIO.parse(str(gbk_file), "genbank"):
            for feat in rec.features:
                if feat.type in ["source", "gene"]:
                    continue
                q = feat.qualifiers
                lt = q.get("locus_tag", [f"{prefix}_unknown"])[0]
                prod = q.get("product", ["hypothetical protein"])[0]
                trans = q.get("translation", [""])[0]
                prot_id = q.get("protein_id", [None])[0]
                gene_name = q.get("gene", [None])[0]
                
                f_start = int(feat.location.start) + 1
                f_end = int(feat.location.end)
                f_len = f_end - f_start + 1
                f_strand = "+" if feat.location.strand >= 0 else "-"
                
                mw = BuiltinAnnotator.calculate_molecular_weight(trans) if trans else 0.0

                features.append(FeatureItem(
                    id=lt,
                    locus_tag=lt,
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
                    translation=trans if trans else None
                ))

        # 统计
        records = list(SeqIO.parse(str(input_fasta), "fasta"))
        total_len = sum(len(r.seq) for r in records)
        full_seq = "".join(str(r.seq) for r in records)
        gc_val = BuiltinAnnotator.calculate_gc(full_seq)

        cds_cnt = sum(1 for f in features if f.feature_type == "CDS")
        trna_cnt = sum(1 for f in features if f.feature_type == "tRNA")
        rrna_cnt = sum(1 for f in features if f.feature_type == "rRNA")
        tmrna_cnt = sum(1 for f in features if f.feature_type == "tmRNA")
        crispr_cnt = sum(1 for f in features if f.feature_type == "CRISPR")

        summary = AnnotationSummary(
            total_length=total_len,
            num_contigs=len(records),
            gc_content=gc_val,
            cds_count=cds_cnt,
            trna_count=trna_cnt,
            rrna_count=rrna_cnt,
            tmrna_count=tmrna_cnt,
            crispr_count=crispr_cnt,
            total_features=len(features),
            coding_density_pct=round((sum(f.length_bp for f in features if f.feature_type == 'CDS') / total_len) * 100.0, 2) if total_len > 0 else 0.0,
            avg_gene_length=round(sum(f.length_bp for f in features if f.feature_type == 'CDS') / max(1, cds_cnt), 1)
        )

        files = {
            "gbk": str(gbk_file.resolve()),
            "tsv": str(tsv_file.resolve()) if tsv_file.exists() else "",
            "gff": str(gff_file.resolve()) if gff_file.exists() else "",
            "faa": str(faa_file.resolve()) if faa_file.exists() else "",
            "ffn": str(ffn_file.resolve()) if ffn_file.exists() else ""
        }
        return summary, features, files
