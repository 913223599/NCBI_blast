# -*- coding: utf-8 -*-
"""
基于 OrfFunctionalJudge (R2/R3) 的后置区段境界精修、灰区碎段挽救与防御岛排雷模块。

单一职责设计：
1. 不改动 Stage 1.2 边界主干权重，以标准 PredictedRegion 与 ORF 坐标流接入扫描流水线；
2. 单变量组件 1 (`refine_region_boundaries_with_judge`)：利用 R3 ORF 级精判向左右侧翼安全延展被过早切断的噬菌体尾巴（如 Fels-2 断尾），并温和剔除边缘纯宿主/防御 ORF；
3. 单变量组件 2 (`rescue_and_filter_regions_with_judge`)：对放宽门槛召回的灰区弱峰区段执行 R3 严格二审，在死守高 GC/质粒零误报前提下挽救极碎裂隐蔽前噬菌体；
4. 完整度拆分评估：R3 主导 `is_phage`、10 类功能分区与 `P9` 排雷；R2 未校准核心结构分支主导区段完整度打分。
"""
from __future__ import annotations

import json
import logging
from ...utils.resource_guard import get_safe_cpu_budget
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set, Tuple

import numpy as np

from ..benchmark.metrics import (
    PredictedRegion,
    WindowPrediction,
    assemble_contig_subbin_profile,
)
from ..student.judge_calibration import apply_blended_logit_calibration
from ..student.orf_functional_judge import (
    JUDGE_CLASS_NAMES,
    build_orf_functional_judge,
    predict_contig_orfs_with_judge,
)

logger = logging.getLogger("phage_discovery.inference.judge_region_refiner")


def _extract_single_contig_orfs(item: Tuple[str, str]) -> Tuple[str, List[Tuple[int, int, int, str]]]:
    import pyrodigal

    cid, seq = item
    s_up = (seq or "").upper()
    lst: List[Tuple[int, int, int, str]] = []
    if len(s_up) >= 100:
        gf = pyrodigal.GeneFinder(meta=True)
        for g in gf.find_genes(s_up.encode("ascii", errors="replace")):
            aa = g.translate(include_stop=False).strip()
            if aa and "*" not in aa:
                lst.append((g.begin - 1, g.end, g.strand, aa))
    lst.sort(key=lambda x: (x[0], x[1]))
    return cid, lst


def extract_contig_orfs_pyrodigal(
    contig_seqs: Dict[str, str],
    *,
    contig_ids: Optional[Sequence[str]] = None,
    workers: Optional[int] = None,
) -> Dict[str, List[Tuple[int, int, int, str]]]:
    """按需多核并行提取指定 Contig 的 Pyrodigal 连续 ORF 列表 [(start, end, strand, aa_seq), ...]。"""
    target_ids = list(contig_ids) if contig_ids is not None else list(contig_seqs.keys())
    items = [(cid, contig_seqs[cid]) for cid in target_ids if cid in contig_seqs]
    if not items:
        return {}

    max_w = get_safe_cpu_budget(requested=workers or 0, reserve_cores=4, max_cap=16 if workers is None else None)
    out: Dict[str, List[Tuple[int, int, int, str]]] = {}
    if max_w <= 1 or len(items) == 1:
        for it in items:
            cid, lst = _extract_single_contig_orfs(it)
            out[cid] = lst
        return out

    with ThreadPoolExecutor(max_workers=min(max_w, len(items))) as pool:
        for cid, lst in pool.map(_extract_single_contig_orfs, items):
            out[cid] = lst
    return out


def _load_judge_ckpt(ckpt_path: Path, device: str):
    import torch

    ck = torch.load(ckpt_path, map_location=device, weights_only=False)
    model = build_orf_functional_judge(
        stat_mean=ck["stat_mean"],
        stat_std=ck["stat_std"],
        use_aa_seq=bool(ck["use_aa_seq"]),
        arch=str(ck.get("arch", "baseline")),
    ).to(device)
    model.load_state_dict(ck["state_dict"], strict=True)
    model.eval()
    return model


def resolve_unified_version_tag(
    uni_meta: Optional[Dict[str, Any]] = None,
    s12_meta: Optional[Dict[str, Any]] = None,
) -> str:
    """按显式声明优先、架构标识与 DNA 微调元信息兜底的契约统一解析版本标签。"""
    u_m = uni_meta or {}
    s_m = s12_meta or {}
    explicit = str(u_m.get("model_version") or u_m.get("version") or "").strip()
    if explicit:
        return explicit

    uni_arch = str(u_m.get("arch") or "").strip().lower()
    if uni_arch.startswith("unified_v"):
        suffix = uni_arch[len("unified_v") :].replace("_", ".")
        if suffix:
            return f"Unified V{suffix}"

    if "v4_3_dna_finetune" in s_m or str(s_m.get("model_version") or "").lower() == "v4_3":
        return "Unified V4.3"
    return "Unified V4"


def load_judge_ensemble_bundle(
    models_v4_root: Path,
    *,
    device: str = "cpu",
    r3_subdir: str = "orf_judge_ablation_r3",
    r2_subdir: str = "orf_judge_ablation_r2",
    prefer_unified: bool = True,
) -> Optional[Dict[str, Any]]:
    """从 models/full_v4 下按相对路径加载统一分化模型（优先）或回退加载 R3 + R2 分离模型组。"""
    root = Path(models_v4_root).resolve()
    uni_dir = root / "orf_judge_unified"
    uni_meta: Dict[str, Any] = {}
    if prefer_unified and (uni_dir / "unified_judge_seq.pt").is_file():
        stat_pt = uni_dir / "orf_judge_statonly.pt"
        if not stat_pt.is_file():
            stat_pt = root / r3_subdir / "orf_judge_statonly.pt"
        seq_pt = uni_dir / "unified_judge_seq.pt"
        cal_npz = uni_dir / "logit_calibrator.npz"
        if not cal_npz.is_file():
            cal_npz = root / r3_subdir / "logit_calibrator.npz"
        summary_p = uni_dir / "unified_summary.json"
        if summary_p.is_file():
            try:
                loaded_sum = json.loads(summary_p.read_text(encoding="utf-8"))
                if isinstance(loaded_sum, dict):
                    uni_meta = loaded_sum
            except Exception:
                uni_meta = {}
        r2_seq_obj = None
        use_uni = True
    else:
        r3_dir = root / r3_subdir
        stat_pt = r3_dir / "orf_judge_statonly.pt"
        seq_pt = r3_dir / "orf_judge_seq.pt"
        cal_npz = r3_dir / "logit_calibrator.npz"
        r2_seq_pt = root / r2_subdir / "orf_judge_seq.pt"
        r2_seq_obj = _load_judge_ckpt(r2_seq_pt, device) if r2_seq_pt.is_file() else None
        use_uni = False

    if not stat_pt.is_file() or not seq_pt.is_file():
        return None

    calibrator = None
    if cal_npz.is_file():
        cd = np.load(cal_npz, allow_pickle=False)
        calibrator = {
            "func_alphas": cd["func_alphas"],
            "phage_alpha": float(cd["phage_alpha"][0]),
            "func_bias": cd["func_bias"],
            "phage_bias": float(cd["phage_bias"][0]),
        }

    r3_seq_model = _load_judge_ckpt(seq_pt, device)
    judge_arch = str(uni_meta.get("arch") or getattr(r3_seq_model, "arch", "") or ("unified" if use_uni else "r3"))
    if use_uni and not uni_meta.get("arch"):
        uni_meta = {**uni_meta, "arch": judge_arch}

    s12_meta: Dict[str, Any] = {}
    s12_meta_p = root / "stage1_2" / "stage1_2_meta.json"
    if s12_meta_p.is_file():
        try:
            loaded_s12 = json.loads(s12_meta_p.read_text(encoding="utf-8"))
            if isinstance(loaded_s12, dict):
                s12_meta = loaded_s12
        except Exception:
            s12_meta = {}
    model_version = resolve_unified_version_tag(uni_meta, s12_meta) if use_uni else "R3+R2 Ensemble"

    return {
        "r3_stat": _load_judge_ckpt(stat_pt, device),
        "r3_seq": r3_seq_model,
        "calibrator": calibrator,
        "r2_seq": r2_seq_obj,
        "unified_mode": use_uni,
        "judge_arch": judge_arch,
        "model_version": model_version,
        "judge_summary_meta": uni_meta,
        "device": device,
    }


def score_contigs_with_judge_bundle(
    bundle: Dict[str, Any],
    orfs_by_contig: Dict[str, List[Tuple[int, int, int, str]]],
    *,
    contig_ids: Optional[Sequence[str]] = None,
    batch_size: int = 32,
    active_experts: Optional[Sequence[str]] = None,
) -> Dict[str, Dict[str, np.ndarray]]:
    """对每条 Contig 仅执行 1 次共享底座前向推理并按需分化输出 R3 校准概率与完整度分数。"""
    device = str(bundle.get("device", "cpu"))
    m_stat = bundle["r3_stat"]
    m_seq = bundle["r3_seq"]
    m_r2 = bundle.get("r2_seq")
    cal = bundle.get("calibrator")
    is_uni = getattr(m_seq, "arch", "") in ("unified", "unified_v4_3")

    target_cids = list(contig_ids) if contig_ids is not None else list(orfs_by_contig.keys())
    scored: Dict[str, Dict[str, np.ndarray]] = {}
    for cid in target_cids:
        orfs = orfs_by_contig.get(cid, [])
        if not orfs:
            scored[cid] = {
                "phage_probs": np.zeros(0, dtype=np.float32),
                "func10_probs": np.zeros((0, len(JUDGE_CLASS_NAMES)), dtype=np.float32),
                "r2_core_probs": np.zeros((0, 5), dtype=np.float32),
            }
            continue
        rs = predict_contig_orfs_with_judge(m_stat, orfs, device=device, batch_size=batch_size, return_logits=True)
        rq = predict_contig_orfs_with_judge(
            m_seq,
            orfs,
            device=device,
            batch_size=batch_size,
            return_logits=True,
            active_experts=active_experts if is_uni else None,
            return_intact=is_uni,
        )
        f10, ph = apply_blended_logit_calibration(
            rs["func10_logits"],
            rq["func10_logits"],
            rs["phage_logits"],
            rq["phage_logits"],
            cal,
        )
        if is_uni and "intact_func_probs" in rq:
            r2_core = rq["intact_func_probs"][:, :5]
        elif m_r2 is not None:
            r2_out = predict_contig_orfs_with_judge(m_r2, orfs, device=device, batch_size=batch_size)
            r2_core = r2_out["func10_probs"][:, :5]
        else:
            r2_core = f10[:, :5]
        scored[cid] = {
            "phage_probs": ph,
            "func10_probs": f10,
            "r2_core_probs": r2_core,
        }
    return scored


