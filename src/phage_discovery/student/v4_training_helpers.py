# -*- coding: utf-8 -*-
"""
V4 蒸馏学生模型训练编排辅助模块

将原先集中在 train_distilled_student_v4 中的数据分片装载、教师 OOF 融合、
优化器与损失构建、单轮混合精度训练、早停循环、上下文精修器训练及指标归档
按单一职责拆分为可独立测试的模块函数，保持 100% 数值与接口等价。
"""

import logging
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, cast

import numpy as np

from ..data.functional_partitions import (
    NUM_FUNC_PARTITIONS,
    HomoscedasticMultiTaskLoss,
)
from ..experts.seq_dataset import reverse_complement_codes
from .distilled_student import _focal_bce_with_logits, _kd_bce_loss, _sub_bce_dice_loss
from .v4_arch import (
    _normalize_feature_stats,
    build_distilled_student_v4,
)
from .v4_context_refiner import _predict_v4_all

logger = logging.getLogger("phage_discovery.student.v4_training_helpers")

HEAD_PARAM_PREFIXES: Tuple[str, ...] = (
    "win_head.",
    "sem_head.",
    "func_head.",
    "orf_phage_head.",
    "orf_func_head.",
    "func_win_residual.",
    "sub_head.",
)


def load_and_concat_train_parts(
    load_part_fn: Callable[..., Dict[str, Any]],
    train_feature_dir: Path,
    train_dir: Path,
    *,
    train_parts: Tuple[str, ...],
    contig_ref_parts: Tuple[str, ...],
    extra_mined_fasta: Optional[Path],
    extra_fasta_map: Optional[Dict[str, Path]],
    part_weights: Optional[Dict[str, float]],
    sample_weights_override: Optional[np.ndarray],
    max_len: int,
    workers: Optional[int],
    use_semantic: bool,
    use_functional: bool,
    feature_profile: str,
) -> Dict[str, Any]:
    """按顺序加载并拼接全部训练分片，附带样本权重与 refiner 掩码。"""
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

    for part in ordered_parts:
        if not (Path(train_feature_dir) / f"train_{part}.npz").exists():
            continue
        pdata = load_part_fn(
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

    clean_y_all = np.concatenate([p["clean_labels"] for p in loaded_parts])
    sw_all = np.concatenate(sw_list)
    if sample_weights_override is not None:
        if len(sample_weights_override) != len(clean_y_all):
            raise ValueError(
                f"sample_weights_override 长度不匹配: {len(sample_weights_override)} vs {len(clean_y_all)}"
            )
        sw_all = np.asarray(sample_weights_override, dtype=np.float32)

    has_func_data = bool(use_functional and any(p.get("has_functional", False) for p in loaded_parts))
    part_tags_all = np.concatenate(part_tag_list)
    return {
        "part_names_used": part_names_used,
        "codes_all": np.concatenate([p["codes"] for p in loaded_parts]),
        "len_all": np.concatenate([p["lengths"] for p in loaded_parts]),
        "feats_all": np.concatenate([p["arrs"]["features"] for p in loaded_parts]),
        "tokens_all": np.concatenate([p["tokens"] for p in loaded_parts]),
        "counts_all": np.concatenate([p["counts"] for p in loaded_parts]),
        "sub_all": np.concatenate([p["arrs"]["sub_mask"] for p in loaded_parts]).astype(np.float32),
        "orig_y_all": np.concatenate([p["orig_labels"] for p in loaded_parts]),
        "clean_y_all": clean_y_all,
        "sem_t_all": np.concatenate([p["sem_targets"] for p in loaded_parts]),
        "sem_v_all": np.concatenate([p["sem_valid"] for p in loaded_parts]),
        "has_func_data": has_func_data,
        "func_t_all": np.concatenate([p["func_targets"] for p in loaded_parts]) if has_func_data else None,
        "func_v_all": np.concatenate([p["func_valid"] for p in loaded_parts]) if has_func_data else None,
        "orf_ph_t_all": np.concatenate([p["orf_phage_targets"] for p in loaded_parts]) if has_func_data else None,
        "orf_ph_v_all": np.concatenate([p["orf_phage_valid"] for p in loaded_parts]) if has_func_data else None,
        "orf_fn_t_all": np.concatenate([p["orf_func_targets"] for p in loaded_parts]) if has_func_data else None,
        "orf_fn_v_all": np.concatenate([p["orf_func_valid"] for p in loaded_parts]) if has_func_data else None,
        "cids_all": np.concatenate([p["arrs"]["contig_ids"] for p in loaded_parts]),
        "starts_all": np.concatenate([p["arrs"]["starts"] for p in loaded_parts]),
        "ends_all": np.concatenate([p["arrs"]["ends"] for p in loaded_parts]),
        "sw_all": sw_all,
        "part_tags_all": part_tags_all,
        "refiner_mask_all": np.isin(part_tags_all, contig_ref_parts),
    }


def resolve_teacher_oof_probs(
    clean_y_all: np.ndarray,
    feats_all: np.ndarray,
    cids_all: np.ndarray,
    sw_all: np.ndarray,
    *,
    teacher_probs_override: Optional[np.ndarray],
    teacher_oof_npz: Optional[Path],
    teacher_weights: Tuple[float, float, float],
) -> Tuple[np.ndarray, float]:
    """加载或构造多教师 GroupKFold OOF 软概率。"""
    t_oof0 = time.perf_counter()
    if teacher_probs_override is not None and len(teacher_probs_override) == len(clean_y_all):
        teacher_probs_all = np.asarray(teacher_probs_override, dtype=np.float32)
    elif teacher_oof_npz is not None and Path(teacher_oof_npz).exists():
        teacher_probs_all = _load_teacher_npz(Path(teacher_oof_npz), len(clean_y_all), teacher_weights)
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
    return teacher_probs_all, round(time.perf_counter() - t_oof0, 2)


def _load_teacher_npz(
    npz_path: Path,
    expected_len: int,
    teacher_weights: Tuple[float, float, float],
) -> np.ndarray:
    with np.load(npz_path, allow_pickle=False) as tp_npz:
        if "ensemble_oof" in tp_npz and len(tp_npz["ensemble_oof"]) == expected_len:
            return tp_npz["ensemble_oof"].astype(np.float32)
        wa, wb, wc = teacher_weights
        acc = np.zeros(expected_len, dtype=np.float32)
        wsum = 0.0
        for key, w in (("xgb_oof", wa), ("exp_b_oof", wb), ("exp_c_oof", wc)):
            if key in tp_npz and len(tp_npz[key]) == expected_len and w > 0:
                acc += float(w) * tp_npz[key].astype(np.float32)
                wsum += float(w)
        return (acc / max(1e-6, wsum)).astype(np.float32)


def slice_effective_train_data(
    bundle: Dict[str, Any],
    teacher_probs_all: np.ndarray,
) -> Dict[str, Any]:
    """筛选有效训练样本：保留 clean_labels>=0 以及原始嵌合体边界 (-1)。"""
    clean_y_all = bundle["clean_y_all"]
    orig_y_all = bundle["orig_y_all"]
    use_row = (clean_y_all >= 0) | ((clean_y_all == -1) & (orig_y_all == -1))
    has_func = bool(bundle["has_func_data"])
    tr: Dict[str, Any] = {
        "use_row": use_row,
        "codes_tr": bundle["codes_all"][use_row],
        "len_tr": bundle["len_all"][use_row],
        "feats_tr": bundle["feats_all"][use_row],
        "tokens_tr": bundle["tokens_all"][use_row],
        "counts_tr": bundle["counts_all"][use_row],
        "sub_tr": bundle["sub_all"][use_row],
        "y_tr": clean_y_all[use_row],
        "teacher_tr": teacher_probs_all[use_row],
        "sem_t_tr": bundle["sem_t_all"][use_row],
        "sem_v_tr": bundle["sem_v_all"][use_row],
        "sw_tr": bundle["sw_all"][use_row],
        "func_dim": NUM_FUNC_PARTITIONS if has_func else 0,
        "func_t_tr": bundle["func_t_all"][use_row] if (has_func and bundle["func_t_all"] is not None) else None,
        "func_v_tr": bundle["func_v_all"][use_row] if (has_func and bundle["func_v_all"] is not None) else None,
        "orf_ph_t_tr": bundle["orf_ph_t_all"][use_row] if (has_func and bundle["orf_ph_t_all"] is not None) else None,
        "orf_ph_v_tr": bundle["orf_ph_v_all"][use_row] if (has_func and bundle["orf_ph_v_all"] is not None) else None,
        "orf_fn_t_tr": bundle["orf_fn_t_all"][use_row] if (has_func and bundle["orf_fn_t_all"] is not None) else None,
        "orf_fn_v_tr": bundle["orf_fn_v_all"][use_row] if (has_func and bundle["orf_fn_v_all"] is not None) else None,
    }
    for k in ("func_t_all", "func_v_all", "orf_ph_t_all", "orf_ph_v_all", "orf_fn_t_all", "orf_fn_v_all"):
        bundle[k] = None
    return tr


def setup_v4_model_and_optimizer(
    tr: Dict[str, Any],
    device: Any,
    *,
    epochs: int,
    batch_size: int,
    lr: float,
    dna_channels: int,
    orf_d_model: int,
    orf_nhead: int,
    orf_num_layers: int,
    fusion_dim: int,
    use_homoscedastic_loss: bool,
    init_student_ckpt: Optional[Path],
    backbone_lr_scale: float,
) -> Dict[str, Any]:
    """初始化 V4 学生网络、热启动权重、优化器、学习率调度与正类权重张量。"""
    import torch

    feats_tr = tr["feats_tr"]
    y_tr = tr["y_tr"]
    func_dim = int(tr["func_dim"])
    orf_feat_dim = int(tr["tokens_tr"].shape[-1])
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

    param_groups, max_lrs = _build_param_groups(model, mt_loss_fn, warm_started_from, lr, backbone_lr_scale)
    opt = torch.optim.AdamW(param_groups, lr=lr)
    steps_per_ep = max(1, int(np.ceil(len(y_tr) / batch_size)))
    sched = torch.optim.lr_scheduler.OneCycleLR(opt, max_lr=max_lrs, total_steps=max(1, epochs * steps_per_ep))
    scaler = torch.amp.GradScaler("cuda", enabled=device.type == "cuda")

    pos_w = float(np.clip(float(np.sum(y_tr == 0)) / max(1.0, float(np.sum(y_tr == 1))), 0.5, 4.0))
    sem_pos_weight = torch.tensor([1.5, 1.5, 2.0, 1.5], dtype=torch.float32, device=device)
    sem_loss_fn = torch.nn.BCEWithLogitsLoss(pos_weight=sem_pos_weight, reduction="none")
    func_pos_weight_t, orf_ph_pos_w_t = _compute_func_pos_weights(tr, device)

    return {
        "model": model,
        "feat_std": feat_std,
        "orf_feat_dim": orf_feat_dim,
        "warm_started_from": warm_started_from,
        "n_params": n_params,
        "mt_loss_fn": mt_loss_fn,
        "opt": opt,
        "steps_per_ep": steps_per_ep,
        "sched": sched,
        "scaler": scaler,
        "pos_w": pos_w,
        "sem_loss_fn": sem_loss_fn,
        "func_pos_weight_t": func_pos_weight_t,
        "orf_ph_pos_w_t": orf_ph_pos_w_t,
    }


def _build_param_groups(
    model: Any,
    mt_loss_fn: Any,
    warm_started_from: Optional[str],
    lr: float,
    backbone_lr_scale: float,
) -> Tuple[List[Dict[str, Any]], Any]:
    if warm_started_from is not None:
        bb_scale = float(np.clip(backbone_lr_scale, 0.01, 1.0))
        bb_params = [p for n, p in model.named_parameters() if not n.startswith(HEAD_PARAM_PREFIXES)]
        hd_params = [p for n, p in model.named_parameters() if n.startswith(HEAD_PARAM_PREFIXES)]
        param_groups: List[Dict[str, Any]] = [
            {"params": bb_params, "weight_decay": 1e-2, "lr": lr * bb_scale},
            {"params": hd_params, "weight_decay": 1e-2, "lr": lr},
        ]
        max_lrs: Any = [lr * bb_scale, lr]
        if mt_loss_fn is not None:
            param_groups.append({"params": list(mt_loss_fn.parameters()), "weight_decay": 0.0, "lr": lr})
            max_lrs.append(lr)
        return param_groups, max_lrs

    param_groups = [{"params": list(model.parameters()), "weight_decay": 1e-2}]
    if mt_loss_fn is not None:
        param_groups.append({"params": list(mt_loss_fn.parameters()), "weight_decay": 0.0})
    return param_groups, lr


def _compute_func_pos_weights(tr: Dict[str, Any], device: Any) -> Tuple[Any, Any]:
    import torch

    func_dim = int(tr["func_dim"])
    func_t_tr = tr["func_t_tr"]
    func_v_tr = tr["func_v_tr"]
    if func_dim <= 0 or func_t_tr is None or func_v_tr is None:
        return None, None
    fn_pos = np.sum((func_t_tr > 0.5) * func_v_tr, axis=0)
    fn_neg = np.sum((func_t_tr <= 0.5) * func_v_tr, axis=0)
    fn_pw = np.clip(np.sqrt(fn_neg / np.maximum(1.0, fn_pos)), 1.0, 6.0).astype(np.float32)
    func_pos_weight_t = torch.tensor(fn_pw, dtype=torch.float32, device=device)

    orf_ph_pos_w_t = None
    orf_ph_t_tr = tr["orf_ph_t_tr"]
    orf_ph_v_tr = tr["orf_ph_v_tr"]
    if orf_ph_t_tr is not None and orf_ph_v_tr is not None:
        op_pos = float(np.sum((orf_ph_t_tr > 0.5) * orf_ph_v_tr))
        op_neg = float(np.sum((orf_ph_t_tr <= 0.5) * orf_ph_v_tr))
        orf_ph_pos_w_t = torch.tensor(
            [float(np.clip(np.sqrt(op_neg / max(1.0, op_pos)), 1.0, 5.0))],
            dtype=torch.float32,
            device=device,
        )
    logger.info("Stage 1.2 自动客观功能统计 pos_weight=%s", np.round(fn_pw, 2).tolist())
    return func_pos_weight_t, orf_ph_pos_w_t


def _train_one_v4_epoch(
    tr: Dict[str, Any],
    setup: Dict[str, Any],
    device: Any,
    rng: np.random.Generator,
    *,
    batch_size: int,
    max_len: int,
    modality_dropout_prob: float,
    distill_alpha: float,
    sub_weight: float,
    sem_weight: float,
    temperature: float,
    focal_gamma: float,
) -> float:
    import torch
    import torch.nn.functional as F

    model = setup["model"]
    mt_loss_fn = setup["mt_loss_fn"]
    opt = setup["opt"]
    sched = setup["sched"]
    scaler = setup["scaler"]
    steps_per_ep = setup["steps_per_ep"]
    pos_w = setup["pos_w"]
    sem_loss_fn = setup["sem_loss_fn"]
    func_pos_weight_t = setup["func_pos_weight_t"]
    orf_ph_pos_w_t = setup["orf_ph_pos_w_t"]

    func_dim = int(tr["func_dim"])
    y_tr = tr["y_tr"]
    model.train()
    if mt_loss_fn is not None:
        mt_loss_fn.train()

    order = rng.permutation(len(y_tr))
    ep_loss = 0.0
    for bi in range(steps_per_ep):
        idx = order[bi * batch_size : (bi + 1) * batch_size]
        b_codes = tr["codes_tr"][idx].copy()
        b_len = tr["len_tr"][idx]
        b_sub = tr["sub_tr"][idx].copy()
        rc_mask = (b_len == max_len) | (b_sub.min(axis=1) == b_sub.max(axis=1))
        if rng.random() < 0.5 and np.any(rc_mask):
            b_codes[rc_mask] = reverse_complement_codes(b_codes[rc_mask], b_len[rc_mask])
            full_only = rc_mask & (b_len == max_len)
            b_sub[full_only] = b_sub[full_only, ::-1]

        c_t = torch.from_numpy(b_codes.astype(np.int64)).to(device)
        oh = torch.nn.functional.one_hot(c_t, num_classes=5)[..., :4].permute(0, 2, 1).float()
        ln_t = torch.from_numpy(b_len.astype(np.int64)).to(device)
        tb_t = torch.from_numpy(tr["feats_tr"][idx]).to(device)
        tk_t = torch.from_numpy(tr["tokens_tr"][idx]).to(device)
        cn_t = torch.from_numpy(tr["counts_tr"][idx].astype(np.int64)).to(device)

        orf_keep_for_loss = None
        if modality_dropout_prob > 0.0:
            tb_t, tk_t, cn_t, orf_keep_for_loss = _apply_modality_dropout(
                model, tb_t, tk_t, cn_t, len(idx), modality_dropout_prob, rng, device
            )

        yb_raw = y_tr[idx]
        win_valid = torch.from_numpy((yb_raw >= 0).astype(np.float32)).to(device)
        yb = torch.from_numpy(np.maximum(yb_raw, 0).astype(np.float32)).to(device)
        tp = torch.from_numpy(tr["teacher_tr"][idx]).to(device)
        sb = torch.from_numpy(b_sub).to(device)
        st_t = torch.from_numpy(tr["sem_t_tr"][idx]).to(device)
        sv_t = torch.from_numpy(tr["sem_v_tr"][idx]).to(device)
        wb = torch.from_numpy(tr["sw_tr"][idx]).to(device)

        func_tensors = _slice_batch_func_tensors(tr, idx, orf_keep_for_loss, device) if func_dim > 0 else None

        opt.zero_grad(set_to_none=True)
        with torch.autocast(device_type=device.type, dtype=torch.float16, enabled=device.type == "cuda"):
            out_d = model(oh, tb_t, lengths=ln_t, orf_tokens=tk_t, orf_counts=cn_t, return_aux=True)
            l_hard = _focal_bce_with_logits(
                out_d["win_logit"], yb, pos_weight=pos_w, gamma=focal_gamma, valid_mask=win_valid, sample_weight=wb
            )
            l_kd = _kd_bce_loss(
                out_d["win_logit"], tp, temperature=temperature, valid_mask=win_valid, sample_weight=wb
            )
            l_win = (1.0 - distill_alpha) * l_hard + distill_alpha * l_kd
            l_sub = _sub_bce_dice_loss(out_d["sub_logits"], sb, sample_weight=wb)
            sem_elem = sem_loss_fn(out_d["sem_logits"], st_t).mean(dim=1)
            sem_eff = sv_t * wb
            l_sem = (sem_elem * sem_eff).sum() / sem_eff.sum().clamp(min=1e-4)

            func_losses: List[torch.Tensor] = []
            if func_tensors is not None:
                fn_t, fn_v, op_t, op_v, of_t, of_v = func_tensors
                fn_bce = F.binary_cross_entropy_with_logits(
                    out_d["func_logits"].float(), fn_t, pos_weight=func_pos_weight_t, reduction="none"
                )
                fn_eff = fn_v * wb[:, None]
                l_win_func = (fn_bce * fn_eff).sum() / fn_eff.sum().clamp(min=1e-4)

                op_bce = F.binary_cross_entropy_with_logits(
                    out_d["orf_phage_logits"].float(), op_t, pos_weight=orf_ph_pos_w_t[0], reduction="none"
                )
                op_eff = op_v * wb[:, None]
                l_orf_phage = (op_bce * op_eff).sum() / op_eff.sum().clamp(min=1e-4)

                of_bce = F.binary_cross_entropy_with_logits(
                    out_d["orf_func_logits"].float(), of_t, pos_weight=func_pos_weight_t, reduction="none"
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

    return ep_loss


def _apply_modality_dropout(
    model: Any,
    tb_t: Any,
    tk_t: Any,
    cn_t: Any,
    n_batch: int,
    prob: float,
    rng: np.random.Generator,
    device: Any,
) -> Tuple[Any, Any, Any, Any]:
    import torch

    orf_keep_for_loss = None
    m_drop = rng.random(n_batch)
    orf_drop = m_drop < prob
    tab_drop = (m_drop >= prob) & (m_drop < 2.0 * prob)
    if np.any(orf_drop):
        od_t = torch.from_numpy(orf_drop).to(device)
        cn_t = torch.where(od_t, torch.zeros_like(cn_t), cn_t)
        tk_t = torch.where(od_t[:, None, None], torch.zeros_like(tk_t), tk_t)
        orf_keep_for_loss = (~od_t).to(torch.float32)
    if np.any(tab_drop):
        td_t = torch.from_numpy(tab_drop).to(device)
        tb_t = torch.where(td_t[:, None], model.feat_mean.unsqueeze(0).expand_as(tb_t), tb_t)
    return tb_t, tk_t, cn_t, orf_keep_for_loss


def _slice_batch_func_tensors(
    tr: Dict[str, Any],
    idx: np.ndarray,
    orf_keep_for_loss: Any,
    device: Any,
) -> Optional[Tuple[Any, ...]]:
    import torch

    if tr["func_t_tr"] is None:
        return None
    fn_t = torch.from_numpy(tr["func_t_tr"][idx]).to(device)
    fn_v = torch.from_numpy(tr["func_v_tr"][idx]).to(device)
    op_t = torch.from_numpy(tr["orf_ph_t_tr"][idx]).to(device)
    op_v = torch.from_numpy(tr["orf_ph_v_tr"][idx]).to(device)
    of_t = torch.from_numpy(tr["orf_fn_t_tr"][idx]).to(device)
    of_v = torch.from_numpy(tr["orf_fn_v_tr"][idx]).to(device)
    if orf_keep_for_loss is not None:
        op_v = op_v * orf_keep_for_loss[:, None]
        of_v = of_v * orf_keep_for_loss[:, None]
    return fn_t, fn_v, op_t, op_v, of_t, of_v


def run_v4_training_loop(
    tr: Dict[str, Any],
    va_bundle: Dict[str, Any],
    setup: Dict[str, Any],
    ckpt_path: Path,
    device: Any,
    rng: np.random.Generator,
    *,
    epochs: int,
    patience: int,
    batch_size: int,
    max_len: int,
    modality_dropout_prob: float,
    distill_alpha: float,
    sub_weight: float,
    sem_weight: float,
    temperature: float,
    focal_gamma: float,
) -> Dict[str, Any]:
    """执行多轮训练、验证评估、显存回收与原子早停 checkpoint 落盘。"""
    import torch
    from sklearn.metrics import average_precision_score

    model = setup["model"]
    mt_loss_fn = setup["mt_loss_fn"]
    va_keep = va_bundle["va_keep"]
    va_y = va_bundle["va_y"]
    has_two_va = va_bundle["has_two_va"]
    y_tr = tr["y_tr"]

    best_ap = -1.0
    best_ep = -1
    bad_ep = 0
    history: List[Dict[str, Any]] = []
    if device.type == "cuda":
        torch.cuda.reset_peak_memory_stats()

    t0 = time.perf_counter()
    for ep in range(1, epochs + 1):
        ep_loss = _train_one_v4_epoch(
            tr,
            setup,
            device,
            rng,
            batch_size=batch_size,
            max_len=max_len,
            modality_dropout_prob=modality_dropout_prob,
            distill_alpha=distill_alpha,
            sub_weight=sub_weight,
            sem_weight=sem_weight,
            temperature=temperature,
            focal_gamma=focal_gamma,
        )
        va_pred = _predict_v4_all(
            model,
            va_bundle["va_codes"][va_keep],
            va_bundle["va_len"][va_keep],
            va_bundle["va_feats"][va_keep],
            va_bundle["va_tokens"][va_keep],
            va_bundle["va_counts"][va_keep],
            device,
            batch_size=max(64, batch_size),
        )
        ap = float(average_precision_score(va_y[va_keep], va_pred["win_probs"])) if has_two_va else -ep_loss
        avg_loss = ep_loss / max(1, len(y_tr))
        ep_entry: Dict[str, Any] = {
            "epoch": ep,
            "train_loss": round(avg_loss, 5),
            "val_auprc": round(ap, 5),
        }
        if mt_loss_fn is not None:
            with torch.no_grad():
                tw = torch.exp(
                    -torch.clamp(mt_loss_fn.log_vars, mt_loss_fn.min_log_var, mt_loss_fn.max_log_var)
                ).cpu().numpy()
            ep_entry["task_precisions"] = [round(float(x), 4) for x in tw]
            logger.info(
                "StudentV4 epoch %d: loss=%.4f val_auprc=%.4f task_prec=%s",
                ep,
                avg_loss,
                ap,
                ep_entry["task_precisions"],
            )
        else:
            logger.info("StudentV4 epoch %d: loss=%.4f val_auprc=%.4f", ep, avg_loss, ap)
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
    learned_task_weights = (
        history[best_ep - 1].get("task_precisions") if (1 <= best_ep <= len(history)) else None
    )
    return {
        "best_ap": best_ap,
        "best_ep": best_ep,
        "history": history,
        "train_sec": train_sec,
        "peak_mb": peak_mb,
        "learned_task_weights": learned_task_weights,
    }
