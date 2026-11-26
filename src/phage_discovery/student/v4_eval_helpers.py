# -*- coding: utf-8 -*-
"""
V4 蒸馏学生模型精修器训练与评估落盘辅助模块

负责 RegionContextRefiner / SubBinContextRefiner 联合训练与验证/测试推理，
以及解码器调优、指标评估、NPZ/Meta/Report 原子落盘与显存回收。
"""

import gc
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Tuple

import numpy as np

from ..benchmark.model_eval import (
    evaluate_model_scores_on_split,
    load_split_info,
    tune_decoder_on_val,
)
from ..data.functional_partitions import FUNCTIONAL_PARTITION_NAMES
from .v4_arch import SEMANTIC_DIM
from .v4_context_refiner import (
    _predict_v4_all,
    extract_refiner_step_features,
    group_windows_by_contig,
    predict_with_context_refiner,
    train_context_refiner,
)


def _fit_context_refiner(
    model: Any,
    bundle: Dict[str, Any],
    tr_c_pred: Dict[str, Any],
    va_c: Dict[str, Any],
    va_c_pred: Dict[str, Any],
    refiner_ckpt: Path,
    device: Any,
    *,
    max_len: int,
    epochs: int,
    seed: int,
) -> Tuple[Any, Dict[str, Any]]:
    rmask = bundle["refiner_mask_all"]
    tr_sf_clean = extract_refiner_step_features(
        tr_c_pred["win_logits"],
        tr_c_pred["sem_logits"],
        tr_c_pred["sub_probs"],
        bundle["len_all"][rmask],
        max_len=max_len,
        func_logits=tr_c_pred.get("func_logits"),
    )
    tr_c_pred_ood = _predict_v4_all(
        model,
        bundle["codes_all"][rmask],
        bundle["len_all"][rmask],
        bundle["feats_all"][rmask],
        bundle["tokens_all"][rmask],
        bundle["counts_all"][rmask],
        device,
        drop_tabular_prob=0.25,
        drop_orf_prob=0.15,
        seed=seed + 101,
    )
    tr_sf_ood = extract_refiner_step_features(
        tr_c_pred_ood["win_logits"],
        tr_c_pred_ood["sem_logits"],
        tr_c_pred_ood["sub_probs"],
        bundle["len_all"][rmask],
        max_len=max_len,
        func_logits=tr_c_pred_ood.get("func_logits"),
    )
    tr_sf = np.concatenate([tr_sf_clean, tr_sf_ood], axis=0)
    tr_wl = np.concatenate([tr_c_pred["win_logits"], tr_c_pred_ood["win_logits"]], axis=0)
    tr_y_ref = np.concatenate([bundle["clean_y_all"][rmask], bundle["clean_y_all"][rmask]], axis=0)
    tr_cids_ref = np.concatenate([bundle["cids_all"][rmask], bundle["cids_all"][rmask]], axis=0)
    tr_starts_ref = np.concatenate([bundle["starts_all"][rmask], bundle["starts_all"][rmask]], axis=0)
    tr_tags_ref = np.concatenate(
        [
            bundle["part_tags_all"][rmask],
            np.array([f"ood::{t}" for t in bundle["part_tags_all"][rmask]], dtype=object),
        ],
        axis=0,
    )
    va_sf = extract_refiner_step_features(
        va_c_pred["win_logits"],
        va_c_pred["sem_logits"],
        va_c_pred["sub_probs"],
        va_c["lengths"],
        max_len=max_len,
        func_logits=va_c_pred.get("func_logits"),
    )
    return train_context_refiner(
        tr_sf,
        tr_wl,
        tr_y_ref,
        tr_cids_ref,
        tr_starts_ref,
        va_sf,
        va_c_pred["win_logits"],
        va_c["orig_labels"],
        va_c["arrs"]["contig_ids"],
        va_c["arrs"]["starts"],
        out_path=refiner_ckpt,
        epochs=epochs,
        seed=seed,
        tr_source_tags=tr_tags_ref,
    )