def _is_phage_extension_orf(ph_p: float, f10_row: np.ndarray, *, min_phage_prob: float) -> bool:
    p9 = float(f10_row[9])
    if p9 >= 0.68 and ph_p < 0.70:
        return False
    core_max = float(np.max(f10_row[:5]))
    func_max = float(np.max(f10_row[:7]))
    if ph_p >= min_phage_prob:
        return True
    return (core_max >= 0.50 or func_max >= 0.62) and ph_p >= 0.30


def _is_strong_host_edge_orf(ph_p: float, f10_row: np.ndarray) -> bool:
    p9 = float(f10_row[9])
    func_max = float(np.max(f10_row[:7]))
    if func_max >= 0.35 or ph_p >= 0.25:
        return False
    return (p9 >= 0.55) or (ph_p < 0.12)


def merge_nearby_regions(
    regions: Sequence[PredictedRegion],
    *,
    merge_gap_bp: int = 3000,
) -> List[PredictedRegion]:
    """合并同一 Contig 上间距不超过 merge_gap_bp 的邻接预测区段。"""
    by_cid: Dict[str, List[PredictedRegion]] = defaultdict(list)
    for r in regions:
        by_cid[r.contig_id].append(r)

    merged_all: List[PredictedRegion] = []
    for cid in sorted(by_cid.keys()):
        items = sorted(by_cid[cid], key=lambda x: (x.start_bp, x.end_bp))
        cur: List[PredictedRegion] = []
        for r in items:
            if cur and (r.start_bp - cur[-1].end_bp) <= merge_gap_bp:
                prev = cur[-1]
                cur[-1] = PredictedRegion(
                    contig_id=cid,
                    start_bp=min(prev.start_bp, r.start_bp),
                    end_bp=max(prev.end_bp, r.end_bp),
                    peak_score=max(prev.peak_score, r.peak_score),
                    mean_score=round(0.5 * (prev.mean_score + r.mean_score), 5),
                    window_count=prev.window_count + r.window_count,
                )
            else:
                cur.append(r)
        merged_all.extend(cur)
    return merged_all


def refine_region_boundaries_with_judge(
    regions: Sequence[PredictedRegion],
    orfs_by_contig: Dict[str, List[Tuple[int, int, int, str]]],
    scored_by_contig: Dict[str, Dict[str, np.ndarray]],
    contigs_bp: Dict[str, int],
    *,
    window_preds: Optional[Sequence[WindowPrediction]] = None,
    min_ext_backbone_score: float = 0.22,
    max_flank_bp: int = 8000,
    max_step_gap_bp: int = 2400,
    min_ext_phage_prob: float = 0.72,
    max_host_gap_orfs: int = 0,
    allow_edge_trim: bool = False,
    merge_gap_bp: int = 3000,
) -> List[PredictedRegion]:
    """
    利用 R3 逐 ORF 精判对 Stage 1.2 初筛区段执行受 DNA 主干过渡带约束的侧翼延展
    与可选边缘强宿主 ORF 裁边。仅当外侧邻接区域仍具备一定 DNA 主干响应 (>= min_ext_backbone_score)
    且连续呈现高置信噬菌体蛋白语义时才适度扩边，保护原 200bp SubBin 边界不被滑窗传染拉宽。
    """
    wp_by_cid: Dict[str, List[WindowPrediction]] = defaultdict(list)
    if window_preds is not None:
        for wp in window_preds:
            wp_by_cid[wp.contig_id].append(wp)

    def _has_backbone_support(cid: str, gs: int, ge: int) -> bool:
        if window_preds is None:
            return True
        c_wps = wp_by_cid.get(cid, [])
        if not c_wps:
            return True
        best_s = 0.0
        for wp in c_wps:
            if wp.end_bp > gs and wp.start_bp < ge:
                if wp.score > best_s:
                    best_s = wp.score
        return best_s >= min_ext_backbone_score

    refined: List[PredictedRegion] = []
    for reg in regions:
        cid = reg.contig_id
        orfs = orfs_by_contig.get(cid, [])
        sc = scored_by_contig.get(cid)
        if not orfs or sc is None or len(sc["phage_probs"]) != len(orfs):
            refined.append(reg)
            continue

        ph_probs = sc["phage_probs"]
        f10_probs = sc["func10_probs"]
        c_len = contigs_bp.get(cid, orfs[-1][1])

        in_idxs = [i for i, (gs, ge, _, _) in enumerate(orfs) if reg.start_bp <= 0.5 * (gs + ge) <= reg.end_bp]
        if not in_idxs:
            refined.append(reg)
            continue

        first_i, last_i = in_idxs[0], in_idxs[-1]
        new_start = reg.start_bp
        new_end = reg.end_bp

        # 1. 可选边缘温和裁边
        if allow_edge_trim and len(in_idxs) >= 5:
            trim_l = 0
            while trim_l < 2 and (last_i - first_i) >= 4:
                if _is_strong_host_edge_orf(float(ph_probs[first_i]), f10_probs[first_i]):
                    first_i += 1
                    trim_l += 1
                    new_start = max(reg.start_bp, orfs[first_i][0])
                else:
                    break
            trim_r = 0
            while trim_r < 2 and (last_i - first_i) >= 4:
                if _is_strong_host_edge_orf(float(ph_probs[last_i]), f10_probs[last_i]):
                    last_i -= 1
                    trim_r += 1
                    new_end = min(reg.end_bp, orfs[last_i][1])
                else:
                    break

        # 2. 向左语义外延（受 DNA 主干过渡带与 max_host_gap_orfs 约束）
        cur_left_edge = orfs[first_i][0] if trim_triggered(new_start, reg.start_bp) else new_start
        anchor_start = reg.start_bp
        gap_cnt = 0
        li = first_i - 1
        while li >= 0:
            gs, ge, _, _ = orfs[li]
            if (anchor_start - gs) > max_flank_bp:
                break
            if (cur_left_edge - ge) > max_step_gap_bp:
                break
            if not _has_backbone_support(cid, gs, ge):
                break
            if _is_phage_extension_orf(float(ph_probs[li]), f10_probs[li], min_phage_prob=min_ext_phage_prob):
                new_start = min(new_start, gs)
                cur_left_edge = gs
                gap_cnt = 0
                li -= 1
            else:
                if _is_strong_host_edge_orf(float(ph_probs[li]), f10_probs[li]):
                    break
                gap_cnt += 1
                if gap_cnt > max_host_gap_orfs:
                    break
                cur_left_edge = gs
                li -= 1

        # 3. 向右语义外延（受 DNA 主干过渡带约束）
        cur_right_edge = orfs[last_i][1] if new_end < reg.end_bp else new_end
        anchor_end = reg.end_bp
        gap_cnt = 0
        ri = last_i + 1
        while ri < len(orfs):
            gs, ge, _, _ = orfs[ri]
            if (ge - anchor_end) > max_flank_bp:
                break
            if (gs - cur_right_edge) > max_step_gap_bp:
                break
            if not _has_backbone_support(cid, gs, ge):
                break
            if _is_phage_extension_orf(float(ph_probs[ri]), f10_probs[ri], min_phage_prob=min_ext_phage_prob):
                new_end = max(new_end, ge)
                cur_right_edge = ge
                gap_cnt = 0
                ri += 1
            else:
                if _is_strong_host_edge_orf(float(ph_probs[ri]), f10_probs[ri]):
                    break
                gap_cnt += 1
                if gap_cnt > max_host_gap_orfs:
                    break
                cur_right_edge = ge
                ri += 1

        refined.append(
            PredictedRegion(
                contig_id=cid,
                start_bp=max(0, min(new_start, new_end)),
                end_bp=min(c_len, max(new_start, new_end)),
                peak_score=reg.peak_score,
                mean_score=reg.mean_score,
                window_count=reg.window_count,
            )
        )
    return merge_nearby_regions(refined, merge_gap_bp=merge_gap_bp)


