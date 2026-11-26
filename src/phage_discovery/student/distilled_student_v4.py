# -*- coding: utf-8 -*-
"""
V4 升级版高容量多模态知识蒸馏学生模型与跨窗上下文精修器（全神经网络端到端流水线）

核心改进：
1. Masked Pooling 修复短片段 (<=1kb) 信号稀释问题：对 DNA ResNet+BiGRU 严格按有效长度掩码与 pack_padded 处理，
   确保同一短序列在不同填充长度下表征一致，不被结尾 N-padding 稀释；
2. 内置三模态门控融合网络（约 3.1M 参数）：
   - Branch 1: 1D Dilated ResNet + Packed BiGRU（原始碱基特征 + 200bp 亚窗口分割）；
   - Branch 2: 嵌入式 ORF Synteny Transformer（直接内部抽取操纵子语法表征）；
   - Branch 3: 带内置均值方差归一化的 Residual Tabular MLP（185 维局部结构/理化特征）；
   - Semantic Aux Head: 隐式蛋白功能域监督（离线 DIAMOND 赋予的 4 维语义，推理零 BLASTp）；
3. RegionContextRefiner（跨窗 BiGRU+Attention 精修器）：
   - 在 contig 连续滑窗序列上综合 35kb+ 长程语境与语义概率走势，抑制孤立转座酶脉冲并抬升退化隐蔽前噬菌体。
"""

import argparse
import gc
import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, cast

import numpy as np

from ..benchmark.model_eval import (
    evaluate_model_scores_on_split,
    load_split_info,
    tune_decoder_on_val,
)
from ..data.functional_partitions import (
    FUNCTIONAL_PARTITION_NAMES,
    NUM_FUNC_PARTITIONS,
    HomoscedasticMultiTaskLoss,
)
from ..experts.expert_a_xgb import summarize_report
from ..experts.expert_b_cnn import _resolve_part_fasta
from ..experts.expert_c_orf import MAX_ORFS_PER_WIN, _load_or_extract_part
from ..experts.seq_dataset import load_window_sequences, reverse_complement_codes
from .distilled_student import _focal_bce_with_logits, _kd_bce_loss, _sub_bce_dice_loss
from .v4_arch import (
    REFINER_CTX_AUG_DIM,
    REFINER_STEP_FEAT_DIM,
    SEMANTIC_DIM,
    _normalize_feature_stats,
    build_distilled_student_v4,
    build_region_context_refiner,
)
from .v4_context_refiner import (
    _apply_refiner_augmentations,
    _predict_v4_all,
    extract_refiner_step_features,
    group_windows_by_contig,
    predict_with_context_refiner,
    train_context_refiner,
)
from .v4_sub_head import (
    _compute_boundary_bin_weights,
    _extract_sub_head_inputs,
    refine_student_v4_sub_head,
)

logger = logging.getLogger("phage_discovery.student.distilled_student_v4")

CONTIG_REF_PARTS: Tuple[str, ...] = ("chimeras", "mined", "ext_mined", "hard_neg", "hard_v4")

__all__ = [
    "CONTIG_REF_PARTS",
    "SEMANTIC_DIM",
    "REFINER_STEP_FEAT_DIM",
    "REFINER_CTX_AUG_DIM",
    "_normalize_feature_stats",
    "build_distilled_student_v4",
    "build_region_context_refiner",
    "extract_refiner_step_features",
    "group_windows_by_contig",
    "_predict_v4_all",
    "predict_with_context_refiner",
    "_apply_refiner_augmentations",
    "train_context_refiner",
    "_compute_boundary_bin_weights",
    "_extract_sub_head_inputs",
    "refine_student_v4_sub_head",
    "_load_v4_part",
    "train_distilled_student_v4",
    "main",
]

def _load_v4_part(
    feature_dir: Path,
    manifest_or_train_dir: Path,
    split: str,
    part: str,
    max_len: int,
    workers: Optional[int],
    *,
    fasta_override: Optional[Path] = None,
    use_semantic: bool = True,
    use_functional: bool = False,
    feature_profile: str = "v4",
) -> Dict[str, Any]:
    """统一加载某个分片的 tabular 特征、DNA 编码、ORF 张量以及可选 offline 语义/9D功能分区目标。"""
    arrs, tokens, counts = _load_or_extract_part(
        feature_dir,
        manifest_or_train_dir,
        split,
        part,
        Path(feature_dir),
        workers,
        fasta_override=fasta_override,
        use_semantic_clean_labels=False,
        feature_profile=feature_profile,
    )
    orig_labels = arrs["labels"].astype(np.int8, copy=True)
    clean_labels = orig_labels.copy()
    n = len(orig_labels)
    sem_targets = np.zeros((n, SEMANTIC_DIM), dtype=np.float32)
    sem_valid = np.zeros(n, dtype=np.float32)

    if use_semantic:
        sem_path = Path(feature_dir) / f"{split}_{part}_semantic.npz"
        if sem_path.exists():
            with np.load(sem_path, allow_pickle=False) as sem_npz:
                if "clean_labels" in sem_npz and len(sem_npz["clean_labels"]) == n:
                    clean_labels = sem_npz["clean_labels"].astype(np.int8)
                if "sem_targets" in sem_npz and len(sem_npz["sem_targets"]) == n:
                    raw_sem = sem_npz["sem_targets"].astype(np.float32)
                    if raw_sem.ndim == 2 and raw_sem.shape[1] == SEMANTIC_DIM:
                        sem_targets = raw_sem
                    elif raw_sem.ndim == 2 and raw_sem.shape[1] == 2:
                        sem_targets[:, 0] = raw_sem[:, 0]
                        sem_targets[:, 2] = raw_sem[:, 1]
                if "sem_valid_mask" in sem_npz and len(sem_npz["sem_valid_mask"]) == n:
                    sem_valid = sem_npz["sem_valid_mask"].astype(np.float32)
                elif np.any(sem_targets > 0):
                    sem_valid = np.ones(n, dtype=np.float32)

    has_functional_file = False
    func_targets = np.zeros((n, NUM_FUNC_PARTITIONS), dtype=np.float32)
    func_valid = np.ones((n, NUM_FUNC_PARTITIONS), dtype=np.float32)
    orf_phage_targets = np.zeros((n, MAX_ORFS_PER_WIN), dtype=np.float32)
    orf_phage_valid = np.zeros((n, MAX_ORFS_PER_WIN), dtype=np.float32)
    orf_func_targets = np.zeros((n, MAX_ORFS_PER_WIN, NUM_FUNC_PARTITIONS), dtype=np.float32)
    orf_func_valid = np.zeros((n, MAX_ORFS_PER_WIN), dtype=np.float32)

    if use_functional:
        func_path = Path(feature_dir) / f"{split}_{part}_functional.npz"
        if func_path.exists():
            has_functional_file = True
            with np.load(func_path, allow_pickle=False) as fn_npz:
                if "func_targets" in fn_npz and len(fn_npz["func_targets"]) == n:
                    func_targets = fn_npz["func_targets"].astype(np.float32)
                if "func_valid_mask" in fn_npz and len(fn_npz["func_valid_mask"]) == n:
                    func_valid = fn_npz["func_valid_mask"].astype(np.float32)
                if "orf_phage_targets" in fn_npz and len(fn_npz["orf_phage_targets"]) == n:
                    orf_phage_targets = fn_npz["orf_phage_targets"].astype(np.float32)
                if "orf_phage_valid" in fn_npz and len(fn_npz["orf_phage_valid"]) == n:
                    orf_phage_valid = fn_npz["orf_phage_valid"].astype(np.float32)
                if "orf_func_targets" in fn_npz and len(fn_npz["orf_func_targets"]) == n:
                    orf_func_targets = fn_npz["orf_func_targets"].astype(np.float32)
                if "orf_func_valid" in fn_npz and len(fn_npz["orf_func_valid"]) == n:
                    orf_func_valid = fn_npz["orf_func_valid"].astype(np.float32)
                if "sem_targets" in fn_npz and len(fn_npz["sem_targets"]) == n:
                    # 严格使用客观三源 4D 语义替换旧版可能存在 y 依赖或 PHROG 回填污染的标签
                    sem_targets = fn_npz["sem_targets"].astype(np.float32)
                    sem_valid = np.ones(n, dtype=np.float32)
                if "clean_labels" in fn_npz and len(fn_npz["clean_labels"]) == n:
                    clean_labels = fn_npz["clean_labels"].astype(np.int8)

    fasta = _resolve_part_fasta(feature_dir, manifest_or_train_dir, split, part, fasta_override=fasta_override)
    codes, lengths = load_window_sequences(fasta, arrs["contig_ids"], arrs["starts"], arrs["ends"], max_len=max_len)
    return {
        "arrs": arrs,
        "codes": codes,
        "lengths": lengths,
        "tokens": tokens,
        "counts": counts,
        "orig_labels": orig_labels,
        "clean_labels": clean_labels,
        "sem_targets": sem_targets,
        "sem_valid": sem_valid,
        "has_functional": has_functional_file,
        "func_targets": func_targets,
        "func_valid": func_valid,
        "orf_phage_targets": orf_phage_targets,
        "orf_phage_valid": orf_phage_valid,
        "orf_func_targets": orf_func_targets,
        "orf_func_valid": orf_func_valid,
    }

