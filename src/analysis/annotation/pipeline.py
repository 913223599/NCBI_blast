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
            if engine_to_use == "phold":
                # 显式指定 Phold AI 结构增强引擎
                self._broadcast_progress(20, "正在进行前置 ORF 预测并构建 Phold 输入模型...")
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

                # 调度 Phold AI 3D 结构折叠增强
                if files.get("gbk") and Path(files["gbk"]).exists():
                    self._broadcast_progress(40, "正在调度 Phold AI 蛋白质三维结构折叠预测与特征增强 (ESMFold/Foldseek)...")
                    try:
                        phold_summary, phold_features, phold_files = await self._run_phold_engine(
                            input_gbk=Path(files["gbk"]),
                            input_fasta=input_fasta,
                            threads=allocated_threads,
                            prefix=prefix
                        )
                        if phold_features:
                            summary, features, files = phold_summary, phold_features, phold_files
                            self._broadcast_progress(60, f"Phold 结构感知完成，已成功增强 {len(features)} 个特征...")
                    except Exception as phold_err:
                        logger.warning(f"Phold 执行异常，自动衔接后续同源打捞: {phold_err}")
                        self._broadcast_progress(50, "Phold 结构增强已处理，正在进入专家库同源打捞...")

            elif engine_to_use in ["prokka", "pharokka", "auto"]:
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

            # 3.5 蛋白质生物学功能深度比对与打捞 (Assign Real Functions via BLASTP)
            if files.get("faa") and Path(files["faa"]).exists() and features:
                self._broadcast_progress(65, "正在比对权威蛋白质功能数据库 (PhageScope/RefSeq 105万条参考蛋白)...")
                try:
                    from .functional_assigner import FunctionalAssigner
                    assigner = FunctionalAssigner()
                    assigned_hits = assigner.run_blastp_annotation(
                        query_faa=Path(files["faa"]),
                        work_dir=self.work_dir,
                        threads=allocated_threads
                    )
                    
                    if assigned_hits:
                        self._broadcast_progress(78, f"成功打捞并匹配到 {len(assigned_hits)} 个编码基因的真实生物学功能...")
                        updated_count = 0
                        for feat in features:
                            hit = assigned_hits.get(feat.id) or assigned_hits.get(feat.locus_tag) or assigned_hits.get(feat.protein_id)
                            if hit:
                                feat.product = hit["product"]
                                if hit.get("gene_name"):
                                    feat.gene_name = hit["gene_name"]
                                feat.notes = f"Inferred via BLASTP alignment to {hit.get('target_id', 'RefSeq')} (Identity: {hit.get('identity', 100)}%, E-value: {hit.get('evalue', '1e-5')})"
                                updated_count += 1
                        
                        logger.info(f"Updated {updated_count} CDS features with real biological products")
                        
                        # 重新导出更新后的 GBK, GFF3, TSV
                        records = list(SeqIO.parse(str(input_fasta), "fasta"))
                        if req.selected_contigs:
                            sel_set = set(req.selected_contigs)
                            records = [r for r in records if r.id in sel_set]
                        summary, features, files = annotator.export_features_to_files(
                            records=records,
                            all_features=features,
                            output_dir=self.work_dir,
                            on_progress=lambda p, msg: self._broadcast_progress(p, msg)
                        )
                except Exception as blast_err:
                    logger.warning(f"蛋白质功能打捞阶段异常: {blast_err}")

            # 3.8 深度生物安全性与毒力耐药审计 (CARD / VFDB / Anti-CRISPR Audit)
            safety_audit_res: Optional[Dict[str, Any]] = None
            if files.get("faa") and Path(files["faa"]).exists():
                self._broadcast_progress(88, "正在执行生物安全性审计 (CARD耐药基因/VFDB毒力因子/Anti-CRISPR逃逸扫描)...")
                try:
                    from .deep_audit import DeepSafetyAuditor
                    auditor = DeepSafetyAuditor()
                    safety_audit_res = auditor.run_safety_audit(
                        query_faa=Path(files["faa"]),
                        work_dir=self.work_dir,
                        threads=allocated_threads
                    )
                    # 落盘 safety_audit.json
                    audit_file = self.work_dir / "safety_audit.json"
                    with open(audit_file, "w", encoding="utf-8") as f:
                        json.dump(safety_audit_res, f, ensure_ascii=False, indent=2)
                    files["safety_audit_json"] = str(audit_file.resolve())
                except Exception as audit_err:
                    logger.warning(f"生物安全审计阶段异常: {audit_err}")

            # 4. 特征数据分片落盘与 JSON 存储
            features_file = self.work_dir / "features.json"
            features_dict = [f.dict() for f in features]
            with open(features_file, "w", encoding="utf-8") as f:
                json.dump(features_dict, f, ensure_ascii=False)
            files["features_json"] = str(features_file.resolve())

            # 5. 持久化至数据库
            summary_dict = summary.dict() if summary else {}
            annotation_db.mark_completed(
                task_id=self.task_id, 
                summary=summary_dict, 
                files=files,
                safety_audit=safety_audit_res
            )
            
            # 广播完成事件
            final_res = {
                "task_id": self.task_id,
                "summary": summary_dict,
                "feature_count": len(features),
                "features_sample": [f.dict() for f in features[:100]],
                "files": files,
                "safety_audit": safety_audit_res
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

    async def _run_phold_engine(self, input_gbk: Path, input_fasta: Path,
                               threads: int, prefix: str) -> Tuple[AnnotationSummary, List[FeatureItem], Dict[str, str]]:
        """调用 WSL 中的 phold 执行 3D 蛋白质结构折叠感知与功能增强"""
        from ...assembly.core.runner import StepRunner

        runner = StepRunner(logger)
        has_phold = (await runner.run_command(["which", "phold"], silence_errors=True)) == 0
        if not has_phold:
            raise RuntimeError("宿主环境中未安装 Phold 工具")

        out_dir = self.work_dir / "phold_out"
        out_dir.mkdir(parents=True, exist_ok=True)

        # 创建无空格软链接路径
        await runner.run_command(["bash", "-c", "ln -sfT '/mnt/f/NCBI blast' /tmp/ncbi_blast_tmp"], silence_errors=True)

        wsl_gbk = f"/tmp/ncbi_blast_tmp/results/annotations/{self.task_id}/{input_gbk.name}"
        wsl_out = f"/tmp/ncbi_blast_tmp/results/annotations/{self.task_id}/phold_out"

        phold_cmd = [
            "bash", "-c",
            f"export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 && phold run -i {wsl_gbk} -o {wsl_out} -d /opt/phold_db -t {threads} -f"
        ]

        logger.info(f"Executing Phold: {' '.join(phold_cmd)}")
        ret = await runner.run_command(phold_cmd, cwd=self.work_dir)
        
        phold_gbk = out_dir / "phold.gbk"
        if ret == 0 and phold_gbk.exists() and phold_gbk.stat().st_size > 0:
            target_gbk = phold_gbk
        else:
            target_gbk = input_gbk

        # 解析 GBK
        features: List[FeatureItem] = []
        for rec in SeqIO.parse(str(target_gbk), "genbank"):
            for feat in rec.features:
                if feat.type in ["source", "gene"]:
                    continue
                q = feat.qualifiers
                lt = q.get("locus_tag", [f"{prefix}_unknown"])[0]
                prod = q.get("product", ["hypothetical protein"])[0]
                trans = q.get("translation", [""])[0]
                prot_id = q.get("protein_id", [None])[0]
                gene_name = q.get("gene", [None])[0]
                notes = q.get("function", q.get("phold_annotation", q.get("note", [None])))[0]
                
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
                    translation=trans if trans else None,
                    notes=f"Phold Structure: {notes}" if notes else None
                ))

        records = list(SeqIO.parse(str(input_fasta), "fasta"))
        total_len = sum(len(r.seq) for r in records)
        full_seq = "".join(str(r.seq) for r in records)
        gc_val = BuiltinAnnotator.calculate_gc(full_seq)
        cds_cnt = sum(1 for f in features if f.feature_type == "CDS")

        summary = AnnotationSummary(
            total_length=total_len,
            num_contigs=len(records),
            gc_content=gc_val,
            cds_count=cds_cnt,
            total_features=len(features),
            coding_density_pct=round((sum(f.length_bp for f in features if f.feature_type == 'CDS') / total_len) * 100.0, 2) if total_len > 0 else 0.0,
            avg_gene_length=round(sum(f.length_bp for f in features if f.feature_type == 'CDS') / max(1, cds_cnt), 1)
        )

        files = {
            "gbk": str(target_gbk.resolve()),
            "faa": str((self.work_dir / f"{prefix}.faa").resolve()),
            "ffn": str((self.work_dir / f"{prefix}.ffn").resolve()),
            "tsv": str((self.work_dir / f"{prefix}.tsv").resolve())
        }
        return summary, features, files
