# -*- coding: utf-8 -*-
"""
噬菌体结构与尾部形态预测管理器 (PhageStructureManager)

职责：
1. 探测本地计算资源、PHROG HMM 索引状态以及可选历史注解/前噬菌体数据源；
2. 协调 File / Paste / Annotation Task / PhageDiscovery Region 4 种源的预检与参数提交；
3. 按 Contig 分片落盘 Checkpoint 并并发剖析 TMP 分子标尺与 Virfam+PHROG 多证据形态归类；
4. 安全返回结构预测全文、GenBank 可视化跳转载荷、文件导出与任务销毁。
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import secrets
import shutil
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from starlette.concurrency import run_in_threadpool

from ...backend.broadcaster import broadcaster
from ...workbench.models.tool_config import ToolConfig
from ..annotation.db import annotation_db
from ..phage_finder.db import phage_discovery_db
from .db import phage_structure_db
from .completeness_gate import evaluate_contig_completeness
from .exporter import export_structure_artifacts
from .morphotype_classifier import (
    build_connector_profile,
    build_module_matrix,
    classify_morphotype,
)
from .phrog_catalog import classify_structural_role
from .queue import phage_structure_queue, release_gpu_memory
from .ai_morphotype_model import (
    check_ai_classifier_ready,
    check_unified_judge_ready,
    load_ai_predictor_bundle,
    load_unified_judge_seq_model,
    predict_contig_morphotype_ai,
    release_ai_judge_memory,
)
from .sequence_annotator import (
    check_phold_ready,
    check_wsl_pyhmmer_ready,
    enhance_with_phold_3d,
    get_safe_workers,
    parse_input_contigs,
    predict_missing_orfs_parallel,
    resolve_all_phrogs_hmm_path,
    resolve_structural_hmm_path,
    scan_proteins_with_pyhmmer,
)
from .tmp_analyzer import select_and_analyze_tmps
from .tail_finder_adapter import is_phagetailfinder_ready, run_phagetailfinder_on_contigs
from .thresholds import DEFAULT_THRESHOLDS, MorphotypeClassifierThresholds, PhageStructureThresholds
from .types import (
    AiMorphotypePrediction,
    ContigStructureResult,
    MorphotypePrediction,
    PhageStructureResult,
    StructureBatchItemRequest,
    StructureBatchRunRequest,
    StructureInspectRequest,
    StructureProteinItem,
    StructureRunRequest,
    TailFinderCluster,
    TmpAnalysisItem,
)

logger = logging.getLogger("analysis.phage_structure.manager")


def should_trigger_phold_3d(
    pred: MorphotypePrediction,
    tmps: Sequence[TmpAnalysisItem],
    length_bp: int,
    thresholds: MorphotypeClassifierThresholds = DEFAULT_THRESHOLDS.classifier,
    ai_prediction: Optional[AiMorphotypePrediction] = None,
) -> Tuple[bool, str]:
    """
    判断单条 Contig 是否需要按条件触发 Phold 3D (ProstT5 + Foldseek) 增强复核：
    1. tailed_without_tmp：已判为长尾/肌尾，但序列同源未检出任何 TMP；
    2. low_margin_ambiguous：非 Incomplete 且最高与次高候选分差过小 (且次高 > 2.0)；
    3. incomplete_large_contig：长度 >= phold_incomplete_min_bp 却因缺少 PHROG 同源落入 Incomplete；
    4. ai_rule_conflict：AI 双轨模型高置信结论 (>=0.75) 与规则引擎存在分歧。
    """
    if pred.morphotype_code in ("Myoviridae-like", "Siphoviridae-like") and len(tmps) == 0:
        return True, "tailed_without_tmp"
    if pred.morphotype_code != "Incomplete" and pred.class_scores:
        sorted_vals = sorted(pred.class_scores.values(), reverse=True)
        if (
            len(sorted_vals) >= 2
            and sorted_vals[1] > 2.0
            and (sorted_vals[0] - sorted_vals[1]) < thresholds.low_margin_warning_cutoff
        ):
            return True, "low_margin_ambiguous"
    if pred.morphotype_code == "Incomplete" and length_bp >= thresholds.phold_incomplete_min_bp:
        return True, "incomplete_large_contig"
    if (
        ai_prediction is not None
        and ai_prediction.confidence >= 0.75
        and not ai_prediction.agreement_with_rules
    ):
        return True, "ai_rule_conflict"
    return False, ""


def evaluate_single_contig_structure(
    cid: str,
    info: Dict[str, Any],
    ptf_cnt: int,
    ptf_clusters: List[TailFinderCluster],
    *,
    default_genetic_code: int = 11,
    workers: int = 8,
    thresholds: PhageStructureThresholds = DEFAULT_THRESHOLDS,
    phold_triggered: bool = False,
    phold_trigger_reason: str = "",
    phold_rescued_orfs: int = 0,
    ai_prediction: Optional[AiMorphotypePrediction] = None,
) -> ContigStructureResult:
    """基于蛋白同源与 PTF 簇结果执行单条 Contig 的 TMP 选尺、完整度评估与形态分类。"""
    prots: List[StructureProteinItem] = info["proteins"]
    mm = build_module_matrix(prots)
    cp = build_connector_profile(prots)
    verified_tmp_cnt = sum(
        1
        for p in prots
        if p.structural_role == "TMP" and p.evidence_source in ("pyhmmer_phrog", "phold_3d")
    )
    has_tail_bg = (
        (mm.tail_sheath_count + mm.major_tail_count + mm.tail_tube_count + mm.tail_assembly_chaperone_count + verified_tmp_cnt) > 0
        or mm.baseplate_count >= 2
        or len(ptf_clusters) >= 1
    )
    length_bp = int(info["length_bp"])
    sparse_rescued = int(info.get("sparse_rescued_orfs") or 0)
    dna_seq = info.get("dna_seq", "")

    tmps = select_and_analyze_tmps(
        prots,
        has_tailed_context=has_tail_bg,
        contig_length_bp=length_bp,
        max_workers=workers,
        thresholds=thresholds.tmp,
        split_thresholds=thresholds.split_tmp,
    )
    comp = evaluate_contig_completeness(
        dna_seq=dna_seq,
        length_bp=length_bp,
        proteins=prots,
        module_matrix=mm,
        connector_profile=cp,
        tmp_analyses=tmps,
        ptf_clusters=ptf_clusters,
        sparse_rescued_orfs=sparse_rescued,
        thresholds=thresholds.completeness,
    )
    used_tt = int(info.get("genetic_code_used") or default_genetic_code)
    auto_tt = bool(info.get("genetic_code_auto_selected") or False)
    pred = classify_morphotype(
        prots,
        tmps,
        mm,
        cp,
        ptf_clusters=ptf_clusters,
        genome_length_bp=length_bp,
        dna_seq=dna_seq,
        completeness=comp,
        genetic_code_used=used_tt,
        genetic_code_auto_selected=auto_tt,
        sparse_rescued_orfs=sparse_rescued,
        thresholds=thresholds.classifier,
        comp_thresholds=thresholds.completeness,
    )
    effective_tmps = [] if pred.morphotype_code in ("Podoviridae-like", "Non-tailed") else tmps
    hmm_matched = sum(1 for p in prots if p.hmm_score > 0 or p.phrog_id)

    return ContigStructureResult(
        contig_id=cid,
        length_bp=length_bp,
        gc_percent=float(info["gc_percent"]),
        total_orfs=len(prots),
        hmm_matched_orfs=hmm_matched,
        genetic_code_used=used_tt,
        genetic_code_auto_selected=auto_tt,
        completeness=comp,
        phold_3d_triggered=phold_triggered,
        phold_3d_trigger_reason=phold_trigger_reason,
        phold_3d_rescued_orfs=phold_rescued_orfs,
        prediction=pred,
        ai_prediction=ai_prediction,
        connector_profile=cp,
        module_matrix=mm,
        ptf_tail_protein_count=ptf_cnt,
        ptf_tail_clusters=ptf_clusters,
        tmp_analyses=effective_tmps,
        structural_proteins=sorted(prots, key=lambda x: x.start),
    )


class PhageStructureManager:
    """单例管理噬菌体结构与尾部形态预测全生命周期。"""

    def __init__(self, project_root: Optional[Path] = None):
        self.project_root = Path(project_root) if project_root else ToolConfig.PROJECT_ROOT
        self.results_root = self.project_root / "results" / "phage_structure"
        self.results_root.mkdir(parents=True, exist_ok=True)
        self.db = phage_structure_db
        self.queue = phage_structure_queue
        self.queue.set_executor(self.execute_pipeline_task)

    async def initialize_queue_worker(self) -> None:
        await self.queue.start()

    def get_capabilities(self) -> Dict[str, Any]:
        struct_hmm = resolve_structural_hmm_path()
        all_hmm = resolve_all_phrogs_hmm_path()
        wsl_pyhmmer = check_wsl_pyhmmer_ready()
        cpu_cores = os.cpu_count() or 4
        return {
            "ready": wsl_pyhmmer and (struct_hmm is not None or all_hmm is not None),
            "wsl_pyhmmer_ready": wsl_pyhmmer,
            "phold_ready": check_phold_ready(),
            "phagetailfinder_ready": is_phagetailfinder_ready(),
            "unified_judge_ready": check_unified_judge_ready(self.project_root),
            "ai_classifier_ready": check_ai_classifier_ready(self.project_root),
            "structural_hmm_cached": struct_hmm is not None,
            "structural_hmm_path": str(struct_hmm) if struct_hmm else "",
            "all_phrogs_available": all_hmm is not None,
            "cpu_cores": cpu_cores,
            "safe_workers": get_safe_workers(),
        }

    def _attach_ai_predictions(
        self,
        eval_by_cid: Dict[str, ContigStructureResult],
        target_cids: Sequence[str],
    ) -> None:
        """为指定 Contig 集合附加双轨 AI 形态概率校准，结束后强制释放 PyTorch 显存。"""
        if not target_cids or not check_ai_classifier_ready(self.project_root):
            return
        release_gpu_memory()
        ai_bundle = load_ai_predictor_bundle(project_root=self.project_root)
        if ai_bundle is None:
            return
        try:
            judge_model, _, eff_dev = load_unified_judge_seq_model(project_root=self.project_root)
            for cid in target_cids:
                c_res = eval_by_cid.get(cid)
                if c_res is None:
                    continue
                ai_pred = predict_contig_morphotype_ai(
                    proteins=c_res.structural_proteins,
                    length_bp=c_res.length_bp,
                    gc_percent=c_res.gc_percent,
                    module_matrix=c_res.module_matrix,
                    connector_profile=c_res.connector_profile,
                    tmp_analyses=c_res.tmp_analyses,
                    ptf_clusters=c_res.ptf_tail_clusters,
                    completeness=c_res.completeness,
                    rule_prediction=c_res.prediction,
                    bundle=ai_bundle,
                    judge_model=judge_model,
                    device=eff_dev,
                )
                c_res.ai_prediction = ai_pred
                if (
                    ai_pred is not None
                    and not ai_pred.agreement_with_rules
                    and ai_pred.confidence >= 0.75
                    and ai_pred.conflict_note
                    and ai_pred.conflict_note not in c_res.prediction.warnings
                ):
                    c_res.prediction.warnings.append(ai_pred.conflict_note)
        except Exception as exc:
            logger.warning("双轨 AI 形态推理跳过: %s", exc)
        finally:
            release_ai_judge_memory()
            release_gpu_memory()

    def list_linked_sources(self) -> Dict[str, Any]:
        """获取系统内已完成的功能注释与前噬菌体扫描记录作为快捷数据源。"""
        anno_items: List[Dict[str, Any]] = []
        for t in annotation_db.list_tasks(limit=80):
            if t.get("status") == "completed":
                summ = t.get("summary") or {}
                anno_items.append({
                    "task_id": t["task_id"],
                    "task_name": t["task_name"],
                    "sample_type": t.get("sample_type", "PHAGE"),
                    "cds_count": summ.get("cds_count", 0),
                    "total_length": summ.get("total_length", 0),
                    "created_at": t.get("created_at", ""),
                })

        phage_items: List[Dict[str, Any]] = []
        for t in phage_discovery_db.list_tasks(limit=80):
            if t.get("status") == "completed":
                summ = t.get("summary") or {}
                if int(summ.get("region_count") or 0) > 0:
                    phage_items.append({
                        "task_id": t["task_id"],
                        "task_name": t["task_name"],
                        "region_count": summ.get("region_count", 0),
                        "total_prophage_bp": summ.get("total_prophage_bp", 0),
                        "created_at": t.get("created_at", ""),
                    })
        return {"annotations": anno_items, "phage_discoveries": phage_items}

    def _load_contigs_from_annotation(
        self,
        anno_task_id: str,
        selected_contigs: Optional[List[str]] = None,
    ) -> Dict[str, Dict[str, Any]]:
        task_row = annotation_db.get_task(anno_task_id)
        if not task_row:
            raise FileNotFoundError(f"未找到历史注释任务: {anno_task_id}")
        anno_dir = self.project_root / "results" / "annotations" / anno_task_id
        feat_json = anno_dir / "features.json"
        gbk_p = anno_dir / "ANNO.gbk"
        fasta_p = anno_dir / "input_sequence.fasta"

        contig_seqs: Dict[str, str] = {}
        if fasta_p.is_file():
            parsed = parse_input_contigs(fasta_path=str(fasta_p))
            contig_seqs = {cid: info["dna_seq"] for cid, info in parsed.items()}
        elif gbk_p.is_file():
            parsed = parse_input_contigs(fasta_path=str(gbk_p), selected_contigs=selected_contigs)
            if not feat_json.is_file():
                return parsed
            contig_seqs = {cid: info["dna_seq"] for cid, info in parsed.items()}

        if not feat_json.is_file():
            raise FileNotFoundError(f"注释任务缺少特征文件: {feat_json}")

        raw_feats = json.loads(feat_json.read_text(encoding="utf-8"))
        sel_set = set(selected_contigs) if selected_contigs else None
        out: Dict[str, Dict[str, Any]] = {}

        for f in raw_feats:
            if f.get("feature_type") != "CDS":
                continue
            cid = str(f.get("contig_id") or "contig_1")
            if sel_set is not None and cid not in sel_set:
                continue
            if cid not in out:
                dna = contig_seqs.get(cid, "")
                n_bp = len(dna)
                gc_pct = round((dna.count("G") + dna.count("C")) * 100.0 / max(1, n_bp), 2) if n_bp else 0.0
                out[cid] = {
                    "length_bp": n_bp,
                    "gc_percent": gc_pct,
                    "dna_seq": dna,
                    "proteins": [],
                    "input_type": "annotation",
                }
            aa = str(f.get("translation") or "").strip().upper().rstrip("*")
            prod = str(f.get("product") or "hypothetical protein")
            phrog_id = str(f.get("phrog") or "")
            if not phrog_id:
                notes = str(f.get("notes") or "")
                import re
                m = re.search(r"PHROG\s*#?(\d+)", notes, re.I)
                if m:
                    phrog_id = f"phrog_{m.group(1)}"
            role, role_cn = classify_structural_role(prod, phrog_id=phrog_id)
            start_bp = int(f.get("start") or 0)
            end_bp = int(f.get("end") or 0)
            out[cid]["proteins"].append(
                StructureProteinItem(
                    locus_tag=str(f.get("locus_tag") or f.get("id") or f"CDS_{len(out[cid]['proteins']) + 1}"),
                    contig_id=cid,
                    start=start_bp,
                    end=end_bp,
                    strand=str(f.get("strand") or "+"),
                    length_aa=int(f.get("protein_length_aa") or len(aa)),
                    product=prod,
                    raw_product=prod,
                    phrog_id=phrog_id,
                    structural_role=role,
                    role_label_cn=role_cn,
                    evidence_source=str(f.get("source_engine") or "annotation"),
                    translation=aa,
                )
            )
            out[cid]["length_bp"] = max(out[cid]["length_bp"], end_bp)

        if not out:
            raise ValueError(f"注释任务 {anno_task_id} 中未检测到 CDS 编码基因")
        return out

    def _load_contigs_from_phage_discovery(
        self,
        pd_task_id: str,
        region_index: Optional[int] = None,
        selected_contigs: Optional[List[str]] = None,
    ) -> Dict[str, Dict[str, Any]]:
        pd_dir = self.project_root / "results" / "phage_discovery" / pd_task_id
        fa_p = pd_dir / "prophages.fasta"
        if not fa_p.is_file():
            raise FileNotFoundError(f"前噬菌体扫描任务未导出区段序列: {fa_p}")

        cmap = parse_input_contigs(fasta_path=str(fa_p), selected_contigs=selected_contigs)
        if region_index is not None:
            prefix = f"Phage_{region_index:03d}"
            filtered = {cid: val for cid, val in cmap.items() if cid.startswith(prefix)}
            if not filtered:
                raise FileNotFoundError(f"任务 {pd_task_id} 中未找到区段 {prefix}")
            return filtered
        return cmap

    def inspect_input(self, req: StructureInspectRequest) -> Dict[str, Any]:
        if req.source_mode == "annotation" and req.source_task_id:
            cmap = self._load_contigs_from_annotation(req.source_task_id)
        elif req.source_mode == "phage_discovery" and req.source_task_id:
            cmap = self._load_contigs_from_phage_discovery(req.source_task_id, region_index=req.region_index)
        else:
            cmap = parse_input_contigs(fasta_path=req.fasta_path, fasta_content=req.fasta_content)

        contigs_meta = [
            {
                "id": cid,
                "length_bp": info["length_bp"],
                "gc_percent": info["gc_percent"],
                "cds_count": len(info["proteins"]),
                "input_type": info["input_type"],
            }
            for cid, info in cmap.items()
        ]
        return {
            "success": True,
            "num_contigs": len(contigs_meta),
            "total_length": sum(c["length_bp"] for c in contigs_meta),
            "contigs": contigs_meta,
        }

    def _validate_run_request(self, req: StructureRunRequest) -> None:
        if req.source_mode in ("annotation", "phage_discovery") and not req.source_task_id:
            raise ValueError("联动分析必须指定关联的历史任务 ID")
        if (
            req.source_mode in ("file", "paste")
            and not req.fasta_path
            and not (req.fasta_content and req.fasta_content.strip())
        ):
            raise ValueError("必须提供基因组文件或粘贴 FASTA / GenBank 序列文本")

    @staticmethod
    def _derive_batch_task_name(item: StructureBatchItemRequest, idx: int) -> str:
        if item.task_name and item.task_name.strip():
            return item.task_name.strip()
        if item.fasta_path:
            stem = Path(item.fasta_path).name
            for suf in (".gz", ".fasta", ".fa", ".fna", ".faa", ".gbk", ".gbff", ".gb", ".genbank"):
                if stem.lower().endswith(suf):
                    stem = stem[: -len(suf)]
            if stem:
                return f"{stem}_Structure"
        if item.source_task_id:
            suffix = f"_Phage_{item.region_index:03d}" if item.region_index is not None else ""
            return f"{item.source_task_id}{suffix}_Structure"
        return f"PhageStructure_Batch_{idx:02d}"

    @staticmethod
    def _split_multi_fasta_content(text: str) -> List[tuple[str, str]]:
        """将多条 FASTA 文本按记录头拆分为 [(record_id, single_fasta_text), ...]。"""
        blocks: List[tuple[str, str]] = []
        cur_header: Optional[str] = None
        cur_lines: List[str] = []
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if line.startswith(">"):
                if cur_header is not None and cur_lines:
                    rec_id = cur_header[1:].strip().split()[0] if len(cur_header) > 1 else f"Seq_{len(blocks) + 1}"
                    blocks.append((rec_id, cur_header + "\n" + "\n".join(cur_lines) + "\n"))
                cur_header = line
                cur_lines = []
            elif cur_header is not None:
                cur_lines.append(line)
        if cur_header is not None and cur_lines:
            rec_id = cur_header[1:].strip().split()[0] if len(cur_header) > 1 else f"Seq_{len(blocks) + 1}"
            blocks.append((rec_id, cur_header + "\n" + "\n".join(cur_lines) + "\n"))
        return blocks

    def _expand_batch_item_to_runs(
        self,
        item: StructureBatchItemRequest,
        batch_req: StructureBatchRunRequest,
        idx: int,
    ) -> List[StructureRunRequest]:
        base_kwargs = {
            "threads": batch_req.threads,
            "genetic_code": batch_req.genetic_code,
            "auto_select_genetic_code": batch_req.auto_select_genetic_code,
            "evalue_cutoff": batch_req.evalue_cutoff,
            "score_cutoff": batch_req.score_cutoff,
            "force_hmm_rescan": batch_req.force_hmm_rescan,
            "enable_phold_enhance": batch_req.enable_phold_enhance,
            "phold_trigger_mode": batch_req.phold_trigger_mode,
            "enable_phagetailfinder": batch_req.enable_phagetailfinder,
            "ptf_accurate_mode": batch_req.ptf_accurate_mode,
            "enable_ai_classifier": batch_req.enable_ai_classifier,
        }
        base_name = self._derive_batch_task_name(item, idx)

        if (
            batch_req.split_phage_regions
            and item.source_mode == "phage_discovery"
            and item.source_task_id
            and item.region_index is None
        ):
            cmap = self._load_contigs_from_phage_discovery(item.source_task_id)
            import re as _re

            region_indices: List[int] = []
            seen_idx: set[int] = set()
            for cid in cmap.keys():
                m = _re.match(r"^Phage_(\d+)", cid)
                if m:
                    r_idx = int(m.group(1))
                    if r_idx not in seen_idx:
                        seen_idx.add(r_idx)
                        region_indices.append(r_idx)
            if len(region_indices) > 1:
                stem_base = base_name[:-10] if base_name.endswith("_Structure") else base_name
                runs: List[StructureRunRequest] = []
                for r_idx in region_indices:
                    r_req = StructureRunRequest(
                        task_name=f"{stem_base}_Phage_{r_idx:03d}_Structure",
                        source_mode="phage_discovery",
                        source_task_id=item.source_task_id,
                        region_index=r_idx,
                        metadata={**(item.metadata or {}), "batch": True, "split_region": r_idx},
                        **base_kwargs,
                    )
                    self._validate_run_request(r_req)
                    runs.append(r_req)
                return runs

        if (
            batch_req.split_fasta_records
            and item.source_mode == "paste"
            and item.fasta_content
            and item.fasta_content.lstrip().startswith(">")
        ):
            records = self._split_multi_fasta_content(item.fasta_content)
            if len(records) > 1:
                runs = []
                for rec_idx, (rec_id, rec_text) in enumerate(records, start=1):
                    r_req = StructureRunRequest(
                        task_name=f"{rec_id}_Structure" if rec_id else f"{base_name}_{rec_idx:02d}",
                        source_mode="paste",
                        fasta_content=rec_text,
                        metadata={**(item.metadata or {}), "batch": True, "split_record": rec_idx},
                        **base_kwargs,
                    )
                    self._validate_run_request(r_req)
                    runs.append(r_req)
                return runs

        single_req = StructureRunRequest(
            task_name=base_name,
            source_mode=item.source_mode,
            fasta_path=item.fasta_path,
            fasta_content=item.fasta_content,
            source_task_id=item.source_task_id,
            region_index=item.region_index,
            selected_contigs=item.selected_contigs,
            metadata={**(item.metadata or {}), "batch": True},
            **base_kwargs,
        )
        self._validate_run_request(single_req)
        return [single_req]

    async def _enqueue_run_request(
        self,
        req: StructureRunRequest,
        *,
        task_id: Optional[str] = None,
        broadcast: bool = True,
    ) -> Dict[str, Any]:
        self._validate_run_request(req)
        tid = task_id or f"pstruct_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{secrets.token_hex(3)}"
        task_name = (req.task_name or "").strip() or f"PhageStructure_{tid}"
        self.db.create_task(task_id=tid, task_name=task_name, source_mode=req.source_mode, status="queued")
        q_info = await self.queue.enqueue(tid, req, {"task_name": task_name}, broadcast=broadcast)
        return {
            "task_id": tid,
            "task_name": task_name,
            "source_mode": req.source_mode,
            "status": "queued",
            **q_info,
        }

    async def submit_task(self, req: StructureRunRequest) -> Dict[str, Any]:
        return await self._enqueue_run_request(req, broadcast=True)

    async def submit_batch_tasks(self, batch_req: StructureBatchRunRequest) -> Dict[str, Any]:
        """批量校验、展开并按序将多样本推入后端串行分析队列。"""
        expanded_runs: List[StructureRunRequest] = []
        for idx, item in enumerate(batch_req.items, start=1):
            expanded_runs.extend(self._expand_batch_item_to_runs(item, batch_req, idx))

        if not expanded_runs:
            raise ValueError("批量提交列表中未解析出可分析的样本任务")

        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        batch_id = f"psbatch_{stamp}_{secrets.token_hex(3)}"
        created_items: List[Dict[str, Any]] = []
        for idx, run_req in enumerate(expanded_runs, start=1):
            run_req.metadata = {**(run_req.metadata or {}), "batch_id": batch_id, "batch_index": idx}
            tid = f"pstruct_{stamp}_{idx:03d}_{secrets.token_hex(3)}"
            item_res = await self._enqueue_run_request(run_req, task_id=tid, broadcast=False)
            created_items.append(item_res)

        await self.queue.broadcast_snapshot()
        return {
            "batch_id": batch_id,
            "batch_count": len(created_items),
            "task_ids": [it["task_id"] for it in created_items],
            "tasks": created_items,
            "queue": self.queue.get_queue_snapshot(),
        }

    async def execute_pipeline_task(self, task_id: str, req: StructureRunRequest, context: Dict[str, Any]) -> None:
        loop = asyncio.get_running_loop()

        def _emit_progress(pct: int, step_msg: str) -> None:
            self.db.update_progress(task_id, pct, step_msg, status="running")
            asyncio.run_coroutine_threadsafe(
                broadcaster.broadcast(
                    "phage_structure_progress",
                    {"task_id": task_id, "progress": pct, "current_step": step_msg, "status": "running"},
                ),
                loop,
            )

        t0 = time.perf_counter()
        task_dir = self.results_root / task_id
        task_dir.mkdir(parents=True, exist_ok=True)
        chk_dir = task_dir / "checkpoints"
        chk_dir.mkdir(parents=True, exist_ok=True)

        def _run_sync() -> PhageStructureResult:
            _emit_progress(8, "正在解析输入基因组与现有注释特征...")
            if req.source_mode == "annotation" and req.source_task_id:
                cmap = self._load_contigs_from_annotation(req.source_task_id, req.selected_contigs)
            elif req.source_mode == "phage_discovery" and req.source_task_id:
                cmap = self._load_contigs_from_phage_discovery(
                    req.source_task_id,
                    region_index=req.region_index,
                    selected_contigs=req.selected_contigs,
                )
            else:
                cmap = parse_input_contigs(
                    fasta_path=req.fasta_path,
                    fasta_content=req.fasta_content,
                    selected_contigs=req.selected_contigs,
                )

            if self.queue.is_cancelled(task_id):
                raise RuntimeError("任务已被用户取消")

            workers = get_safe_workers(req.threads)
            _emit_progress(22, f"正在并行执行 ORF 基因识别与密码表评估 (Pyrodigal, {workers} 核)...")
            predict_missing_orfs_parallel(
                cmap,
                genetic_code=req.genetic_code,
                auto_select_genetic_code=req.auto_select_genetic_code,
                workers=workers,
            )

            if self.queue.is_cancelled(task_id):
                raise RuntimeError("任务已被用户取消")

            _emit_progress(45, f"正在执行 PHROGs 序列同源校验与混淆屏障扫描 ({workers} 核)...")
            scan_proteins_with_pyhmmer(
                cmap,
                evalue_cutoff=req.evalue_cutoff,
                score_cutoff=req.score_cutoff,
                workers=workers,
                force_rescan=req.force_hmm_rescan,
                verify_annotated=True,
                hmm_thresholds=DEFAULT_THRESHOLDS.hmm,
                on_progress=lambda msg: _emit_progress(52, msg),
            )

            if self.queue.is_cancelled(task_id):
                raise RuntimeError("任务已被用户取消")

            ptf_map: Dict[str, tuple[int, List[TailFinderCluster]]] = {}
            if req.enable_phagetailfinder and is_phagetailfinder_ready():
                _emit_progress(62, f"正在运行 PhageTailFinder 双状态 HMM 尾部基因簇预测 ({workers} 核)...")
                try:
                    ptf_map = run_phagetailfinder_on_contigs(
                        cmap,
                        workers=workers,
                        accurate_mode=req.ptf_accurate_mode,
                        on_progress=lambda msg: _emit_progress(68, msg),
                    )
                except Exception as ptf_exc:
                    logger.warning("PhageTailFinder 双状态 HMM 扫描跳过: %s", ptf_exc)

            if self.queue.is_cancelled(task_id):
                raise RuntimeError("任务已被用户取消")

            _emit_progress(74, "正在剖析卷尺蛋白 (TMP) polyX/TR 特征并融合 Virfam 连接器判定...")
            contig_seqs: Dict[str, str] = {}
            eval_by_cid: Dict[str, ContigStructureResult] = {}

            for cid, info in cmap.items():
                contig_seqs[cid] = info.get("dna_seq", "")
                ptf_cnt, ptf_clusters = ptf_map.get(cid, (0, []))
                eval_by_cid[cid] = evaluate_single_contig_structure(
                    cid,
                    info,
                    ptf_cnt,
                    ptf_clusters,
                    default_genetic_code=req.genetic_code,
                    workers=workers,
                    thresholds=DEFAULT_THRESHOLDS,
                )

            if req.enable_ai_classifier and check_ai_classifier_ready(self.project_root):
                _emit_progress(77, "正在运行 UnifiedJudge V4.3 双轨 AI 形态分类与校准...")
                self._attach_ai_predictions(eval_by_cid, list(eval_by_cid.keys()))

            if req.enable_phold_enhance and req.phold_trigger_mode != "off":
                triggered_reasons: Dict[str, str] = {}
                for cid, c_res in eval_by_cid.items():
                    if req.phold_trigger_mode == "always":
                        triggered_reasons[cid] = "always_forced"
                    else:
                        should_run, reason = should_trigger_phold_3d(
                            c_res.prediction,
                            c_res.tmp_analyses,
                            c_res.length_bp,
                            thresholds=DEFAULT_THRESHOLDS.classifier,
                            ai_prediction=c_res.ai_prediction,
                        )
                        if should_run:
                            triggered_reasons[cid] = reason

                if triggered_reasons:
                    release_gpu_memory()
                    _emit_progress(80, f"正在触发 Phold 3D (ProstT5 + Foldseek) 复核 {len(triggered_reasons)} 条低确定性 Contig...")
                    rescued_map: Dict[str, int] = {}
                    enhance_with_phold_3d(
                        cmap,
                        workers=workers,
                        min_aa=DEFAULT_THRESHOLDS.classifier.phold_rescue_min_aa,
                        target_contigs=list(triggered_reasons.keys()),
                        batch_size=1,
                        omit_probs=False,
                        rescued_by_contig=rescued_map,
                        on_progress=lambda msg: _emit_progress(83, msg),
                    )
                    release_gpu_memory()
                    if self.queue.is_cancelled(task_id):
                        raise RuntimeError("任务已被用户取消")
                    for cid, reason in triggered_reasons.items():
                        ptf_cnt, ptf_clusters = ptf_map.get(cid, (0, []))
                        eval_by_cid[cid] = evaluate_single_contig_structure(
                            cid,
                            cmap[cid],
                            ptf_cnt,
                            ptf_clusters,
                            default_genetic_code=req.genetic_code,
                            workers=workers,
                            thresholds=DEFAULT_THRESHOLDS,
                            phold_triggered=True,
                            phold_trigger_reason=reason,
                            phold_rescued_orfs=rescued_map.get(cid, 0),
                        )
                    if req.enable_ai_classifier and check_ai_classifier_ready(self.project_root):
                        _emit_progress(86, "正在结合 3D 复核补注释刷新双轨 AI 预测概率...")
                        self._attach_ai_predictions(eval_by_cid, list(triggered_reasons.keys()))

            contig_results: List[ContigStructureResult] = []
            for idx, cid in enumerate(cmap.keys(), start=1):
                c_res = eval_by_cid[cid]
                contig_results.append(c_res)
                # 逐 Contig 分片落盘断点保护，防大批量任务 OOM
                shard_p = chk_dir / f"contig_{idx:03d}.json"
                shard_p.write_text(json.dumps(c_res.model_dump(), ensure_ascii=False), encoding="utf-8")

            # 按证据强弱和 Contig 长度选举整任务代表判定
            primary = max(
                contig_results,
                key=lambda c: (
                    c.prediction.morphotype_code != "Incomplete",
                    c.prediction.confidence,
                    c.length_bp,
                ),
            ).prediction

            elapsed = round(time.perf_counter() - t0, 2)
            total_bp = sum(c.length_bp for c in contig_results)
            summary = {
                "primary_morphotype": primary.morphotype_code,
                "primary_morphotype_cn": primary.morphotype_label_cn,
                "primary_confidence": primary.confidence,
                "estimated_tail_length_nm": primary.estimated_tail_length_nm,
                "contig_count": len(contig_results),
                "total_bp": total_bp,
                "total_orfs": sum(c.total_orfs for c in contig_results),
                "tmp_count": sum(len(c.tmp_analyses) for c in contig_results),
                "ptf_tail_protein_count": sum(c.ptf_tail_protein_count for c in contig_results),
                "ptf_cluster_count": sum(len(c.ptf_tail_clusters) for c in contig_results),
                "elapsed_sec": elapsed,
            }
            res_obj = PhageStructureResult(
                task_id=task_id,
                task_name=context["task_name"],
                created_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                source_mode=req.source_mode,
                elapsed_sec=elapsed,
                total_bp=total_bp,
                contig_count=len(contig_results),
                primary_prediction=primary,
                contigs=contig_results,
                summary=summary,
                files={},
            )
            _emit_progress(90, "正在导出结构报告表格与 GenBank 交互图谱文件...")
            files = export_structure_artifacts(res_obj, contig_seqs, task_dir)
            res_obj.files = files
            # 更新 JSON 内的 files 字段
            Path(files["json"]).write_text(json.dumps(res_obj.model_dump(), ensure_ascii=False, indent=2), encoding="utf-8")
            return res_obj

        try:
            final_res = await run_in_threadpool(_run_sync)
            self.db.mark_completed(
                task_id=task_id,
                summary=final_res.summary,
                files=final_res.files,
                result_path=final_res.files["json"],
            )
            await broadcaster.broadcast(
                "phage_structure_completed",
                {
                    "task_id": task_id,
                    "status": "completed",
                    "progress": 100,
                    "summary": final_res.summary,
                },
            )
        except Exception as exc:
            if self.queue.is_cancelled(task_id):
                self.db.mark_cancelled(task_id)
                await broadcaster.broadcast(
                    "phage_structure_error",
                    {"task_id": task_id, "error": "任务已取消", "status": "cancelled"},
                )
            else:
                raise
        finally:
            release_gpu_memory()

    def list_history(self, limit: int = 100) -> List[Dict[str, Any]]:
        return self.db.list_history(limit=limit)

    def get_task_result(self, task_id: str) -> Dict[str, Any]:
        task = self.db.get_task(task_id)
        if not task:
            raise FileNotFoundError(f"未找到结构预测任务: {task_id}")
        res_path = Path(task.get("result_path") or "")
        if not res_path.is_file():
            fallback = self.results_root / task_id / "structure_report.json"
            if fallback.is_file():
                res_path = fallback
            else:
                raise FileNotFoundError(f"结果报告尚不存在或已移除: {task_id}")
        return json.loads(res_path.read_text(encoding="utf-8"))

    def get_task_gbk(self, task_id: str) -> Dict[str, Any]:
        task = self.db.get_task(task_id)
        if not task:
            raise FileNotFoundError(f"未找到任务: {task_id}")
        gbk_p = Path((task.get("files") or {}).get("gbk") or (self.results_root / task_id / "annotated_structure.gbk"))
        if not gbk_p.is_file():
            raise FileNotFoundError("当前任务未包含可供图谱打开的核酸序列 GenBank 文件")
        return {
            "gbkText": gbk_p.read_text(encoding="utf-8"),
            "taskName": task.get("task_name") or task_id,
        }

    def resolve_task_file(self, task_id: str, file_type: str) -> Path:
        task = self.db.get_task(task_id)
        if not task:
            raise FileNotFoundError(f"未找到任务: {task_id}")
        task_dir = self.results_root / task_id
        if file_type == "folder":
            if not task_dir.is_dir():
                raise FileNotFoundError(f"任务目录不存在: {task_dir}")
            return task_dir
        fmap = task.get("files") or {}
        if file_type in fmap and Path(fmap[file_type]).is_file():
            return Path(fmap[file_type])
        default_names = {
            "json": "structure_report.json",
            "summary_tsv": "morphotype_summary.tsv",
            "features_tsv": "structure_features.tsv",
            "tmp_tsv": "tmp_analysis.tsv",
            "gbk": "annotated_structure.gbk",
        }
        cand = task_dir / default_names.get(file_type, "")
        if cand.is_file():
            return cand
        raise FileNotFoundError(f"未找到 {file_type} 导出产物")

    async def cancel_task(self, task_id: str) -> Dict[str, Any]:
        return await self.queue.cancel_task(task_id)

    def delete_task(self, task_id: str) -> None:
        self.queue.remove_from_waiting(task_id)
        task_dir = self.results_root / task_id
        if task_dir.is_dir():
            shutil.rmtree(task_dir, ignore_errors=True)
        self.db.delete_task(task_id)


_STRUCTURE_MANAGER: Optional[PhageStructureManager] = None


def get_phage_structure_manager() -> PhageStructureManager:
    global _STRUCTURE_MANAGER
    if _STRUCTURE_MANAGER is None:
        _STRUCTURE_MANAGER = PhageStructureManager()
    return _STRUCTURE_MANAGER
