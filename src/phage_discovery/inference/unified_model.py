# -*- coding: utf-8 -*-
"""
统一分区分化与按需条件激活噬菌体发现模型 (`UnifiedPhageModel`)。

设计哲学（共享基础知识底座 + 内部功能分化 + 运行时按需激活）：
1. 两大基础设施底座：
   - DNA 基因组底座 (Stage 1.2 ResNet+BiGRU+Tab)：高效掠过全基因组提取 5kb/200bp 序列与边界表征；
   - 蛋白折叠与操纵子底座 (UnifiedJudge)：仅在必要时被唤醒，共享一次序列编码与操纵子相对注意力前向计算 `h_base`。
2. 内部分化专家路由 (`active_experts`)：
   - `"boundary"`：DNA 200bp SubBin 断点精修边界；
   - `"gray_rescue"`：从 200bp SubBin 提取压低分的隐蔽短碎片并触发专家二审；
   - `"defense_func"`：经操纵子宏观态势调控 + Logit 校准的 10 类精准功能分区与 P9 防御排雷；
   - `"intact"`：直连未经宏观平滑的共享底座高保真旁路，保持结构完整度高区分度 (`Intact_AUROC`)。
"""
from __future__ import annotations

import concurrent.futures
import gc
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

import numpy as np

from ..benchmark.metrics import PredictedRegion, WindowPrediction, decode_subwindow_probs_to_regions
from ..experts.seq_dataset import encode_dna
from .judge_region_refiner import (
    extract_contig_orfs_pyrodigal,
    extract_subbin_gray_candidates,
    load_judge_ensemble_bundle,
    rescue_and_filter_regions_with_judge,
    score_contigs_with_judge_bundle,
    summarize_region_with_judge,
)
from .report_exporter import export_unified_scan_outputs
from .scanner import (
    GenomeScanner,
    _collect_contig_score_tracks,
    _collect_region_profiles,
    _extract_contig_worker,
    iter_fasta,
)

ALL_UNIFIED_EXPERTS: Tuple[str, ...] = ("boundary", "gray_rescue", "defense_func", "intact")


def _resolve_safe_workers(requested: int) -> int:
    """保留部分 CPU 核心防止长时间满载导致主机卡死。"""
    cpu_cnt = os.cpu_count() or 4
    safe_cap = max(1, cpu_cnt - 2)
    return max(1, min(int(requested), safe_cap))


def _release_accelerator_memory() -> None:
    gc.collect()
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except ImportError:
        pass


@dataclass
class UnifiedScanResult:
    """统一按需激活模型扫描输出与资源路由统计。"""

    contigs_bp: Dict[str, int]
    total_bp: int
    total_windows: int
    base_regions: List[PredictedRegion]
    regions: List[PredictedRegion]
    region_annotations: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    routing_stats: Dict[str, Any] = field(default_factory=dict)
    timings_sec: Dict[str, float] = field(default_factory=dict)
    suppressed_candidates: List[Dict[str, Any]] = field(default_factory=list)
    region_profiles: Dict[str, List[Dict[str, Any]]] = field(default_factory=dict)
    contig_score_tracks: Dict[str, List[Dict[str, Any]]] = field(default_factory=dict)


