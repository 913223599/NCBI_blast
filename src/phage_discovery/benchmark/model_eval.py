# -*- coding: utf-8 -*-
"""
通用模型基准评测适配层：把任意模型对特征分片给出的窗口得分接入统一评测契约。

- 独立窗口集：每个 window_id 一行得分 -> evaluate_window_predictions；
- 嵌合体集：滑窗得分 -> 滞回解码 -> evaluate_chimera_predictions；
- 解码阈值只允许在 val split 上网格搜索，再原样应用到 test，杜绝在测试集上调参。
"""
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from .metrics import (
    WindowPrediction,
    decode_subwindow_probs_to_regions,
    decode_window_scores_to_regions,
)
from .runner import evaluate_chimera_predictions, evaluate_window_predictions

DEFAULT_SEED_GRID = (0.6, 0.7, 0.8, 0.9, 0.95)
DEFAULT_EXTEND_GRID = (0.3, 0.4, 0.5, 0.6, 0.7)
DEFAULT_SUB_GRID = (0.35, 0.45, 0.48, 0.50, 0.55, 0.65)


def _to_window_preds(contig_ids: np.ndarray, starts: np.ndarray, ends: np.ndarray, scores: np.ndarray) -> List[WindowPrediction]:
    return [
        WindowPrediction(str(c), int(s), int(e), float(p))
        for c, s, e, p in zip(contig_ids, starts, ends, scores)
    ]


def evaluate_chimera_scores(
    split_info: Dict[str, Any],
    chim: Dict[str, np.ndarray],
    scores: np.ndarray,
    seed_threshold: float,
    extend_threshold: float,
    chim_sub_probs: Optional[np.ndarray] = None,
    sub_threshold: Optional[float] = None,
    *,
    plateau_min_windows: int = 0,
    plateau_second_threshold: Optional[float] = None,
    precomputed_bin_profiles: Optional[Dict[str, Any]] = None,
    smooth_profile: bool = True,
    refine_pad_bp: int = 2000,
) -> Dict[str, Any]:
    preds = _to_window_preds(chim["contig_ids"], chim["starts"], chim["ends"], scores)
    if chim_sub_probs is not None and sub_threshold is not None:
        regions = decode_subwindow_probs_to_regions(
            preds, chim_sub_probs,
            seed_threshold=seed_threshold,
            extend_threshold=extend_threshold,
            sub_threshold=sub_threshold,
            merge_gap_bp=3000, min_region_bp=3000,
            plateau_min_windows=plateau_min_windows,
            plateau_second_threshold=plateau_second_threshold,
            precomputed_bin_profiles=precomputed_bin_profiles,
            smooth_profile=smooth_profile,
            refine_pad_bp=refine_pad_bp,
        )
    else:
        regions = decode_window_scores_to_regions(
            preds, seed_threshold=seed_threshold, extend_threshold=extend_threshold,
            merge_gap_bp=3000, min_region_bp=3000,
            plateau_min_windows=plateau_min_windows,
            plateau_second_threshold=plateau_second_threshold,
        )
    return evaluate_chimera_predictions(
        Path(split_info["chimeras"]["truth_tsv"]),
        Path(split_info["chimeras"]["contigs_tsv"]),
        regions,
        iou_threshold=0.5,
    )


