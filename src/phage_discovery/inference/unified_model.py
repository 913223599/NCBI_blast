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
from ...utils.resource_guard import get_safe_cpu_budget
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set, Tuple

import numpy as np

from ..benchmark.metrics import (
    PredictedRegion,
    WindowPrediction,
    assemble_contig_subbin_profile,
    decode_subwindow_probs_to_regions,
)
from ..experts.seq_dataset import encode_dna
from ..features.window_features import compute_sequence_global_context
from .att_boundary_refiner import AttAlignmentHit, refine_regions_with_att_sites
from .judge_region_refiner import (
    absorb_companion_subbin_peaks,
    close_flanks_to_integrase_anchors,
    snap_split_core_orfs,
    bridge_complementary_phage_fragments,
    extract_contig_orfs_pyrodigal,
    extract_subbin_gray_candidates,
    load_judge_ensemble_bundle,
    reconcile_tentative_siblings,
    refine_region_boundaries_bimodal,
    rescue_and_filter_regions_with_judge,
    resolve_unified_version_tag,
    score_contigs_with_judge_bundle,
    split_tandem_prophage_regions,
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
    return get_safe_cpu_budget(requested=requested, reserve_cores=2)


def _release_accelerator_memory() -> None:
    gc.collect()
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except ImportError:
        pass


def _build_active_contig_subbin_profiles(
    win_preds: Sequence[WindowPrediction],
    sub_probs: np.ndarray,
    subbin_profiles: Optional[Dict[str, List[Tuple[int, np.ndarray]]]],
    contigs_bp: Dict[str, int],
    target_cids: Sequence[str],
    *,
    smooth_profile: bool,
    bin_bp: int = 200,
) -> Dict[str, np.ndarray]:
    """仅为命中活性候选的 Contig 构建每 200 bp 连续 SubBin 置信度轨迹，避免对大量阴性序列开销。"""
    if not target_cids or not win_preds or len(sub_probs) == 0:
        return {}
    target_set = set(target_cids)
    by_cid_idx: Dict[str, List[int]] = defaultdict(list)
    for idx, wp in enumerate(win_preds):
        if wp.contig_id in target_set:
            by_cid_idx[wp.contig_id].append(idx)

    out: Dict[str, np.ndarray] = {}
    for cid, idxs in by_cid_idx.items():
        c_wps = [win_preds[i] for i in idxs]
        c_subs = [sub_probs[i] for i in idxs]
        c_len = contigs_bp.get(cid, max(wp.end_bp for wp in c_wps))
        pre = subbin_profiles.get(cid) if subbin_profiles else None
        out[cid] = assemble_contig_subbin_profile(
            c_wps,
            c_subs,
            c_len,
            bin_bp=bin_bp,
            precomputed_segments=pre,
            smooth_profile=smooth_profile,
        )
    return out


def _resolve_unified_model_meta(
    dna_scanner: Any,
    judge_bundle: Optional[Dict[str, Any]],
) -> Tuple[str, str]:
    """统一解析当前挂载引擎的版本标签与蛋白裁判架构名。"""
    s12_meta: Dict[str, Any] = {}
    pt_path = getattr(dna_scanner, "model_pt_path", None)
    if pt_path:
        try:
            meta_cand = Path(pt_path).resolve().parent / "stage1_2_meta.json"
            if meta_cand.is_file():
                obj = json.loads(meta_cand.read_text(encoding="utf-8"))
                if isinstance(obj, dict):
                    s12_meta = obj
        except Exception:
            s12_meta = {}

    if judge_bundle is None:
        dna_ver = str(getattr(dna_scanner, "model_version", "v4") or "v4")
        prof = str(getattr(dna_scanner, "feature_profile", "") or "")
        return ("Stage 1.2" if prof == "stage1" else f"DNA ({dna_ver})"), ""

    judge_arch = str(judge_bundle.get("judge_arch") or "").strip()
    if not judge_arch:
        m_seq = judge_bundle.get("r3_seq")
        judge_arch = str(getattr(m_seq, "arch", "") or ("unified" if judge_bundle.get("unified_mode") else "r3"))

    explicit = str(judge_bundle.get("model_version") or "").strip()
    if explicit:
        return explicit, judge_arch

    uni_meta = dict(judge_bundle.get("judge_summary_meta") or {})
    if not uni_meta.get("arch") and judge_arch:
        uni_meta["arch"] = judge_arch
    if judge_bundle.get("unified_mode"):
        return resolve_unified_version_tag(uni_meta, s12_meta), judge_arch
    return "R3+R2 Ensemble", judge_arch


def plan_long_contig_segments(
    seq_len: int,
    chunk_max_bp: int,
    win_size: int = 5000,
    overlap_bp: Optional[int] = None,
) -> List[Tuple[int, int]]:
    """
    为超过 chunk_max_bp 的单条超长 Contig 规划带重叠缓冲带的滑动分片区间 [(seg_start, seg_end), ...]。
    """
    if seq_len <= 0:
        return []
    win_unit = max(1, win_size)
    seg_len = max(win_unit, max(1, chunk_max_bp))
    if seq_len <= seg_len:
        return [(0, seq_len)]

    if overlap_bp is None:
        ov = min(200_000, max(win_unit * 2, seg_len // 4))
    else:
        ov = overlap_bp
    ov = max(0, min(ov, seg_len - win_unit))
    stride = max(win_unit, seg_len - ov)
    min_tail = min(seg_len, max(win_unit * 4, ov * 2))

    segments: List[Tuple[int, int]] = []
    pos = 0
    while pos < seq_len:
        if pos + seg_len >= seq_len:
            rem = seq_len - pos
            if segments and rem < min_tail:
                tail_s = max(0, seq_len - min_tail)
                if tail_s <= segments[-1][0]:
                    break
                segments.append((tail_s, seq_len))
            else:
                segments.append((pos, seq_len))
            break
        segments.append((pos, pos + seg_len))
        pos += stride
    return segments


def _compute_segment_ownership(
    segments: Sequence[Tuple[int, int]],
    total_bp: int,
) -> List[Tuple[int, int]]:
    """根据相邻分段重叠区中点划分各分段的主导归属坐标区间。"""
    n_seg = len(segments)
    if n_seg == 0:
        return []
    mids = [
        (segments[i + 1][0] + segments[i][1]) // 2
        for i in range(n_seg - 1)
    ]
    ownership: List[Tuple[int, int]] = []
    for idx in range(n_seg):
        own_s = 0 if idx == 0 else mids[idx - 1]
        own_e = total_bp if idx + 1 == n_seg else mids[idx]
        ownership.append((own_s, own_e))
    return ownership


@dataclass
class _SegRegionItem:
    reg: PredictedRegion
    seg_idx: int
    clearance: int
    in_own_core: bool
    ann: Optional[Dict[str, Any]]


def _reconcile_segmented_region_list(
    contig_id: str,
    seg_records: Sequence[Dict[str, Any]],
    *,
    region_field: str,
    ann_field: Optional[str],
    merge_gap_bp: int,
) -> Tuple[List[PredictedRegion], Dict[str, Dict[str, Any]]]:
    """跨超长 Contig 重叠分段去重并择优保留离人为切口更远的完整区段。"""
    raw_items: List[_SegRegionItem] = []
    for rec in seg_records:
        seg_idx = int(rec.get("segment_idx", 0))
        seg_count = int(rec.get("segment_count", 1))
        seg_s = int(rec.get("seg_start", 0))
        seg_e = int(rec.get("seg_end") if rec.get("seg_end") is not None else (rec.get("bp") or 0))
        own_s = int(rec.get("own_start", seg_s))
        own_e = int(rec.get("own_end", seg_e))
        anns = rec.get(ann_field, {}) if ann_field else {}

        for r_obj in rec.get(region_field, []):
            reg = UnifiedPhageModel._dict_to_region(r_obj)
            center = 0.5 * (reg.start_bp + reg.end_bp)
            in_own = (own_s <= center < own_e) or (seg_idx + 1 == seg_count and center <= own_e)
            left_clear = (reg.start_bp - seg_s) if seg_idx > 0 else 1_000_000_000
            right_clear = (seg_e - reg.end_bp) if (seg_idx + 1 < seg_count) else 1_000_000_000
            clearance = min(left_clear, right_clear)
            key = f"{contig_id}:{reg.start_bp}-{reg.end_bp}"
            raw_items.append(
                _SegRegionItem(
                    reg=reg,
                    seg_idx=seg_idx,
                    clearance=clearance,
                    in_own_core=in_own,
                    ann=anns.get(key) if isinstance(anns, dict) else None,
                )
            )

    if not raw_items:
        return [], {}

    filtered = [it for it in raw_items if it.in_own_core or it.clearance >= 1000]
    candidates = filtered if filtered else raw_items
    candidates.sort(key=lambda it: (it.reg.start_bp, it.reg.end_bp, -it.clearance))

    def _rank(it: _SegRegionItem) -> Tuple[int, int, int, int, float]:
        span = it.reg.end_bp - it.reg.start_bp
        return (1 if it.clearance >= 1500 else 0, 1 if it.in_own_core else 0, min(it.clearance, 50_000), span, it.reg.peak_score)

    winners: List[_SegRegionItem] = []
    for cur in candidates:
        if winners:
            prev = winners[-1]
            ov_bp = min(prev.reg.end_bp, cur.reg.end_bp) - max(prev.reg.start_bp, cur.reg.start_bp)
            near_gap = cur.reg.start_bp - prev.reg.end_bp
            across_segs = prev.seg_idx != cur.seg_idx
            boundary_adjacent = across_segs and near_gap <= min(500, merge_gap_bp) and (
                prev.clearance < 1500 or cur.clearance < 1500
            )
            if across_segs and (ov_bp > 0 or boundary_adjacent):
                if _rank(cur) > _rank(prev):
                    winners[-1] = cur
                continue
        winners.append(cur)

    out_regs: List[PredictedRegion] = []
    out_anns: Dict[str, Dict[str, Any]] = {}
    for it in winners:
        out_regs.append(it.reg)
        if it.ann is not None:
            out_anns[f"{contig_id}:{it.reg.start_bp}-{it.reg.end_bp}"] = it.ann
    return out_regs, out_anns


def _reconcile_segmented_contig_results(
    contig_id: str,
    seg_records: Sequence[Dict[str, Any]],
    *,
    merge_gap_bp: int = 3000,
) -> Tuple[List[PredictedRegion], List[PredictedRegion], Dict[str, Dict[str, Any]], List[Dict[str, Any]]]:
    """合并还原单条超长 Contig 各个分段的基础区段、终审区段、注释与被抑制候选。"""
    ordered = sorted(seg_records, key=lambda r: int(r.get("segment_idx", 0)))
    base_regs, _ = _reconcile_segmented_region_list(
        contig_id,
        ordered,
        region_field="base_regions",
        ann_field=None,
        merge_gap_bp=merge_gap_bp,
    )
    final_regs, final_anns = _reconcile_segmented_region_list(
        contig_id,
        ordered,
        region_field="regions",
        ann_field="region_annotations",
        merge_gap_bp=merge_gap_bp,
    )

    supp_items: List[Tuple[int, int, int, Dict[str, Any]]] = []
    for rec in ordered:
        s_idx = int(rec.get("segment_idx", 0))
        for item in rec.get("suppressed_candidates", []):
            supp_items.append((int(item.get("start_bp", 0)), int(item.get("end_bp", 0)), s_idx, item))
    supp_items.sort(key=lambda x: (x[0], x[1]))

    dedup_supp: List[Tuple[int, int, int, Dict[str, Any]]] = []
    for s_bp, e_bp, s_idx, item in supp_items:
        if dedup_supp:
            ps, pe, p_idx, _ = dedup_supp[-1]
            if p_idx != s_idx and min(pe, e_bp) - max(ps, s_bp) > 0:
                if (e_bp - s_bp) > (pe - ps):
                    dedup_supp[-1] = (s_bp, e_bp, s_idx, item)
                continue
        dedup_supp.append((s_bp, e_bp, s_idx, item))

    return base_regs, final_regs, final_anns, [x[3] for x in dedup_supp]


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
        self.model_version, self.judge_arch = _resolve_unified_model_meta(dna_scanner, judge_bundle)

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

    def _run_dna_backbone_core(
        self,
        contig_seqs: Dict[str, str],
        *,
        executor: Optional[concurrent.futures.Executor] = None,
        collect_judge_orfs: bool = False,
        global_ctx_by_contig: Optional[Mapping[str, Tuple[np.ndarray, float, bool]]] = None,
    ) -> Tuple[
        List[WindowPrediction],
        np.ndarray,
        Any,
        List[PredictedRegion],
        Dict[str, float],
        Dict[str, List[Tuple[int, int, int, str]]],
    ]:
        scanner = self.dna_scanner
        t_f0 = time.perf_counter()
        extract_orfs = scanner.model_version == "v4"
        ctx_map = global_ctx_by_contig or {}
        tasks: List[Tuple[Any, ...]] = []
        for cid, seq in contig_seqs.items():
            g_ctx = ctx_map.get(cid)
            if g_ctx is not None:
                tasks.append(
                    (cid, seq, scanner.win_size, scanner.step_size, extract_orfs, scanner.feature_profile, collect_judge_orfs, g_ctx)
                )
            elif collect_judge_orfs:
                tasks.append(
                    (cid, seq, scanner.win_size, scanner.step_size, extract_orfs, scanner.feature_profile, True)
                )
            else:
                tasks.append(
                    (cid, seq, scanner.win_size, scanner.step_size, extract_orfs, scanner.feature_profile)
                )
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
        reused_judge_orfs: Dict[str, List[Tuple[int, int, int, str]]] = {}
        for item in extracted:
            cid = item["contig_id"]
            seq_up = contig_seqs[cid].upper()
            feats_list.append(item["features"])
            if extract_orfs and "orf_tokens" in item:
                orf_tk_list.append(item["orf_tokens"])
                orf_cn_list.append(item["orf_counts"])
            if collect_judge_orfs and "judge_orfs" in item:
                reused_judge_orfs[cid] = item["judge_orfs"]
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
        return (
            win_preds,
            sub_probs,
            subbin_profiles,
            base_regions,
            {"dna_feature_sec": feat_sec, "dna_infer_decode_sec": dna_sec},
            reused_judge_orfs,
        )

    def _run_dna_backbone(
        self,
        contig_seqs: Dict[str, str],
        *,
        executor: Optional[concurrent.futures.Executor] = None,
    ) -> Tuple[List[WindowPrediction], np.ndarray, Any, List[PredictedRegion], Dict[str, float]]:
        win_preds, sub_probs, subbin_profiles, base_regions, t_dna, _ = self._run_dna_backbone_core(
            contig_seqs,
            executor=executor,
            collect_judge_orfs=False,
        )
        return win_preds, sub_probs, subbin_profiles, base_regions, t_dna

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
        global_ctx_by_contig: Optional[Mapping[str, Tuple[np.ndarray, float, bool]]] = None,
    ) -> UnifiedScanResult:
        """
        对给定 Contig 序列字典执行共享底座 + 条件按需激活扫描。
        仅在存在主区段或灰区候选的少数 Contig 上才唤醒蛋白知识底座，零浪费算力。
        """
        experts = set(active_experts) if active_experts is not None else set(self.active_experts)
        contigs_bp = {cid: len(seq) for cid, seq in contig_seqs.items()}
        total_bp = sum(contigs_bp.values())
        need_protein_experts = bool(experts & {"gray_rescue", "defense_func", "intact"}) and self.judge_bundle is not None

        has_custom_backbone = type(self)._run_dna_backbone is not UnifiedPhageModel._run_dna_backbone
        reused_orfs_map: Dict[str, List[Tuple[int, int, int, str]]] = {}
        if has_custom_backbone:
            win_preds, sub_probs, subbin_profiles, base_regions, t_dna = (
                self._run_dna_backbone(contig_seqs, executor=executor)
                if executor is not None
                else self._run_dna_backbone(contig_seqs)
            )
        else:
            win_preds, sub_probs, subbin_profiles, base_regions, t_dna, reused_orfs_map = self._run_dna_backbone_core(
                contig_seqs,
                executor=executor,
                collect_judge_orfs=(need_protein_experts and precomputed_orfs is None),
                global_ctx_by_contig=global_ctx_by_contig,
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
            "sibling_rescued": 0,
            "boundary_snapped": 0,
            "topology_bridged": 0,
            "topology_split": 0,
            "att_aligned": 0,
        }
        per_contig_windows: Dict[str, int] = {}
        for wp in win_preds:
            per_contig_windows[wp.contig_id] = per_contig_windows.get(wp.contig_id, 0) + 1

        reused_orf_cids = 0
        if need_protein_experts and activated_cids:
            assert self.judge_bundle is not None
            if precomputed_orfs is not None:
                orfs_map = {cid: precomputed_orfs.get(cid, []) for cid in activated_cids}
                reused_orf_cids = len(activated_cids)
            else:
                orfs_map = {}
                missing_cids: List[str] = []
                for cid in activated_cids:
                    if cid in reused_orfs_map:
                        orfs_map[cid] = reused_orfs_map[cid]
                        reused_orf_cids += 1
                    else:
                        missing_cids.append(cid)
                reused_orfs_map.clear()
                if missing_cids:
                    orfs_map.update(
                        extract_contig_orfs_pyrodigal(
                            contig_seqs,
                            contig_ids=missing_cids,
                            workers=_resolve_safe_workers(self.dna_scanner.workers),
                        )
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

            att_hits: Dict[str, AttAlignmentHit] = {}
            if need_gray or "defense_func" in experts:
                tentative_siblings: List[Dict[str, Any]] = []
                final_regions, rescue_stats = rescue_and_filter_regions_with_judge(
                    base_regions,
                    gray_cands if need_gray else [],
                    orfs_map,
                    scored,
                    enable_topology_postprocess=False,
                    enable_sibling_arm_rescue=True,
                    suppressed_out=suppressed_candidates,
                    tentative_siblings_out=tentative_siblings,
                )
                boundary_snapped = 0
                profiles_by_cid: Dict[str, np.ndarray] = {}
                if "boundary" in experts and final_regions:
                    raw_smooth = getattr(self.dna_scanner, "smooth_sub_profile", None)
                    smooth_p = bool(raw_smooth) if raw_smooth is not None else (not bool(subbin_profiles))
                    act_prof_cids = sorted({r.contig_id for r in final_regions})
                    profiles_by_cid = _build_active_contig_subbin_profiles(
                        win_preds,
                        sub_probs,
                        subbin_profiles,
                        contigs_bp,
                        act_prof_cids,
                        smooth_profile=smooth_p,
                    )
                    if profiles_by_cid:
                        min_reg_bp = int(getattr(self.dna_scanner, "min_region_bp", 3000) or 3000)
                        merge_gap = int(getattr(self.dna_scanner, "merge_gap_bp", 3000) or 3000)
                        final_regions, boundary_snapped = refine_region_boundaries_bimodal(
                            final_regions,
                            orfs_map,
                            scored,
                            contigs_bp,
                            profiles_by_cid,
                            min_region_bp=min_reg_bp,
                            merge_gap_bp=merge_gap,
                        )
                bridge_input = list(final_regions) + [ent["region"] for ent in tentative_siblings]
                final_regions, rescue_stats["topology_bridged"] = bridge_complementary_phage_fragments(
                    bridge_input,
                    orfs_map,
                    scored,
                )
                final_regions = reconcile_tentative_siblings(
                    final_regions,
                    tentative_siblings,
                    stats=rescue_stats,
                    suppressed_out=suppressed_candidates,
                )
                companion_absorbed = 0
                core_snapped = 0
                integrase_closed = 0
                if "boundary" in experts and final_regions and profiles_by_cid:
                    # 1a: 先在串联分裂前吸纳隔窄谷(<=4.5kb)的强 SubBin 伴生早期次级峰
                    final_regions, companion_absorbed = absorb_companion_subbin_peaks(
                        final_regions,
                        orfs_map,
                        scored,
                        profiles_by_cid,
                        contigs_bp,
                        sub_thr=float(getattr(self.dna_scanner, "sub_threshold", 0.45) or 0.45),
                        merge_gap_bp=int(getattr(self.dna_scanner, "merge_gap_bp", 3000) or 3000),
                    )
                    # 桥接及吸纳之后进行双模态端点防劈断校正
                    final_regions, post_snapped = refine_region_boundaries_bimodal(
                        final_regions,
                        orfs_map,
                        scored,
                        contigs_bp,
                        profiles_by_cid,
                        min_region_bp=int(getattr(self.dna_scanner, "min_region_bp", 3000) or 3000),
                        merge_gap_bp=int(getattr(self.dna_scanner, "merge_gap_bp", 3000) or 3000),
                    )
                    boundary_snapped += post_snapped
                final_regions, rescue_stats["topology_split"] = split_tandem_prophage_regions(
                    final_regions,
                    orfs_map,
                    scored,
                )
                if "boundary" in experts and final_regions and profiles_by_cid:
                    # 1b: 串联分隔点受锁状态下，修复残余高置信形态/整合蛋白边缘断口 (如 K-12 Qin / Sp18 Int)
                    final_regions, core_snapped = snap_split_core_orfs(
                        final_regions,
                        orfs_map,
                        scored,
                        profiles_by_cid,
                    )
                att_aligned = 0
                if "boundary" in experts and final_regions:
                    final_regions, att_aligned = refine_regions_with_att_sites(
                        final_regions,
                        contig_seqs,
                        orfs_map,
                        scored,
                        flank_pad_bp=2100,
                        details_out=att_hits,
                    )
                if "boundary" in experts and final_regions and profiles_by_cid:
                    # 2: 仅针对尚未被 attL/attR 精准锁死的侧翼区段执行真整合酶极点闭环延拓
                    locked_keys = set(att_hits.keys())
                    final_regions, integrase_closed = close_flanks_to_integrase_anchors(
                        final_regions,
                        orfs_map,
                        scored,
                        profiles_by_cid,
                        contigs_bp,
                        locked_keys=locked_keys,
                    )
                    if integrase_closed > 0:
                        unlocked_regs = [
                            r for r in final_regions if f"{r.contig_id}:{r.start_bp}-{r.end_bp}" not in locked_keys
                        ]
                        if unlocked_regs:
                            post_hits: Dict[str, AttAlignmentHit] = {}
                            post_refined, post_att = refine_regions_with_att_sites(
                                unlocked_regs,
                                contig_seqs,
                                orfs_map,
                                scored,
                                flank_pad_bp=2100,
                                details_out=post_hits,
                            )
                            att_aligned += post_att
                            post_iter = iter(post_refined)
                            final_regions = [
                                r if f"{r.contig_id}:{r.start_bp}-{r.end_bp}" in locked_keys else next(post_iter)
                                for r in final_regions
                            ]
                            att_hits.update(post_hits)
                rescue_stats["companion_absorbed"] = companion_absorbed
                rescue_stats["core_orfs_snapped"] = core_snapped
                rescue_stats["integrase_closed"] = integrase_closed
                rescue_stats["boundary_snapped"] = boundary_snapped
                rescue_stats["att_aligned"] = att_aligned

            if "defense_func" in experts or "intact" in experts:
                for reg in final_regions:
                    key = f"{reg.contig_id}:{reg.start_bp}-{reg.end_bp}"
                    if reg.contig_id in orfs_map and reg.contig_id in scored:
                        ann = summarize_region_with_judge(
                            reg,
                            orfs_map[reg.contig_id],
                            scored[reg.contig_id],
                        )
                        if key in att_hits:
                            ann["att_site"] = att_hits[key].to_dict()
                        region_annotations[key] = ann
        else:
            reused_orfs_map.clear()

        protein_sec = round(time.perf_counter() - t_p0, 3)
        total_contigs = max(1, len(contig_seqs))
        routing_stats = {
            "schema_version": "1.0",
            "model_version": self.model_version,
            "judge_arch": self.judge_arch,
            "total_contigs": len(contig_seqs),
            "protein_activated_contigs": len(activated_cids) if need_protein_experts else 0,
            "protein_skip_ratio": round(
                1.0 - (float(len(activated_cids)) / float(total_contigs) if need_protein_experts else 0.0),
                4,
            ),
            "pyrodigal_reused_contigs": reused_orf_cids,
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
                flank_bp=profile_flank_bp,
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
            "start_bp": reg.start_bp,
            "end_bp": reg.end_bp,
            "peak_score": reg.peak_score,
            "mean_score": reg.mean_score,
            "window_count": reg.window_count,
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

    @staticmethod
    def _write_streaming_checkpoint(
        ckpt_path: Path,
        completed_set: Set[str],
        completed_segments: Dict[str, Set[int]],
        timings_acc: Dict[str, float],
    ) -> None:
        tmp_ckpt = ckpt_path.with_name(f".{ckpt_path.name}.tmp")
        ckpt_payload = {
            "schema_version": "1.0",
            "completed_contigs": sorted(completed_set),
            "completed_segments": {
                cid: sorted(idxs)
                for cid, idxs in sorted(completed_segments.items())
                if idxs and cid not in completed_set
            },
            "timings_sec": timings_acc,
        }
        tmp_ckpt.write_text(json.dumps(ckpt_payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp_ckpt.replace(ckpt_path)

    @staticmethod
    def _accumulate_timings(timings_acc: Dict[str, float], step_timings: Dict[str, float]) -> None:
        for tk in ("dna_feature_sec", "dna_infer_decode_sec", "protein_judge_sec", "total_sec"):
            timings_acc[tk] = round(timings_acc.get(tk, 0.0) + step_timings.get(tk, 0.0), 3)

    @staticmethod
    def _count_owned_windows(
        seg_s: int,
        seg_e: int,
        own_s: int,
        own_e: int,
        is_last: bool,
        win_size: int,
        step_size: int,
    ) -> int:
        seg_len = max(0, seg_e - seg_s)
        if seg_len <= 0:
            return 0
        starts: List[int] = []
        if seg_len <= win_size:
            starts.append(0)
        else:
            pos = 0
            while pos < seg_len:
                end_pos = min(seg_len, pos + win_size)
                if end_pos - pos < win_size // 2 and starts:
                    starts.append(max(0, seg_len - win_size))
                    break
                starts.append(pos)
                if end_pos == seg_len:
                    break
                pos += step_size
        cnt = 0
        for s in starts:
            e = min(seg_len, s + win_size)
            g_mid = seg_s + 0.5 * (s + e)
            if own_s <= g_mid < own_e or (is_last and own_s <= g_mid <= own_e):
                cnt += 1
        return cnt

    def _flush_streaming_chunk(
        self,
        chunk_seqs: Dict[str, str],
        *,
        active_experts: Optional[Sequence[str]],
        executor: Optional[concurrent.futures.Executor],
        chunks_jsonl: Path,
        ckpt_path: Path,
        completed_set: Set[str],
        completed_segments: Dict[str, Set[int]],
        timings_acc: Dict[str, float],
    ) -> None:
        chunk_res = self.scan_sequences(
            chunk_seqs,
            active_experts=active_experts,
            executor=executor,
        )
        self._accumulate_timings(timings_acc, chunk_res.timings_sec)

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
                    "record_type": "contig",
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

        self._write_streaming_checkpoint(ckpt_path, completed_set, completed_segments, timings_acc)

        del chunk_res
        _release_accelerator_memory()

    def _stream_long_single_contig(
        self,
        cid: str,
        seq: str,
        *,
        chunk_max_bp: int,
        overlap_bp: Optional[int],
        active_experts: Optional[Sequence[str]],
        executor: Optional[concurrent.futures.Executor],
        chunks_jsonl: Path,
        ckpt_path: Path,
        completed_set: Set[str],
        completed_segments: Dict[str, Set[int]],
        timings_acc: Dict[str, float],
    ) -> None:
        """对超长单条 Contig 按重叠分段逐片扫描、增量落盘并更新分段级 Checkpoint。"""
        seq_len = len(seq)
        segments = plan_long_contig_segments(
            seq_len,
            chunk_max_bp,
            win_size=self.dna_scanner.win_size,
            overlap_bp=overlap_bp,
        )
        ownership = _compute_segment_ownership(segments, seq_len)
        done_segs = completed_segments.setdefault(cid, set())
        seg_total = len(segments)
        global_ctx = compute_sequence_global_context(seq, context_win_size=self.dna_scanner.win_size)

        for seg_idx, (seg_s, seg_e) in enumerate(segments):
            if seg_idx in done_segs:
                continue
            seg_key = f"{cid}__seg_{seg_idx}"
            sub_seq = seq[seg_s:seg_e]
            seg_res = self.scan_sequences(
                {seg_key: sub_seq},
                active_experts=active_experts,
                executor=executor,
                global_ctx_by_contig={seg_key: global_ctx},
            )
            self._accumulate_timings(timings_acc, seg_res.timings_sec)

            base_dicts: List[Dict[str, Any]] = []
            for reg in seg_res.base_regions:
                d = self._region_to_dict(reg)
                d["contig_id"] = cid
                d["start_bp"] = reg.start_bp + seg_s
                d["end_bp"] = reg.end_bp + seg_s
                base_dicts.append(d)

            final_dicts: List[Dict[str, Any]] = []
            ann_dict: Dict[str, Dict[str, Any]] = {}
            for reg in seg_res.regions:
                g_start = reg.start_bp + seg_s
                g_end = reg.end_bp + seg_s
                d = self._region_to_dict(reg)
                d["contig_id"] = cid
                d["start_bp"] = g_start
                d["end_bp"] = g_end
                final_dicts.append(d)
                old_k = f"{reg.contig_id}:{reg.start_bp}-{reg.end_bp}"
                if old_k in seg_res.region_annotations:
                    ann_dict[f"{cid}:{g_start}-{g_end}"] = seg_res.region_annotations[old_k]

            supp_dicts: List[Dict[str, Any]] = []
            for item in seg_res.suppressed_candidates:
                sup_item = dict(item)
                sup_item["contig_id"] = cid
                sup_item["start_bp"] = int(item.get("start_bp", 0)) + seg_s
                sup_item["end_bp"] = int(item.get("end_bp", 0)) + seg_s
                supp_dicts.append(sup_item)

            own_s, own_e = ownership[seg_idx]
            owned_win = self._count_owned_windows(
                seg_s,
                seg_e,
                own_s,
                own_e,
                is_last=(seg_idx + 1 == seg_total),
                win_size=self.dna_scanner.win_size,
                step_size=self.dna_scanner.step_size,
            )
            act_set = set(seg_res.routing_stats.get("activated_contig_ids", []))
            rec: Dict[str, Any] = {
                "record_type": "segment",
                "contig_id": cid,
                "contig_total_bp": seq_len,
                "segment_idx": seg_idx,
                "segment_count": seg_total,
                "seg_start": seg_s,
                "seg_end": seg_e,
                "own_start": own_s,
                "own_end": own_e,
                "bp": seg_e - seg_s,
                "windows": owned_win,
                "protein_activated": seg_key in act_set,
                "base_regions": base_dicts,
                "regions": final_dicts,
                "region_annotations": ann_dict,
                "suppressed_candidates": supp_dicts,
                "chunk_rescue_stats": seg_res.routing_stats.get("rescue_stats", {}),
            }
            with chunks_jsonl.open("a", encoding="utf-8", newline="\n") as fh:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")

            done_segs.add(seg_idx)
            if len(done_segs) >= seg_total:
                completed_set.add(cid)
            self._write_streaming_checkpoint(ckpt_path, completed_set, completed_segments, timings_acc)

            del seg_res
            _release_accelerator_memory()

    @staticmethod
    def _load_or_reset_streaming_state(
        ckpt_path: Path,
        chunks_jsonl: Path,
        *,
        resume: bool,
    ) -> Tuple[Set[str], Dict[str, Set[int]], Dict[str, float]]:
        completed_set: Set[str] = set()
        completed_segments: Dict[str, Set[int]] = {}
        timings_acc: Dict[str, float] = {
            "dna_feature_sec": 0.0,
            "dna_infer_decode_sec": 0.0,
            "protein_judge_sec": 0.0,
            "total_sec": 0.0,
        }
        if resume and ckpt_path.is_file() and chunks_jsonl.is_file():
            ckpt_obj = json.loads(ckpt_path.read_text(encoding="utf-8"))
            completed_set = {str(x) for x in ckpt_obj.get("completed_contigs", [])}
            raw_segs = ckpt_obj.get("completed_segments", {})
            if isinstance(raw_segs, dict):
                completed_segments = {
                    str(k): {int(i) for i in v}
                    for k, v in raw_segs.items()
                    if isinstance(v, list)
                }
            timings_acc.update({k: float(v) for k, v in ckpt_obj.get("timings_sec", {}).items()})
        else:
            if chunks_jsonl.exists():
                chunks_jsonl.unlink()
            if ckpt_path.exists():
                ckpt_path.unlink()
        return completed_set, completed_segments, timings_acc

    def _dispatch_streaming_fasta(
        self,
        fa_path: Path,
        *,
        chunk_max_bp: int,
        long_contig_overlap_bp: Optional[int],
        active_experts: Optional[Sequence[str]],
        safe_workers: int,
        chunks_jsonl: Path,
        ckpt_path: Path,
        completed_set: Set[str],
        completed_segments: Dict[str, Set[int]],
        timings_acc: Dict[str, float],
    ) -> None:
        pool_ctx: Any = None
        pool: Any = None
        if safe_workers > 1:
            pool_ctx = concurrent.futures.ProcessPoolExecutor(max_workers=safe_workers)
            pool = pool_ctx.__enter__()
        try:
            cur_chunk: Dict[str, str] = {}
            cur_bp = 0
            for cid, seq in iter_fasta(fa_path):
                if cid in completed_set:
                    continue
                seq_len = len(seq)
                if seq_len > chunk_max_bp or (cur_chunk and (cur_bp + seq_len) > chunk_max_bp):
                    if cur_chunk:
                        self._flush_streaming_chunk(
                            cur_chunk,
                            active_experts=active_experts,
                            executor=pool,
                            chunks_jsonl=chunks_jsonl,
                            ckpt_path=ckpt_path,
                            completed_set=completed_set,
                            completed_segments=completed_segments,
                            timings_acc=timings_acc,
                        )
                        cur_chunk = {}
                        cur_bp = 0
                if seq_len > chunk_max_bp:
                    self._stream_long_single_contig(
                        cid,
                        seq,
                        chunk_max_bp=chunk_max_bp,
                        overlap_bp=long_contig_overlap_bp,
                        active_experts=active_experts,
                        executor=pool,
                        chunks_jsonl=chunks_jsonl,
                        ckpt_path=ckpt_path,
                        completed_set=completed_set,
                        completed_segments=completed_segments,
                        timings_acc=timings_acc,
                    )
                    continue
                cur_chunk[cid] = seq
                cur_bp += seq_len
            if cur_chunk:
                self._flush_streaming_chunk(
                    cur_chunk,
                    active_experts=active_experts,
                    executor=pool,
                    chunks_jsonl=chunks_jsonl,
                    ckpt_path=ckpt_path,
                    completed_set=completed_set,
                    completed_segments=completed_segments,
                    timings_acc=timings_acc,
                )
        finally:
            if pool_ctx is not None:
                pool_ctx.__exit__(None, None, None)

    def _aggregate_streaming_chunks(
        self,
        chunks_jsonl: Path,
        completed_set: Set[str],
    ) -> Tuple[
        Dict[str, int],
        int,
        int,
        int,
        List[PredictedRegion],
        List[PredictedRegion],
        Dict[str, Dict[str, Any]],
        List[Dict[str, Any]],
        Dict[str, int],
    ]:
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
        segmented_records_by_cid: Dict[str, Dict[int, Dict[str, Any]]] = {}

        if chunks_jsonl.is_file():
            seen_cids: Set[str] = set()
            with chunks_jsonl.open("r", encoding="utf-8") as fh:
                for line in fh:
                    line_s = line.strip()
                    if not line_s:
                        continue
                    rec = json.loads(line_s)
                    cid = str(rec["contig_id"])
                    if completed_set and cid not in completed_set:
                        continue
                    if rec.get("record_type") == "segment" or "segment_idx" in rec:
                        segmented_records_by_cid.setdefault(cid, {})[int(rec.get("segment_idx", 0))] = rec
                        continue
                    if cid in seen_cids:
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

        for cid, seg_map in segmented_records_by_cid.items():
            seg_list = [seg_map[k] for k in sorted(seg_map.keys())]
            contigs_bp[cid] = int(seg_list[0].get("contig_total_bp") or max(int(r.get("seg_end", 0)) for r in seg_list))
            total_windows += sum(int(r.get("windows", 0)) for r in seg_list)
            if any(bool(r.get("protein_activated")) for r in seg_list):
                activated_cnt += 1
            for r in seg_list:
                for rk in rescue_acc:
                    rescue_acc[rk] += int(r.get("chunk_rescue_stats", {}).get(rk, 0))
            seg_base, seg_final, seg_anns, seg_supp = _reconcile_segmented_contig_results(
                cid, seg_list, merge_gap_bp=self.dna_scanner.merge_gap_bp
            )
            base_regions.extend(seg_base)
            final_regions.extend(seg_final)
            region_annotations.update(seg_anns)
            suppressed_all.extend(seg_supp)

        return (
            contigs_bp,
            total_windows,
            activated_cnt,
            len(segmented_records_by_cid),
            base_regions,
            final_regions,
            region_annotations,
            suppressed_all,
            rescue_acc,
        )

    def scan_fasta_streaming(
        self,
        fasta_path: Path,
        out_dir: Path,
        *,
        chunk_max_bp: int = 10_000_000,
        long_contig_overlap_bp: Optional[int] = None,
        active_experts: Optional[Sequence[str]] = None,
        resume: bool = True,
        export_outputs: bool = True,
    ) -> UnifiedScanResult:
        """
        流式分片扫描大体积 FASTA 并持久复用进程池，支持超长单 Contig 序列内切片、断点续跑与标准产物导出。
        """
        fa_path = Path(fasta_path)
        out_root = Path(out_dir)
        out_root.mkdir(parents=True, exist_ok=True)
        chunks_jsonl = out_root / "chunks.jsonl"
        ckpt_path = out_root / "checkpoint.json"

        completed_set, completed_segments, timings_acc = self._load_or_reset_streaming_state(
            ckpt_path, chunks_jsonl, resume=resume
        )
        experts = set(active_experts) if active_experts is not None else set(self.active_experts)
        safe_workers = _resolve_safe_workers(self.dna_scanner.workers)

        self._dispatch_streaming_fasta(
            fa_path,
            chunk_max_bp=chunk_max_bp,
            long_contig_overlap_bp=long_contig_overlap_bp,
            active_experts=active_experts,
            safe_workers=safe_workers,
            chunks_jsonl=chunks_jsonl,
            ckpt_path=ckpt_path,
            completed_set=completed_set,
            completed_segments=completed_segments,
            timings_acc=timings_acc,
        )

        (
            contigs_bp,
            total_windows,
            activated_cnt,
            segmented_long_contigs,
            base_regions,
            final_regions,
            region_annotations,
            suppressed_all,
            rescue_acc,
        ) = self._aggregate_streaming_chunks(chunks_jsonl, completed_set)

        total_bp = sum(contigs_bp.values())
        total_contigs = max(1, len(contigs_bp))
        need_protein = bool(experts & {"gray_rescue", "defense_func", "intact"}) and self.judge_bundle is not None
        routing_stats = {
            "schema_version": "1.0",
            "model_version": self.model_version,
            "judge_arch": self.judge_arch,
            "total_contigs": len(contigs_bp),
            "segmented_long_contigs": segmented_long_contigs,
            "protein_activated_contigs": activated_cnt if need_protein else 0,
            "protein_skip_ratio": round(
                1.0 - (float(activated_cnt) / float(total_contigs) if need_protein else 0.0),
                4,
            ),
            "active_experts": sorted(experts),
            "unified_judge_mode": bool(self.judge_bundle and self.judge_bundle.get("unified_mode", False)),
            "rescue_stats": rescue_acc,
            "streaming_chunk_max_bp": chunk_max_bp,
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

