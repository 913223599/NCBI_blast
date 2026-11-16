# -*- coding: utf-8 -*-
"""
零泄露 Logit 空间多模型集成、跨模态 DNA/AA 协同融合与按类阈值校准模块。

设计定位：
1. 解决正样本极度不平衡下使用 `pos_weight` 训练导致的各类后验概率标定漂移（固定 `0.5` 阈值下罕见类归零或过召回）；
2. 将双通道概率均值 (`0.5 * (p1 + p2)`) 升级为 Logit 空间按类加权凸组合 + 零泄露验证集拟合的偏置校准，严格保持类内排序单调性 (AUROC/AUPRC 不损失)；
3. 支持可选的 Stage 1.2 DNA 主干信号作为跨模态先验残差注入，强化长程边界与完整度判别。
"""
from __future__ import annotations

from typing import Any, Dict, Optional, Sequence, Tuple

import numpy as np


def probs_to_logits(probs: np.ndarray, eps: float = 1e-6) -> np.ndarray:
    """将 [0, 1] 概率安全逆变换回实数 Logit 空间。"""
    p = np.clip(np.asarray(probs, dtype=np.float64), float(eps), 1.0 - float(eps))
    return np.log(p / (1.0 - p)).astype(np.float32)


def sigmoid_np(logits: np.ndarray) -> np.ndarray:
    """数值稳定的 NumPy Sigmoid。"""
    z = np.clip(np.asarray(logits, dtype=np.float64), -30.0, 30.0)
    return (1.0 / (1.0 + np.exp(-z))).astype(np.float32)