class UnifiedPhageModel:
    """共享底座、内部分化与条件激活的统一前噬菌体精准发现模型。"""

    def __init__(
        self,
        dna_scanner: GenomeScanner,
        judge_bundle: Optional[Dict[str, Any]] = None,
        *,
        active_experts: Sequence[str] = ALL_UNIFIED_EXPERTS,
    ):
        self.dna_scanner = dna_scanner
        self.judge_bundle = judge_bundle
        self.active_experts: Set[str] = set(active_experts)

    @classmethod
    def from_models_root(
        cls,
        models_v4_root: Path,
        *,
        stage1_2_subdir: str = "stage1_2",
        workers: int = 16,
        device: str = "cuda",
        active_experts: Sequence[str] = ALL_UNIFIED_EXPERTS,
        prefer_unified_judge: bool = True,
    ) -> "UnifiedPhageModel":
        root = Path(models_v4_root).resolve()
        dna_scanner = GenomeScanner.from_model_dir(root / stage1_2_subdir, workers=workers, device=device)
        need_protein = bool(set(active_experts) - {"boundary"})
        bundle = (
            load_judge_ensemble_bundle(root, device=device, prefer_unified=prefer_unified_judge)
            if need_protein
            else None
        )
        return cls(dna_scanner=dna_scanner, judge_bundle=bundle, active_experts=active_experts)

    def _run_dna_backbone(
        self,
        contig_seqs: Dict[str, str],
        *,
        executor: Optional[concurrent.futures.Executor] = None,
    ) -> Tuple[List[WindowPrediction], np.ndarray, Any, List[PredictedRegion], Dict[str, float]]:
        scanner = self.dna_scanner
        t_f0 = time.perf_counter()
        extract_orfs = scanner.model_version == "v4"
        tasks = [
            (cid, seq, scanner.win_size, scanner.step_size, extract_orfs, scanner.feature_profile)
            for cid, seq in contig_seqs.items()
        ]
        safe_workers = _resolve_safe_workers(scanner.workers)
        extracted = []
        if len(tasks) > 1 and safe_workers > 1:
            if executor is not None:
                for res in executor.map(_extract_contig_worker, tasks):
                    extracted.append(res)
            else:
                with concurrent.futures.ProcessPoolExecutor(max_workers=min(safe_workers, len(tasks))) as ex:
                    for res in ex.map(_extract_contig_worker, tasks):
                        extracted.append(res)
        else:
            for t in tasks:
                extracted.append(_extract_contig_worker(t))
        feat_sec = round(time.perf_counter() - t_f0, 3)

        t_d0 = time.perf_counter()
        win_preds: List[WindowPrediction] = []
        feats_list, codes_list, len_list, orf_tk_list, orf_cn_list = [], [], [], [], []
        cid_list, start_list, end_list = [], [], []
        for item in extracted:
            cid = item["contig_id"]
            seq_up = contig_seqs[cid].upper()
            feats_list.append(item["features"])
            if extract_orfs and "orf_tokens" in item:
                orf_tk_list.append(item["orf_tokens"])
                orf_cn_list.append(item["orf_counts"])
            for s, e in zip(item["starts"], item["ends"]):
                sub = seq_up[int(s) : int(e)]
                enc = np.full(scanner.win_size, 4, dtype=np.uint8)
                raw = encode_dna(sub)[: scanner.win_size]
                enc[: len(raw)] = raw
                codes_list.append(enc)
                len_list.append(len(raw))
                cid_list.append(cid)
                start_list.append(int(s))
                end_list.append(int(e))
                win_preds.append(WindowPrediction(contig_id=cid, start_bp=int(s), end_bp=int(e), score=0.0))

        sub_probs = np.zeros((0, 25), dtype=np.float32)
        subbin_profiles: Any = None
        if feats_list:
            win_scores, sub_probs, subbin_profiles = scanner._predict_windows_with_profiles(
                np.stack(codes_list, axis=0),
                np.asarray(len_list, dtype=np.int64),
                np.concatenate(feats_list, axis=0),
                orf_tokens=np.concatenate(orf_tk_list, axis=0) if orf_tk_list else None,
                orf_counts=np.concatenate(orf_cn_list, axis=0) if orf_cn_list else None,
                contig_ids=np.asarray(cid_list),
                starts=np.asarray(start_list, dtype=np.int64),
                ends=np.asarray(end_list, dtype=np.int64),
                return_orf_preds=False,
            )
            for idx, wp in enumerate(win_preds):
                wp.score = float(win_scores[idx])

        has_prof = bool(subbin_profiles)
        smooth_p = scanner.smooth_sub_profile if scanner.smooth_sub_profile is not None else (not has_prof)
        refine_pad = scanner.refine_pad_bp if scanner.refine_pad_bp is not None else 3000
        base_regions = decode_subwindow_probs_to_regions(
            win_preds,
            sub_probs,
            seed_threshold=scanner.seed_threshold,
            extend_threshold=scanner.extend_threshold,
            sub_threshold=scanner.sub_threshold,
            merge_gap_bp=scanner.merge_gap_bp,
            min_region_bp=scanner.min_region_bp,
            plateau_min_windows=scanner.plateau_min_windows,
            plateau_second_threshold=scanner.plateau_second_threshold,
            precomputed_bin_profiles=subbin_profiles,
            smooth_profile=smooth_p,
            refine_pad_bp=refine_pad,
        )
        dna_sec = round(time.perf_counter() - t_d0, 3)
        return win_preds, sub_probs, subbin_profiles, base_regions, {"dna_feature_sec": feat_sec, "dna_infer_decode_sec": dna_sec}

    def scan_sequences(
        self,
        contig_seqs: Dict[str, str],
        *,
        active_experts: Optional[Sequence[str]] = None,
        precomputed_orfs: Optional[Dict[str, List[Tuple[int, int, int, str]]]] = None,
        executor: Optional[concurrent.futures.Executor] = None,
        collect_profiles: bool = False,
        profile_flank_bp: int = 2000,
        collect_score_tracks: bool = False,
    ) -> UnifiedScanResult:
        """
        对给定 Contig 序列字典执行共享底座 + 条件按需激活扫描。
        仅在存在主区段或灰区候选的少数 Contig 上才唤醒蛋白知识底座，零浪费算力。
        """
        experts = set(active_experts) if active_experts is not None else set(self.active_experts)
        contigs_bp = {cid: len(seq) for cid, seq in contig_seqs.items()}
        total_bp = sum(contigs_bp.values())

        win_preds, sub_probs, subbin_profiles, base_regions, t_dna = (
            self._run_dna_backbone(contig_seqs, executor=executor)
            if executor is not None
            else self._run_dna_backbone(contig_seqs)
        )

        need_gray = "gray_rescue" in experts
        gray_cands = (
            extract_subbin_gray_candidates(
                win_preds,
                sub_probs,
                min_region_bp=5000,
                min_peak_sub_prob=0.90,
                min_mean_sub_prob=0.80,
            )
            if need_gray
            else []
        )

        # 按需条件激活蛋白知识底座：仅唤醒存在主区段或灰区候选的 Contig
        need_protein_experts = bool(experts & {"gray_rescue", "defense_func", "intact"}) and self.judge_bundle is not None
        activated_cids = sorted({r.contig_id for r in base_regions} | {r.contig_id for r in gray_cands})

        t_p0 = time.perf_counter()
        final_regions = list(base_regions)
        region_annotations: Dict[str, Dict[str, Any]] = {}
        suppressed_candidates: List[Dict[str, Any]] = []
        rescue_stats: Dict[str, int] = {
            "base_kept": len(base_regions),
            "base_vetoed": 0,
            "gray_candidates": 0,
            "gray_rescued": 0,
            "gray_rejected": 0,
            "topology_bridged": 0,
            "topology_split": 0,
        }
        per_contig_windows: Dict[str, int] = {}
        for wp in win_preds:
            per_contig_windows[wp.contig_id] = per_contig_windows.get(wp.contig_id, 0) + 1

        if need_protein_experts and activated_cids:
            assert self.judge_bundle is not None
            if precomputed_orfs is not None:
                orfs_map = {cid: precomputed_orfs.get(cid, []) for cid in activated_cids}
            else:
                orfs_map = extract_contig_orfs_pyrodigal(
                    contig_seqs,
                    contig_ids=activated_cids,
                    workers=_resolve_safe_workers(self.dna_scanner.workers),
                )

            prot_exp_list = []
            if "defense_func" in experts or "gray_rescue" in experts:
                prot_exp_list.append("defense_func")
            if "intact" in experts:
                prot_exp_list.append("intact")

            scored = score_contigs_with_judge_bundle(
                self.judge_bundle,
                orfs_map,
                contig_ids=activated_cids,
                batch_size=32,
                active_experts=prot_exp_list,
            )

            if need_gray or "defense_func" in experts:
                final_regions, rescue_stats = rescue_and_filter_regions_with_judge(
                    base_regions,
                    gray_cands if need_gray else [],
                    orfs_map,
                    scored,
                    suppressed_out=suppressed_candidates,
                )

            if "defense_func" in experts or "intact" in experts:
                for reg in final_regions:
                    key = f"{reg.contig_id}:{reg.start_bp}-{reg.end_bp}"
                    if reg.contig_id in orfs_map and reg.contig_id in scored:
                        region_annotations[key] = summarize_region_with_judge(
                            reg,
                            orfs_map[reg.contig_id],
                            scored[reg.contig_id],
                        )

        protein_sec = round(time.perf_counter() - t_p0, 3)
        total_contigs = max(1, len(contig_seqs))
        routing_stats = {
            "total_contigs": len(contig_seqs),
            "protein_activated_contigs": len(activated_cids) if need_protein_experts else 0,
            "protein_skip_ratio": round(
                1.0 - (float(len(activated_cids)) / float(total_contigs) if need_protein_experts else 0.0),
                4,
            ),
            "active_experts": sorted(experts),
            "unified_judge_mode": bool(self.judge_bundle and self.judge_bundle.get("unified_mode", False)),
            "rescue_stats": rescue_stats,
            "activated_contig_ids": activated_cids if need_protein_experts else [],
            "windows_by_contig": per_contig_windows,
        }
        timings = dict(t_dna)
        timings["protein_judge_sec"] = protein_sec
        timings["total_sec"] = round(sum(timings.values()), 3)

        region_profiles: Dict[str, List[Dict[str, Any]]] = {}
        if collect_profiles and final_regions and len(sub_probs) > 0:
            raw_smooth = getattr(self.dna_scanner, "smooth_sub_profile", None)
            smooth_p = bool(raw_smooth) if raw_smooth is not None else (not bool(subbin_profiles))
            region_profiles = _collect_region_profiles(
                win_preds,
                sub_probs,
                subbin_profiles,
                final_regions,
                contigs_bp,
                smooth_profile=smooth_p,
                flank_bp=int(profile_flank_bp),
            )

        score_tracks: Dict[str, List[Dict[str, Any]]] = (
            _collect_contig_score_tracks(win_preds, contigs_bp)
            if collect_score_tracks and win_preds
            else {}
        )

        return UnifiedScanResult(
            contigs_bp=contigs_bp,
            total_bp=total_bp,
            total_windows=len(win_preds),
            base_regions=base_regions,
            regions=final_regions,
            region_annotations=region_annotations,
            routing_stats=routing_stats,
            timings_sec=timings,
            suppressed_candidates=suppressed_candidates,
            region_profiles=region_profiles,
            contig_score_tracks=score_tracks,
        )

    def scan_fasta(
        self,
        fasta_path: Path,
        *,
        active_experts: Optional[Sequence[str]] = None,
        precomputed_orfs: Optional[Dict[str, List[Tuple[int, int, int, str]]]] = None,
    ) -> UnifiedScanResult:
        contig_seqs = {cid: seq for cid, seq in iter_fasta(Path(fasta_path))}
        return self.scan_sequences(
            contig_seqs,
            active_experts=active_experts,
            precomputed_orfs=precomputed_orfs,
        )

    @staticmethod
    def _region_to_dict(reg: PredictedRegion) -> Dict[str, Any]:
        return {
            "contig_id": reg.contig_id,
            "start_bp": int(reg.start_bp),
            "end_bp": int(reg.end_bp),
            "peak_score": float(reg.peak_score),
            "mean_score": float(reg.mean_score),
            "window_count": int(reg.window_count),
        }

    @staticmethod
    def _dict_to_region(obj: Dict[str, Any]) -> PredictedRegion:
        return PredictedRegion(
            contig_id=str(obj["contig_id"]),
            start_bp=int(obj["start_bp"]),
            end_bp=int(obj["end_bp"]),
            peak_score=float(obj["peak_score"]),
            mean_score=float(obj["mean_score"]),
            window_count=int(obj["window_count"]),
        )

    def _flush_streaming_chunk(
        self,
        chunk_seqs: Dict[str, str],
        *,
        active_experts: Optional[Sequence[str]],
        executor: Optional[concurrent.futures.Executor],
        chunks_jsonl: Path,
        ckpt_path: Path,
        completed_set: Set[str],
        timings_acc: Dict[str, float],
    ) -> None:
        chunk_res = self.scan_sequences(
            chunk_seqs,
            active_experts=active_experts,
            executor=executor,
        )
        for tk in ("dna_feature_sec", "dna_infer_decode_sec", "protein_judge_sec", "total_sec"):
            timings_acc[tk] = round(timings_acc.get(tk, 0.0) + float(chunk_res.timings_sec.get(tk, 0.0)), 3)

        base_by_cid: Dict[str, List[Dict[str, Any]]] = {cid: [] for cid in chunk_seqs}
        for reg in chunk_res.base_regions:
            base_by_cid.setdefault(reg.contig_id, []).append(self._region_to_dict(reg))

        final_by_cid: Dict[str, List[Dict[str, Any]]] = {cid: [] for cid in chunk_seqs}
        ann_by_cid: Dict[str, Dict[str, Dict[str, Any]]] = {cid: {} for cid in chunk_seqs}
        for reg in chunk_res.regions:
            final_by_cid.setdefault(reg.contig_id, []).append(self._region_to_dict(reg))
            key = f"{reg.contig_id}:{reg.start_bp}-{reg.end_bp}"
            if key in chunk_res.region_annotations:
                ann_by_cid.setdefault(reg.contig_id, {})[key] = chunk_res.region_annotations[key]

        supp_by_cid: Dict[str, List[Dict[str, Any]]] = {cid: [] for cid in chunk_seqs}
        for item in chunk_res.suppressed_candidates:
            supp_by_cid.setdefault(str(item["contig_id"]), []).append(item)

        act_set = set(chunk_res.routing_stats.get("activated_contig_ids", []))
        win_by_cid = chunk_res.routing_stats.get("windows_by_contig", {})
        with chunks_jsonl.open("a", encoding="utf-8", newline="\n") as fh:
            for idx, (cid, seq) in enumerate(chunk_seqs.items()):
                rec: Dict[str, Any] = {
                    "contig_id": cid,
                    "bp": len(seq),
                    "windows": int(win_by_cid.get(cid, 0)),
                    "protein_activated": cid in act_set,
                    "base_regions": base_by_cid.get(cid, []),
                    "regions": final_by_cid.get(cid, []),
                    "region_annotations": ann_by_cid.get(cid, {}),
                    "suppressed_candidates": supp_by_cid.get(cid, []),
                }
                if idx == 0:
                    rec["chunk_rescue_stats"] = chunk_res.routing_stats.get("rescue_stats", {})
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
                completed_set.add(cid)

        tmp_ckpt = ckpt_path.with_name(f".{ckpt_path.name}.tmp")
        ckpt_payload = {
            "completed_contigs": sorted(completed_set),
            "timings_sec": timings_acc,
        }
        tmp_ckpt.write_text(json.dumps(ckpt_payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp_ckpt.replace(ckpt_path)

        del chunk_res
        _release_accelerator_memory()

    def scan_fasta_streaming(
        self,
        fasta_path: Path,
        out_dir: Path,
        *,
        chunk_max_bp: int = 10_000_000,
        active_experts: Optional[Sequence[str]] = None,
        resume: bool = True,
        export_outputs: bool = True,
    ) -> UnifiedScanResult:
        """
        流式分片扫描大体积 FASTA 并持久复用进程池，支持按 Contig 断点续跑与标准产物导出。
        """
        fa_path = Path(fasta_path)
        out_root = Path(out_dir)
        out_root.mkdir(parents=True, exist_ok=True)
        chunks_jsonl = out_root / "chunks.jsonl"
        ckpt_path = out_root / "checkpoint.json"

        completed_set: Set[str] = set()
        timings_acc: Dict[str, float] = {
            "dna_feature_sec": 0.0,
            "dna_infer_decode_sec": 0.0,
            "protein_judge_sec": 0.0,
            "total_sec": 0.0,
        }
        if resume and ckpt_path.is_file() and chunks_jsonl.is_file():
            ckpt_obj = json.loads(ckpt_path.read_text(encoding="utf-8"))
            completed_set = set(str(x) for x in ckpt_obj.get("completed_contigs", []))
            timings_acc.update({k: float(v) for k, v in ckpt_obj.get("timings_sec", {}).items()})
        else:
            if chunks_jsonl.exists():
                chunks_jsonl.unlink()
            if ckpt_path.exists():
                ckpt_path.unlink()

        experts = set(active_experts) if active_experts is not None else set(self.active_experts)
        safe_workers = _resolve_safe_workers(self.dna_scanner.workers)

        pool_ctx: Any = None
        pool: Any = None

        def _ensure_pool() -> Any:
            nonlocal pool_ctx, pool
            if pool is None and safe_workers > 1:
                pool_ctx = concurrent.futures.ProcessPoolExecutor(max_workers=safe_workers)
                pool = pool_ctx.__enter__()
            return pool

        try:
            cur_chunk: Dict[str, str] = {}
            cur_bp = 0
            for cid, seq in iter_fasta(fa_path):
                if cid in completed_set:
                    continue
                seq_len = len(seq)
                if cur_chunk and (cur_bp + seq_len) > int(chunk_max_bp):
                    self._flush_streaming_chunk(
                        cur_chunk,
                        active_experts=active_experts,
                        executor=_ensure_pool(),
                        chunks_jsonl=chunks_jsonl,
                        ckpt_path=ckpt_path,
                        completed_set=completed_set,
                        timings_acc=timings_acc,
                    )
                    cur_chunk = {}
                    cur_bp = 0
                cur_chunk[cid] = seq
                cur_bp += seq_len
            if cur_chunk:
                self._flush_streaming_chunk(
                    cur_chunk,
                    active_experts=active_experts,
                    executor=_ensure_pool(),
                    chunks_jsonl=chunks_jsonl,
                    ckpt_path=ckpt_path,
                    completed_set=completed_set,
                    timings_acc=timings_acc,
                )
        finally:
            if pool_ctx is not None:
                pool_ctx.__exit__(None, None, None)

        contigs_bp: Dict[str, int] = {}
        total_windows = 0
        activated_cnt = 0
        base_regions: List[PredictedRegion] = []
        final_regions: List[PredictedRegion] = []
        region_annotations: Dict[str, Dict[str, Any]] = {}
        suppressed_all: List[Dict[str, Any]] = []
        rescue_acc: Dict[str, int] = {
            "base_kept": 0,
            "base_vetoed": 0,
            "gray_candidates": 0,
            "gray_rescued": 0,
            "gray_rejected": 0,
            "topology_bridged": 0,
            "topology_split": 0,
        }

        if chunks_jsonl.is_file():
            seen_cids: Set[str] = set()
            with chunks_jsonl.open("r", encoding="utf-8") as fh:
                for line in fh:
                    line_s = line.strip()
                    if not line_s:
                        continue
                    rec = json.loads(line_s)
                    cid = str(rec["contig_id"])
                    if cid in seen_cids or (completed_set and cid not in completed_set):
                        continue
                    seen_cids.add(cid)
                    contigs_bp[cid] = int(rec["bp"])
                    total_windows += int(rec.get("windows", 0))
                    if rec.get("protein_activated"):
                        activated_cnt += 1
                    base_regions.extend(self._dict_to_region(x) for x in rec.get("base_regions", []))
                    final_regions.extend(self._dict_to_region(x) for x in rec.get("regions", []))
                    region_annotations.update(rec.get("region_annotations", {}))
                    suppressed_all.extend(rec.get("suppressed_candidates", []))
                    for rk in rescue_acc:
                        rescue_acc[rk] += int(rec.get("chunk_rescue_stats", {}).get(rk, 0))

        total_bp = sum(contigs_bp.values())
        total_contigs = max(1, len(contigs_bp))
        need_protein = bool(experts & {"gray_rescue", "defense_func", "intact"}) and self.judge_bundle is not None
        routing_stats = {
            "total_contigs": len(contigs_bp),
            "protein_activated_contigs": activated_cnt if need_protein else 0,
            "protein_skip_ratio": round(
                1.0 - (float(activated_cnt) / float(total_contigs) if need_protein else 0.0),
                4,
            ),
            "active_experts": sorted(experts),
            "unified_judge_mode": bool(self.judge_bundle and self.judge_bundle.get("unified_mode", False)),
            "rescue_stats": rescue_acc,
            "streaming_chunk_max_bp": int(chunk_max_bp),
        }

        if export_outputs:
            export_unified_scan_outputs(
                out_root,
                regions=final_regions,
                region_annotations=region_annotations,
                routing_stats=routing_stats,
                timings_sec=timings_acc,
                total_bp=total_bp,
                total_windows=total_windows,
                source_fasta_path=fa_path,
                suppressed_candidates=suppressed_all,
            )

        return UnifiedScanResult(
            contigs_bp=contigs_bp,
            total_bp=total_bp,
            total_windows=total_windows,
            base_regions=base_regions,
            regions=final_regions,
            region_annotations=region_annotations,
            routing_stats=routing_stats,
            timings_sec=timings_acc,
            suppressed_candidates=suppressed_all,
        )