def train_and_eval_refiners(
    model: Any,
    bundle: Dict[str, Any],
    va_c: Dict[str, Any],
    va_c_pred: Dict[str, Any],
    te_c: Dict[str, Any],
    te_c_pred: Dict[str, Any],
    out_root: Path,
    device: Any,
    *,
    max_len: int,
    seed: int,
    train_refiner: bool,
    refiner_epochs: int,
    train_subbin_refiner: bool,
    subbin_epochs: int,
) -> Dict[str, Any]:
    """训练可选 RegionContextRefiner 与 SubBinContextRefiner，并输出验证/测试集精修分数。"""
    from .subbin_refiner import (
        build_contig_subbin_sequences,
        extract_per_orf_viral_scores,
        predict_subbin_probs_with_refiner,
        project_orf_to_25bins,
        train_subbin_context_refiner,
    )

    refiner_mask = bundle["refiner_mask_all"]
    refiner = None
    refiner_info: Dict[str, Any] = {"enabled": False}
    refiner_ckpt = out_root / "context_refiner.pt"
    subbin_refiner = None
    subbin_info: Dict[str, Any] = {"enabled": False}
    subbin_ckpt = out_root / "subbin_refiner.pt"

    tr_c_pred = None
    if (train_refiner or train_subbin_refiner) and np.any(refiner_mask):
        tr_c_pred = _predict_v4_all(
            model,
            bundle["codes_all"][refiner_mask],
            bundle["len_all"][refiner_mask],
            bundle["feats_all"][refiner_mask],
            bundle["tokens_all"][refiner_mask],
            bundle["counts_all"][refiner_mask],
            device,
        )

    if train_refiner and tr_c_pred is not None:
        refiner, r_rep = _fit_context_refiner(
            model,
            bundle,
            tr_c_pred,
            va_c,
            va_c_pred,
            refiner_ckpt,
            device,
            max_len=max_len,
            epochs=refiner_epochs,
            seed=seed,
        )
        refiner_info = {"enabled": True, "ckpt_path": str(refiner_ckpt), **r_rep}

    va_chim_raw_sc = va_c_pred["win_probs"]
    te_chim_raw_sc = te_c_pred["win_probs"]
    va_chim_ref_sc = (
        predict_with_context_refiner(
            refiner,
            va_c_pred["win_logits"],
            va_c_pred["sem_logits"],
            va_c_pred["sub_probs"],
            va_c["lengths"],
            va_c["arrs"]["contig_ids"],
            va_c["arrs"]["starts"],
            device,
            max_len=max_len,
            func_logits=va_c_pred.get("func_logits"),
        )
        if refiner is not None
        else va_chim_raw_sc
    )
    te_chim_ref_sc = (
        predict_with_context_refiner(
            refiner,
            te_c_pred["win_logits"],
            te_c_pred["sem_logits"],
            te_c_pred["sub_probs"],
            te_c["lengths"],
            te_c["arrs"]["contig_ids"],
            te_c["arrs"]["starts"],
            device,
            max_len=max_len,
            func_logits=te_c_pred.get("func_logits"),
        )
        if refiner is not None
        else te_chim_raw_sc
    )

    va_subbin_profiles = None
    te_subbin_profiles = None
    va_chim_sub_eval = va_c_pred["sub_probs"]
    te_chim_sub_eval = te_c_pred["sub_probs"]

    if train_subbin_refiner and tr_c_pred is not None:
        tr_ref_sc = (
            predict_with_context_refiner(
                refiner,
                tr_c_pred["win_logits"],
                tr_c_pred["sem_logits"],
                tr_c_pred["sub_probs"],
                bundle["len_all"][refiner_mask],
                np.array(
                    [f"{t}::{c}" for t, c in zip(bundle["part_tags_all"][refiner_mask], bundle["cids_all"][refiner_mask])],
                    dtype=object,
                ),
                bundle["starts_all"][refiner_mask],
                device,
                max_len=max_len,
                func_logits=tr_c_pred.get("func_logits"),
            )
            if refiner is not None
            else tr_c_pred["win_probs"]
        )
        tr_orf_bins = project_orf_to_25bins(
            bundle["tokens_all"][refiner_mask],
            bundle["counts_all"][refiner_mask],
            extract_per_orf_viral_scores(
                model, bundle["tokens_all"][refiner_mask], bundle["counts_all"][refiner_mask], device
            ),
        )
        va_orf_bins = project_orf_to_25bins(
            va_c["tokens"],
            va_c["counts"],
            extract_per_orf_viral_scores(model, va_c["tokens"], va_c["counts"], device),
        )
        tr_sb_groups = group_windows_by_contig(
            bundle["cids_all"][refiner_mask],
            bundle["starts_all"][refiner_mask],
            max_gap_bp=max_len,
            source_tags=bundle["part_tags_all"][refiner_mask],
        )
        va_sb_groups = group_windows_by_contig(
            va_c["arrs"]["contig_ids"], va_c["arrs"]["starts"], max_gap_bp=max_len
        )
        tr_sb_seqs = build_contig_subbin_sequences(
            tr_sb_groups,
            bundle["starts_all"][refiner_mask],
            bundle["ends_all"][refiner_mask],
            tr_ref_sc,
            tr_c_pred["win_probs"],
            tr_c_pred["sem_logits"],
            tr_c_pred["sub_probs"],
            win_orf_25bins=tr_orf_bins,
            sub_targets=bundle["sub_all"][refiner_mask],
            valid_win_mask=(bundle["clean_y_all"][refiner_mask] >= 0),
        )
        va_sb_seqs = build_contig_subbin_sequences(
            va_sb_groups,
            va_c["arrs"]["starts"],
            va_c["arrs"]["ends"],
            va_chim_ref_sc,
            va_chim_raw_sc,
            va_c_pred["sem_logits"],
            va_c_pred["sub_probs"],
            win_orf_25bins=va_orf_bins,
            sub_targets=va_c["arrs"]["sub_mask"].astype(np.float32),
        )
        subbin_refiner, sb_rep = train_subbin_context_refiner(
            tr_sb_seqs, va_sb_seqs, out_path=subbin_ckpt, epochs=subbin_epochs, seed=seed
        )
        subbin_info = {"enabled": True, "ckpt_path": str(subbin_ckpt), **sb_rep}

        va_subbin_profiles, va_chim_sub_eval = predict_subbin_probs_with_refiner(
            subbin_refiner,
            va_sb_groups,
            va_c["arrs"]["contig_ids"],
            va_c["arrs"]["starts"],
            va_c["arrs"]["ends"],
            va_chim_ref_sc,
            va_chim_raw_sc,
            va_c_pred["sem_logits"],
            va_c_pred["sub_probs"],
            device,
            win_orf_25bins=va_orf_bins,
            min_windows=2,
        )
        te_orf_bins = project_orf_to_25bins(
            te_c["tokens"],
            te_c["counts"],
            extract_per_orf_viral_scores(model, te_c["tokens"], te_c["counts"], device),
        )
        te_sb_groups = group_windows_by_contig(
            te_c["arrs"]["contig_ids"], te_c["arrs"]["starts"], max_gap_bp=max_len
        )
        te_subbin_profiles, te_chim_sub_eval = predict_subbin_probs_with_refiner(
            subbin_refiner,
            te_sb_groups,
            te_c["arrs"]["contig_ids"],
            te_c["arrs"]["starts"],
            te_c["arrs"]["ends"],
            te_chim_ref_sc,
            te_chim_raw_sc,
            te_c_pred["sem_logits"],
            te_c_pred["sub_probs"],
            device,
            win_orf_25bins=te_orf_bins,
            min_windows=2,
        )
        del tr_orf_bins, va_orf_bins, te_orf_bins, tr_sb_seqs, va_sb_seqs

    return {
        "refiner": refiner,
        "refiner_info": refiner_info,
        "refiner_ckpt": refiner_ckpt,
        "subbin_refiner": subbin_refiner,
        "subbin_info": subbin_info,
        "subbin_ckpt": subbin_ckpt,
        "va_chim_raw_sc": va_chim_raw_sc,
        "te_chim_raw_sc": te_chim_raw_sc,
        "va_chim_ref_sc": va_chim_ref_sc,
        "te_chim_ref_sc": te_chim_ref_sc,
        "va_subbin_profiles": va_subbin_profiles,
        "te_subbin_profiles": te_subbin_profiles,
        "va_chim_sub_eval": va_chim_sub_eval,
        "te_chim_sub_eval": te_chim_sub_eval,
    }


