# -*- coding: utf-8 -*-
"""
功能注释流水线 (AnnotationPipeline)
支持多引擎流式级联与互补补全 (Multi-Engine Streaming Waterfall Pipeline)
按流水线顺序流式处理各引擎，逐层漏斗式补充前序引擎未能注释的部分。
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, Type

from Bio import SeqIO

from ...core.broadcaster import broadcaster
from ...utils.resource_guard import get_safe_cpu_budget
from .builtin_annotator import BuiltinAnnotator
from .db import annotation_db
from .engines import (
    BuiltinEngine,
    HomologyEngine,
    PharokkaEngine,
    PholdEngine,
    ProdigalEngine,
    ProkkaEngine,
)
from .fuser import AnnotationFuser
from .types import AnnotationRunRequest, FeatureItem

logger = logging.getLogger("analysis.annotation.pipeline")

_HOMOLOGY_DB_LABELS: Tuple[Tuple[str, str], ...] = (
    ("phagescope", "PhageScope"),
    ("swissprot", "Swiss-Prot"),
    ("cdd_pfam", "CDD/Pfam"),
    ("vfdb", "VFDB"),
    ("card", "CARD"),
)


class AnnotationPipeline:
    """功能注释执行管线"""

    def __init__(self, task_id: str, work_dir: Path) -> None:
        self.task_id = task_id
        self.work_dir = Path(work_dir)
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self._is_cancelled = False
        self._current_max_progress = 0
        # 逐阶段诊断：记录每个引擎/数据库是"已执行 / 被跳过 / 执行异常"，避免静默降级
        self.diagnostics: List[Dict[str, Any]] = []

    def cancel(self) -> None:
        self._is_cancelled = True

    def _broadcast_progress(self, progress: int, step_desc: str, log_line: Optional[str] = None) -> None:
        """实时广播任务进度与控制台日志 (单调递增保护，严禁进度倒退)"""
        p = max(self._current_max_progress, min(100, progress))
        self._current_max_progress = p
        data = {
            "task_id": self.task_id,
            "progress": p,
            "current_step": step_desc,
            "log": log_line,
        }
        broadcaster.broadcast_sync("annotation_progress", data)
        annotation_db.update_progress(self.task_id, p, step_desc)

    def _make_stage_progress(
        self, start_pct: int, end_pct: int, stage_prefix: str = ""
    ) -> Callable[[int, str, Optional[str]], None]:
        """为子引擎创建专用的动态相对进度映射器 (将子任务 0%~100% 线性映射至全局 [start_pct, end_pct])"""

        def on_sub_progress(sub_pct: int, msg: str, log: Optional[str] = None) -> None:
            clamped_sub = max(0, min(100, sub_pct))
            mapped = int(start_pct + (clamped_sub / 100.0) * (end_pct - start_pct))
            full_msg = f"{stage_prefix} {msg}".strip() if stage_prefix else msg
            self._broadcast_progress(mapped, full_msg, log)

        return on_sub_progress

    def _record_stage(self, stage: str, status: str, detail: str, **extra: Any) -> Dict[str, Any]:
        """记录阶段诊断，并把"跳过/失败"原因同步到控制台日志，便于用户定位连接问题"""
        entry: Dict[str, Any] = {"stage": stage, "status": status, "detail": detail}
        entry.update(extra)
        self.diagnostics.append(entry)
        icon = {"ok": "[OK]", "skipped": "[SKIP]", "no-hit": "[INFO]", "failed": "[FAIL]"}.get(status, "-")
        message = f"{icon} {stage}: {detail}"
        logger.info("[流程诊断] %s", message)
        try:
            self._broadcast_progress(self._current_max_progress, message, message)
        except Exception as _exc:
            logger.debug("AnnotationPipeline._record_stage 忽略非致命异常: %s", _exc)
        return entry

    @staticmethod
    def _count_unannotated_cds(features: List[FeatureItem]) -> int:
        return sum(
            1 for f in features if f.feature_type == "CDS" and AnnotationFuser.is_unannotated(f.product)
        )

    @staticmethod
    def _resolve_primary_engine_plan(
        choice: str, sample_type: str
    ) -> List[Tuple[str, str, Type[Any]]]:
        """根据用户选择的引擎和样本类型，生成有序的主引擎降级候选链。"""
        explicit_map: Dict[str, Tuple[str, str, Type[Any]]] = {
            "pharokka": ("pharokka", "Pharokka", PharokkaEngine),
            "prokka": ("prokka", "Prokka", ProkkaEngine),
            "prodigal": ("prodigal", "Prodigal", ProdigalEngine),
        }
        if choice in explicit_map:
            return [explicit_map[choice]]
        if choice == "auto":
            plan: List[Tuple[str, str, Type[Any]]] = []
            if sample_type.upper() in ("PHAGE", "VIRUS"):
                plan.append(("pharokka", "Pharokka", PharokkaEngine))
            plan.append(("prodigal", "Prodigal", ProdigalEngine))
            return plan
        return []

    async def _run_stage1_primary(
        self,
        *,
        req: AnnotationRunRequest,
        input_fasta: Path,
        allocated_threads: int,
        prefix: str,
        primary_engine_choice: str,
    ) -> Tuple[List[FeatureItem], Dict[str, str], str]:
        """阶段 1：按策略链执行主结构特征预测，失败或不可用时平滑降级至 BuiltinEngine。"""
        stage1_progress = self._make_stage_progress(10, 38, "【阶段 1/5】")
        self._broadcast_progress(10, "【阶段 1/5】正在生成基础特征与 CDS 预测模型...")

        features: List[FeatureItem] = []
        files: Dict[str, str] = {}
        actual_engine = "builtin"
        primary_success = False

        for engine_key, engine_label, engine_cls in self._resolve_primary_engine_plan(
            primary_engine_choice, req.sample_type
        ):
            engine = engine_cls()
            if not await engine.is_available():
                self._record_stage(
                    f"阶段1 主引擎 {engine_label}",
                    "skipped",
                    engine.unavailable_reason or f"{engine_label} 引擎不可用",
                )
                continue
            try:
                features, files = await engine.run(
                    input_fasta=input_fasta,
                    work_dir=self.work_dir,
                    req=req,
                    threads=allocated_threads,
                    prefix=prefix,
                    on_progress=stage1_progress,
                )
                primary_success = True
                actual_engine = engine_key
                break
            except Exception as exc:
                logger.warning("%s 运行异常，准备自动降级: %s", engine_label, exc)
                self._record_stage(f"阶段1 主引擎 {engine_label}", "failed", f"运行异常，已降级: {exc}")

        if not primary_success or not features:
            builtin_eng = BuiltinEngine()
            features, files = await builtin_eng.run(
                input_fasta=input_fasta,
                work_dir=self.work_dir,
                req=req,
                threads=allocated_threads,
                prefix=prefix,
                on_progress=stage1_progress,
            )
            actual_engine = "builtin"

        return features, files, actual_engine

    @staticmethod
    def _format_homology_db_summary(db_diag: Dict[str, Any]) -> str:
        summary_bits: List[str] = []
        for db_key, label in _HOMOLOGY_DB_LABELS:
            info = db_diag.get(db_key) or {}
            if not info:
                continue
            if not info.get("ready"):
                summary_bits.append(f"{label} 未就绪({info.get('path')})")
            elif info.get("added") or info.get("assigned"):
                summary_bits.append(f"{label} +{info.get('added') or info.get('assigned')}")
            elif info.get("hits"):
                summary_bits.append(f"{label} 命中{info.get('hits')}")
            else:
                summary_bits.append(f"{label} 已连接")
        return "；".join(summary_bits) or "数据库诊断缺失"

    def _run_stage2_homology(
        self,
        *,
        req: AnnotationRunRequest,
        records: List[Any],
        features: List[FeatureItem],
        files: Dict[str, str],
        annotator_helper: BuiltinAnnotator,
        allocated_threads: int,
        unanno_cds: int,
    ) -> Tuple[List[FeatureItem], Dict[str, str]]:
        """阶段 2：权威数据库多核同源打捞 (40% ~ 58%)。"""
        faa_path = files.get("faa")
        if not req.enable_homology:
            self._record_stage("阶段2 同源打捞", "skipped", "参数 enable_homology=false，用户关闭了同源打捞")
            return features, files
        if not (faa_path and Path(faa_path).exists() and Path(faa_path).stat().st_size > 0):
            self._record_stage("阶段2 同源打捞", "skipped", f"缺少有效的蛋白 FASTA 输入 (faa={faa_path})")
            return features, files
        if unanno_cds <= 0:
            self._record_stage("阶段2 同源打捞", "skipped", "所有 CDS 均已有明确功能，无需同源打捞")
            return features, files

        stage2_progress = self._make_stage_progress(40, 58, "【阶段 2/5: 同源打捞】")
        self._broadcast_progress(40, "【阶段 2/5】流经 PhageScope 105万条权威蛋白库进行同源打捞...")
        homo_eng = HomologyEngine()
        try:
            updated_cnt = homo_eng.complement_features(
                features=features,
                query_faa=Path(faa_path),
                work_dir=self.work_dir,
                threads=allocated_threads,
                on_progress=stage2_progress,
            )
            db_diag = homo_eng.diagnostics or {}
            db_summary = self._format_homology_db_summary(db_diag)
            if updated_cnt > 0:
                _, features, files = annotator_helper.export_features_to_files(
                    records=records, all_features=features, output_dir=self.work_dir
                )
                self._record_stage(
                    "阶段2 同源打捞",
                    "ok",
                    f"成功为 {updated_cnt} 个基因赋予真实功能（{db_summary}）",
                    databases=db_diag,
                )
            else:
                self._record_stage(
                    "阶段2 同源打捞",
                    "no-hit",
                    f"已连接数据库但未获得可用同源注释（{db_summary}）",
                    databases=db_diag,
                )
        except Exception as exc:
            logger.warning("同源打捞阶段异常: %s", exc)
            self._record_stage("阶段2 同源打捞", "failed", f"执行异常: {exc}")
        return features, files

    async def _run_stage3_pharokka_cascade(
        self,
        *,
        req: AnnotationRunRequest,
        input_fasta: Path,
        records: List[Any],
        features: List[FeatureItem],
        files: Dict[str, str],
        annotator_helper: BuiltinAnnotator,
        allocated_threads: int,
        prefix: str,
        actual_primary_engine: str,
        unanno_cds: int,
    ) -> Tuple[List[FeatureItem], Dict[str, str]]:
        """阶段 3：专业领域 Pharokka 级联互补 (60% ~ 72%)。"""
        if req.sample_type.upper() not in ("PHAGE", "VIRUS"):
            self._record_stage(
                "阶段3 Pharokka 级联",
                "skipped",
                f"样本类型为 {req.sample_type}，Pharokka 级联仅用于噬菌体/病毒样本",
            )
            return features, files
        if actual_primary_engine == "pharokka":
            self._record_stage("阶段3 Pharokka 级联", "skipped", "主引擎已使用 Pharokka，无需重复级联")
            return features, files
        if unanno_cds <= 0:
            self._record_stage("阶段3 Pharokka 级联", "skipped", "已无未注释基因")
            return features, files

        pharokka_eng = PharokkaEngine()
        if not await pharokka_eng.is_available():
            self._record_stage(
                "阶段3 Pharokka 级联",
                "skipped",
                pharokka_eng.unavailable_reason or "Pharokka 引擎不可用",
            )
            return features, files

        stage3_progress = self._make_stage_progress(60, 72, "【阶段 3/5: 级联互补】")
        self._broadcast_progress(60, "【阶段 3/5】流经 Pharokka 噬菌体专用模型库执行 PHROGs 互补...")
        try:
            pharokka_feats, _ = await pharokka_eng.run(
                input_fasta=input_fasta,
                work_dir=self.work_dir / "pharokka_cascade",
                req=req,
                threads=allocated_threads,
                prefix=prefix,
                on_progress=stage3_progress,
            )
            if pharokka_feats:
                features, p_upd = AnnotationFuser.merge_by_coordinates(
                    base_features=features,
                    incoming_features=pharokka_feats,
                    engine_name="Pharokka",
                    overlap_threshold=0.75,
                )
                if p_upd > 0:
                    self._broadcast_progress(72, f"Pharokka 成功补充并修正 {p_upd} 个基因特征与 PHROGs 分类...")
                    _, features, files = annotator_helper.export_features_to_files(
                        records=records, all_features=features, output_dir=self.work_dir
                    )
                self._record_stage("阶段3 Pharokka 级联", "ok", f"Pharokka 补充/修正 {p_upd} 个特征")
            else:
                self._record_stage("阶段3 Pharokka 级联", "no-hit", "Pharokka 未返回可用特征")
        except Exception as exc:
            logger.warning("Pharokka 级联补充异常: %s", exc)
            self._record_stage("阶段3 Pharokka 级联", "failed", f"执行异常: {exc}")
        return features, files

    async def _run_stage4_phold_3d(
        self,
        *,
        req: AnnotationRunRequest,
        primary_engine_choice: str,
        records: List[Any],
        features: List[FeatureItem],
        files: Dict[str, str],
        annotator_helper: BuiltinAnnotator,
        allocated_threads: int,
        unanno_cds: int,
    ) -> Tuple[List[FeatureItem], Dict[str, str]]:
        """阶段 4：Phold AI 蛋白质三维结构感知增强 (74% ~ 88%)。"""
        if not (req.enable_phold or primary_engine_choice == "phold"):
            self._record_stage("阶段4 Phold 3D", "skipped", "参数 enable_phold=false，用户关闭了 3D 结构增强")
            return features, files
        gbk_path = files.get("gbk")
        if not (gbk_path and Path(gbk_path).exists()):
            self._record_stage("阶段4 Phold 3D", "skipped", f"缺少 GenBank 中间文件 (gbk={gbk_path})")
            return features, files
        if unanno_cds <= 0:
            self._record_stage("阶段4 Phold 3D", "skipped", "已无未注释基因")
            return features, files

        phold_eng = PholdEngine()
        if not await phold_eng.is_available():
            self._record_stage("阶段4 Phold 3D", "skipped", phold_eng.unavailable_reason or "Phold 引擎不可用")
            return features, files

        stage4_progress = self._make_stage_progress(74, 88, "【阶段 4/5: 3D构象感知】")
        self._broadcast_progress(74, "【阶段 4/5】流经 Phold AI 进行 3D 空间结构感知与 Foldseek 补漏...")
        try:
            phold_upd = await phold_eng.complement_from_gbk(
                features=features,
                input_gbk=Path(gbk_path),
                work_dir=self.work_dir,
                threads=allocated_threads,
                on_progress=stage4_progress,
            )
            if phold_upd > 0:
                _, features, files = annotator_helper.export_features_to_files(
                    records=records, all_features=features, output_dir=self.work_dir
                )
            self._record_stage(
                "阶段4 Phold 3D",
                "ok" if phold_upd > 0 else "no-hit",
                f"Phold 补全 {phold_upd} 个假定蛋白",
            )
        except Exception as exc:
            logger.warning("Phold 3D 空间结构增强阶段异常: %s", exc)
            self._record_stage("阶段4 Phold 3D", "failed", f"执行异常: {exc}")
        return features, files

    def _run_stage6_safety_audit(
        self,
        *,
        req: AnnotationRunRequest,
        features: List[FeatureItem],
        files: Dict[str, str],
        allocated_threads: int,
    ) -> Optional[Dict[str, Any]]:
        """阶段 6：深度生物安全性与防御系统审计 (90% ~ 95%)。"""
        if not req.enable_safety_audit:
            self._record_stage("阶段6 生物安全审计", "skipped", "参数 enable_safety_audit=false，用户关闭了安全审计")
            return None
        faa_path = files.get("faa")
        if not (faa_path and Path(faa_path).exists()):
            self._record_stage("阶段6 生物安全审计", "skipped", "缺少蛋白 FASTA 输入")
            return None

        self._broadcast_progress(91, "正在执行生物安全性审计 (CARD耐药基因/VFDB毒力因子/Anti-CRISPR逃逸扫描)...")
        try:
            from .deep_audit import DeepSafetyAuditor

            auditor = DeepSafetyAuditor()
            safety_audit_res = auditor.run_safety_audit(
                query_faa=Path(faa_path),
                work_dir=self.work_dir,
                threads=allocated_threads,
            )
            audit_file = self.work_dir / "safety_audit.json"
            with open(audit_file, "w", encoding="utf-8") as f:
                json.dump(safety_audit_res, f, ensure_ascii=False, indent=2)
            files["safety_audit_json"] = str(audit_file.resolve())

            fused_acr_cnt = AnnotationFuser.integrate_safety_audit(features, safety_audit_res)
            if fused_acr_cnt > 0:
                logger.info("Successfully integrated %d Anti-CRISPR/Safety annotations into features", fused_acr_cnt)
            self._record_stage(
                "阶段6 生物安全审计",
                "ok",
                f"CARD 耐药 {len(safety_audit_res.get('amr_genes', []))} 个，"
                f"VFDB 毒力 {len(safety_audit_res.get('virulent_factors', []))} 个，"
                f"Anti-CRISPR: {safety_audit_res.get('anti_crispr_status')}",
                databases=getattr(auditor, "diagnostics", {}),
            )
            return safety_audit_res
        except Exception as exc:
            logger.warning("生物安全审计阶段异常: %s", exc)
            self._record_stage("阶段6 生物安全审计", "failed", f"执行异常: {exc}")
            return None

    def _finalize_and_persist(
        self,
        *,
        records: List[Any],
        records_len_dict: Dict[str, int],
        full_seq: str,
        features: List[FeatureItem],
        annotator_helper: BuiltinAnnotator,
        safety_audit_res: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """阶段 7：生成最终标准成果、落盘 JSON、更新数据库并广播完成事件 (96% ~ 100%)。"""
        self._broadcast_progress(96, "正在汇总多引擎级联结果并生成标准 GenBank/GFF3 成果...")
        _, features, files = annotator_helper.export_features_to_files(
            records=records, all_features=features, output_dir=self.work_dir
        )

        comprehensive_summary = AnnotationFuser.generate_summary(
            records_len_dict=records_len_dict, full_seq=full_seq, features=features
        )
        summary_dict = comprehensive_summary.model_dump()
        summary_dict["pipeline_diagnostics"] = self.diagnostics
        summary_file = self.work_dir / "summary.json"
        with open(summary_file, "w", encoding="utf-8") as f:
            json.dump(summary_dict, f, ensure_ascii=False, indent=2)
        files["summary_json"] = str(summary_file.resolve())

        features_file = self.work_dir / "features.json"
        with open(features_file, "w", encoding="utf-8") as f:
            json.dump([feat.model_dump() for feat in features], f, ensure_ascii=False)
        files["features_json"] = str(features_file.resolve())

        self._broadcast_progress(
            100,
            f"注释全部完成 (总特征数: {len(features)}, 已知功能: {comprehensive_summary.annotated_count}, "
            f"未知: {comprehensive_summary.hypothetical_count})",
        )
        annotation_db.mark_completed(
            task_id=self.task_id,
            summary=summary_dict,
            files=files,
            safety_audit=safety_audit_res,
        )
        final_res = {
            "task_id": self.task_id,
            "summary": summary_dict,
            "feature_count": len(features),
            "features_sample": [feat.model_dump() for feat in features[:100]],
            "files": files,
            "safety_audit": safety_audit_res,
        }
        broadcaster.broadcast_sync("annotation_completed", final_res)
        return final_res

    def _check_cancelled(self, broadcast_msg: Optional[str] = None) -> Optional[Dict[str, Any]]:
        if not self._is_cancelled:
            return None
        annotation_db.mark_cancelled(self.task_id)
        if broadcast_msg:
            self._broadcast_progress(0, broadcast_msg)
        return {"status": "cancelled"}

    async def execute(self, req: AnnotationRunRequest) -> Dict[str, Any]:
        """执行全套多引擎流式级联互补注释流程"""
        try:
            self._current_max_progress = 0
            self._broadcast_progress(5, "正在初始化注释工作区与输入序列...")

            input_fasta = self._prepare_input_fasta(req)
            allocated_threads = get_safe_cpu_budget(requested=req.threads or 0, reserve_cores=2)
            prefix = req.prefix or "ANNO"
            primary_engine_choice = (req.engine or "auto").lower()

            with open(input_fasta, "r", encoding="utf-8", errors="ignore") as f:
                records = list(SeqIO.parse(f, "fasta"))
            records_len_dict = {r.id: len(r.seq) for r in records}
            full_seq = "".join(str(r.seq) for r in records)

            annotator_helper = BuiltinAnnotator(
                genetic_code=req.genetic_code,
                min_orf_len_bp=req.min_contig_len,
                prefix=prefix,
            )

            # 阶段 1: 基础特征预测
            features, files, actual_primary_engine = await self._run_stage1_primary(
                req=req,
                input_fasta=input_fasta,
                allocated_threads=allocated_threads,
                prefix=prefix,
                primary_engine_choice=primary_engine_choice,
            )
            if cancelled := self._check_cancelled("任务已被用户取消"):
                return cancelled

            _, features, files = annotator_helper.export_features_to_files(
                records=records, all_features=features, output_dir=self.work_dir
            )
            total_cds = sum(1 for feat in features if feat.feature_type == "CDS")
            unanno_cds = self._count_unannotated_cds(features)
            self._record_stage(
                "阶段1 基础特征预测",
                "ok",
                f"实际主引擎: {actual_primary_engine}；特征 {len(features)} 个，其中 CDS {total_cds} 个（待打捞 {unanno_cds} 个）",
                engine=actual_primary_engine,
            )
            self._broadcast_progress(
                38,
                f"【阶段 1 完成】已构建 {len(features)} 个基础特征 (CDS: {total_cds} 个，待打捞功能: {unanno_cds} 个)",
            )

            # 阶段 2: 权威数据库多核同源打捞
            features, files = self._run_stage2_homology(
                req=req,
                records=records,
                features=features,
                files=files,
                annotator_helper=annotator_helper,
                allocated_threads=allocated_threads,
                unanno_cds=unanno_cds,
            )
            if cancelled := self._check_cancelled():
                return cancelled

            # 阶段 3: Pharokka 领域级联互补
            features, files = await self._run_stage3_pharokka_cascade(
                req=req,
                input_fasta=input_fasta,
                records=records,
                features=features,
                files=files,
                annotator_helper=annotator_helper,
                allocated_threads=allocated_threads,
                prefix=prefix,
                actual_primary_engine=actual_primary_engine,
                unanno_cds=self._count_unannotated_cds(features),
            )
            if cancelled := self._check_cancelled():
                return cancelled

            # 阶段 4: Phold 3D 构象感知增强
            features, files = await self._run_stage4_phold_3d(
                req=req,
                primary_engine_choice=primary_engine_choice,
                records=records,
                features=features,
                files=files,
                annotator_helper=annotator_helper,
                allocated_threads=allocated_threads,
                unanno_cds=self._count_unannotated_cds(features),
            )

            # 阶段 5: 全量重算功能分类大类
            self._broadcast_progress(89, "【阶段 5/5】正在重新梳理并归纳基因功能大类分类...")
            for feat in features:
                if feat.feature_type == "CDS" or not feat.category:
                    feat.category = AnnotationFuser.infer_category(feat.product, feat.notes)

            # 阶段 6: 生物安全性审计
            safety_audit_res = self._run_stage6_safety_audit(
                req=req, features=features, files=files, allocated_threads=allocated_threads
            )

            # 阶段 7: 落盘与持久化
            return self._finalize_and_persist(
                records=records,
                records_len_dict=records_len_dict,
                full_seq=full_seq,
                features=features,
                annotator_helper=annotator_helper,
                safety_audit_res=safety_audit_res,
            )

        except Exception as exc:
            logger.error("功能注释流水线执行失败: %s", exc, exc_info=True)
            err_msg = str(exc)
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
            with (
                open(src_path, "r", encoding="utf-8", errors="ignore") as fin,
                open(target_fasta, "w", encoding="utf-8") as fout,
            ):
                for line in fin:
                    if line.startswith(">"):
                        fout.write(f"{line.split()[0]}\n")
                    else:
                        fout.write(line)
        else:
            raise ValueError("未提供有效的 FASTA 序列文本或文件路径")

        with open(target_fasta, "r", encoding="utf-8", errors="ignore") as f:
            records = list(SeqIO.parse(f, "fasta"))
        if not records:
            raise ValueError("解析 FASTA 失败，未检测到有效序列")

        if req.selected_contigs:
            selected_set = set(req.selected_contigs)
            records = [r for r in records if r.id in selected_set]
            if not records:
                raise ValueError("未匹配到任何用户勾选的 Contig 序列")

        filtered = [r for r in records if len(r.seq) >= req.min_contig_len]
        if not filtered:
            filtered = [max(records, key=lambda x: len(x.seq))]

        with open(target_fasta, "w", encoding="utf-8") as f:
            SeqIO.write(filtered, f, "fasta")

        return target_fasta
