# -*- coding: utf-8 -*-
"""
功能注释流水线 (AnnotationPipeline)
支持多引擎流式级联与互补补全 (Multi-Engine Streaming Waterfall Pipeline)
按流水线顺序流式处理各引擎，逐层漏斗式补充前序引擎未能注释的部分。
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

from .types import AnnotationRunRequest, FeatureItem, AnnotationSummary, SafetyAuditResult
from .builtin_annotator import BuiltinAnnotator
from .fuser import AnnotationFuser
from .engines import (
    BuiltinEngine,
    ProdigalEngine,
    ProkkaEngine,
    PharokkaEngine,
    HomologyEngine,
    PholdEngine
)
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
        self._current_max_progress = 0

    def cancel(self):
        self._is_cancelled = True

    def _broadcast_progress(self, progress: int, step_desc: str, log_line: Optional[str] = None):
        """实时广播任务进度与控制台日志 (单调递增保护，严禁进度倒退)"""
        p = max(self._current_max_progress, min(100, progress))
        self._current_max_progress = p

        data = {
            "task_id": self.task_id,
            "progress": p,
            "current_step": step_desc,
            "log": log_line
        }
        broadcaster.broadcast_sync("annotation_progress", data)
        annotation_db.update_progress(self.task_id, p, step_desc)

    def _make_stage_progress(self, start_pct: int, end_pct: int, stage_prefix: str = ""):
        """为子引擎创建专用的动态相对进度映射器 (将子任务 0%~100% 线性映射至全局 [start_pct, end_pct])"""
        def on_sub_progress(sub_pct: int, msg: str, log: Optional[str] = None):
            clamped_sub = max(0, min(100, sub_pct))
            mapped = int(start_pct + (clamped_sub / 100.0) * (end_pct - start_pct))
            full_msg = f"{stage_prefix} {msg}".strip() if stage_prefix else msg
            self._broadcast_progress(mapped, full_msg, log)
        return on_sub_progress

    async def execute(self, req: AnnotationRunRequest) -> Dict[str, Any]:
        """执行全套多引擎流式级联互补注释流程"""
        try:
            self._current_max_progress = 0
            self._broadcast_progress(5, "正在初始化注释工作区与输入序列...")
            
            # 1. 准备输入 FASTA 文件
            input_fasta = self._prepare_input_fasta(req)
            
            # 2. 计算系统可用多核线程 (保留核心防卡死)
            sys_cores = os.cpu_count() or 4
            allocated_threads = req.threads or max(1, sys_cores - 1)
            
            prefix = req.prefix or "ANNO"
            primary_engine_choice = (req.engine or "auto").lower()

            features: List[FeatureItem] = []
            files: Dict[str, str] = {}
            with open(input_fasta, "r", encoding="utf-8", errors="ignore") as f:
                records = list(SeqIO.parse(f, "fasta"))
            records_len_dict = {r.id: len(r.seq) for r in records}
            full_seq = "".join(str(r.seq) for r in records)

            annotator_helper = BuiltinAnnotator(
                genetic_code=req.genetic_code,
                min_orf_len_bp=req.min_contig_len,
                prefix=prefix
            )

            # ==========================================
            # 阶段 1: 基础结构与全特征预测 (Primary Model: 10% ~ 38%)
            # ==========================================
            stage1_progress = self._make_stage_progress(10, 38, "【阶段 1/5】")
            self._broadcast_progress(10, "【阶段 1/5】正在生成基础特征与 CDS 预测模型...")
            primary_success = False

            if primary_engine_choice == "pharokka":
                pharokka_eng = PharokkaEngine()
                if await pharokka_eng.is_available():
                    try:
                        features, files = await pharokka_eng.run(
                            input_fasta=input_fasta,
                            work_dir=self.work_dir,
                            req=req,
                            threads=allocated_threads,
                            prefix=prefix,
                            on_progress=stage1_progress
                        )
                        primary_success = True
                    except Exception as e:
                        logger.warning(f"Pharokka 运行异常，准备自动降级: {e}")

            elif primary_engine_choice == "prokka":
                prokka_eng = ProkkaEngine()
                if await prokka_eng.is_available():
                    try:
                        features, files = await prokka_eng.run(
                            input_fasta=input_fasta,
                            work_dir=self.work_dir,
                            req=req,
                            threads=allocated_threads,
                            prefix=prefix,
                            on_progress=stage1_progress
                        )
                        primary_success = True
                    except Exception as e:
                        logger.warning(f"Prokka 运行异常，准备自动降级: {e}")

            elif primary_engine_choice == "prodigal":
                prodigal_eng = ProdigalEngine()
                if await prodigal_eng.is_available():
                    try:
                        features, files = await prodigal_eng.run(
                            input_fasta=input_fasta,
                            work_dir=self.work_dir,
                            req=req,
                            threads=allocated_threads,
                            prefix=prefix,
                            on_progress=stage1_progress
                        )
                        primary_success = True
                    except Exception as e:
                        logger.warning(f"Prodigal 运行异常，准备自动降级: {e}")

            elif primary_engine_choice == "auto":
                # 自动调度策略: 噬菌体尝试 Pharokka，细菌尝试 Prokka/Prodigal
                if req.sample_type.upper() in ["PHAGE", "VIRUS"]:
                    pharokka_eng = PharokkaEngine()
                    if await pharokka_eng.is_available():
                        try:
                            features, files = await pharokka_eng.run(
                                input_fasta=input_fasta,
                                work_dir=self.work_dir,
                                req=req,
                                threads=allocated_threads,
                                prefix=prefix,
                                on_progress=stage1_progress
                            )
                            primary_success = True
                        except Exception as e:
                            logger.info(f"Auto 调度 Pharokka 异常，切换备选: {e}")

                if not primary_success:
                    prodigal_eng = ProdigalEngine()
                    if await prodigal_eng.is_available():
                        try:
                            features, files = await prodigal_eng.run(
                                input_fasta=input_fasta,
                                work_dir=self.work_dir,
                                req=req,
                                threads=allocated_threads,
                                prefix=prefix,
                                on_progress=stage1_progress
                            )
                            primary_success = True
                        except Exception as e:
                            logger.info(f"Auto 调度 Prodigal 异常，切换内置引擎: {e}")

            # 若未成功或选内置，使用 BuiltinEngine
            if not primary_success or not features:
                builtin_eng = BuiltinEngine()
                features, files = await builtin_eng.run(
                    input_fasta=input_fasta,
                    work_dir=self.work_dir,
                    req=req,
                    threads=allocated_threads,
                    prefix=prefix,
                    on_progress=stage1_progress
                )

            if self._is_cancelled:
                annotation_db.mark_cancelled(self.task_id)
                self._broadcast_progress(0, "任务已被用户取消")
                return {"status": "cancelled"}

            # 生成 Stage 1 检查点文件
            _, features, files = annotator_helper.export_features_to_files(
                records=records,
                all_features=features,
                output_dir=self.work_dir
            )

            total_cds = sum(1 for f in features if f.feature_type == "CDS")
            unanno_cds = sum(1 for f in features if f.feature_type == "CDS" and AnnotationFuser.is_unannotated(f.product))
            self._broadcast_progress(38, f"【阶段 1 完成】已构建 {len(features)} 个基础特征 (CDS: {total_cds} 个，待打捞功能: {unanno_cds} 个)")

            # ==========================================
            # 阶段 2: 权威数据库多核同源打捞 (Homology Rescue: 40% ~ 58%)
            # ==========================================
            if req.enable_homology and files.get("faa") and Path(files["faa"]).exists() and unanno_cds > 0:
                stage2_progress = self._make_stage_progress(40, 58, "【阶段 2/5: 同源打捞】")
                self._broadcast_progress(40, "【阶段 2/5】流经 PhageScope 105万条权威蛋白库进行同源打捞...")
                try:
                    homo_eng = HomologyEngine()
                    updated_cnt = homo_eng.complement_features(
                        features=features,
                        query_faa=Path(files["faa"]),
                        work_dir=self.work_dir,
                        threads=allocated_threads,
                        on_progress=stage2_progress
                    )
                    
                    if updated_cnt > 0:
                        # 刷新写盘 Checkpoint
                        _, features, files = annotator_helper.export_features_to_files(
                            records=records,
                            all_features=features,
                            output_dir=self.work_dir
                        )
                except Exception as e:
                    logger.warning(f"同源打捞阶段异常: {e}")

            if self._is_cancelled:
                annotation_db.mark_cancelled(self.task_id)
                return {"status": "cancelled"}

            # 重新评估未注释数量
            unanno_cds = sum(1 for f in features if f.feature_type == "CDS" and AnnotationFuser.is_unannotated(f.product))

            # ==========================================
            # 阶段 3: 专业领域特征流式互补 (Domain / Specific Engine: 60% ~ 72%)
            # ==========================================
            # 若主引擎不是 Pharokka，但处于噬菌体模式且有未注释基因，流经 Pharokka 补充 PHROGs 分类与缺失位点
            if req.sample_type.upper() in ["PHAGE", "VIRUS"] and primary_engine_choice not in ["pharokka"] and unanno_cds > 0:
                pharokka_eng = PharokkaEngine()
                if await pharokka_eng.is_available():
                    stage3_progress = self._make_stage_progress(60, 72, "【阶段 3/5: 级联互补】")
                    self._broadcast_progress(60, "【阶段 3/5】流经 Pharokka 噬菌体专用模型库执行 PHROGs 互补...")
                    try:
                        pharokka_feats, _ = await pharokka_eng.run(
                            input_fasta=input_fasta,
                            work_dir=self.work_dir / "pharokka_cascade",
                            req=req,
                            threads=allocated_threads,
                            prefix=prefix,
                            on_progress=stage3_progress
                        )
                        if pharokka_feats:
                            features, p_upd = AnnotationFuser.merge_by_coordinates(
                                base_features=features,
                                incoming_features=pharokka_feats,
                                engine_name="Pharokka",
                                overlap_threshold=0.75
                            )
                            if p_upd > 0:
                                self._broadcast_progress(72, f"Pharokka 成功补充并修正 {p_upd} 个基因特征与 PHROGs 分类...")
                                _, features, files = annotator_helper.export_features_to_files(
                                    records=records,
                                    all_features=features,
                                    output_dir=self.work_dir
                                )
                    except Exception as p_err:
                        logger.warning(f"Pharokka 级联补充异常: {p_err}")

            if self._is_cancelled:
                annotation_db.mark_cancelled(self.task_id)
                return {"status": "cancelled"}

            unanno_cds = sum(1 for f in features if f.feature_type == "CDS" and AnnotationFuser.is_unannotated(f.product))

            # ==========================================
            # 阶段 4: Phold AI 蛋白质三维结构感知增强 (3D AI Structure Rescue: 74% ~ 88%)
            # ==========================================
            should_run_phold = req.enable_phold or primary_engine_choice == "phold"
            if should_run_phold and files.get("gbk") and Path(files["gbk"]).exists() and unanno_cds > 0:
                phold_eng = PholdEngine()
                if await phold_eng.is_available():
                    stage4_progress = self._make_stage_progress(74, 88, "【阶段 4/5: 3D构象感知】")
                    self._broadcast_progress(74, "【阶段 4/5】流经 Phold AI 进行 3D 空间结构感知与 Foldseek 补漏...")
                    try:
                        phold_upd = await phold_eng.complement_from_gbk(
                            features=features,
                            input_gbk=Path(files["gbk"]),
                            work_dir=self.work_dir,
                            threads=allocated_threads,
                            on_progress=stage4_progress
                        )
                        if phold_upd > 0:
                            _, features, files = annotator_helper.export_features_to_files(
                                records=records,
                                all_features=features,
                                output_dir=self.work_dir
                            )
                    except Exception as phold_err:
                        logger.warning(f"Phold 3D 空间结构增强阶段异常: {phold_err}")

            # 阶段 5: 全量重新评估并补齐功能分类大类 (89%)
            self._broadcast_progress(89, "【阶段 5/5】正在重新梳理并归纳基因功能大类分类...")
            for f in features:
                if not f.category:
                    f.category = AnnotationFuser.infer_category(f.product, f.notes)

            # ==========================================
            # 阶段 6: 深度生物安全性与防御系统审计 (CARD / VFDB / Anti-CRISPR: 90% ~ 95%)
            # ==========================================
            safety_audit_res: Optional[Dict[str, Any]] = None
            if req.enable_safety_audit and files.get("faa") and Path(files["faa"]).exists():
                self._broadcast_progress(91, "正在执行生物安全性审计 (CARD耐药基因/VFDB毒力因子/Anti-CRISPR逃逸扫描)...")
                try:
                    from .deep_audit import DeepSafetyAuditor
                    auditor = DeepSafetyAuditor()
                    safety_audit_res = auditor.run_safety_audit(
                        query_faa=Path(files["faa"]),
                        work_dir=self.work_dir,
                        threads=allocated_threads
                    )
                    audit_file = self.work_dir / "safety_audit.json"
                    with open(audit_file, "w", encoding="utf-8") as f:
                        json.dump(safety_audit_res, f, ensure_ascii=False, indent=2)
                    files["safety_audit_json"] = str(audit_file.resolve())
                except Exception as audit_err:
                    logger.warning(f"生物安全审计阶段异常: {audit_err}")

            # ==========================================
            # 阶段 7: 生成最终标准成果与落盘 (96% ~ 99%)
            # ==========================================
            self._broadcast_progress(96, "正在汇总多引擎级联结果并生成标准 GenBank/GFF3 成果...")

            # 最终文件导出
            final_summary, features, files = annotator_helper.export_features_to_files(
                records=records,
                all_features=features,
                output_dir=self.work_dir
            )

            # 重新生成全维度统计摘要 (包含各引擎贡献度、功能大类分布)
            comprehensive_summary = AnnotationFuser.generate_summary(
                records_len_dict=records_len_dict,
                full_seq=full_seq,
                features=features
            )

            # 特征数据分片落盘与 JSON 存储 (断点保护)
            features_file = self.work_dir / "features.json"
            features_dict = [f.model_dump() for f in features]
            with open(features_file, "w", encoding="utf-8") as f:
                json.dump(features_dict, f, ensure_ascii=False)
            files["features_json"] = str(features_file.resolve())

            # 持久化至数据库
            summary_dict = comprehensive_summary.model_dump()
            annotation_db.mark_completed(
                task_id=self.task_id, 
                summary=summary_dict, 
                files=files,
                safety_audit=safety_audit_res
            )
            
            # 1. 广播 100% 进度
            self._broadcast_progress(100, f"注释全部完成 (总特征数: {len(features)}, 已知功能: {comprehensive_summary.annotated_count}, 未知: {comprehensive_summary.hypothetical_count})")

            # 2. 最终广播完成事件
            final_res = {
                "task_id": self.task_id,
                "summary": summary_dict,
                "feature_count": len(features),
                "features_sample": [f.model_dump() for f in features[:100]],
                "files": files,
                "safety_audit": safety_audit_res
            }
            broadcaster.broadcast_sync("annotation_completed", final_res)
            return final_res

        except Exception as e:
            logger.error(f"功能注释流水线执行失败: {e}", exc_info=True)
            err_msg = str(e)
            annotation_db.mark_failed(self.task_id, err_msg)
            self._broadcast_progress(0, f"注释失败: {err_msg}", err_msg)
            raise

    def _prepare_input_fasta(self, req: AnnotationRunRequest) -> Path:
        """规范化并生成合法的输入 FASTA 文件"""
        target_fasta = self.work_dir / "input_sequence.fasta"

        if req.fasta_content and req.fasta_content.strip():
            raw_content = req.fasta_content.strip()
            if not raw_content.startswith(">"):
                raw_content = f">Sequence_1\n{raw_content}"
            
            with open(target_fasta, "w", encoding="utf-8") as f:
                f.write(raw_content)
                f.write("\n")
        elif req.fasta_path and Path(req.fasta_path).exists():
            src_path = Path(req.fasta_path)
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

        with open(target_fasta, "r", encoding="utf-8", errors="ignore") as f:
            records = list(SeqIO.parse(f, "fasta"))
        if not records:
            raise ValueError("解析 FASTA 失败，未检测到有效序列")

        if req.selected_contigs and len(req.selected_contigs) > 0:
            selected_set = set(req.selected_contigs)
            records = [r for r in records if r.id in selected_set]
            if not records:
                raise ValueError("未匹配到任何用户勾选的 Contig 序列")

        filtered = [r for r in records if len(r.seq) >= req.min_contig_len]
        if not filtered:
            longest = max(records, key=lambda x: len(x.seq))
            filtered = [longest]

        with open(target_fasta, "w", encoding="utf-8") as f:
            SeqIO.write(filtered, f, "fasta")

        return target_fasta