def evaluate_and_save_v4_artifacts(
    bench_dir: Path,
    out_root: Path,
    ckpt_path: Path,
    va_w: Dict[str, Any],
    va_w_pred: Dict[str, Any],
    va_c: Dict[str, Any],
    va_c_pred: Dict[str, Any],
    te_w: Dict[str, Any],
    te_w_pred: Dict[str, Any],
    te_c: Dict[str, Any],
    te_c_pred: Dict[str, Any],
    ref_out: Dict[str, Any],
    meta_cfg: Dict[str, Any],
    summary_ctx: Dict[str, Any],
    *,
    enable_plateau_decoder: bool,
) -> Dict[str, Any]:
    """执行解码器调优、验证/测试指标评估、NPZ/Meta/Report 原子落盘并回收显存。"""
    import torch

    va_win_sc = va_w_pred["win_probs"]
    te_win_sc = te_w_pred["win_probs"]
    va_chim_raw_sc = ref_out["va_chim_raw_sc"]
    te_chim_raw_sc = ref_out["te_chim_raw_sc"]
    va_chim_ref_sc = ref_out["va_chim_ref_sc"]
    te_chim_ref_sc = ref_out["te_chim_ref_sc"]
    va_chim_sub_eval = ref_out["va_chim_sub_eval"]
    te_chim_sub_eval = ref_out["te_chim_sub_eval"]
    va_subbin_profiles = ref_out["va_subbin_profiles"]
    te_subbin_profiles = ref_out["te_subbin_profiles"]
    refiner_info = ref_out["refiner_info"]
    subbin_info = ref_out["subbin_info"]

    plateau_cands = ((4, 0.90), (0, None)) if enable_plateau_decoder else ((0, None),)
    use_sb = ref_out["subbin_refiner"] is not None
    sb_smooth = not use_sb
    sb_pad = 3000 if use_sb else 2000

    decoder_raw = tune_decoder_on_val(
        load_split_info(bench_dir, "val"), va_c["arrs"], va_chim_raw_sc, chim_sub_probs=va_c_pred["sub_probs"]
    )
    decoder_ref = (
        tune_decoder_on_val(
            load_split_info(bench_dir, "val"),
            va_c["arrs"],
            va_chim_ref_sc,
            chim_sub_probs=va_chim_sub_eval,
            plateau_candidates=plateau_cands,
            precomputed_bin_profiles=va_subbin_profiles,
            smooth_profile=sb_smooth,
            refine_pad_bp=sb_pad,
        )
        if (ref_out["refiner"] is not None or use_sb)
        else decoder_raw
    )

    val_raw_rep = evaluate_model_scores_on_split(
        bench_dir,
        "val",
        va_w["arrs"],
        va_win_sc,
        va_c["arrs"],
        va_chim_raw_sc,
        decoder_raw["seed_threshold"],
        decoder_raw["extend_threshold"],
        chim_sub_probs=va_c_pred["sub_probs"],
        sub_threshold=decoder_raw.get("sub_threshold"),
    )
    test_raw_rep = evaluate_model_scores_on_split(
        bench_dir,
        "test",
        te_w["arrs"],
        te_win_sc,
        te_c["arrs"],
        te_chim_raw_sc,
        decoder_raw["seed_threshold"],
        decoder_raw["extend_threshold"],
        chim_sub_probs=te_c_pred["sub_probs"],
        sub_threshold=decoder_raw.get("sub_threshold"),
    )
    val_ref_rep = evaluate_model_scores_on_split(
        bench_dir,
        "val",
        va_w["arrs"],
        va_win_sc,
        va_c["arrs"],
        va_chim_ref_sc,
        decoder_ref["seed_threshold"],
        decoder_ref["extend_threshold"],
        chim_sub_probs=va_chim_sub_eval,
        sub_threshold=decoder_ref.get("sub_threshold"),
        plateau_min_windows=int(decoder_ref.get("plateau_min_windows", 0)),
        plateau_second_threshold=decoder_ref.get("plateau_second_threshold"),
        precomputed_bin_profiles=va_subbin_profiles,
        smooth_profile=bool(decoder_ref.get("smooth_profile", True)),
        refine_pad_bp=int(decoder_ref.get("refine_pad_bp", 2000)),
    )
    test_ref_rep = evaluate_model_scores_on_split(
        bench_dir,
        "test",
        te_w["arrs"],
        te_win_sc,
        te_c["arrs"],
        te_chim_ref_sc,
        decoder_ref["seed_threshold"],
        decoder_ref["extend_threshold"],
        chim_sub_probs=te_chim_sub_eval,
        sub_threshold=decoder_ref.get("sub_threshold"),
        plateau_min_windows=int(decoder_ref.get("plateau_min_windows", 0)),
        plateau_second_threshold=decoder_ref.get("plateau_second_threshold"),
        precomputed_bin_profiles=te_subbin_profiles,
        smooth_profile=bool(decoder_ref.get("smooth_profile", True)),
        refine_pad_bp=int(decoder_ref.get("refine_pad_bp", 2000)),
    )

    np.savez_compressed(
        out_root / "student_scores.npz",
        val_windows=va_win_sc,
        val_chimeras=va_chim_ref_sc,
        val_chimeras_raw=va_chim_raw_sc,
        val_chimeras_sub=va_c_pred["sub_probs"],
        val_chimeras_sub_refined=va_chim_sub_eval,
        test_windows=te_win_sc,
        test_chimeras=te_chim_ref_sc,
        test_chimeras_raw=te_chim_raw_sc,
        test_chimeras_sub=te_c_pred["sub_probs"],
        test_chimeras_sub_refined=te_chim_sub_eval,
    )

    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()

    func_dim = int(meta_cfg["func_dim"])
    meta = {
        **meta_cfg,
        "sem_dim": SEMANTIC_DIM,
        "func_partition_names": list(FUNCTIONAL_PARTITION_NAMES) if func_dim > 0 else [],
        "use_context_refiner": bool(refiner_info["enabled"]),
        "refiner_arch": refiner_info.get("refiner_arch", "v2" if refiner_info["enabled"] else "none"),
        "refiner_ckpt": str(ref_out["refiner_ckpt"]) if refiner_info["enabled"] else None,
        "use_subbin_refiner": bool(subbin_info["enabled"]),
        "subbin_arch": subbin_info.get("arch", "none"),
        "subbin_ckpt": str(ref_out["subbin_ckpt"]) if subbin_info["enabled"] else None,
        "student_ckpt": str(ckpt_path),
    }
    meta_path = out_root / "student_v4_meta.json"
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    total_test_mb = float(test_raw_rep["chimera_benchmark"]["overall"].get("total_scanned_mb") or 20.862)
    est_sec_per_5mb = round((summary_ctx["infer_sec"] / max(1e-6, total_test_mb)) * 5.0, 3)
    active_dec = decoder_ref if refiner_info["enabled"] else decoder_raw
    use_ref = bool(refiner_info["enabled"] or subbin_info["enabled"])

    report: Dict[str, Any] = {
        "model_name": "StudentV4_TriModal_FunctionalDistilled" if func_dim > 0 else "StudentV4_TriModal_MaskedSemantic",
        "model_version": "v4",
        "warm_started_from": summary_ctx["warm_started_from"],
        "trained_at": datetime.now().isoformat(timespec="seconds"),
        "device": summary_ctx["device"],
        "architecture": meta,
        "params": summary_ctx["n_params"],
        "train_parts_used": summary_ctx["part_names_used"],
        "train_rows": summary_ctx["train_rows"],
        "oof_teacher_sec": summary_ctx["oof_sec"],
        "data_prep_sec": summary_ctx["data_prep_sec"],
        "train_sec": summary_ctx["train_sec"],
        "peak_gpu_mem_mb": summary_ctx["peak_mb"],
        "test_inference_sec": summary_ctx["infer_sec"],
        "est_sec_per_5mb": est_sec_per_5mb,
        "best_epoch": summary_ctx["best_ep"],
        "best_val_auprc": round(summary_ctx["best_ap"], 5),
        "learned_task_weights": summary_ctx["learned_task_weights"],
        "history": summary_ctx["history"],
        "sub_head_refinement": summary_ctx["sub_tune_info"],
        "context_refiner": refiner_info,
        "subbin_refiner": subbin_info,
        "decoder_tuned_on_val": active_dec,
        "decoder_raw_on_val": decoder_raw,
        "val": val_ref_rep if use_ref else val_raw_rep,
        "test": test_ref_rep if use_ref else test_raw_rep,
        "val_raw": val_raw_rep,
        "test_raw": test_raw_rep,
        "model_path": str(ckpt_path),
        "meta_path": str(meta_path),
    }
    for fname in ("student_v4_report.json", "student_report.json"):
        rp = out_root / fname
        tmp_rp = out_root / f".{fname}.tmp"
        tmp_rp.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp_rp.replace(rp)
    report["report_path"] = str(out_root / "student_v4_report.json")
    return report