def _compute_binary_f1(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    tp = float(np.sum((y_true == 1) & (y_pred == 1)))
    fp = float(np.sum((y_true == 0) & (y_pred == 1)))
    fn = float(np.sum((y_true == 1) & (y_pred == 0)))
    denom = 2.0 * tp + fp + fn
    return (2.0 * tp / denom) if denom > 0.0 else 0.0


def fit_logit_calibrator_on_val(
    val_func_logits: np.ndarray,
    val_func_targets: np.ndarray,
    val_func_known: np.ndarray,
    val_phage_logits: np.ndarray,
    val_phage_targets: np.ndarray,
    *,
    bias_grid_steps: int = 121,
    max_abs_bias: float = 2.0,
    min_pos_for_tune: int = 10,
    reg_lambda: float = 0.015,
    tune_phage: bool = False,
    core_class_max_pos_bias: float = 0.35,
) -> Dict[str, Any]:
    """
    仅使用零泄露验证集拟合各维度在标准 `prob >= 0.5` (即 `logit - bias >= 0`) 判决点下的最优 Logit 偏置。

    参数:
      val_func_logits: (N, C) 验证集有效已知 ORF 功能 logits
      val_func_targets: (N, C) 0/1 功能真值
      val_func_known: (N,) 0/1 已知掩码 (与训练完全零重合)
      val_phage_logits: (M,) 验证集有效 ORF is_phage logits
      val_phage_targets: (M,) 0/1 is_phage 真值
    返回:
      包含 `func_bias (C,)`, `phage_bias (float)`, `val_func_f1_before/after`, `val_phage_f1_before/after` 的校准器字典。
    """
    f_log = np.asarray(val_func_logits, dtype=np.float64)
    f_tgt = np.asarray(val_func_targets, dtype=np.float64)
    km = np.asarray(val_func_known, dtype=np.float64) > 0.5
    n_cls = f_log.shape[1]

    f_log_k = f_log[km]
    f_tgt_k = (f_tgt[km] > 0.5).astype(np.int32)

    bias_grid = np.linspace(-float(max_abs_bias), float(max_abs_bias), int(bias_grid_steps))
    func_bias = np.zeros(n_cls, dtype=np.float32)
    f1_before = np.zeros(n_cls, dtype=np.float32)
    f1_after = np.zeros(n_cls, dtype=np.float32)

    for ci in range(n_cls):
        yt = f_tgt_k[:, ci]
        if int(np.sum(yt)) < int(min_pos_for_tune) or int(np.sum(1 - yt)) == 0:
            continue
        zc = f_log_k[:, ci]
        base_f1 = _compute_binary_f1(yt, (zc >= 0.0).astype(np.int32))
        f1_before[ci] = float(base_f1)

        best_b = 0.0
        best_obj = base_f1
        best_f1 = base_f1
        # 利用正则约束偏置幅度；对核心结构类 (P0..P4) 限制过大正则偏置，保护区段级结构完整度信号不被压低
        for b in bias_grid:
            if ci < 5 and float(b) > float(core_class_max_pos_bias):
                continue
            f1v = _compute_binary_f1(yt, ((zc - b) >= 0.0).astype(np.int32))
            obj = f1v - float(reg_lambda) * (float(b) ** 2)
            if obj > best_obj + 1e-6:
                best_obj = obj
                best_b = float(b)
                best_f1 = float(f1v)

        func_bias[ci] = float(best_b)
        f1_after[ci] = float(best_f1)

    p_log = np.asarray(val_phage_logits, dtype=np.float64)
    p_tgt = (np.asarray(val_phage_targets, dtype=np.float64) > 0.5).astype(np.int32)
    ph_f1_before = _compute_binary_f1(p_tgt, (p_log >= 0.0).astype(np.int32))
    best_ph_b = 0.0
    best_ph_f1 = ph_f1_before
    if tune_phage and len(p_tgt) > 0 and 0 < int(np.sum(p_tgt)) < len(p_tgt):
        best_ph_obj = ph_f1_before
        for b in bias_grid:
            # 禁止负偏置下调 is_phage 门槛，防止宿主防御岛误判率飙升
            if float(b) < 0.0:
                continue
            f1v = _compute_binary_f1(p_tgt, ((p_log - b) >= 0.0).astype(np.int32))
            obj = f1v - float(reg_lambda) * (float(b) ** 2)
            if obj > best_ph_obj + 1e-6:
                best_ph_obj = obj
                best_ph_b = float(b)
                best_ph_f1 = float(f1v)

    return {
        "func_bias": func_bias,
        "phage_bias": float(best_ph_b),
        "val_func_f1_before": f1_before,
        "val_func_f1_after": f1_after,
        "val_phage_f1_before": float(ph_f1_before),
        "val_phage_f1_after": float(best_ph_f1),
    }


def apply_logit_calibration(
    func_logits: np.ndarray,
    phage_logits: np.ndarray,
    calibrator: Optional[Dict[str, Any]],
) -> Tuple[np.ndarray, np.ndarray]:
    """将拟合好的按类 Logit 偏置校准器应用于原始 logits，返回校准后概率 (func_probs, phage_probs)。"""
    f_z = np.asarray(func_logits, dtype=np.float32)
    p_z = np.asarray(phage_logits, dtype=np.float32)
    if calibrator is None:
        return sigmoid_np(f_z), sigmoid_np(p_z)

    f_bias = np.asarray(calibrator.get("func_bias", np.zeros(f_z.shape[-1], dtype=np.float32)), dtype=np.float32)
    p_bias = float(calibrator.get("phage_bias", 0.0))
    return sigmoid_np(f_z - f_bias[None, :]), sigmoid_np(p_z - p_bias)


def fit_logit_blend_and_calibrator(
    val_stat_func_logits: np.ndarray,
    val_seq_func_logits: np.ndarray,
    val_func_targets: np.ndarray,
    val_func_known: np.ndarray,
    val_stat_phage_logits: np.ndarray,
    val_seq_phage_logits: np.ndarray,
    val_phage_targets: np.ndarray,
    *,
    alpha_candidates: Sequence[float] = (0.3, 0.4, 0.5, 0.6, 0.7),
) -> Dict[str, Any]:
    """
    在零泄露验证集上为每个功能类与 is_phage 选择最优 Logit 融合权重 (w * seq + (1 - w) * stat)
    并随后拟合按类校准偏置。
    """
    from sklearn.metrics import average_precision_score

    sf = np.asarray(val_stat_func_logits, dtype=np.float64)
    qf = np.asarray(val_seq_func_logits, dtype=np.float64)
    yt = (np.asarray(val_func_targets, dtype=np.float64) > 0.5).astype(np.int32)
    km = np.asarray(val_func_known, dtype=np.float64) > 0.5
    n_cls = sf.shape[1]

    func_alphas = np.full(n_cls, 0.5, dtype=np.float32)
    sf_k, qf_k, yt_k = sf[km], qf[km], yt[km]
    for ci in range(n_cls):
        y_c = yt_k[:, ci]
        if int(np.sum(y_c)) < 10 or int(np.sum(1 - y_c)) == 0:
            continue
        best_a = 0.5
        best_ap = -1.0
        for a in alpha_candidates:
            blend_c = float(a) * qf_k[:, ci] + (1.0 - float(a)) * sf_k[:, ci]
            ap = float(average_precision_score(y_c, blend_c))
            if ap > best_ap + 1e-6:
                best_ap = ap
                best_a = float(a)
        func_alphas[ci] = float(best_a)

    sp = np.asarray(val_stat_phage_logits, dtype=np.float64)
    qp = np.asarray(val_seq_phage_logits, dtype=np.float64)
    pt = (np.asarray(val_phage_targets, dtype=np.float64) > 0.5).astype(np.int32)
    best_ph_a = 0.5
    best_ph_ap = -1.0
    if len(pt) > 0 and 0 < int(np.sum(pt)) < len(pt):
        for a in alpha_candidates:
            blend_p = float(a) * qp + (1.0 - float(a)) * sp
            ap = float(average_precision_score(pt, blend_p))
            if ap > best_ph_ap + 1e-6:
                best_ph_ap = ap
                best_ph_a = float(a)

    blended_f = qf * func_alphas[None, :] + sf * (1.0 - func_alphas[None, :])
    blended_p = qp * best_ph_a + sp * (1.0 - best_ph_a)

    cal = fit_logit_calibrator_on_val(
        blended_f,
        val_func_targets,
        val_func_known,
        blended_p,
        val_phage_targets,
    )
    cal["func_alphas"] = func_alphas
    cal["phage_alpha"] = float(best_ph_a)
    return cal


def apply_blended_logit_calibration(
    stat_func_logits: np.ndarray,
    seq_func_logits: np.ndarray,
    stat_phage_logits: np.ndarray,
    seq_phage_logits: np.ndarray,
    calibrator: Optional[Dict[str, Any]] = None,
) -> Tuple[np.ndarray, np.ndarray]:
    """根据校准器中的 Logit 权重合并 Stat-Only 与 AA-Seq，再应用按类 Logit 偏置输出概率。"""
    sf = np.asarray(stat_func_logits, dtype=np.float32)
    qf = np.asarray(seq_func_logits, dtype=np.float32)
    sp = np.asarray(stat_phage_logits, dtype=np.float32)
    qp = np.asarray(seq_phage_logits, dtype=np.float32)

    if calibrator is None:
        return sigmoid_np(0.5 * (sf + qf)), sigmoid_np(0.5 * (sp + qp))

    f_alpha = np.asarray(calibrator.get("func_alphas", np.full(sf.shape[-1], 0.5, dtype=np.float32)), dtype=np.float32)
    p_alpha = float(calibrator.get("phage_alpha", 0.5))

    blended_f = qf * f_alpha[None, :] + sf * (1.0 - f_alpha[None, :])
    blended_p = qp * p_alpha + sp * (1.0 - p_alpha)
    return apply_logit_calibration(blended_f, blended_p, calibrator)


def blend_with_stage1_2_cross_modal(
    judge_func10_probs: np.ndarray,
    judge_phage_probs: np.ndarray,
    s12_func9_probs: np.ndarray,
    s12_phage_probs: np.ndarray,
    *,
    s12_phage_weight: float = 0.25,
    s12_func_weight: float = 0.20,
) -> Tuple[np.ndarray, np.ndarray]:
    """
    在 Logit 空间将前置 DNA 滑窗主干 (Stage 1.2) 的跨模态边界信号轻度融入精判 Judge 概率：
      - DNA 主干擅长长程编码密度/GC偏移/完整片段边界识别；
      - Judge 擅长高精功能分区 (P0..P8) 与宿主防御 P9 排雷 (P9 仅由 Judge 主导，不让未知 P9 的 Stage 1.2 稀释)。
    """
    jf = probs_to_logits(judge_func10_probs)
    jp = probs_to_logits(judge_phage_probs)
    sf9 = probs_to_logits(s12_func9_probs)
    sp = probs_to_logits(s12_phage_probs)

    fused_f_logits = jf.copy()
    w_f = float(np.clip(s12_func_weight, 0.0, 0.9))
    fused_f_logits[:, :9] = (1.0 - w_f) * jf[:, :9] + w_f * sf9[:, :9]

    w_p = float(np.clip(s12_phage_weight, 0.0, 0.9))
    fused_p_logits = (1.0 - w_p) * jp + w_p * sp

    return sigmoid_np(fused_f_logits), sigmoid_np(fused_p_logits)