def tune_decoder_on_val(
    split_info: Dict[str, Any],
    chim: Dict[str, np.ndarray],
    scores: np.ndarray,
    seed_grid: Tuple[float, ...] = DEFAULT_SEED_GRID,
    extend_grid: Tuple[float, ...] = DEFAULT_EXTEND_GRID,
    chim_sub_probs: Optional[np.ndarray] = None,
    sub_grid: Tuple[float, ...] = DEFAULT_SUB_GRID,
    *,
    plateau_candidates: Optional[Tuple[Tuple[int, Optional[float]], ...]] = None,
    precomputed_bin_profiles: Optional[Dict[str, Any]] = None,
    smooth_profile: bool = True,
    refine_pad_bp: int = 2000,
) -> Dict[str, Any]:
    """在 val 嵌合体上网格搜索滞回/边界精修阈值：主目标 F1(IoU>=0.5)，次目标 strict F1(IoU>=0.8) 与低 FP/Mb。"""
    best: Optional[Dict[str, Any]] = None
    sub_candidates = sub_grid if chim_sub_probs is not None else (None,)
    plat_grid = plateau_candidates if plateau_candidates is not None else ((0, None),)
    for p_min_w, p_sec in plat_grid:
        for seed in seed_grid:
            for ext in extend_grid:
                if ext > seed:
                    continue
                for sub_th in sub_candidates:
                    res = evaluate_chimera_scores(
                        split_info, chim, scores, seed, ext,
                        chim_sub_probs=chim_sub_probs, sub_threshold=sub_th,
                        plateau_min_windows=p_min_w,
                        plateau_second_threshold=p_sec,
                        precomputed_bin_profiles=precomputed_bin_profiles,
                        smooth_profile=smooth_profile,
                        refine_pad_bp=refine_pad_bp,
                    )
                    f1 = res["overall"]["primary"]["f1"]
                    strict_f1 = res["overall"]["strict_iou_0_8"]["f1"]
                    mae = res["overall"]["primary"].get("breakpoint_mae_bp")
                    neg_mae = -(float(mae) if mae is not None else 1e9)
                    fpmb = res["overall"].get("pure_negative_fp_per_mb") or 0.0
                    key = (f1, strict_f1, -fpmb, neg_mae)
                    if best is None or key > best["key"]:
                        best = {
                            "key": key,
                            "seed_threshold": seed,
                            "extend_threshold": ext,
                            "sub_threshold": sub_th,
                            "plateau_min_windows": p_min_w,
                            "plateau_second_threshold": p_sec,
                            "refine_pad_bp": refine_pad_bp,
                            "smooth_profile": smooth_profile,
                            "val_f1": f1,
                            "val_strict_f1": strict_f1,
                            "val_fp_per_mb": fpmb,
                            "val_breakpoint_mae_bp": mae,
                        }
    assert best is not None
    best.pop("key")
    return best


def evaluate_model_scores_on_split(
    bench_dir: Path,
    split_name: str,
    win: Dict[str, np.ndarray],
    win_scores: np.ndarray,
    chim: Dict[str, np.ndarray],
    chim_scores: np.ndarray,
    seed_threshold: float,
    extend_threshold: float,
    chim_sub_probs: Optional[np.ndarray] = None,
    sub_threshold: Optional[float] = None,
    *,
    plateau_min_windows: int = 0,
    plateau_second_threshold: Optional[float] = None,
    precomputed_bin_profiles: Optional[Dict[str, Any]] = None,
    smooth_profile: bool = True,
    refine_pad_bp: int = 2000,
) -> Dict[str, Any]:
    manifest = json.loads((Path(bench_dir) / "benchmark_manifest.json").read_text(encoding="utf-8"))
    info = manifest["splits"][split_name]
    score_map = {str(c): float(s) for c, s in zip(win["contig_ids"], win_scores)}
    win_eval = evaluate_window_predictions(Path(info["windows"]["truth_tsv"]), score_map, threshold=0.5)
    chim_eval = evaluate_chimera_scores(
        info, chim, chim_scores, seed_threshold, extend_threshold,
        chim_sub_probs=chim_sub_probs, sub_threshold=sub_threshold,
        plateau_min_windows=plateau_min_windows,
        plateau_second_threshold=plateau_second_threshold,
        precomputed_bin_profiles=precomputed_bin_profiles,
        smooth_profile=smooth_profile,
        refine_pad_bp=refine_pad_bp,
    )
    return {
        "evaluated_at": datetime.now().isoformat(timespec="seconds"),
        "split": split_name,
        "decoder": {
            "seed_threshold": seed_threshold,
            "extend_threshold": extend_threshold,
            "sub_threshold": sub_threshold,
            "plateau_min_windows": plateau_min_windows,
            "plateau_second_threshold": plateau_second_threshold,
            "smooth_profile": smooth_profile,
            "refine_pad_bp": refine_pad_bp,
        },
        "window_benchmark": win_eval,
        "chimera_benchmark": chim_eval,
    }


def load_split_info(bench_dir: Path, split_name: str) -> Dict[str, Any]:
    manifest = json.loads((Path(bench_dir) / "benchmark_manifest.json").read_text(encoding="utf-8"))
    return manifest["splits"][split_name]