def _subbin_interval_stats(
    prof: Optional[np.ndarray],
    start_bp: int,
    end_bp: int,
    *,
    bin_bp: int = 200,
) -> Tuple[float, float]:
    """计算指定 DNA 区间在 200 bp SubBin 连续置信度曲线上的均值与峰值。"""
    if prof is None or len(prof) == 0 or end_bp <= start_bp:
        return 0.0, 0.0
    b0 = max(0, start_bp // bin_bp)
    b1 = min(len(prof), max(b0 + 1, (end_bp + bin_bp - 1) // bin_bp))
    sl = prof[b0:b1]
    if len(sl) == 0:
        return 0.0, 0.0
    return float(np.mean(sl)), float(np.max(sl))


def refine_region_boundaries_bimodal(
    regions: Sequence[PredictedRegion],
    orfs_by_contig: Dict[str, List[Tuple[int, int, int, str]]],
    scored_by_contig: Dict[str, Dict[str, np.ndarray]],
    contigs_bp: Dict[str, int],
    profiles_by_contig: Mapping[str, np.ndarray],
    *,
    snap_out_sub_mean: float = 0.15,
    snap_out_sub_max: float = 0.24,
    snap_min_phage: float = 0.80,
    min_hang_bp: int = 25,
    min_region_bp: int = 3000,
    merge_gap_bp: int = 3000,
    bin_bp: int = 200,
) -> Tuple[List[PredictedRegion], int]:
    """
    DNA 200 bp SubBin 与 UnifiedJudge 双模态门控边界防劈断校准：
    1. 仅当被边界劈断的 ORF 既具备高置信噬菌体蛋白语义 (phage >= snap_min_phage 或核心模块支持)
       又在其基因外露部分保有明确 200 bp SubBin 过渡支持时，外扩囊括完整 ORF，防止把跨界嵌合片段盲目拖入；
    2. 若被劈断 ORF 为强宿主/防御基因 (p9 >= 0.62 或 phage < 0.15 且非核心模块) 且外露 SubBin 偏低，则回退缩进至该基因外缘。
    """
    if not regions:
        return [], 0

    refined: List[PredictedRegion] = []
    snapped_edges = 0

    for reg in regions:
        cid = reg.contig_id
        orfs = orfs_by_contig.get(cid, [])
        sc = scored_by_contig.get(cid)
        prof = profiles_by_contig.get(cid)
        if not orfs or sc is None or len(sc.get("phage_probs", ())) != len(orfs):
            refined.append(reg)
            continue

        ph_p = sc["phage_probs"]
        f10_p = sc["func10_probs"]
        c_len = contigs_bp.get(cid, orfs[-1][1])
        ns, ne = reg.start_bp, reg.end_bp

        # 左边界劈断检查
        for idx, (gs, ge, _, _) in enumerate(orfs):
            if gs >= ns:
                break
            if ge > ns + min_hang_bp:
                overhang = ns - gs
                out_mean, out_max = _subbin_interval_stats(prof, gs, ns, bin_bp=bin_bp)
                p_val = float(ph_p[idx])
                p9_val = float(f10_p[idx, 9])
                core_max = float(np.max(f10_p[idx, :5]))
                func_max = float(np.max(f10_p[idx, :8]))

                if p9_val < 0.55 and (p_val >= snap_min_phage or (core_max >= 0.55 and p_val >= 0.65)):
                    if (out_mean >= snap_out_sub_mean) or (overhang <= 300 and out_max >= snap_out_sub_max):
                        if gs < ns:
                            ns = gs
                            snapped_edges += 1
                elif (p9_val >= 0.62 and p_val < 0.45) or (p_val < 0.15 and func_max < 0.30 and float(f10_p[idx, 4]) < 0.25):
                    if out_mean < 0.20 and (ne - ge) >= min_region_bp and ge > ns:
                        ns = ge
                        snapped_edges += 1

        # 右边界劈断检查
        for idx in range(len(orfs) - 1, -1, -1):
            gs, ge, _, _ = orfs[idx]
            if ge <= ne:
                break
            if gs < ne - min_hang_bp:
                overhang = ge - ne
                out_mean, out_max = _subbin_interval_stats(prof, ne, ge, bin_bp=bin_bp)
                p_val = float(ph_p[idx])
                p9_val = float(f10_p[idx, 9])
                core_max = float(np.max(f10_p[idx, :5]))
                func_max = float(np.max(f10_p[idx, :8]))

                if p9_val < 0.55 and (p_val >= snap_min_phage or (core_max >= 0.55 and p_val >= 0.65)):
                    if (out_mean >= snap_out_sub_mean) or (overhang <= 300 and out_max >= snap_out_sub_max):
                        if ge > ne:
                            ne = ge
                            snapped_edges += 1
                elif (p9_val >= 0.62 and p_val < 0.45) or (p_val < 0.15 and func_max < 0.30 and float(f10_p[idx, 4]) < 0.25):
                    if out_mean < 0.20 and (gs - ns) >= min_region_bp and gs < ne:
                        ne = gs
                        snapped_edges += 1

        refined.append(
            PredictedRegion(
                contig_id=cid,
                start_bp=max(0, min(ns, ne)),
                end_bp=min(c_len, max(ns, ne)),
                peak_score=reg.peak_score,
                mean_score=reg.mean_score,
                window_count=reg.window_count,
            )
        )
    return merge_nearby_regions(refined, merge_gap_bp=merge_gap_bp), snapped_edges


def _extract_active_subbin_segments(
    prof: np.ndarray,
    start_bp: int,
    end_bp: int,
    contig_len: int,
    *,
    sub_thr: float = 0.45,
    bin_bp: int = 200,
) -> List[Tuple[int, int]]:
    """提取指定区间内平滑填充单 bin 缺口后的连续 >= sub_thr 的 SubBin 活跃片段。"""
    n_bins = len(prof)
    b0 = max(0, start_bp // bin_bp)
    b1 = min(n_bins, (end_bp + bin_bp - 1) // bin_bp)
    if b1 <= b0:
        return []
    act = prof[b0:b1] >= sub_thr
    if act.size >= 3:
        act = act.copy()
        act[1:-1] = act[1:-1] | ((~act[1:-1]) & act[:-2] & act[2:])
    segs: List[Tuple[int, int]] = []
    cur_s = -1
    for offset, flag in enumerate(act):
        ab = b0 + offset
        if flag and cur_s < 0:
            cur_s = ab
        elif not flag and cur_s >= 0:
            segs.append((cur_s * bin_bp, min(contig_len, ab * bin_bp)))
            cur_s = -1
    if cur_s >= 0:
        segs.append((cur_s * bin_bp, min(contig_len, b1 * bin_bp)))
    return segs


def _can_absorb_companion_peak(
    prof: np.ndarray,
    orfs: Sequence[Tuple[int, int, int, str]],
    ph: np.ndarray,
    f10: np.ndarray,
    r2: np.ndarray,
    ps: int,
    pe: int,
    valley_s: int,
    valley_e: int,
    *,
    min_peak_len_bp: int = 4200,
    bin_bp: int = 200,
) -> bool:
    """校验窄谷对面的伴生 SubBin 次级峰是否属于同一前噬菌体的早期/极点侧翼臂。"""
    if (pe - ps) < min_peak_len_bp:
        return False
    sm, sx = _subbin_interval_stats(prof, ps, pe, bin_bp=bin_bp)
    if sx < 0.85 or sm < 0.65:
        return False

    v_idxs = [i for i, (gs, ge, _, _) in enumerate(orfs) if valley_s <= 0.5 * (gs + ge) <= valley_e]
    p_idxs = [i for i, (gs, ge, _, _) in enumerate(orfs) if ps <= 0.5 * (gs + ge) <= pe]
    if not p_idxs:
        return False

    if v_idxs:
        if float(np.max(f10[v_idxs, 9])) >= 0.65:
            return False
        consec_host = 0
        for vi in v_idxs:
            if float(ph[vi]) < 0.15 and float(f10[vi, 4]) < 0.20:
                consec_host += 1
                if consec_host >= 3:
                    return False
            else:
                consec_host = 0

    n_head = int(np.sum((r2[p_idxs, 0] >= 0.55) | (f10[p_idxs, 0] >= 0.60)))
    if n_head > 0:
        return False
    if float(np.max(f10[p_idxs, 9])) >= 0.65:
        return False
    return any(float(ph[pi]) >= 0.70 or float(f10[pi, 4]) >= 0.70 for pi in p_idxs)


def absorb_companion_subbin_peaks(
    regions: Sequence[PredictedRegion],
    orfs_by_contig: Mapping[str, Sequence[Tuple[int, int, int, str]]],
    scored_by_contig: Mapping[str, Dict[str, np.ndarray]],
    profiles_by_contig: Mapping[str, np.ndarray],
    contigs_bp: Mapping[str, int],
    *,
    max_valley_bp: int = 4500,
    search_span_bp: int = 16000,
    min_peak_len_bp: int = 4200,
    sub_thr: float = 0.45,
    merge_gap_bp: int = 3000,
    bin_bp: int = 200,
) -> Tuple[List[PredictedRegion], int]:
    """
    吸纳与主区段仅隔窄低谷 (<=4.5 kb) 且未独立成区的强 SubBin 伴生次级峰。
    通过谷内宿主墙校验、次级峰无冗余 Head 核约束与邻近主区段间隔保护杜绝错误并发。
    """
    if not regions:
        return [], 0

    by_cid: Dict[str, List[PredictedRegion]] = defaultdict(list)
    for r in regions:
        by_cid[r.contig_id].append(r)

    absorbed_cnt = 0
    out: List[PredictedRegion] = []
    for cid, regs in sorted(by_cid.items()):
        regs_s = sorted(regs, key=lambda x: (x.start_bp, x.end_bp))
        prof = profiles_by_contig.get(cid)
        orfs = orfs_by_contig.get(cid, [])
        sc = scored_by_contig.get(cid)
        if prof is None or len(prof) == 0 or not orfs or sc is None or len(sc.get("phage_probs", ())) != len(orfs):
            out.extend(regs_s)
            continue

        ph = sc["phage_probs"]
        f10 = sc["func10_probs"]
        r2 = _get_r2_core_probs(sc)
        c_len = contigs_bp.get(cid, max(len(prof) * bin_bp, orfs[-1][1]))

        for idx_r, reg in enumerate(regs_s):
            ns, ne = reg.start_bp, reg.end_bp
            prev_limit = regs_s[idx_r - 1].end_bp + 2000 if idx_r > 0 else 0
            next_limit = regs_s[idx_r + 1].start_bp - 2000 if idx_r + 1 < len(regs_s) else c_len

            l_lim = max(prev_limit, ns - search_span_bp)
            l_peaks = _extract_active_subbin_segments(prof, l_lim, max(l_lim, ns - bin_bp), c_len, sub_thr=sub_thr, bin_bp=bin_bp)
            if l_peaks:
                ps, pe = l_peaks[-1]
                if 0 < (ns - pe) <= max_valley_bp and _can_absorb_companion_peak(
                    prof, orfs, ph, f10, r2, ps, pe, pe, ns, min_peak_len_bp=min_peak_len_bp, bin_bp=bin_bp
                ):
                    ns = ps
                    absorbed_cnt += 1

            r_lim = min(next_limit, ne + search_span_bp)
            r_peaks = _extract_active_subbin_segments(prof, min(r_lim, ne + bin_bp), r_lim, c_len, sub_thr=sub_thr, bin_bp=bin_bp)
            if r_peaks:
                ps, pe = r_peaks[0]
                if 0 < (ps - ne) <= max_valley_bp and _can_absorb_companion_peak(
                    prof, orfs, ph, f10, r2, ps, pe, ne, ps, min_peak_len_bp=min_peak_len_bp, bin_bp=bin_bp
                ):
                    ne = pe
                    absorbed_cnt += 1

            out.append(PredictedRegion(cid, ns, ne, reg.peak_score, reg.mean_score, reg.window_count))

    return merge_nearby_regions(out, merge_gap_bp=merge_gap_bp), absorbed_cnt


def _should_snap_core_orf(
    ph: np.ndarray,
    f10: np.ndarray,
    r2: np.ndarray,
    prof: np.ndarray,
    idx_o: int,
    out_s: int,
    out_e: int,
    *,
    min_r2_core: float,
    min_ph_core: float,
    max_p9_core: float,
    min_out_sub_max: float,
    bin_bp: int,
) -> bool:
    """判定被边界轻度切分的边缘 ORF 是否属于具备外侧 DNA 残余支持的高置信噬菌体核心/整合酶蛋白。"""
    if float(ph[idx_o]) < min_ph_core or float(f10[idx_o, 9]) >= max_p9_core:
        return False
    if float(np.max(r2[idx_o, :5])) < min_r2_core:
        return False
    _, out_max = _subbin_interval_stats(prof, out_s, out_e, bin_bp=bin_bp)
    return out_max >= min_out_sub_max


def snap_split_core_orfs(
    regions: Sequence[PredictedRegion],
    orfs_by_contig: Mapping[str, Sequence[Tuple[int, int, int, str]]],
    scored_by_contig: Mapping[str, Dict[str, np.ndarray]],
    profiles_by_contig: Mapping[str, np.ndarray],
    *,
    min_r2_core: float = 0.70,
    min_ph_core: float = 0.90,
    max_p9_core: float = 0.20,
    min_out_sub_max: float = 0.05,
    max_snap_out_bp: int = 2200,
    min_hang_bp: int = 25,
    tandem_touch_bp: int = 200,
    bin_bp: int = 200,
) -> Tuple[List[PredictedRegion], int]:
    """
    在串联切分之后、att 对齐之前执行的精确核心与整合蛋白防劈断校准：
    - 锁定紧邻同 Contig 相邻区段 (<=200 bp) 的串联切分点，绝不越线吞入邻近前噬菌体；
    - 精确接纳高置信形态/整合酶核心边缘断口，要求外露段具备 >= min_out_sub_max 的 DNA 残余支持。
    """
    if not regions:
        return [], 0

    by_cid: Dict[str, List[PredictedRegion]] = defaultdict(list)
    for r in regions:
        by_cid[r.contig_id].append(r)

    snapped = 0
    out: List[PredictedRegion] = []
    for cid, regs in sorted(by_cid.items()):
        regs_s = sorted(regs, key=lambda x: (x.start_bp, x.end_bp))
        orfs = orfs_by_contig.get(cid, [])
        sc = scored_by_contig.get(cid)
        prof = profiles_by_contig.get(cid)
        if not orfs or sc is None or prof is None or len(sc.get("phage_probs", ())) != len(orfs):
            out.extend(regs_s)
            continue

        ph = sc["phage_probs"]
        f10 = sc["func10_probs"]
        r2 = _get_r2_core_probs(sc)
        for idx_r, reg in enumerate(regs_s):
            ns, ne = reg.start_bp, reg.end_bp
            prev_end = regs_s[idx_r - 1].end_bp if idx_r > 0 else 0
            next_start = regs_s[idx_r + 1].start_bp if idx_r + 1 < len(regs_s) else 10**12
            touch_prev = idx_r > 0 and (ns - prev_end) <= tandem_touch_bp
            touch_next = (idx_r + 1 < len(regs_s)) and (next_start - ne) <= tandem_touch_bp

            if not touch_prev:
                for i, (gs, ge, _, _) in enumerate(orfs):
                    if gs >= ns:
                        break
                    if gs >= prev_end and ge > ns + min_hang_bp and (ns - gs) <= max_snap_out_bp:
                        if _should_snap_core_orf(
                            ph,
                            f10,
                            r2,
                            prof,
                            i,
                            gs,
                            ns,
                            min_r2_core=min_r2_core,
                            min_ph_core=min_ph_core,
                            max_p9_core=max_p9_core,
                            min_out_sub_max=min_out_sub_max,
                            bin_bp=bin_bp,
                        ):
                            ns = min(ns, gs)
                            snapped += 1

            if not touch_next:
                for i in range(len(orfs) - 1, -1, -1):
                    gs, ge, _, _ = orfs[i]
                    if ge <= ne:
                        break
                    if ge <= next_start and gs < ne - min_hang_bp and (ge - ne) <= max_snap_out_bp:
                        if _should_snap_core_orf(
                            ph,
                            f10,
                            r2,
                            prof,
                            i,
                            ne,
                            ge,
                            min_r2_core=min_r2_core,
                            min_ph_core=min_ph_core,
                            max_p9_core=max_p9_core,
                            min_out_sub_max=min_out_sub_max,
                            bin_bp=bin_bp,
                        ):
                            ne = max(ne, ge)
                            snapped += 1

            out.append(PredictedRegion(cid, ns, ne, reg.peak_score, reg.mean_score, reg.window_count))
    return out, snapped


def _is_true_integrase_orf(ph: np.ndarray, f10: np.ndarray, idx_o: int) -> bool:
    """区分高置信噬菌体整合酶 (P4) 与插入序列转座酶 (P8)，杜绝将宿主 IS 元件误作整合极点。"""
    p4 = float(f10[idx_o, 4])
    p8 = float(f10[idx_o, 8])
    return p4 >= 0.65 and p4 >= p8 + 0.05 and float(ph[idx_o]) >= 0.72 and float(f10[idx_o, 9]) < 0.35


def _has_unannotated_dead_moat(
    prof: np.ndarray,
    orfs: Sequence[Tuple[int, int, int, str]],
    ph: np.ndarray,
    f10: np.ndarray,
    s_bp: int,
    e_bp: int,
    *,
    max_moat_bp: int = 3000,
    bin_bp: int = 200,
) -> bool:
    """检测跨越区间是否存在 >= max_moat_bp 且不被强噬菌体 ORF (ph>=0.80) 支撑的全冷 DNA 死水沟。"""
    b0 = max(0, s_bp // bin_bp)
    b1 = min(len(prof), (e_bp + bin_bp - 1) // bin_bp)
    if b1 <= b0:
        return False
    strong_bins = np.zeros(b1 - b0, dtype=bool)
    for idx_o, (gs, ge, _, _) in enumerate(orfs):
        if ge <= s_bp or gs >= e_bp:
            continue
        if float(ph[idx_o]) >= 0.80 and float(f10[idx_o, 9]) < 0.40:
            ib0 = max(b0, gs // bin_bp) - b0
            ib1 = min(b1, (ge + bin_bp - 1) // bin_bp) - b0
            strong_bins[ib0:ib1] = True

    need_bins = max_moat_bp // bin_bp
    run = 0
    for offset, v in enumerate(prof[b0:b1]):
        if float(v) < 0.035 and not strong_bins[offset]:
            run += 1
            if run >= need_bins:
                return True
        else:
            run = 0
    return False


def _passes_integrase_span_quality(
    prof: np.ndarray,
    orfs: Sequence[Tuple[int, int, int, str]],
    sc: Dict[str, np.ndarray],
    r2: np.ndarray,
    span_idxs: List[int],
    anch_i: int,
    dist_bp: int,
    s_bp: int,
    e_bp: int,
    *,
    max_search_bp: int,
    min_long_sub_mean: float,
    max_moat_bp: int,
    bin_bp: int,
) -> bool:
    """基于碱基长度 (bp) 加权与死水沟校验判定 Integrase 闭环检索跨度是否安全可靠。"""
    ph = sc["phage_probs"]
    f10 = sc["func10_probs"]
    if not span_idxs or dist_bp > max_search_bp or not _is_true_integrase_orf(ph, f10, anch_i):
        return False

    span_ph = ph[span_idxs]
    span_f10 = f10[span_idxs]
    span_r2 = r2[span_idxs]
    if int(np.sum((span_r2[:, 0] >= 0.60) | (span_f10[:, 0] >= 0.65))) > 0:
        return False
    if _has_unannotated_dead_moat(prof, orfs, ph, f10, s_bp, e_bp, max_moat_bp=max_moat_bp, bin_bp=bin_bp):
        return False

    consec_host = 0
    for si in span_idxs:
        if float(ph[si]) < 0.20 and float(f10[si, 4]) < 0.20:
            consec_host += 1
            if consec_host >= 3:
                return False
        else:
            consec_host = 0

    lens = np.array([max(50, orfs[si][1] - orfs[si][0]) for si in span_idxs], dtype=np.float64)
    bp_tot = float(np.sum(lens))
    bp_mean = float(np.sum(span_ph * lens) / bp_tot)
    bp_frac = float(np.sum(lens[span_ph >= 0.50]) / bp_tot)
    host_bp = float(np.sum(lens[(span_ph < 0.20) | (span_f10[:, 9] >= 0.62)]))
    max_p9 = float(np.max(span_f10[:, 9]))
    sm, sx = _subbin_interval_stats(prof, s_bp, e_bp, bin_bp=bin_bp)

    if dist_bp <= 2200:
        return bp_mean >= 0.72 and host_bp == 0.0 and max_p9 < 0.35 and sx >= 0.25
    return (
        bp_mean >= 0.62
        and bp_frac >= 0.56
        and max_p9 < 0.62
        and host_bp <= 2500.0
        and (sm >= min_long_sub_mean or sx >= 0.28)
    )


def _search_directional_integrase_anchor(
    orfs: Sequence[Tuple[int, int, int, str]],
    sc: Dict[str, np.ndarray],
    r2: np.ndarray,
    prof: np.ndarray,
    *,
    anchor_edge_bp: int,
    limit_bp: int,
    boundary_orf_idx: int,
    direction: int,
    edge_in_int: float,
    locked_side: bool,
    max_search_bp: int,
    min_long_sub_mean: float,
    max_moat_bp: int,
    bin_bp: int,
) -> Optional[int]:
    """沿单向 (direction=-1 向左, +1 向右) 搜索未封口端点的真 Integrase 锚点并延拓同族整合酶簇。"""
    if locked_side or edge_in_int >= 0.55:
        return None

    ph = sc["phage_probs"]
    f10 = sc["func10_probs"]
    cand_indices = (
        range(boundary_orf_idx - 1, -1, -1)
        if direction < 0
        else range(boundary_orf_idx + 1, len(orfs))
    )

    best_idx: Optional[int] = None
    for ci in cand_indices:
        cand_bound = orfs[ci][0] if direction < 0 else orfs[ci][1]
        if (cand_bound < limit_bp) if direction < 0 else (cand_bound > limit_bp):
            break
        dist_bp = (anchor_edge_bp - cand_bound) if direction < 0 else (cand_bound - anchor_edge_bp)
        if dist_bp > max_search_bp:
            break
        span_idxs = list(range(ci, boundary_orf_idx)) if direction < 0 else list(range(boundary_orf_idx + 1, ci + 1))
        s_bp, e_bp = (cand_bound, anchor_edge_bp) if direction < 0 else (anchor_edge_bp, cand_bound)
        if _passes_integrase_span_quality(
            prof,
            orfs,
            sc,
            r2,
            span_idxs,
            ci,
            dist_bp,
            s_bp,
            e_bp,
            max_search_bp=max_search_bp,
            min_long_sub_mean=min_long_sub_mean,
            max_moat_bp=max_moat_bp,
            bin_bp=bin_bp,
        ):
            best_idx = ci

    if best_idx is None:
        return None

    # 同一末端 <=500 bp 内的连续 Integrase 碎片簇整体囊括
    while True:
        next_idx = best_idx + direction
        if next_idx < 0 or next_idx >= len(orfs):
            break
        next_bound = orfs[next_idx][0] if direction < 0 else orfs[next_idx][1]
        within_limit = (next_bound >= limit_bp) if direction < 0 else (next_bound <= limit_bp)
        adj_gap = (orfs[best_idx][0] - orfs[next_idx][1]) if direction < 0 else (orfs[next_idx][0] - orfs[best_idx][1])
        next_dist = abs(next_bound - anchor_edge_bp)
        if (
            within_limit
            and adj_gap <= 500
            and next_dist <= max_search_bp
            and _is_true_integrase_orf(ph, f10, next_idx)
        ):
            best_idx = next_idx
        else:
            break

    final_bound = orfs[best_idx][0] if direction < 0 else orfs[best_idx][1]
    if (final_bound < anchor_edge_bp) if direction < 0 else (final_bound > anchor_edge_bp):
        return final_bound
    return None


def close_flanks_to_integrase_anchors(
    regions: Sequence[PredictedRegion],
    orfs_by_contig: Mapping[str, Sequence[Tuple[int, int, int, str]]],
    scored_by_contig: Mapping[str, Dict[str, np.ndarray]],
    profiles_by_contig: Mapping[str, np.ndarray],
    contigs_bp: Mapping[str, int],
    *,
    locked_keys: Optional[Set[str]] = None,
    max_search_bp: int = 18000,
    min_long_sub_mean: float = 0.040,
    max_moat_bp: int = 3000,
    bin_bp: int = 200,
) -> Tuple[List[PredictedRegion], int]:
    """
    基于真整合酶 (Integrase P4) 极点锚定的侧翼闭环定界：
    - 严禁修改已被精确 attL/attR 对齐锁死的区段 (locked_keys)；
    - 严禁重新合并区段，并锁死串联/紧贴边界 (<=1.5 kb)，永久保护背靠背前噬菌体对；
    - 仅在未封口侧翼搜索受高蛋白连续度与非死水沟支撑保护的 Integrase 极点延伸。
    """
    if not regions:
        return [], 0

    locked = locked_keys or set()
    by_cid: Dict[str, List[PredictedRegion]] = defaultdict(list)
    for r in regions:
        by_cid[r.contig_id].append(r)

    closed_cnt = 0
    out: List[PredictedRegion] = []
    for cid, regs in sorted(by_cid.items()):
        regs_s = sorted(regs, key=lambda x: (x.start_bp, x.end_bp))
        orfs = orfs_by_contig.get(cid, [])
        sc = scored_by_contig.get(cid)
        prof = profiles_by_contig.get(cid)
        if not orfs or sc is None or prof is None or len(sc.get("phage_probs", ())) != len(orfs):
            out.extend(regs_s)
            continue

        ph = sc["phage_probs"]
        f10 = sc["func10_probs"]
        r2 = _get_r2_core_probs(sc)
        c_len = contigs_bp.get(cid, max(len(prof) * bin_bp, orfs[-1][1]))

        for idx_r, reg in enumerate(regs_s):
            if f"{cid}:{reg.start_bp}-{reg.end_bp}" in locked:
                out.append(reg)
                continue

            ns, ne = reg.start_bp, reg.end_bp
            prev_end = regs_s[idx_r - 1].end_bp if idx_r > 0 else 0
            next_start = regs_s[idx_r + 1].start_bp if idx_r + 1 < len(regs_s) else c_len
            lock_l = idx_r > 0 and (ns - prev_end) <= 1500
            lock_r = (idx_r + 1 < len(regs_s)) and (next_start - ne) <= 1500
            prev_limit = prev_end + 3500 if idx_r > 0 else 0
            next_limit = next_start - 3500 if idx_r + 1 < len(regs_s) else c_len

            in_idxs = [i for i, (gs, ge, _, _) in enumerate(orfs) if ns <= 0.5 * (gs + ge) <= ne]
            if not in_idxs:
                out.append(reg)
                continue

            left_in_int = max((float(f10[i, 4]) for i in in_idxs[:3] if float(ph[i]) >= 0.65), default=0.0)
            right_in_int = max((float(f10[i, 4]) for i in in_idxs[-3:] if float(ph[i]) >= 0.65), default=0.0)

            new_l = _search_directional_integrase_anchor(
                orfs,
                sc,
                r2,
                prof,
                anchor_edge_bp=ns,
                limit_bp=prev_limit,
                boundary_orf_idx=in_idxs[0],
                direction=-1,
                edge_in_int=left_in_int,
                locked_side=lock_l,
                max_search_bp=max_search_bp,
                min_long_sub_mean=min_long_sub_mean,
                max_moat_bp=max_moat_bp,
                bin_bp=bin_bp,
            )
            if new_l is not None:
                ns = new_l
                closed_cnt += 1

            new_r = _search_directional_integrase_anchor(
                orfs,
                sc,
                r2,
                prof,
                anchor_edge_bp=ne,
                limit_bp=next_limit,
                boundary_orf_idx=in_idxs[-1],
                direction=1,
                edge_in_int=right_in_int,
                locked_side=lock_r,
                max_search_bp=max_search_bp,
                min_long_sub_mean=min_long_sub_mean,
                max_moat_bp=max_moat_bp,
                bin_bp=bin_bp,
            )
            if new_r is not None:
                ne = new_r
                closed_cnt += 1

            out.append(PredictedRegion(cid, ns, ne, reg.peak_score, reg.mean_score, reg.window_count))

    return out, closed_cnt


def extract_subbin_gray_candidates(
    window_preds: Sequence[WindowPrediction],
    sub_probs: np.ndarray,
    *,
    bin_bp: int = 200,
    sub_active_threshold: float = 0.40,
    min_region_bp: int = 5000,
    min_peak_sub_prob: float = 0.90,
    min_mean_sub_prob: float = 0.55,
    merge_gap_bp: int = 2000,
) -> List[PredictedRegion]:
    """
    从 200bp 亚窗口 (sub_probs) 局部剖面抽取被全局 ContextRefiner 压低 window_score、
    但具备强烈局域连续 200bp 响应的灰区候选片段（供 R3 Judge 二审筛选隐蔽短前噬菌体）。
    """
    if not window_preds or sub_probs is None or len(sub_probs) == 0:
        return []

    by_cid: Dict[str, List[int]] = defaultdict(list)
    max_end: Dict[str, int] = defaultdict(int)
    for i, wp in enumerate(window_preds):
        by_cid[wp.contig_id].append(i)
        if wp.end_bp > max_end[wp.contig_id]:
            max_end[wp.contig_id] = wp.end_bp

    cands: List[PredictedRegion] = []
    for cid, idxs in sorted(by_cid.items()):
        contig_end = max_end[cid]
        prof = assemble_contig_subbin_profile(
            [window_preds[i] for i in idxs],
            [sub_probs[i] for i in idxs],
            contig_end,
            bin_bp=bin_bp,
            smooth_profile=True,
        )
        if len(prof) == 0:
            continue
        active = (prof >= sub_active_threshold).copy()
        if active.size >= 3:
            active[1:-1] = active[1:-1] | ((~active[1:-1]) & active[:-2] & active[2:])

        segs: List[Tuple[int, int]] = []
        seg_s = -1
        for bi, fl in enumerate(active):
            if fl and seg_s < 0:
                seg_s = bi
            elif not fl and seg_s >= 0:
                segs.append((seg_s, bi))
                seg_s = -1
        if seg_s >= 0:
            segs.append((seg_s, len(active)))

        merged_segs: List[Tuple[int, int]] = []
        gap_bins = max(0, merge_gap_bp // bin_bp)
        for bs, be in segs:
            if merged_segs and (bs - merged_segs[-1][1]) <= gap_bins:
                merged_segs[-1] = (merged_segs[-1][0], be)
            else:
                merged_segs.append((bs, be))

        for bs, be in merged_segs:
            s_bp = bs * bin_bp
            e_bp = min(contig_end, be * bin_bp)
            if (e_bp - s_bp) < min_region_bp:
                continue
            seg_vals = prof[bs:be]
            pk = float(np.max(seg_vals))
            mn = float(np.mean(seg_vals))
            if pk >= min_peak_sub_prob and mn >= min_mean_sub_prob:
                cands.append(
                    PredictedRegion(
                        contig_id=cid,
                        start_bp=s_bp,
                        end_bp=e_bp,
                        peak_score=round(pk, 5),
                        mean_score=round(mn, 5),
                        window_count=max(1, (e_bp - s_bp) // 2500),
                    )
                )
    return cands


def trim_triggered(new_val: int, old_val: int) -> bool:
    return new_val > old_val


def _region_overlaps_any(
    cand: PredictedRegion,
    others: Sequence[PredictedRegion],
    min_overlap_bp: int = 500,
    min_clearance_bp: int = 0,
) -> bool:
    for r in others:
        if r.contig_id != cand.contig_id:
            continue
        if min_clearance_bp > 0:
            if max(r.start_bp - min_clearance_bp, cand.start_bp) < min(r.end_bp + min_clearance_bp, cand.end_bp):
                return True
        elif min(r.end_bp, cand.end_bp) - max(r.start_bp, cand.start_bp) >= min_overlap_bp:
            return True
    return False


def _get_r2_core_probs(sc: Dict[str, np.ndarray]) -> np.ndarray:
    """安全获取 R2/Head B 核心结构 5 维概率矩阵，缺失时回落至 R3 功能前 5 列。"""
    if "r2_core_probs" in sc and sc["r2_core_probs"] is not None:
        return sc["r2_core_probs"]
    return sc["func10_probs"][:, :5]


def _should_veto_base_region(
    ph_sub: np.ndarray,
    f10_sub: np.ndarray,
    *,
    strict_veto_max_mean_phage: float,
    morph_veto_max_mean_phage: float,
    r2_sub: Optional[np.ndarray] = None,
    enable_cross_head_mge_veto: bool = True,
) -> bool:
    """判定主干候选是否属于无形态结构核心的宿主防御岛、质粒 MGE 或接合耐药移动岛假阳性。"""
    mean_ph = float(np.mean(ph_sub))
    max_f10 = np.max(f10_sub, axis=0)
    core_mods = int(np.sum(max_f10[:5] >= 0.50))
    morph_mods = int(np.sum(max_f10[:3] >= 0.50))
    max_p8 = float(max_f10[8])
    max_p9 = float(max_f10[9])
    # 极低蛋白响应且零核心模块（Head/Conn/Tail/Lysis/Int 全无）：安全清除纯粹 DNA 误提质粒或纯复制型片段（如 V583 2227k ICE 残片）
    if mean_ph <= 0.10 and core_mods == 0 and int(np.sum(ph_sub >= 0.50)) == 0:
        return True
    if mean_ph < strict_veto_max_mean_phage and core_mods == 0 and max_p9 >= 0.65:
        return True
    if morph_mods == 0 and mean_ph < morph_veto_max_mean_phage:
        if (max_p9 >= 0.65 and max_p8 >= 0.50) or max_p9 >= 0.72 or (max_p8 >= 0.60 and mean_ph < 0.46):
            return True

    # Opt-1a 跨头联合排雷：Head B 确认零形态/裂解蛋白，同时 Head A 并发高 MGE(P8) 与高防御(P9) 载荷
    if enable_cross_head_mge_veto and r2_sub is not None and len(r2_sub) > 0:
        r2_morph_cnt = int(np.sum(np.max(r2_sub[:, :4], axis=0) >= 0.50))
        mean_p9 = float(np.mean(f10_sub[:, 9]))
        if r2_morph_cnt == 0 and max_p8 >= 0.55 and max_p9 >= 0.45 and mean_p9 >= 0.18 and mean_ph < 0.72:
            return True

    return False


def _is_gray_tailocin_like(
    f10_sub: np.ndarray,
    r2_sub: np.ndarray,
) -> bool:
    """识别灰区中缺乏衣壳(Head)、颈环(Connector)与整合酶(Int)的纯尾部+裂解细菌素(Tailocin)。"""
    max_f10 = np.max(f10_sub, axis=0)
    max_r2 = np.max(r2_sub, axis=0)
    r2_tail_cnt = int(np.sum(r2_sub[:, 2] >= 0.50))
    r2_head_max = float(max_r2[0])
    r2_conn_max = float(max_r2[1])
    int_max = float(max(max_r2[4], max_f10[4]))
    if r2_tail_cnt >= 3 and r2_head_max < 0.45 and r2_conn_max < 0.45 and int_max < 0.45:
        return True

    # 校准后 Head A (f10_sub) 明确为纯尾+裂解且无 Head/Connector/Integrase 时，允许容忍 Head B 至多 1 个单 ORF 噪音
    f10_tail_cnt = int(np.sum(f10_sub[:, 2] >= 0.50))
    f10_head_cnt = int(np.sum(f10_sub[:, 0] >= 0.50))
    f10_conn_cnt = int(np.sum(f10_sub[:, 1] >= 0.50))
    r2_head_cnt = int(np.sum(r2_sub[:, 0] >= 0.55))
    r2_conn_cnt = int(np.sum(r2_sub[:, 1] >= 0.55))
    return (
        f10_tail_cnt >= 3
        and f10_head_cnt == 0
        and f10_conn_cnt == 0
        and float(max_f10[0]) < 0.48
        and float(max_f10[1]) < 0.48
        and r2_head_cnt <= 1
        and r2_conn_cnt <= 1
        and int_max < 0.45
    )


def _passes_gray_rescue_criteria(
    ph_sub: np.ndarray,
    f10_sub: np.ndarray,
    *,
    rescue_min_orfs: int,
    rescue_min_mean_phage: float,
    rescue_min_frac_phage: float,
    rescue_min_active_modules: int,
    rescue_max_mean_p9: float,
    rescue_min_morph_prob: float,
    require_structural_evidence: bool,
    r2_sub: Optional[np.ndarray] = None,
    enable_elastic_rescue: bool = True,
    enable_tailocin_guard: bool = True,
    cand_len_bp: int = 0,
    cand_peak_score: float = 0.0,
    cand_mean_score: float = 0.0,
) -> bool:
    """对 SubBin 灰区候选执行梯度核验与 Tailocin 排雷，兼顾极短隐蔽前噬菌体挽救与零误报防线。"""
    n_orf = len(ph_sub)
    mean_ph = float(np.mean(ph_sub))
    frac_ph = float(np.mean(ph_sub >= 0.50))
    pos_cnt = int(np.sum(ph_sub >= 0.50))
    max_f10 = np.max(f10_sub, axis=0)
    r2_use = r2_sub if r2_sub is not None else f10_sub[:, :5]
    max_r2 = np.max(r2_use, axis=0)
    active_phage_mods = int(np.sum(max_f10[:7] >= 0.50))
    df_cnt = int(np.sum(f10_sub[:, 9] >= 0.65))
    mean_p9 = float(np.mean(f10_sub[:, 9]))

    passed = (
        mean_ph >= rescue_min_mean_phage
        and frac_ph >= rescue_min_frac_phage
        and pos_cnt >= max(3, rescue_min_orfs - 1)
        and active_phage_mods >= rescue_min_active_modules
        and mean_p9 <= rescue_max_mean_p9
        and df_cnt <= pos_cnt // 2
    )
    if passed and require_structural_evidence:
        morph_mods = int(np.sum(max_f10[:3] >= rescue_min_morph_prob))
        core_mods = int(np.sum(max_f10[:5] >= 0.50))
        has_lysis_pair = float(max_f10[3]) >= 0.65 and core_mods >= 2
        if morph_mods == 0 and not has_lysis_pair:
            passed = False
        # 质粒/转座酶高风险标签激活时需多形态模块交叉佐证，防范孤立假结构蛋白误召
        elif float(max_f10[8]) >= 0.55 and morph_mods < 2:
            passed = False

    if not passed and require_structural_evidence and enable_elastic_rescue:
        # Opt-3a 弹性高置信梯度：整合 Head A/B 形态核心并集，在多模块齐备时放宽边缘 P8 阻断（如 Sakai Sp17）
        comb_morph = np.maximum(max_f10[:3], max_r2[:3])
        comb_morph_mods = int(np.sum(comb_morph >= rescue_min_morph_prob))
        comb_core = int(np.sum(np.maximum(max_f10[:5], max_r2[:5]) >= 0.50))
        if (
            n_orf >= rescue_min_orfs
            and mean_ph >= 0.72
            and frac_ph >= 0.75
            and active_phage_mods >= 3
            and mean_p9 <= 0.45
            and df_cnt <= 2
            and comb_morph_mods >= 1
            and comb_core >= 2
        ):
            passed = True

    if not passed and require_structural_evidence and enable_elastic_rescue:
        # Opt-3b2 短形态簇挽救：针对 6..10 ORF、零防御零 MGE 且具备 Head B 核实尾/头的紧致碎片（如 LT2 STM2234）
        r2_tail_or_head = int(np.sum(r2_use[:, 0] >= 0.50)) + int(np.sum(r2_use[:, 2] >= 0.50))
        if (
            6 <= n_orf <= 10
            and mean_ph >= 0.62
            and frac_ph >= 0.60
            and pos_cnt >= 3
            and df_cnt == 0
            and float(max_f10[8]) < 0.25
            and float(max_f10[2]) >= 0.75
            and r2_tail_or_head >= 1
        ):
            passed = True

    if not passed and require_structural_evidence and enable_elastic_rescue:
        # Opt-3c 非尾丝状噬菌体(Inovirus)高平台 DNA + 双流双衣壳与整合酶协同挽救（如 PAO1 Pf4）
        r2_head_cnt = int(np.sum(r2_use[:, 0] >= 0.50))
        if (
            cand_len_bp >= 10000
            and cand_peak_score >= 0.98
            and cand_mean_score >= 0.90
            and n_orf >= 12
            and mean_ph >= 0.28
            and df_cnt == 0
            and mean_p9 <= 0.28
            and float(max_f10[8]) < 0.75
            and float(max_f10[0]) >= 0.65
            and float(max_r2[0]) >= 0.65
            and r2_head_cnt >= 2
            and float(max(max_f10[4], max_r2[4])) >= 0.70
        ):
            passed = True

    if not passed:
        return False

    if require_structural_evidence and enable_tailocin_guard and _is_gray_tailocin_like(f10_sub, r2_use):
        return False

    return True


def bridge_complementary_phage_fragments(
    regions: Sequence[PredictedRegion],
    orfs_by_contig: Dict[str, List[Tuple[int, int, int, str]]],
    scored_by_contig: Dict[str, Dict[str, np.ndarray]],
    *,
    max_subarm_gap_bp: int = 10000,
    max_bridge_gap_bp: int = 20000,
) -> Tuple[List[PredictedRegion], int]:
    """
    Opt-4b2 两级严格互补半臂桥接：
    - Pass 1（结构子臂合拢 <=10kb）：先将中间无强宿主防御且各自专精互补的 Head 臂 (h>=3, l==0, i==0)
      与 Tail+Lysis 臂 (h==0, t>=3, l>=1, i==0) 合拢成完整结构大臂；
    - Pass 2（早臂-结构臂桥接 <=20kb）：一方是缺失 Head 的 >=30kb 早期复制/整合长臂、
      另一方是缺失 Integrase 的完整 Head+Tail+Lysis 结构臂，总跨度 >= 75kb 且 gap 内无宿主防御墙并含锚点支持时，
      桥接回单株完整巨型前噬菌体（如 B. subtilis SPbeta），严禁合并两株独立完整噬菌体或独立小卫星岛。
    """
    if len(regions) <= 1:
        return list(regions), 0

    by_cid: Dict[str, List[PredictedRegion]] = defaultdict(list)
    for r in regions:
        by_cid[r.contig_id].append(r)

    def _arm_stats(
        reg: PredictedRegion,
        orfs: Sequence[Tuple[int, int, int, str]],
        sc: Dict[str, np.ndarray],
    ) -> Tuple[int, int, int, int, int, int]:
        idxs = [i for i, (gs, ge, _, _) in enumerate(orfs) if reg.start_bp <= 0.5 * (gs + ge) <= reg.end_bp]
        span = reg.end_bp - reg.start_bp
        if not idxs:
            return 0, 0, 0, 0, 0, span
        r2 = _get_r2_core_probs(sc)[idxs]
        f10 = sc["func10_probs"][idxs]
        n_head = int(np.sum(r2[:, 0] >= 0.50))
        n_tail = int(np.sum(r2[:, 2] >= 0.50))
        n_lysis = int(np.sum(r2[:, 3] >= 0.50))
        n_int = int(np.sum(r2[:, 4] >= 0.50))
        n_rep = int(np.sum(f10[:, 5] >= 0.50)) + int(np.sum(f10[:, 6] >= 0.50))
        return n_head, n_tail, n_lysis, n_int, n_rep, span

    def _gap_supports_bridge(
        cur: PredictedRegion,
        nxt: PredictedRegion,
        orfs: Sequence[Tuple[int, int, int, str]],
        sc: Dict[str, np.ndarray],
    ) -> bool:
        gap_idxs = [i for i, (gs, ge, _, _) in enumerate(orfs) if cur.end_bp <= 0.5 * (gs + ge) <= nxt.start_bp]
        if not gap_idxs:
            return False
        ph_arr = sc["phage_probs"]
        f10 = sc["func10_probs"]
        r2 = _get_r2_core_probs(sc)
        p9_host = sum(1 for i in gap_idxs if float(f10[i, 9]) >= 0.65 and float(ph_arr[i]) < 0.40)
        if p9_host >= 2:
            return False
        strong_anchors = sum(1 for i in gap_idxs if float(ph_arr[i]) >= 0.70)
        core_or_ph = sum(1 for i in gap_idxs if float(np.max(r2[i, :5])) >= 0.45 or float(ph_arr[i]) >= 0.55)
        return (strong_anchors >= 2) or (p9_host == 0 and core_or_ph >= 3)

    def _merge_pair(cur: PredictedRegion, nxt: PredictedRegion, cid: str) -> PredictedRegion:
        return PredictedRegion(
            contig_id=cid,
            start_bp=cur.start_bp,
            end_bp=nxt.end_bp,
            peak_score=max(cur.peak_score, nxt.peak_score),
            mean_score=round(0.5 * (cur.mean_score + nxt.mean_score), 5),
            window_count=cur.window_count + nxt.window_count,
        )

    out: List[PredictedRegion] = []
    bridged_cnt = 0
    for cid in sorted(by_cid.keys()):
        regs_s = sorted(by_cid[cid], key=lambda x: (x.start_bp, x.end_bp))
        orfs = orfs_by_contig.get(cid, [])
        sc = scored_by_contig.get(cid)
        if not orfs or sc is None:
            out.extend(regs_s)
            continue

        # Pass 1: 结构子臂优先合拢
        pass1: List[PredictedRegion] = [regs_s[0]]
        for nxt in regs_s[1:]:
            cur = pass1[-1]
            gap = nxt.start_bp - cur.end_bp
            if 1000 < gap <= max_subarm_gap_bp:
                h1, t1, l1, i1, _, _ = _arm_stats(cur, orfs, sc)
                h2, t2, l2, i2, _, _ = _arm_stats(nxt, orfs, sc)
                sub_12 = (h1 >= 3 and i1 == 0 and l1 == 0) and (h2 == 0 and t2 >= 3 and l2 >= 1 and i2 == 0)
                sub_21 = (h2 >= 3 and i2 == 0 and l2 == 0) and (h1 == 0 and t1 >= 3 and l1 >= 1 and i1 == 0)
                if (sub_12 or sub_21) and _gap_supports_bridge(cur, nxt, orfs, sc):
                    pass1[-1] = _merge_pair(cur, nxt, cid)
                    bridged_cnt += 1
                    continue
            pass1.append(nxt)

        # Pass 2: 早臂-结构臂桥接
        pass2: List[PredictedRegion] = [pass1[0]]
        for nxt in pass1[1:]:
            cur = pass2[-1]
            gap = nxt.start_bp - cur.end_bp
            if 3000 < gap <= max_bridge_gap_bp:
                h1, t1, l1, i1, rep1, len1 = _arm_stats(cur, orfs, sc)
                h2, t2, l2, i2, rep2, len2 = _arm_stats(nxt, orfs, sc)
                arm_1_early = (h1 == 0 and len1 >= 30000 and rep1 >= 10 and i1 >= 1) and (
                    h2 >= 3 and t2 >= 5 and l2 >= 1 and i2 == 0
                )
                arm_2_early = (h2 == 0 and len2 >= 30000 and rep2 >= 10 and i2 >= 1) and (
                    h1 >= 3 and t1 >= 5 and l1 >= 1 and i1 == 0
                )
                if (arm_1_early or arm_2_early) and (nxt.end_bp - cur.start_bp) >= 75000 and _gap_supports_bridge(cur, nxt, orfs, sc):
                    pass2[-1] = _merge_pair(cur, nxt, cid)
                    bridged_cnt += 1
                    continue
            pass2.append(nxt)

        out.extend(pass2)
    return out, bridged_cnt


def split_tandem_prophage_regions(
    regions: Sequence[PredictedRegion],
    orfs_by_contig: Dict[str, List[Tuple[int, int, int, str]]],
    scored_by_contig: Dict[str, Dict[str, np.ndarray]],
) -> Tuple[List[PredictedRegion], int]:
    """
    Opt-4a2 严格串联前噬菌体拆分：
    仅当长区段 (>=65kb, >=40 ORFs) 内部存在 >=2 个间距 >=25kb 的多基因强衣壳核心簇 (每簇 >=3 个 P0>=0.80)，
    且两簇之间同时呈现深度低噬菌体谷底 (>=2 个 ph<0.35) 与高置信整合酶界桩 (>=2 个 P4>=0.70) 时，
    在谷底/界桩前沿将其精准拆分为两株独立前噬菌体，零误切巨噬菌体。
    """
    out: List[PredictedRegion] = []
    split_cnt = 0
    for reg in regions:
        if (reg.end_bp - reg.start_bp) < 65000:
            out.append(reg)
            continue
        orfs = orfs_by_contig.get(reg.contig_id, [])
        sc = scored_by_contig.get(reg.contig_id)
        if not orfs or sc is None:
            out.append(reg)
            continue
        idxs = [i for i, (gs, ge, _, _) in enumerate(orfs) if reg.start_bp <= 0.5 * (gs + ge) <= reg.end_bp]
        if len(idxs) < 40:
            out.append(reg)
            continue

        r2_probs = _get_r2_core_probs(sc)
        ph_probs = sc["phage_probs"]
        p0_positions = [int(0.5 * (orfs[i][0] + orfs[i][1])) for i in idxs if float(r2_probs[i, 0]) >= 0.80]
        if len(p0_positions) < 6:
            out.append(reg)
            continue

        clusters: List[List[int]] = [[p0_positions[0]]]
        for pos in p0_positions[1:]:
            if pos - clusters[-1][-1] <= 12000:
                clusters[-1].append(pos)
            else:
                clusters.append([pos])
        strong_clusters = [c for c in clusters if len(c) >= 3]
        if len(strong_clusters) < 2:
            out.append(reg)
            continue

        c0_end = strong_clusters[0][-1]
        c1_start = strong_clusters[1][0]
        if (c1_start - c0_end) < 25000:
            out.append(reg)
            continue

        mid_idxs = [
            i
            for i in idxs
            if (c0_end + 5000) <= 0.5 * (orfs[i][0] + orfs[i][1]) <= (c1_start - 5000)
        ]
        p4_strong = [i for i in mid_idxs if float(r2_probs[i, 4]) >= 0.70]
        deep_valley = [i for i in mid_idxs if float(ph_probs[i]) < 0.35]
        if len(p4_strong) >= 2 and len(deep_valley) >= 2:
            p4_onset = orfs[p4_strong[0]][0]
            pre_val = [i for i in deep_valley if orfs[i][1] <= p4_onset + 3000]
            split_bp = orfs[pre_val[-1]][1] if pre_val else p4_onset
            if (split_bp - reg.start_bp) >= 20000 and (reg.end_bp - split_bp) >= 20000:
                half_win = max(1, reg.window_count // 2)
                out.append(
                    PredictedRegion(
                        contig_id=reg.contig_id,
                        start_bp=reg.start_bp,
                        end_bp=split_bp,
                        peak_score=reg.peak_score,
                        mean_score=reg.mean_score,
                        window_count=half_win,
                    )
                )
                out.append(
                    PredictedRegion(
                        contig_id=reg.contig_id,
                        start_bp=split_bp,
                        end_bp=reg.end_bp,
                        peak_score=reg.peak_score,
                        mean_score=reg.mean_score,
                        window_count=max(1, reg.window_count - half_win),
                    )
                )
                split_cnt += 1
                continue
        out.append(reg)
    return out, split_cnt


def reconcile_tentative_siblings(
    regions: Sequence[PredictedRegion],
    tentative_siblings: Sequence[Dict[str, Any]],
    *,
    stats: Optional[Dict[str, int]] = None,
    suppressed_out: Optional[List[Dict[str, Any]]] = None,
) -> List[PredictedRegion]:
    """
    验证暂存邻接兄弟臂是否在拓扑桥接阶段真正并入了更大前噬菌体；
    凡未与主臂合拢的孤立碎片均安全撤回并计为 gray_rejected，严防新增独立误报。
    """
    if not tentative_siblings:
        return list(regions)

    sib_entries = list(tentative_siblings)
    kept_out: List[PredictedRegion] = []

    for reg in regions:
        matched_isolated = False
        for ent in sib_entries:
            cand: PredictedRegion = ent["region"]
            if reg.contig_id != cand.contig_id:
                continue
            ov = min(reg.end_bp, cand.end_bp) - max(reg.start_bp, cand.start_bp)
            cand_len = max(1, cand.end_bp - cand.start_bp)
            reg_len = reg.end_bp - reg.start_bp
            # 若最终输出区段就是该暂存孤岛自己（未被其他臂桥接扩大），判定为未并入，安全剔除
            if ov >= 0.8 * cand_len and reg_len <= cand_len + 1500:
                matched_isolated = True
                break
        if not matched_isolated:
            kept_out.append(reg)

    for ent in sib_entries:
        cand = ent["region"]
        cand_len = max(1, cand.end_bp - cand.start_bp)
        merged_into_host = any(
            reg.contig_id == cand.contig_id
            and (min(reg.end_bp, cand.end_bp) - max(reg.start_bp, cand.start_bp)) >= 0.7 * cand_len
            and (reg.end_bp - reg.start_bp) >= cand_len + 2000
            for reg in kept_out
        )
        if merged_into_host:
            if stats is not None:
                if not ent.get("is_shadow", False):
                    stats["gray_rescued"] = stats.get("gray_rescued", 0) + 1
                stats["sibling_rescued"] = stats.get("sibling_rescued", 0) + 1
        else:
            if not ent.get("is_shadow", False):
                if stats is not None:
                    stats["gray_rejected"] = stats.get("gray_rejected", 0) + 1
                if suppressed_out is not None:
                    suppressed_out.append({
                        "contig_id": cand.contig_id,
                        "start_bp": cand.start_bp,
                        "end_bp": cand.end_bp,
                        "reason": "gray_rejected",
                        "mean_phage_prob": ent["mean_phage_prob"],
                        "max_p9": ent["max_p9"],
                    })
    return kept_out


def rescue_and_filter_regions_with_judge(
    base_regions: Sequence[PredictedRegion],
    relaxed_regions: Sequence[PredictedRegion],
    orfs_by_contig: Dict[str, List[Tuple[int, int, int, str]]],
    scored_by_contig: Dict[str, Dict[str, np.ndarray]],
    *,
    rescue_min_orfs: int = 6,
    rescue_min_mean_phage: float = 0.58,
    rescue_min_frac_phage: float = 0.60,
    rescue_min_active_modules: int = 2,
    rescue_max_mean_p9: float = 0.35,
    rescue_min_morph_prob: float = 0.55,
    require_structural_evidence: bool = True,
    min_base_clearance_bp: int = 10000,
    strict_veto_max_mean_phage: float = 0.22,
    morph_veto_max_mean_phage: float = 0.48,
    merge_gap_bp: int = 3000,
    enable_cross_head_mge_veto: bool = True,
    enable_elastic_rescue: bool = True,
    enable_tailocin_guard: bool = True,
    enable_topology_postprocess: bool = True,
    enable_sibling_arm_rescue: bool = True,
    max_bridge_gap_bp: int = 20000,
    suppressed_out: Optional[List[Dict[str, Any]]] = None,
    tentative_siblings_out: Optional[List[Dict[str, Any]]] = None,
) -> Tuple[List[PredictedRegion], Dict[str, int]]:
    """
    主干双通道区段级仲裁与拓扑精修：
      1. 保留高置信主干区段，联合 Head A/B 拦截强防御岛、质粒 MGE 与复合接合耐药移动岛；
      2. 对远离主区段 (>= min_base_clearance_bp) 的 SubBin 灰区候选执行弹性梯度审核，并拦截纯尾簇细菌素；
      3. 协同挽救紧邻已知前噬菌体的互补分离子臂并执行两级互补半臂桥接及严格双芯串联拆分。
    """
    kept: List[PredictedRegion] = []
    stats = {
        "base_kept": 0,
        "base_vetoed": 0,
        "gray_candidates": 0,
        "gray_rescued": 0,
        "gray_rejected": 0,
        "sibling_rescued": 0,
        "topology_bridged": 0,
        "topology_split": 0,
    }

    for reg in base_regions:
        orfs = orfs_by_contig.get(reg.contig_id, [])
        sc = scored_by_contig.get(reg.contig_id)
        if not orfs or sc is None:
            kept.append(reg)
            stats["base_kept"] += 1
            continue
        idxs = [i for i, (gs, ge, _, _) in enumerate(orfs) if reg.start_bp <= 0.5 * (gs + ge) <= reg.end_bp]
        if len(idxs) >= 5:
            ph_sub = sc["phage_probs"][idxs]
            f10_sub = sc["func10_probs"][idxs]
            r2_sub = _get_r2_core_probs(sc)[idxs]
            if _should_veto_base_region(
                ph_sub,
                f10_sub,
                strict_veto_max_mean_phage=strict_veto_max_mean_phage,
                morph_veto_max_mean_phage=morph_veto_max_mean_phage,
                r2_sub=r2_sub,
                enable_cross_head_mge_veto=enable_cross_head_mge_veto,
            ):
                stats["base_vetoed"] += 1
                if suppressed_out is not None:
                    suppressed_out.append({
                        "contig_id": reg.contig_id,
                        "start_bp": reg.start_bp,
                        "end_bp": reg.end_bp,
                        "reason": "base_veto",
                        "mean_phage_prob": round(float(np.mean(ph_sub)), 4),
                        "max_p9": round(float(np.max(f10_sub[:, 9])), 4),
                    })
                continue
        kept.append(reg)
        stats["base_kept"] += 1

    deferred_gray_rejects: List[Tuple[PredictedRegion, Optional[np.ndarray], Optional[np.ndarray], int, bool]] = []
    for cand in relaxed_regions:
        if _region_overlaps_any(cand, base_regions, min_overlap_bp=500, min_clearance_bp=0):
            continue
        in_clearance_shadow = _region_overlaps_any(cand, base_regions, min_overlap_bp=500, min_clearance_bp=min_base_clearance_bp)
        if not in_clearance_shadow:
            stats["gray_candidates"] += 1
        elif not enable_sibling_arm_rescue:
            continue

        orfs = orfs_by_contig.get(cand.contig_id, [])
        sc = scored_by_contig.get(cand.contig_id)
        if not orfs or sc is None:
            if not in_clearance_shadow:
                stats["gray_rejected"] += 1
            continue
        idxs = [i for i, (gs, ge, _, _) in enumerate(orfs) if cand.start_bp <= 0.5 * (gs + ge) <= cand.end_bp]
        if len(idxs) < rescue_min_orfs:
            if enable_sibling_arm_rescue and len(idxs) >= 3 and (cand.end_bp - cand.start_bp) >= 4000:
                deferred_gray_rejects.append((cand, sc["phage_probs"][idxs], sc["func10_probs"][idxs], len(idxs), in_clearance_shadow))
            elif not in_clearance_shadow:
                stats["gray_rejected"] += 1
            continue

        ph_sub = sc["phage_probs"][idxs]
        f10_sub = sc["func10_probs"][idxs]
        if in_clearance_shadow:
            # 紧邻 base 区段的碎片仅允许进入暂存兄弟臂判定，绝不放行成为独立区段
            deferred_gray_rejects.append((cand, ph_sub, f10_sub, len(idxs), True))
            continue

        r2_sub = _get_r2_core_probs(sc)[idxs]
        if _passes_gray_rescue_criteria(
            ph_sub,
            f10_sub,
            rescue_min_orfs=rescue_min_orfs,
            rescue_min_mean_phage=rescue_min_mean_phage,
            rescue_min_frac_phage=rescue_min_frac_phage,
            rescue_min_active_modules=rescue_min_active_modules,
            rescue_max_mean_p9=rescue_max_mean_p9,
            rescue_min_morph_prob=rescue_min_morph_prob,
            require_structural_evidence=require_structural_evidence,
            r2_sub=r2_sub,
            enable_elastic_rescue=enable_elastic_rescue,
            enable_tailocin_guard=enable_tailocin_guard,
            cand_len_bp=cand.end_bp - cand.start_bp,
            cand_peak_score=cand.peak_score,
            cand_mean_score=cand.mean_score,
        ):
            kept.append(cand)
            stats["gray_rescued"] += 1
        else:
            deferred_gray_rejects.append((cand, ph_sub, f10_sub, len(idxs), False))

    tentative_siblings: List[Dict[str, Any]] = []
    if deferred_gray_rejects:
        kept_by_cid: Dict[str, List[PredictedRegion]] = defaultdict(list)
        if enable_sibling_arm_rescue and kept:
            for kr in kept:
                kept_by_cid[kr.contig_id].append(kr)

        for cand, ph_sub, f10_sub, n_orfs, is_shadow in deferred_gray_rejects:
            assert ph_sub is not None and f10_sub is not None
            mean_ph_v = round(float(np.mean(ph_sub)), 4)
            max_p9_v = round(float(np.max(f10_sub[:, 9])), 4)
            queued_sibling = False
            if enable_sibling_arm_rescue and (cand.end_bp - cand.start_bp) >= 4000 and n_orfs >= 3:
                anchors = kept_by_cid.get(cand.contig_id, [])
                near_anchor = any(
                    0 <= max(a.start_bp - cand.end_bp, cand.start_bp - a.end_bp) <= max_bridge_gap_bp
                    for a in anchors
                )
                if near_anchor and mean_ph_v >= 0.70 and max_p9_v < 0.55 and float(np.max(f10_sub[:, :5])) >= 0.50:
                    tentative_siblings.append({
                        "region": cand,
                        "mean_phage_prob": mean_ph_v,
                        "max_p9": max_p9_v,
                        "is_shadow": is_shadow,
                    })
                    queued_sibling = True
            if not queued_sibling and not is_shadow:
                stats["gray_rejected"] += 1
                if suppressed_out is not None:
                    suppressed_out.append({
                        "contig_id": cand.contig_id,
                        "start_bp": cand.start_bp,
                        "end_bp": cand.end_bp,
                        "reason": "gray_rejected",
                        "mean_phage_prob": mean_ph_v,
                        "max_p9": max_p9_v,
                    })

    # 重要：仅正式通过单岛核验的区段走邻接合并，暂存兄弟臂严禁靠 merge_nearby_regions 粘合，
    # 必须直接进入互补拓扑桥接验证并在未成功并入主臂时安全剔除。
    merged = merge_nearby_regions(kept, merge_gap_bp=merge_gap_bp)
    if enable_topology_postprocess:
        bridge_input = list(merged) + [ent["region"] for ent in tentative_siblings]
        merged, stats["topology_bridged"] = bridge_complementary_phage_fragments(
            bridge_input,
            orfs_by_contig,
            scored_by_contig,
            max_bridge_gap_bp=max_bridge_gap_bp,
        )
        merged = reconcile_tentative_siblings(
            merged,
            tentative_siblings,
            stats=stats,
            suppressed_out=suppressed_out,
        )
        merged, stats["topology_split"] = split_tandem_prophage_regions(
            merged,
            orfs_by_contig,
            scored_by_contig,
        )
    elif tentative_siblings:
        if tentative_siblings_out is not None:
            tentative_siblings_out.extend(tentative_siblings)
        else:
            for ent in tentative_siblings:
                if not ent.get("is_shadow", False):
                    stats["gray_rejected"] += 1
                    if suppressed_out is not None:
                        cand = ent["region"]
                        suppressed_out.append({
                            "contig_id": cand.contig_id,
                            "start_bp": cand.start_bp,
                            "end_bp": cand.end_bp,
                            "reason": "gray_rejected",
                            "mean_phage_prob": ent["mean_phage_prob"],
                            "max_p9": ent["max_p9"],
                        })
    return merged, stats


def summarize_region_with_judge(
    reg: PredictedRegion,
    orfs: Sequence[Tuple[int, int, int, str]],
    scored: Dict[str, np.ndarray],
    *,
    module_threshold: float = 0.5,
) -> Dict[str, Any]:
    """汇总 R3 分区/排雷与 R2 核心完整度，输出标准化的区段级功能报告。"""
    idxs = [i for i, (gs, ge, _, _) in enumerate(orfs) if reg.start_bp <= 0.5 * (gs + ge) <= reg.end_bp]
    if not idxs:
        return {"n_orfs": 0, "active_modules": [], "completeness_class": "cryptic_or_incomplete"}

    ph_sub = scored["phage_probs"][idxs]
    f10_sub = scored["func10_probs"][idxs]
    r2_sub = _get_r2_core_probs(scored)[idxs]

    max_f10 = np.max(f10_sub, axis=0)
    active_mods = [JUDGE_CLASS_NAMES[c] for c in range(9) if float(max_f10[c]) >= module_threshold]
    r2_core_max = np.max(r2_sub, axis=0)
    core_sum = float(np.sum(r2_core_max))
    core_cnt = int(np.sum(r2_core_max >= 0.45))
    has_head = float(r2_core_max[0]) >= 0.45 or float(max_f10[0]) >= module_threshold
    comp_cls = "complete_structural_core" if (core_cnt >= 3 and has_head) else "cryptic_or_incomplete"

    return {
        "n_orfs": len(idxs),
        "mean_phage_prob": round(float(np.mean(ph_sub)), 4),
        "max_p9_defense_prob": round(float(max_f10[9]), 4),
        "r2_core_completeness_sum": round(core_sum, 4),
        "r2_core_active_count": core_cnt,
        "completeness_class": comp_cls,
        "active_modules": active_mods,
    }