def train_distilled_student_v4(
    train_feature_dir: Path,
    train_dir: Path,
    eval_feature_dir: Path,
    bench_dir: Path,
    out_dir: Path,
    *,
    train_parts: Tuple[str, ...] = ("windows", "chimeras"),
    extra_mined_fasta: Optional[Path] = None,
    extra_fasta_map: Optional[Dict[str, Path]] = None,
    part_weights: Optional[Dict[str, float]] = None,
    teacher_oof_npz: Optional[Path] = None,
    teacher_probs_override: Optional[np.ndarray] = None,
    teacher_weights: Tuple[float, float, float] = (0.4, 0.35, 0.25),
    epochs: int = 24,
    batch_size: int = 64,
    lr: float = 8e-4,
    patience: int = 6,
    max_len: int = 5000,
    dna_channels: int = 160,
    orf_d_model: int = 128,
    orf_nhead: int = 4,
    orf_num_layers: int = 3,
    fusion_dim: int = 256,
    distill_alpha: float = 0.55,
    sub_weight: float = 0.25,
    sem_weight: float = 0.25,
    temperature: float = 2.0,
    focal_gamma: float = 2.0,
    modality_dropout_prob: float = 0.10,
    tune_sub_head: bool = True,
    train_refiner: bool = True,
    refiner_epochs: int = 16,
    train_subbin_refiner: bool = True,
    subbin_epochs: int = 16,
    enable_plateau_decoder: bool = True,
    use_semantic: bool = True,
    use_functional: bool = False,
    use_homoscedastic_loss: bool = False,
    feature_profile: str = "v4",
    init_student_ckpt: Optional[Path] = None,
    backbone_lr_scale: float = 0.25,
    sample_weights_override: Optional[np.ndarray] = None,
    workers: Optional[int] = None,
    seed: int = 42,
) -> Dict[str, Any]:
    """训练 V4 高容量三模态蒸馏学生模型（可选 9D 客观功能分区蒸馏与 Kendall 自动加权）与跨窗上下文精修器并生成测试报告。"""
    import torch
    import torch.nn.functional as F
    from sklearn.metrics import average_precision_score

    torch.manual_seed(seed)
    rng = np.random.default_rng(seed)
    out_root = Path(out_dir).resolve()
    out_root.mkdir(parents=True, exist_ok=True)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    f_map = {k: Path(v) for k, v in (extra_fasta_map or {}).items()}
    if extra_mined_fasta is not None and "mined" not in f_map:
        f_map["mined"] = Path(extra_mined_fasta)
    ordered_parts = list(train_parts)
    mined_npz = Path(train_feature_dir) / "train_mined.npz"
    if "mined" in f_map and f_map["mined"].exists() and mined_npz.exists() and "mined" not in ordered_parts:
        ordered_parts.append("mined")

    w_map = part_weights or {}
    loaded_parts: List[Dict[str, Any]] = []
    part_names_used: List[str] = []
    sw_list: List[np.ndarray] = []
    part_tag_list: List[np.ndarray] = []

    t_data0 = time.perf_counter()
    for part in ordered_parts:
        if not (Path(train_feature_dir) / f"train_{part}.npz").exists():
            continue
        pdata = _load_v4_part(
            train_feature_dir,
            train_dir,
            "train",
            part,
            max_len,
            workers,
            fasta_override=f_map.get(part),
            use_semantic=use_semantic,
            use_functional=use_functional,
            feature_profile=feature_profile,
        )
        n_p = len(pdata["clean_labels"])
        if n_p == 0:
            continue
        loaded_parts.append(pdata)
        part_names_used.append(part)
        sw_list.append(np.full(n_p, float(w_map.get(part, 1.0)), dtype=np.float32))
        part_tag_list.append(np.full(n_p, part, dtype=object))

    codes_all = np.concatenate([p["codes"] for p in loaded_parts])
    len_all = np.concatenate([p["lengths"] for p in loaded_parts])
    feats_all = np.concatenate([p["arrs"]["features"] for p in loaded_parts])
    tokens_all = np.concatenate([p["tokens"] for p in loaded_parts])
    counts_all = np.concatenate([p["counts"] for p in loaded_parts])
    sub_all = np.concatenate([p["arrs"]["sub_mask"] for p in loaded_parts]).astype(np.float32)
    orig_y_all = np.concatenate([p["orig_labels"] for p in loaded_parts])
    clean_y_all = np.concatenate([p["clean_labels"] for p in loaded_parts])
    sem_t_all = np.concatenate([p["sem_targets"] for p in loaded_parts])
    sem_v_all = np.concatenate([p["sem_valid"] for p in loaded_parts])
    has_func_data = bool(use_functional and any(p.get("has_functional", False) for p in loaded_parts))
    func_t_all = np.concatenate([p["func_targets"] for p in loaded_parts]) if has_func_data else None
    func_v_all = np.concatenate([p["func_valid"] for p in loaded_parts]) if has_func_data else None
    orf_ph_t_all = np.concatenate([p["orf_phage_targets"] for p in loaded_parts]) if has_func_data else None
    orf_ph_v_all = np.concatenate([p["orf_phage_valid"] for p in loaded_parts]) if has_func_data else None
    orf_fn_t_all = np.concatenate([p["orf_func_targets"] for p in loaded_parts]) if has_func_data else None
    orf_fn_v_all = np.concatenate([p["orf_func_valid"] for p in loaded_parts]) if has_func_data else None
    cids_all = np.concatenate([p["arrs"]["contig_ids"] for p in loaded_parts])
    starts_all = np.concatenate([p["arrs"]["starts"] for p in loaded_parts])
    ends_all = np.concatenate([p["arrs"]["ends"] for p in loaded_parts])
    sw_all = np.concatenate(sw_list)
    if sample_weights_override is not None:
        if len(sample_weights_override) != len(clean_y_all):
            raise ValueError(
                f"sample_weights_override 长度不匹配: {len(sample_weights_override)} vs {len(clean_y_all)}"
            )
        sw_all = np.asarray(sample_weights_override, dtype=np.float32)
    part_tags_all = np.concatenate(part_tag_list)
    refiner_mask_all = np.isin(part_tags_all, CONTIG_REF_PARTS)
    del loaded_parts, sw_list, part_tag_list

    # 加载或构造多教师 GroupKFold OOF 软概率
    t_oof0 = time.perf_counter()
    if teacher_probs_override is not None and len(teacher_probs_override) == len(clean_y_all):
        teacher_probs_all = np.asarray(teacher_probs_override, dtype=np.float32)
    elif teacher_oof_npz is not None and Path(teacher_oof_npz).exists():
        with np.load(teacher_oof_npz, allow_pickle=False) as tp_npz:
            if "ensemble_oof" in tp_npz and len(tp_npz["ensemble_oof"]) == len(clean_y_all):
                teacher_probs_all = tp_npz["ensemble_oof"].astype(np.float32)
            else:
                wa, wb, wc = teacher_weights
                acc = np.zeros(len(clean_y_all), dtype=np.float32)
                wsum = 0.0
                for key, w in (("xgb_oof", wa), ("exp_b_oof", wb), ("exp_c_oof", wc)):
                    if key in tp_npz and len(tp_npz[key]) == len(clean_y_all) and w > 0:
                        acc += float(w) * tp_npz[key].astype(np.float32)
                        wsum += float(w)
                teacher_probs_all = (acc / max(1e-6, wsum)).astype(np.float32)
    else:
        from .distilled_student import compute_group_oof_xgb_probs

        keep_xgb = clean_y_all >= 0
        xgb_oof = np.where(clean_y_all == 1, 0.9, 0.1).astype(np.float32)
        if np.any(keep_xgb) and np.unique(clean_y_all[keep_xgb]).size > 1:
            xgb_oof[keep_xgb] = compute_group_oof_xgb_probs(
                feats_all[keep_xgb],
                clean_y_all[keep_xgb].astype(np.int32),
                cids_all[keep_xgb],
                n_splits=min(5, len(np.unique(cids_all[keep_xgb]))),
                sample_weights=sw_all[keep_xgb],
                n_estimators=400,
            )
        teacher_probs_all = xgb_oof
    oof_sec = round(time.perf_counter() - t_oof0, 2)

    # 验证集与测试集准备（严禁使用任何测试数据进行训练/早停）
    va_w = _load_v4_part(
        eval_feature_dir, bench_dir, "val", "windows", max_len, workers,
        use_semantic=False, feature_profile=feature_profile,
    )
    va_c = _load_v4_part(
        eval_feature_dir, bench_dir, "val", "chimeras", max_len, workers,
        use_semantic=False, feature_profile=feature_profile,
    )
    va_codes = np.concatenate([va_w["codes"], va_c["codes"]])
    va_len = np.concatenate([va_w["lengths"], va_c["lengths"]])
    va_feats = np.concatenate([va_w["arrs"]["features"], va_c["arrs"]["features"]])
    va_tokens = np.concatenate([va_w["tokens"], va_c["tokens"]])
    va_counts = np.concatenate([va_w["counts"], va_c["counts"]])
    va_y = np.concatenate([va_w["orig_labels"], va_c["orig_labels"]])
    va_keep = va_y >= 0
    has_two_va = bool(np.any(va_keep) and np.unique(va_y[va_keep]).size > 1)

    # 筛选训练样本：保留 clean_labels>=0 以及真正原始嵌合体边界 (-1)，剔除语义清洗屏蔽的伪负样本
    use_row = (clean_y_all >= 0) | ((clean_y_all == -1) & (orig_y_all == -1))
    codes_tr = codes_all[use_row]
    len_tr = len_all[use_row]
    feats_tr = feats_all[use_row]
    tokens_tr = tokens_all[use_row]
    counts_tr = counts_all[use_row]
    sub_tr = sub_all[use_row]
    y_tr = clean_y_all[use_row]
    teacher_tr = teacher_probs_all[use_row]
    sem_t_tr = sem_t_all[use_row]
    sem_v_tr = sem_v_all[use_row]
    sw_tr = sw_all[use_row]

    func_t_tr = func_t_all[use_row] if (has_func_data and func_t_all is not None) else None
    func_v_tr = func_v_all[use_row] if (has_func_data and func_v_all is not None) else None
    orf_ph_t_tr = orf_ph_t_all[use_row] if (has_func_data and orf_ph_t_all is not None) else None
    orf_ph_v_tr = orf_ph_v_all[use_row] if (has_func_data and orf_ph_v_all is not None) else None
    orf_fn_t_tr = orf_fn_t_all[use_row] if (has_func_data and orf_fn_t_all is not None) else None
    orf_fn_v_tr = orf_fn_v_all[use_row] if (has_func_data and orf_fn_v_all is not None) else None
    del func_t_all, func_v_all, orf_ph_t_all, orf_ph_v_all, orf_fn_t_all, orf_fn_v_all
    func_dim = NUM_FUNC_PARTITIONS if has_func_data else 0

    orf_feat_dim = int(tokens_tr.shape[-1])
    valid_idx = y_tr >= 0
    feat_mean, feat_std = _normalize_feature_stats(feats_tr[valid_idx] if np.any(valid_idx) else feats_tr)
    warm_started_from: Optional[str] = None
    init_sd: Optional[Dict[str, torch.Tensor]] = None
    if init_student_ckpt is not None:
        init_path = Path(init_student_ckpt).resolve()
        if not init_path.exists():
            raise FileNotFoundError(f"热启动权重文件不存在: {init_path}")
        init_sd = torch.load(init_path, map_location="cpu", weights_only=True)
        if (
            "feat_mean" in init_sd
            and "feat_std" in init_sd
            and tuple(init_sd["feat_mean"].shape) == tuple(feat_mean.shape)
        ):
            feat_mean = init_sd["feat_mean"].detach().cpu().numpy().astype(np.float32)
            feat_std = init_sd["feat_std"].detach().cpu().numpy().astype(np.float32)
        warm_started_from = str(init_path)

    model = build_distilled_student_v4(
        feats_tr.shape[1],
        feat_mean,
        feat_std,
        dna_channels=dna_channels,
        orf_d_model=orf_d_model,
        orf_nhead=orf_nhead,
        orf_num_layers=orf_num_layers,
        fusion_dim=fusion_dim,
        orf_feat_dim=orf_feat_dim,
        func_dim=func_dim,
    ).to(device)
    if init_sd is not None:
        model.load_state_dict(init_sd, strict=True)
        logger.info("已热加载原模型权重（零参数增量）: %s", warm_started_from)
    n_params = int(sum(p.numel() for p in model.parameters()))

    num_tasks = (6 if func_dim > 0 else 3) if use_homoscedastic_loss else 0
    mt_loss_fn = (
        HomoscedasticMultiTaskLoss(num_tasks=num_tasks, min_log_var=-3.0, max_log_var=3.0).to(device)
        if use_homoscedastic_loss
        else None
    )
    head_prefixes = (
        "win_head.",
        "sem_head.",
        "func_head.",
        "orf_phage_head.",
        "orf_func_head.",
        "func_win_residual.",
        "sub_head.",
    )
    if warm_started_from is not None:
        bb_scale = float(np.clip(backbone_lr_scale, 0.01, 1.0))
        bb_params = [p for n, p in model.named_parameters() if not n.startswith(head_prefixes)]
        hd_params = [p for n, p in model.named_parameters() if n.startswith(head_prefixes)]
        param_groups: List[Dict[str, Any]] = [
            {"params": bb_params, "weight_decay": 1e-2, "lr": lr * bb_scale},
            {"params": hd_params, "weight_decay": 1e-2, "lr": lr},
        ]
        max_lrs: Any = [lr * bb_scale, lr]
        if mt_loss_fn is not None:
            param_groups.append({"params": list(mt_loss_fn.parameters()), "weight_decay": 0.0, "lr": lr})
            max_lrs.append(lr)
    else:
        param_groups = [{"params": list(model.parameters()), "weight_decay": 1e-2}]
        max_lrs = lr
        if mt_loss_fn is not None:
            param_groups.append({"params": list(mt_loss_fn.parameters()), "weight_decay": 0.0})
    opt = torch.optim.AdamW(param_groups, lr=lr)
    steps_per_ep = max(1, int(np.ceil(len(y_tr) / batch_size)))
    sched = torch.optim.lr_scheduler.OneCycleLR(opt, max_lr=max_lrs, total_steps=max(1, epochs * steps_per_ep))
    scaler = torch.amp.GradScaler("cuda", enabled=device.type == "cuda")

    pos_cnt = float(np.sum(y_tr == 1))
    neg_cnt = float(np.sum(y_tr == 0))
    pos_w = float(np.clip(neg_cnt / max(1.0, pos_cnt), 0.5, 4.0))
    sem_pos_weight = torch.tensor([1.5, 1.5, 2.0, 1.5], dtype=torch.float32, device=device)
    sem_loss_fn = torch.nn.BCEWithLogitsLoss(pos_weight=sem_pos_weight, reduction="none")

    func_pos_weight_t = None
    orf_ph_pos_w_t = None
    if func_dim > 0 and func_t_tr is not None and func_v_tr is not None:
        fn_pos = np.sum((func_t_tr > 0.5) * func_v_tr, axis=0)
        fn_neg = np.sum((func_t_tr <= 0.5) * func_v_tr, axis=0)
        fn_pw = np.clip(np.sqrt(fn_neg / np.maximum(1.0, fn_pos)), 1.0, 6.0).astype(np.float32)
        func_pos_weight_t = torch.tensor(fn_pw, dtype=torch.float32, device=device)
        if orf_ph_t_tr is not None and orf_ph_v_tr is not None:
            op_pos = float(np.sum((orf_ph_t_tr > 0.5) * orf_ph_v_tr))
            op_neg = float(np.sum((orf_ph_t_tr <= 0.5) * orf_ph_v_tr))
            orf_ph_pos_w_t = torch.tensor([float(np.clip(np.sqrt(op_neg / max(1.0, op_pos)), 1.0, 5.0))], dtype=torch.float32, device=device)
        logger.info(f"Stage 1.2 自动客观功能统计 pos_weight={np.round(fn_pw, 2).tolist()}")

    ckpt_path = out_root / "student_v4.pt"
    best_ap = -1.0
    best_ep = -1
    bad_ep = 0
    history: List[Dict[str, Any]] = []
    if device.type == "cuda":
        torch.cuda.reset_peak_memory_stats()

    t0 = time.perf_counter()
    for ep in range(1, epochs + 1):
        model.train()
        if mt_loss_fn is not None:
            mt_loss_fn.train()
        order = rng.permutation(len(y_tr))
        ep_loss = 0.0
        for bi in range(steps_per_ep):
            idx = order[bi * batch_size:(bi + 1) * batch_size]
            b_codes = codes_tr[idx].copy()
            b_len = len_tr[idx]
            b_sub = sub_tr[idx].copy()
            rc_mask = (b_len == max_len) | (b_sub.min(axis=1) == b_sub.max(axis=1))
            if rng.random() < 0.5 and np.any(rc_mask):
                b_codes[rc_mask] = reverse_complement_codes(b_codes[rc_mask], b_len[rc_mask])
                full_only = rc_mask & (b_len == max_len)
                b_sub[full_only] = b_sub[full_only, ::-1]

            c_t = torch.from_numpy(b_codes.astype(np.int64)).to(device)
            oh = torch.nn.functional.one_hot(c_t, num_classes=5)[..., :4].permute(0, 2, 1).float()
            ln_t = torch.from_numpy(b_len.astype(np.int64)).to(device)
            tb_t = torch.from_numpy(feats_tr[idx]).to(device)
            tk_t = torch.from_numpy(tokens_tr[idx]).to(device)
            cn_t = torch.from_numpy(counts_tr[idx].astype(np.int64)).to(device)

            # 轻量模态随机丢弃（Modality Dropout）：随机将少数样本 Tabular 或 ORF 屏蔽，增强纯 DNA 分支表征
            orf_keep_for_loss = None
            if modality_dropout_prob > 0.0:
                m_drop = rng.random(len(idx))
                orf_drop = m_drop < modality_dropout_prob
                tab_drop = (m_drop >= modality_dropout_prob) & (m_drop < 2.0 * modality_dropout_prob)
                if np.any(orf_drop):
                    od_t = torch.from_numpy(orf_drop).to(device)
                    cn_t = torch.where(od_t, torch.zeros_like(cn_t), cn_t)
                    tk_t = torch.where(od_t[:, None, None], torch.zeros_like(tk_t), tk_t)
                    orf_keep_for_loss = (~od_t).to(torch.float32)
                if np.any(tab_drop):
                    td_t = torch.from_numpy(tab_drop).to(device)
                    tb_t = torch.where(td_t[:, None], model.feat_mean.unsqueeze(0).expand_as(tb_t), tb_t)

            yb_raw = y_tr[idx]
            win_valid = torch.from_numpy((yb_raw >= 0).astype(np.float32)).to(device)
            yb = torch.from_numpy(np.maximum(yb_raw, 0).astype(np.float32)).to(device)
            tp = torch.from_numpy(teacher_tr[idx]).to(device)
            sb = torch.from_numpy(b_sub).to(device)
            st_t = torch.from_numpy(sem_t_tr[idx]).to(device)
            sv_t = torch.from_numpy(sem_v_tr[idx]).to(device)
            wb = torch.from_numpy(sw_tr[idx]).to(device)

            if func_dim > 0 and func_t_tr is not None:
                fn_t = torch.from_numpy(func_t_tr[idx]).to(device)
                fn_v = torch.from_numpy(func_v_tr[idx]).to(device)
                op_t = torch.from_numpy(orf_ph_t_tr[idx]).to(device)
                op_v = torch.from_numpy(orf_ph_v_tr[idx]).to(device)
                of_t = torch.from_numpy(orf_fn_t_tr[idx]).to(device)
                of_v = torch.from_numpy(orf_fn_v_tr[idx]).to(device)
                if orf_keep_for_loss is not None:
                    op_v = op_v * orf_keep_for_loss[:, None]
                    of_v = of_v * orf_keep_for_loss[:, None]

            opt.zero_grad(set_to_none=True)
            with torch.autocast(device_type=device.type, dtype=torch.float16, enabled=device.type == "cuda"):
                out_d = model(oh, tb_t, lengths=ln_t, orf_tokens=tk_t, orf_counts=cn_t, return_aux=True)
                w_logit = out_d["win_logit"]
                s_logits = out_d["sub_logits"]
                sem_logits = out_d["sem_logits"]

                l_hard = _focal_bce_with_logits(
                    w_logit, yb, pos_weight=pos_w, gamma=focal_gamma, valid_mask=win_valid, sample_weight=wb,
                )
                l_kd = _kd_bce_loss(
                    w_logit, tp, temperature=temperature, valid_mask=win_valid, sample_weight=wb,
                )
                l_win = (1.0 - distill_alpha) * l_hard + distill_alpha * l_kd
                l_sub = _sub_bce_dice_loss(s_logits, sb, sample_weight=wb)
                sem_elem = sem_loss_fn(sem_logits, st_t).mean(dim=1)
                sem_eff = sv_t * wb
                l_sem = (sem_elem * sem_eff).sum() / sem_eff.sum().clamp(min=1e-4)

                func_losses: List[torch.Tensor] = []
                if func_dim > 0 and func_t_tr is not None:
                    fn_bce = F.binary_cross_entropy_with_logits(
                        out_d["func_logits"].float(), fn_t, pos_weight=func_pos_weight_t, reduction="none",
                    )
                    fn_eff = fn_v * wb[:, None]
                    l_win_func = (fn_bce * fn_eff).sum() / fn_eff.sum().clamp(min=1e-4)

                    op_bce = F.binary_cross_entropy_with_logits(
                        out_d["orf_phage_logits"].float(), op_t, pos_weight=orf_ph_pos_w_t[0], reduction="none",
                    )
                    op_eff = op_v * wb[:, None]
                    l_orf_phage = (op_bce * op_eff).sum() / op_eff.sum().clamp(min=1e-4)

                    of_bce = F.binary_cross_entropy_with_logits(
                        out_d["orf_func_logits"].float(), of_t, pos_weight=func_pos_weight_t, reduction="none",
                    )
                    of_eff = of_v[:, :, None] * wb[:, None, None]
                    l_orf_func = (of_bce * of_eff).sum() / of_eff.sum().clamp(min=1e-4)
                    func_losses = [l_win_func, l_orf_phage, l_orf_func]

            if mt_loss_fn is not None:
                task_list = [l_win.float(), l_sub.float(), l_sem.float(), *[x.float() for x in func_losses]]
                loss = mt_loss_fn(task_list)
            else:
                loss = l_win + sub_weight * l_sub + sem_weight * l_sem
                if func_losses:
                    loss = loss + 0.25 * (func_losses[0] + func_losses[1] + func_losses[2]) / 3.0

            cast(torch.Tensor, scaler.scale(loss)).backward()
            scaler.unscale_(opt)
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            if mt_loss_fn is not None:
                torch.nn.utils.clip_grad_norm_(mt_loss_fn.parameters(), 1.0)
            scale_before = scaler.get_scale()
            scaler.step(opt)
            scaler.update()
            if not (device.type == "cuda" and scaler.get_scale() < scale_before):
                sched.step()
            ep_loss += float(loss.item()) * len(idx)

        va_pred = _predict_v4_all(
            model, va_codes[va_keep], va_len[va_keep], va_feats[va_keep], va_tokens[va_keep], va_counts[va_keep], device,
            batch_size=max(64, batch_size),
        )
        ap = float(average_precision_score(va_y[va_keep], va_pred["win_probs"])) if has_two_va else -ep_loss
        ep_entry: Dict[str, Any] = {
            "epoch": ep,
            "train_loss": round(ep_loss / max(1, len(y_tr)), 5),
            "val_auprc": round(ap, 5),
        }
        if mt_loss_fn is not None:
            with torch.no_grad():
                tw = torch.exp(-torch.clamp(mt_loss_fn.log_vars, mt_loss_fn.min_log_var, mt_loss_fn.max_log_var)).cpu().numpy()
            ep_entry["task_precisions"] = [round(float(x), 4) for x in tw]
            logger.info(
                f"StudentV4 epoch {ep}: loss={ep_loss / max(1, len(y_tr)):.4f} val_auprc={ap:.4f} task_prec={ep_entry['task_precisions']}"
            )
        else:
            logger.info(f"StudentV4 epoch {ep}: loss={ep_loss / max(1, len(y_tr)):.4f} val_auprc={ap:.4f}")
        history.append(ep_entry)
        if device.type == "cuda":
            torch.cuda.empty_cache()
        if ap > best_ap or best_ep < 0:
            best_ap, best_ep, bad_ep = ap, ep, 0
            tmp = ckpt_path.with_name(f".{ckpt_path.name}.tmp")
            torch.save(model.state_dict(), tmp)
            tmp.replace(ckpt_path)
        else:
            bad_ep += 1
            if bad_ep >= patience:
                break

    train_sec = round(time.perf_counter() - t0, 2)
    peak_mb = round(torch.cuda.max_memory_allocated() / (1024 * 1024), 1) if device.type == "cuda" else 0.0
    model.load_state_dict(torch.load(ckpt_path, map_location=device, weights_only=True))
    learned_task_weights = history[best_ep - 1].get("task_precisions") if (best_ep >= 1 and best_ep <= len(history)) else None
    del func_t_tr, func_v_tr, orf_ph_t_tr, orf_ph_v_tr, orf_fn_t_tr, orf_fn_v_tr
    if mt_loss_fn is not None:
        del mt_loss_fn

    sub_tune_info: Dict[str, Any] = {"enabled": False}
    if tune_sub_head:
        sub_tune_info = {
            "enabled": True,
            **refine_student_v4_sub_head(
                model,
                codes_tr,
                len_tr,
                feats_tr,
                tokens_tr,
                counts_tr,
                sub_tr,
                sw_tr,
                va_c["codes"],
                va_c["lengths"],
                va_c["arrs"]["features"],
                va_c["tokens"],
                va_c["counts"],
                va_c["arrs"]["sub_mask"].astype(np.float32),
                out_ckpt_path=ckpt_path,
                device=device,
                seed=seed,
                tr_labels=y_tr,
            ),
        }

    del codes_tr, len_tr, feats_tr, tokens_tr, counts_tr, sub_tr, sem_t_tr, sem_v_tr, sw_tr
    gc.collect()

    va_w_pred = _predict_v4_all(
        model, va_w["codes"], va_w["lengths"], va_w["arrs"]["features"], va_w["tokens"], va_w["counts"], device,
    )
    va_c_pred = _predict_v4_all(
        model, va_c["codes"], va_c["lengths"], va_c["arrs"]["features"], va_c["tokens"], va_c["counts"], device,
    )
    te_w = _load_v4_part(
        eval_feature_dir, bench_dir, "test", "windows", max_len, workers,
        use_semantic=False, feature_profile=feature_profile,
    )
    te_c = _load_v4_part(
        eval_feature_dir, bench_dir, "test", "chimeras", max_len, workers,
        use_semantic=False, feature_profile=feature_profile,
    )

    t_inf0 = time.perf_counter()
    te_w_pred = _predict_v4_all(
        model, te_w["codes"], te_w["lengths"], te_w["arrs"]["features"], te_w["tokens"], te_w["counts"], device,
    )
    te_c_pred = _predict_v4_all(
        model, te_c["codes"], te_c["lengths"], te_c["arrs"]["features"], te_c["tokens"], te_c["counts"], device,
    )
    infer_sec = round(time.perf_counter() - t_inf0, 3)

    # 可选训练 RegionContextRefiner 与场景 A 200 bp SubBinContextRefiner（融合物理连续分片并按 source_tag+gap 拆分）
    from .subbin_refiner import (
        build_contig_subbin_sequences,
        extract_per_orf_viral_scores,
        predict_subbin_probs_with_refiner,
        project_orf_to_25bins,
        train_subbin_context_refiner,
    )

    refiner = None
    refiner_info: Dict[str, Any] = {"enabled": False}
    refiner_ckpt = out_root / "context_refiner.pt"
    subbin_refiner = None
    subbin_info: Dict[str, Any] = {"enabled": False}
    subbin_ckpt = out_root / "subbin_refiner.pt"
    tr_c_pred = None
    if (train_refiner or train_subbin_refiner) and np.any(refiner_mask_all):
        tr_c_pred = _predict_v4_all(
            model,
            codes_all[refiner_mask_all],
            len_all[refiner_mask_all],
            feats_all[refiner_mask_all],
            tokens_all[refiner_mask_all],
            counts_all[refiner_mask_all],
            device,
        )

    if train_refiner and tr_c_pred is not None:
        tr_sf_clean = extract_refiner_step_features(
            tr_c_pred["win_logits"],
            tr_c_pred["sem_logits"],
            tr_c_pred["sub_probs"],
            len_all[refiner_mask_all],
            max_len=max_len,
            func_logits=tr_c_pred.get("func_logits"),
        )
        # 构造真实无泄露 OOD 扰动视图（屏蔽部分 Tabular/ORF 模态）消除长训学生过拟合引起的 Refiner 暴露偏差
        tr_c_pred_ood = _predict_v4_all(
            model,
            codes_all[refiner_mask_all],
            len_all[refiner_mask_all],
            feats_all[refiner_mask_all],
            tokens_all[refiner_mask_all],
            counts_all[refiner_mask_all],
            device,
            drop_tabular_prob=0.25,
            drop_orf_prob=0.15,
            seed=seed + 101,
        )
        tr_sf_ood = extract_refiner_step_features(
            tr_c_pred_ood["win_logits"],
            tr_c_pred_ood["sem_logits"],
            tr_c_pred_ood["sub_probs"],
            len_all[refiner_mask_all],
            max_len=max_len,
            func_logits=tr_c_pred_ood.get("func_logits"),
        )
        tr_sf = np.concatenate([tr_sf_clean, tr_sf_ood], axis=0)
        tr_wl = np.concatenate([tr_c_pred["win_logits"], tr_c_pred_ood["win_logits"]], axis=0)
        tr_y_ref = np.concatenate([clean_y_all[refiner_mask_all], clean_y_all[refiner_mask_all]], axis=0)
        tr_cids_ref = np.concatenate([cids_all[refiner_mask_all], cids_all[refiner_mask_all]], axis=0)
        tr_starts_ref = np.concatenate([starts_all[refiner_mask_all], starts_all[refiner_mask_all]], axis=0)
        tr_tags_ref = np.concatenate([
            part_tags_all[refiner_mask_all],
            np.array([f"ood::{t}" for t in part_tags_all[refiner_mask_all]], dtype=object),
        ], axis=0)
        del tr_c_pred_ood, tr_sf_clean, tr_sf_ood

        va_sf = extract_refiner_step_features(
            va_c_pred["win_logits"],
            va_c_pred["sem_logits"],
            va_c_pred["sub_probs"],
            va_c["lengths"],
            max_len=max_len,
            func_logits=va_c_pred.get("func_logits"),
        )
        refiner, r_rep = train_context_refiner(
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
            epochs=refiner_epochs,
            seed=seed,
            tr_source_tags=tr_tags_ref,
        )
        del tr_sf, tr_wl, tr_y_ref, tr_cids_ref, tr_starts_ref, tr_tags_ref
        refiner_info = {"enabled": True, "ckpt_path": str(refiner_ckpt), **r_rep}

    va_chim_raw_sc = va_c_pred["win_probs"]
    te_chim_raw_sc = te_c_pred["win_probs"]
    va_chim_ref_sc = predict_with_context_refiner(
        refiner, va_c_pred["win_logits"], va_c_pred["sem_logits"], va_c_pred["sub_probs"],
        va_c["lengths"], va_c["arrs"]["contig_ids"], va_c["arrs"]["starts"], device, max_len=max_len,
        func_logits=va_c_pred.get("func_logits"),
    ) if refiner is not None else va_chim_raw_sc
    te_chim_ref_sc = predict_with_context_refiner(
        refiner, te_c_pred["win_logits"], te_c_pred["sem_logits"], te_c_pred["sub_probs"],
        te_c["lengths"], te_c["arrs"]["contig_ids"], te_c["arrs"]["starts"], device, max_len=max_len,
        func_logits=te_c_pred.get("func_logits"),
    ) if refiner is not None else te_chim_raw_sc

    va_subbin_profiles = None
    te_subbin_profiles = None
    va_chim_sub_eval = va_c_pred["sub_probs"]
    te_chim_sub_eval = te_c_pred["sub_probs"]

    if train_subbin_refiner and tr_c_pred is not None:
        tr_ref_sc = predict_with_context_refiner(
            refiner, tr_c_pred["win_logits"], tr_c_pred["sem_logits"], tr_c_pred["sub_probs"],
            len_all[refiner_mask_all],
            np.array([f"{t}::{c}" for t, c in zip(part_tags_all[refiner_mask_all], cids_all[refiner_mask_all])], dtype=object),
            starts_all[refiner_mask_all],
            device, max_len=max_len, func_logits=tr_c_pred.get("func_logits"),
        ) if refiner is not None else tr_c_pred["win_probs"]

        tr_orf_bins = project_orf_to_25bins(
            tokens_all[refiner_mask_all], counts_all[refiner_mask_all],
            extract_per_orf_viral_scores(model, tokens_all[refiner_mask_all], counts_all[refiner_mask_all], device),
        )
        va_orf_bins = project_orf_to_25bins(
            va_c["tokens"], va_c["counts"],
            extract_per_orf_viral_scores(model, va_c["tokens"], va_c["counts"], device),
        )
        tr_sb_groups = group_windows_by_contig(
            cids_all[refiner_mask_all], starts_all[refiner_mask_all],
            max_gap_bp=max_len, source_tags=part_tags_all[refiner_mask_all],
        )
        va_sb_groups = group_windows_by_contig(va_c["arrs"]["contig_ids"], va_c["arrs"]["starts"], max_gap_bp=max_len)
        tr_sb_seqs = build_contig_subbin_sequences(
            tr_sb_groups,
            starts_all[refiner_mask_all],
            ends_all[refiner_mask_all],
            tr_ref_sc,
            tr_c_pred["win_probs"],
            tr_c_pred["sem_logits"],
            tr_c_pred["sub_probs"],
            win_orf_25bins=tr_orf_bins,
            sub_targets=sub_all[refiner_mask_all],
            valid_win_mask=(clean_y_all[refiner_mask_all] >= 0),
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
            tr_sb_seqs, va_sb_seqs, out_path=subbin_ckpt, epochs=subbin_epochs, seed=seed,
        )
        subbin_info = {"enabled": True, "ckpt_path": str(subbin_ckpt), **sb_rep}

        va_subbin_profiles, va_chim_sub_eval = predict_subbin_probs_with_refiner(
            subbin_refiner, va_sb_groups, va_c["arrs"]["contig_ids"], va_c["arrs"]["starts"], va_c["arrs"]["ends"],
            va_chim_ref_sc, va_chim_raw_sc, va_c_pred["sem_logits"], va_c_pred["sub_probs"],
            device, win_orf_25bins=va_orf_bins, min_windows=2,
        )
        te_orf_bins = project_orf_to_25bins(
            te_c["tokens"], te_c["counts"],
            extract_per_orf_viral_scores(model, te_c["tokens"], te_c["counts"], device),
        )
        te_sb_groups = group_windows_by_contig(te_c["arrs"]["contig_ids"], te_c["arrs"]["starts"], max_gap_bp=max_len)
        te_subbin_profiles, te_chim_sub_eval = predict_subbin_probs_with_refiner(
            subbin_refiner, te_sb_groups, te_c["arrs"]["contig_ids"], te_c["arrs"]["starts"], te_c["arrs"]["ends"],
            te_chim_ref_sc, te_chim_raw_sc, te_c_pred["sem_logits"], te_c_pred["sub_probs"],
            device, win_orf_25bins=te_orf_bins, min_windows=2,
        )
        del tr_orf_bins, va_orf_bins, te_orf_bins, tr_sb_seqs, va_sb_seqs

    del codes_all, len_all, feats_all, tokens_all, counts_all, sub_all
    gc.collect()
    if device.type == "cuda":
        torch.cuda.empty_cache()

    va_win_sc = va_w_pred["win_probs"]
    te_win_sc = te_w_pred["win_probs"]

    plateau_cands = ((4, 0.90), (0, None)) if enable_plateau_decoder else ((0, None),)
    use_sb = subbin_refiner is not None
    sb_smooth = not use_sb
    sb_pad = 3000 if use_sb else 2000

    decoder_raw = tune_decoder_on_val(
        load_split_info(bench_dir, "val"), va_c["arrs"], va_chim_raw_sc, chim_sub_probs=va_c_pred["sub_probs"],
    )
    decoder_ref = tune_decoder_on_val(
        load_split_info(bench_dir, "val"), va_c["arrs"], va_chim_ref_sc, chim_sub_probs=va_chim_sub_eval,
        plateau_candidates=plateau_cands,
        precomputed_bin_profiles=va_subbin_profiles,
        smooth_profile=sb_smooth,
        refine_pad_bp=sb_pad,
    ) if (refiner is not None or use_sb) else decoder_raw

    val_raw_rep = evaluate_model_scores_on_split(
        bench_dir, "val", va_w["arrs"], va_win_sc, va_c["arrs"], va_chim_raw_sc,
        decoder_raw["seed_threshold"], decoder_raw["extend_threshold"],
        chim_sub_probs=va_c_pred["sub_probs"], sub_threshold=decoder_raw.get("sub_threshold"),
    )
    test_raw_rep = evaluate_model_scores_on_split(
        bench_dir, "test", te_w["arrs"], te_win_sc, te_c["arrs"], te_chim_raw_sc,
        decoder_raw["seed_threshold"], decoder_raw["extend_threshold"],
        chim_sub_probs=te_c_pred["sub_probs"], sub_threshold=decoder_raw.get("sub_threshold"),
    )
    val_ref_rep = evaluate_model_scores_on_split(
        bench_dir, "val", va_w["arrs"], va_win_sc, va_c["arrs"], va_chim_ref_sc,
        decoder_ref["seed_threshold"], decoder_ref["extend_threshold"],
        chim_sub_probs=va_chim_sub_eval, sub_threshold=decoder_ref.get("sub_threshold"),
        plateau_min_windows=int(decoder_ref.get("plateau_min_windows", 0)),
        plateau_second_threshold=decoder_ref.get("plateau_second_threshold"),
        precomputed_bin_profiles=va_subbin_profiles,
        smooth_profile=bool(decoder_ref.get("smooth_profile", True)),
        refine_pad_bp=int(decoder_ref.get("refine_pad_bp", 2000)),
    )
    test_ref_rep = evaluate_model_scores_on_split(
        bench_dir, "test", te_w["arrs"], te_win_sc, te_c["arrs"], te_chim_ref_sc,
        decoder_ref["seed_threshold"], decoder_ref["extend_threshold"],
        chim_sub_probs=te_chim_sub_eval, sub_threshold=decoder_ref.get("sub_threshold"),
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

    # 释放模型并保存 V4 元数据与标准/兼容双份报告
    del model, refiner, subbin_refiner
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()

    meta = {
        "model_version": "v4",
        "feature_profile": feature_profile,
        "feat_dim": int(feat_std.shape[0]),
        "orf_feat_dim": orf_feat_dim,
        "max_len": max_len,
        "dna_channels": dna_channels,
        "orf_d_model": orf_d_model,
        "orf_nhead": orf_nhead,
        "orf_num_layers": orf_num_layers,
        "fusion_dim": fusion_dim,
        "sem_dim": SEMANTIC_DIM,
        "func_dim": int(func_dim),
        "func_partition_names": list(FUNCTIONAL_PARTITION_NAMES) if func_dim > 0 else [],
        "use_homoscedastic_loss": bool(use_homoscedastic_loss),
        "use_context_refiner": bool(refiner_info["enabled"]),
        "refiner_arch": refiner_info.get("refiner_arch", "v2" if refiner_info["enabled"] else "none"),
        "refiner_ckpt": str(refiner_ckpt) if refiner_info["enabled"] else None,
        "use_subbin_refiner": bool(subbin_info["enabled"]),
        "subbin_arch": subbin_info.get("arch", "none"),
        "subbin_ckpt": str(subbin_ckpt) if subbin_info["enabled"] else None,
        "student_ckpt": str(ckpt_path),
    }
    meta_path = out_root / "student_v4_meta.json"
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    total_test_mb = float(test_raw_rep["chimera_benchmark"]["overall"].get("total_scanned_mb") or 20.862)
    est_sec_per_5mb = round((infer_sec / max(1e-6, total_test_mb)) * 5.0, 3)

    active_dec = decoder_ref if refiner_info["enabled"] else decoder_raw
    report: Dict[str, Any] = {
        "model_name": "StudentV4_TriModal_FunctionalDistilled" if func_dim > 0 else "StudentV4_TriModal_MaskedSemantic",
        "model_version": "v4",
        "warm_started_from": warm_started_from,
        "trained_at": datetime.now().isoformat(timespec="seconds"),
        "device": str(device),
        "architecture": meta,
        "params": n_params,
        "train_parts_used": part_names_used,
        "train_rows": int(np.sum(use_row)),
        "oof_teacher_sec": oof_sec,
        "data_prep_sec": round(time.perf_counter() - t_data0, 2),
        "train_sec": train_sec,
        "peak_gpu_mem_mb": peak_mb,
        "test_inference_sec": infer_sec,
        "est_sec_per_5mb": est_sec_per_5mb,
        "best_epoch": best_ep,
        "best_val_auprc": round(best_ap, 5),
        "learned_task_weights": learned_task_weights,
        "history": history,
        "sub_head_refinement": sub_tune_info,
        "context_refiner": refiner_info,
        "subbin_refiner": subbin_info,
        "decoder_tuned_on_val": active_dec,
        "decoder_raw_on_val": decoder_raw,
        "val": val_ref_rep if (refiner_info["enabled"] or subbin_info["enabled"]) else val_raw_rep,
        "test": test_ref_rep if (refiner_info["enabled"] or subbin_info["enabled"]) else test_raw_rep,
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

def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="训练 V4 三模态知识蒸馏学生模型与上下文精修器")
    parser.add_argument("--train-feature-dir", required=True)
    parser.add_argument("--train-dir", required=True)
    parser.add_argument("--eval-feature-dir", required=True)
    parser.add_argument("--bench-dir", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--epochs", type=int, default=24)
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--extra-mined-fasta", default=None)
    parser.add_argument("--no-refiner", action="store_true")
    parser.add_argument("--no-subbin-refiner", action="store_true")
    args = parser.parse_args()
    rep = train_distilled_student_v4(
        Path(args.train_feature_dir),
        Path(args.train_dir),
        Path(args.eval_feature_dir),
        Path(args.bench_dir),
        Path(args.out_dir),
        epochs=args.epochs,
        batch_size=args.batch_size,
        extra_mined_fasta=Path(args.extra_mined_fasta) if args.extra_mined_fasta else None,
        train_refiner=not args.no_refiner,
        train_subbin_refiner=not args.no_subbin_refiner,
    )
    print(json.dumps(summarize_report({**rep, "best_iteration": rep["best_epoch"]}), ensure_ascii=False, indent=2))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
