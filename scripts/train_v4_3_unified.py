# -*- coding: utf-8 -*-
"""
UnifiedJudge V4.3 联合优化训练与校准脚本（DualSkip + 可控顶层解冻 + Tailocin/质粒硬负感知）：

设计亮点：
1. 严格从生产 R3/Unified 权重热启动，仅温和解冻顶层操纵子注意力 ctx_blocks[-1] + macro_fuse +
   双分化头（Head A 分区鉴伪 / TailocinGuard 风险抑制头 / Head B DualSkip 完整度头），锁定底层 1-mer 基序防止遗忘；
2. 联合 R3 冻结教师 KL/Logit 防遗忘锚定 + R2 教师完整度无平滑蒸馏 + 硬负样本 (Tailocin/质粒/古菌病毒/ICE) 专项负监督；
3. 同步微调 statonly 对照支路，并在零泄露 val 上重拟 V4.3 双流 logit_calibrator.npz；
4. 所有实验权重输出至独立沙盒目录 models/full_v4_3_exp/orf_judge_unified，待全套四重门禁验收后再替换生产。
"""
from __future__ import annotations

import argparse
import gc
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, Tuple

import numpy as np
import torch
from sklearn.metrics import roc_auc_score
from torch import nn
from torch.utils.data import DataLoader, Subset, TensorDataset

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.run_orf_judge_ablation import _compute_multilabel_metrics  # noqa: E402
from src.phage_discovery.student.judge_calibration import (  # noqa: E402
    fit_logit_blend_and_calibrator,
)
from src.phage_discovery.student.orf_functional_judge import (  # noqa: E402
    CTX_WIN_ORFS,
    NUM_JUDGE_CLASSES,
    build_orf_functional_judge,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("train_v4_3_unified")


def _clear_cuda() -> None:
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()


def _build_balanced_train_indices(tr_hk: np.ndarray) -> np.ndarray:
    """构造均衡重采样索引：剔除易误伤丝状噬菌体的古菌病毒(3)，对稀疏 Tailocin(1) 12x、ICE(4) 6x 过采样。"""
    hk = np.asarray(tr_hk, dtype=np.int64)
    base_idx = np.where((hk == 0) | (hk == 2))[0]
    tc_idx = np.where(hk == 1)[0]
    ice_idx = np.where(hk == 4)[0]
    parts = [base_idx]
    if len(tc_idx) > 0:
        parts.append(np.tile(tc_idx, 12))
    if len(ice_idx) > 0:
        parts.append(np.tile(ice_idx, 6))
    return np.concatenate(parts, axis=0)


def _extract_teacher_anchors(
    ckpt_path: Path,
    ids_arr: np.ndarray,
    lens_arr: np.ndarray,
    stat_arr: np.ndarray,
    vc_arr: np.ndarray,
    *,
    arch_override: str | None = None,
    device: torch.device,
    batch_size: int = 32,
) -> Tuple[np.ndarray, np.ndarray]:
    """抽取教师模型的 func10_logits 与 phage_logits float16 缓存（严控显存并用后立即清库）。"""
    ck = torch.load(ckpt_path, map_location="cpu", weights_only=False)
    model = build_orf_functional_judge(
        stat_mean=ck["stat_mean"],
        stat_std=ck["stat_std"],
        use_aa_seq=bool(ck["use_aa_seq"]),
        arch=str(arch_override or ck.get("arch", "r3")),
    ).to(device)
    model.load_state_dict(ck["state_dict"], strict=True)
    model.eval()

    ds = TensorDataset(
        torch.from_numpy(ids_arr),
        torch.from_numpy(lens_arr),
        torch.from_numpy(stat_arr),
        torch.from_numpy(vc_arr),
    )
    loader = DataLoader(ds, batch_size=batch_size, shuffle=False)
    f_chunks, p_chunks = [], []
    with torch.no_grad():
        for ids, lens, st, vc in loader:
            ids = ids.to(device, dtype=torch.long)
            lens = lens.to(device, dtype=torch.long)
            st = st.to(device, dtype=torch.float32)
            vc = vc.to(device, dtype=torch.long)
            with torch.amp.autocast("cuda", enabled=(device.type == "cuda"), dtype=torch.bfloat16):
                f_log, p_log = model(ids, lens, st, vc)
            f_chunks.append(f_log.to(torch.float16).cpu().numpy())
            p_chunks.append(p_log.to(torch.float16).cpu().numpy())
    del model, ck
    _clear_cuda()
    return np.concatenate(f_chunks, axis=0), np.concatenate(p_chunks, axis=0)


def _train_statonly_v4_3(
    ds: Any,
    init_stat_ckpt: Path,
    out_stat_ckpt: Path,
    *,
    device: torch.device,
    epochs: int = 8,
    batch_size: int = 128,
    lr: float = 1e-4,
) -> None:
    """用包含 V4.3 硬负样本的新数据集温和热启动微调 statonly 模型（带原权重教师防遗忘锚定）。"""
    ck = torch.load(init_stat_ckpt, map_location="cpu", weights_only=False)
    m_stat = build_orf_functional_judge(
        stat_mean=ds["stat_mean"],
        stat_std=ds["stat_std"],
        use_aa_seq=False,
        arch=str(ck.get("arch", "r3")),
    ).to(device)
    m_stat.load_state_dict(ck["state_dict"], strict=True)

    # 先从冻结原 statonly 抽出基座教师锚点，防止 Sakai Sp17 等边缘灰区样本分数漂移
    m_teacher = build_orf_functional_judge(
        stat_mean=ck["stat_mean"],
        stat_std=ck["stat_std"],
        use_aa_seq=False,
        arch=str(ck.get("arch", "r3")),
    ).to(device)
    m_teacher.load_state_dict(ck["state_dict"], strict=True)
    m_teacher.eval()
    for p in m_teacher.parameters():
        p.requires_grad_(False)

    tr_vc = ds["tr_vc"]
    tr_vm = np.arange(CTX_WIN_ORFS)[None, :] < tr_vc[:, None]
    tr_km = tr_vm & (ds["tr_kn"] > 0.5)
    y10_valid = ds["tr_y10"][tr_km]
    pos_cnt = np.maximum(np.sum(y10_valid > 0.5, axis=0), 1.0)
    neg_cnt = np.maximum(len(y10_valid) - pos_cnt, 1.0)
    pw_10 = torch.tensor(np.clip(np.sqrt(neg_cnt / pos_cnt), 1.0, 6.0).astype(np.float32), device=device)

    tr_ds = TensorDataset(
        torch.from_numpy(ds["tr_ids"]),
        torch.from_numpy(ds["tr_lens"]),
        torch.from_numpy(ds["tr_stat"]),
        torch.from_numpy(ds["tr_vc"]),
        torch.from_numpy(ds["tr_y10"]),
        torch.from_numpy(ds["tr_ph"]),
        torch.from_numpy(ds["tr_kn"]),
        torch.from_numpy(ds["tr_hard_kind"]),
    )
    bal_idx = _build_balanced_train_indices(ds["tr_hard_kind"])
    tr_loader = DataLoader(Subset(tr_ds, bal_idx.tolist()), batch_size=batch_size, shuffle=True)
    va_ds = TensorDataset(
        torch.from_numpy(ds["va_ids"]),
        torch.from_numpy(ds["va_lens"]),
        torch.from_numpy(ds["va_stat"]),
        torch.from_numpy(ds["va_vc"]),
        torch.from_numpy(ds["va_y10"]),
        torch.from_numpy(ds["va_ph"]),
        torch.from_numpy(ds["va_kn"]),
        torch.from_numpy(ds["va_unseen"]),
    )
    va_loader = DataLoader(va_ds, batch_size=batch_size, shuffle=False)

    opt = torch.optim.AdamW(m_stat.parameters(), lr=lr, weight_decay=2e-4)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=max(1, epochs))
    bce_f = nn.BCEWithLogitsLoss(reduction="none", pos_weight=pw_10)
    bce_p = nn.BCEWithLogitsLoss(reduction="none")

    best_sc = -1.0
    best_sd: Dict[str, torch.Tensor] = {}
    for ep in range(1, epochs + 1):
        m_stat.train()
        for ids, lens, st, vc, y10, ph, kn, hk in tr_loader:
            ids = ids.to(device, dtype=torch.long)
            lens = lens.to(device, dtype=torch.long)
            st = st.to(device, dtype=torch.float32)
            vc = vc.to(device, dtype=torch.long)
            y10 = y10.to(device, dtype=torch.float32)
            ph = ph.to(device, dtype=torch.float32)
            kn = kn.to(device, dtype=torch.float32)
            hk = hk.to(device, dtype=torch.long)

            with torch.no_grad():
                tf_log, tp_log = m_teacher(ids, lens, st, vc)

            f_log, p_log = m_stat(ids, lens, st, vc)
            pos = torch.arange(CTX_WIN_ORFS, device=device)[None, :]
            vm = (pos < vc[:, None]).to(torch.float32)
            km = (vm * kn).unsqueeze(-1)
            is_base_m = vm * (hk == 0).unsqueeze(-1).to(torch.float32)

            hard_w = torch.ones_like(hk, dtype=torch.float32)
            hard_w = torch.where(hk == 1, 2.0, hard_w)
            hard_w = torch.where((hk == 2) | (hk == 4), 1.5, hard_w)
            hard_w = hard_w.unsqueeze(-1)

            lf = (bce_f(f_log, y10) * km).sum() / km.sum().clamp(min=1.0) / float(NUM_JUDGE_CLASSES)
            lp = (bce_p(p_log, ph) * vm * hard_w).sum() / (vm * hard_w).sum().clamp(min=1.0)
            l_kd_f = (
                (nn.functional.mse_loss(f_log, tf_log, reduction="none") * is_base_m.unsqueeze(-1)).sum()
                / is_base_m.sum().clamp(min=1.0)
                / float(NUM_JUDGE_CLASSES)
            )
            l_kd_p = (nn.functional.mse_loss(p_log, tp_log, reduction="none") * is_base_m).sum() / is_base_m.sum().clamp(min=1.0)
            loss = 1.0 * lf + 1.0 * lp + 0.45 * l_kd_f + 0.65 * l_kd_p
            opt.zero_grad(set_to_none=True)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(m_stat.parameters(), 2.0)
            opt.step()
        sched.step()

        m_stat.eval()
        all_yt, all_yp, all_km, all_pt, all_pp, all_vm = [], [], [], [], [], []
        with torch.no_grad():
            for ids, lens, st, vc, y10, ph, kn, unseen in va_loader:
                t_id = ids.to(device, dtype=torch.long)
                t_ln = lens.to(device, dtype=torch.long)
                t_st = st.to(device, dtype=torch.float32)
                t_vc = vc.to(device, dtype=torch.long)
                f_log, p_log = m_stat(t_id, t_ln, t_st, t_vc)
                pos = torch.arange(CTX_WIN_ORFS, device=device)[None, :]
                vm = (pos < t_vc[:, None]).cpu().numpy() & (unseen.numpy() > 0.5)
                km = vm & (kn.numpy() > 0.5)
                all_yt.append(y10.numpy())
                all_yp.append(torch.sigmoid(f_log).cpu().numpy())
                all_km.append(km.astype(np.float32))
                all_pt.append(ph.numpy())
                all_pp.append(torch.sigmoid(p_log).cpu().numpy())
                all_vm.append(vm.astype(np.float32))
        yt_c = np.concatenate(all_yt)
        yp_c = np.concatenate(all_yp)
        km_c = np.concatenate(all_km)
        pt_c = np.concatenate(all_pt)
        pp_c = np.concatenate(all_pp)
        vm_b = np.concatenate(all_vm) > 0.5
        mf = _compute_multilabel_metrics(yt_c, yp_c, km_c)
        au = float(roc_auc_score((pt_c[vm_b] > 0.5).astype(np.int32), pp_c[vm_b]))
        sc = mf["macro_f1_p08"] + 0.5 * au
        if sc > best_sc:
            best_sc = sc
            best_sd = {k: v.detach().cpu().clone() for k, v in m_stat.state_dict().items()}
    logger.info("[statonly V4.3] best val score=%.4f -> %s", best_sc, out_stat_ckpt)
    tmp_p = out_stat_ckpt.with_name(f".{out_stat_ckpt.stem}.tmp.pt")
    torch.save(
        {
            "state_dict": best_sd,
            "stat_mean": ds["stat_mean"],
            "stat_std": ds["stat_std"],
            "use_aa_seq": False,
            "arch": str(ck.get("arch", "r3")),
            "params": sum(p.numel() for p in m_stat.parameters()),
        },
        tmp_p,
    )
    tmp_p.replace(out_stat_ckpt)
    del m_stat, m_teacher, ck
    _clear_cuda()


def train_unified_v4_3(
    pd_root: Path,
    *,
    epochs: int = 12,
    batch_size: int = 32,
    grad_accum: int = 4,
    head_lr: float = 4e-4,
    top_ctx_lr: float = 8e-5,
    reuse_stat: bool = False,
) -> Path:
    t0 = time.perf_counter()
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    ds_path = pd_root / "training" / "orf_judge_v4_3" / "judge_dataset_v4_3.npz"
    if not ds_path.is_file():
        raise FileNotFoundError(f"找不到 V4.3 训练数据集: {ds_path}")
    ds = np.load(ds_path, allow_pickle=False)

    models_v4 = pd_root / "models" / "full_v4"
    r2_ckpt = models_v4 / "orf_judge_ablation_r2" / "orf_judge_seq.pt"
    uni_ckpt = models_v4 / "orf_judge_unified" / "unified_judge_seq.pt"
    init_stat_ckpt = models_v4 / "orf_judge_unified" / "orf_judge_statonly.pt"

    out_root = pd_root / "models" / "full_v4_3_exp" / "orf_judge_unified"
    out_root.mkdir(parents=True, exist_ok=True)

    # 1. 微调并保存 V4.3 statonly 模型（默认执行带教师锚定的温和微调）
    out_stat_ckpt = out_root / "orf_judge_statonly.pt"
    if reuse_stat and out_stat_ckpt.is_file():
        logger.info("复用已存在的 V4.3 statonly 权重 %s", out_stat_ckpt)
    else:
        _train_statonly_v4_3(ds, init_stat_ckpt, out_stat_ckpt, device=device, epochs=8, lr=1e-4)

    # 2. 提取教师防遗忘锚点 (R3 现役底座保真 + R2 完整度教师)，分片缓存防止重抽
    anchor_cache = pd_root / "training" / "orf_judge_v4_3" / "teacher_anchors_f16.npz"
    if not anchor_cache.is_file():
        logger.info("抽取现役 Unified Head A 防遗忘教师锚点 (tr/va)...")
        tr_r3_f, tr_r3_p = _extract_teacher_anchors(
            uni_ckpt, ds["tr_ids"], ds["tr_lens"], ds["tr_stat"], ds["tr_vc"], arch_override="unified", device=device, batch_size=32
        )
        va_r3_f, _ = _extract_teacher_anchors(
            uni_ckpt, ds["va_ids"], ds["va_lens"], ds["va_stat"], ds["va_vc"], arch_override="unified", device=device, batch_size=32
        )
        logger.info("抽取 R2 教师完整度无平滑锚点...")
        tr_r2_f, _ = _extract_teacher_anchors(
            r2_ckpt, ds["tr_ids"], ds["tr_lens"], ds["tr_stat"], ds["tr_vc"], device=device, batch_size=32
        )
        np.savez(anchor_cache, tr_r3_f=tr_r3_f, tr_r3_p=tr_r3_p, va_r3_f=va_r3_f, tr_r2_f=tr_r2_f)
    else:
        logger.info("复用已缓存教师锚点 %s", anchor_cache)
        ac = np.load(anchor_cache, allow_pickle=False)
        tr_r3_f, tr_r3_p, va_r3_f, tr_r2_f = ac["tr_r3_f"], ac["tr_r3_p"], ac["va_r3_f"], ac["tr_r2_f"]

    # 3. 初始化 UnifiedJudge V4.3 并热启动全部重合参数
    ck_uni = torch.load(uni_ckpt, map_location="cpu", weights_only=False)
    model = build_orf_functional_judge(
        stat_mean=ds["stat_mean"],
        stat_std=ds["stat_std"],
        use_aa_seq=True,
        arch="unified_v4_3",
        aa_mask_prob=0.10,
    ).to(device)
    sd_new = model.state_dict()
    for k, v in ck_uni["state_dict"].items():
        if k in sd_new and sd_new[k].shape == v.shape:
            sd_new[k] = v.clone()
    model.load_state_dict(sd_new, strict=True)

    # 参数分组控制：严格冻结 seq_enc / stat_enc / orf_fuse / ctx_blocks[0..1]，
    # 仅温和解冻 ctx_blocks[2] 与全部专家输出头
    for p in model.parameters():
        p.requires_grad_(False)

    top_ctx_params = []
    head_params = []
    for name, p in model.named_parameters():
        if name.startswith("ctx_blocks.2."):
            p.requires_grad_(True)
            top_ctx_params.append(p)
        elif any(
            name.startswith(prefix)
            for prefix in (
                "macro_",
                "win_core_head.",
                "func10_head.",
                "phage_head.",
                "gamma_",
                "intact_dualskip_proj.",
                "intact_func_head.",
                "tailocin_guard_head.",
            )
        ):
            p.requires_grad_(True)
            head_params.append(p)

    trainable_cnt = sum(p.numel() for p in model.parameters() if p.requires_grad)
    total_cnt = sum(p.numel() for p in model.parameters())
    logger.info("Unified V4.3 可训练参数: %d / %d (%.1f%%)", trainable_cnt, total_cnt, 100.0 * trainable_cnt / total_cnt)

    tr_vc = ds["tr_vc"]
    tr_vm = np.arange(CTX_WIN_ORFS)[None, :] < tr_vc[:, None]
    tr_km = tr_vm & (ds["tr_kn"] > 0.5)
    y10_valid = ds["tr_y10"][tr_km]
    pos_cnt = np.maximum(np.sum(y10_valid > 0.5, axis=0), 1.0)
    neg_cnt = np.maximum(len(y10_valid) - pos_cnt, 1.0)
    pw_10 = torch.tensor(np.clip(np.sqrt(neg_cnt / pos_cnt), 1.0, 6.0).astype(np.float32), device=device)

    tr_ds = TensorDataset(
        torch.from_numpy(ds["tr_ids"]),
        torch.from_numpy(ds["tr_lens"]),
        torch.from_numpy(ds["tr_stat"]),
        torch.from_numpy(ds["tr_vc"]),
        torch.from_numpy(ds["tr_y10"]),
        torch.from_numpy(ds["tr_ph"]),
        torch.from_numpy(ds["tr_kn"]),
        torch.from_numpy(ds["tr_hard_kind"]),
        torch.from_numpy(tr_r3_f),
        torch.from_numpy(tr_r2_f),
    )
    va_ds = TensorDataset(
        torch.from_numpy(ds["va_ids"]),
        torch.from_numpy(ds["va_lens"]),
        torch.from_numpy(ds["va_stat"]),
        torch.from_numpy(ds["va_vc"]),
        torch.from_numpy(ds["va_y10"]),
        torch.from_numpy(ds["va_ph"]),
        torch.from_numpy(ds["va_kn"]),
        torch.from_numpy(ds["va_unseen"]),
    )
    has_hard_va = len(ds["hard_va_vc"]) > 0
    if has_hard_va:
        hva_ds = TensorDataset(
            torch.from_numpy(ds["hard_va_ids"]),
            torch.from_numpy(ds["hard_va_lens"]),
            torch.from_numpy(ds["hard_va_stat"]),
            torch.from_numpy(ds["hard_va_vc"]),
            torch.from_numpy(ds["hard_va_hk"]),
        )
        hva_loader = DataLoader(hva_ds, batch_size=64, shuffle=False)
    else:
        hva_loader = None

    bal_tr_idx = _build_balanced_train_indices(ds["tr_hard_kind"])
    tr_loader = DataLoader(
        Subset(tr_ds, bal_tr_idx.tolist()),
        batch_size=batch_size,
        shuffle=True,
        pin_memory=(device.type == "cuda"),
    )
    va_loader = DataLoader(va_ds, batch_size=64, shuffle=False, pin_memory=(device.type == "cuda"))

    opt = torch.optim.AdamW(
        [
            {"params": top_ctx_params, "lr": top_ctx_lr},
            {"params": head_params, "lr": head_lr},
        ],
        weight_decay=3e-4,
    )
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=max(1, epochs))
    bce_10 = nn.BCEWithLogitsLoss(reduction="none", pos_weight=pw_10)
    bce_bin = nn.BCEWithLogitsLoss(reduction="none")
    scaler = torch.amp.GradScaler("cuda", enabled=(device.type == "cuda"))

    best_score = -1e9
    best_sd: Dict[str, torch.Tensor] = {}
    best_metrics: Dict[str, Any] = {}

    for ep in range(1, epochs + 1):
        model.train()
        ep_loss = 0.0
        n_steps = 0
        opt.zero_grad(set_to_none=True)

        for step_idx, (ids, lens, st, vc, y10, ph, kn, hk, r3_f, r2_f) in enumerate(tr_loader):
            ids = ids.to(device, dtype=torch.long, non_blocking=True)
            lens = lens.to(device, dtype=torch.long, non_blocking=True)
            st = st.to(device, dtype=torch.float32, non_blocking=True)
            vc = vc.to(device, dtype=torch.long, non_blocking=True)
            y10 = y10.to(device, dtype=torch.float32, non_blocking=True)
            ph = ph.to(device, dtype=torch.float32, non_blocking=True)
            kn = kn.to(device, dtype=torch.float32, non_blocking=True)
            hk = hk.to(device, dtype=torch.long, non_blocking=True)
            r3_f = r3_f.to(device, dtype=torch.float32, non_blocking=True)
            r2_f = r2_f.to(device, dtype=torch.float32, non_blocking=True)

            with torch.amp.autocast("cuda", enabled=(device.type == "cuda"), dtype=torch.bfloat16):
                exp = model(ids, lens, st, vc, return_experts=True)
                f_log = exp["func10_logits"]
                p_log = exp["phage_logits"]
                in_log = exp["intact_func_logits"]
                wc_log = exp["win_core_logit"]
                tc_log = exp["tailocin_neg_logit"]

                pos = torch.arange(CTX_WIN_ORFS, device=device)[None, :]
                vm = (pos < vc[:, None]).to(torch.float32)
                km = (vm * kn).unsqueeze(-1)
                is_base_2d = (hk == 0).unsqueeze(-1).to(torch.float32)
                is_base_3d = is_base_2d.unsqueeze(-1)

                # 1. Head A (10 类功能分区): 真实监督 + 在基础样本上防遗忘对齐 R3 教师 logits
                l_f_sup = (bce_10(f_log, y10) * km).sum() / km.sum().clamp(min=1.0) / float(NUM_JUDGE_CLASSES)
                base_m = vm.unsqueeze(-1) * is_base_3d
                l_f_kd = (
                    nn.functional.mse_loss(f_log, r3_f, reduction="none") * base_m
                ).sum() / base_m.sum().clamp(min=1.0) / float(NUM_JUDGE_CLASSES)

                # 2. Phage Head: 配合 12x Tailocin / 6x ICE 均衡采样，温和聚焦各硬负子类
                hk_w = torch.ones_like(hk, dtype=torch.float32)
                hk_w = torch.where(hk == 1, 2.0, hk_w)
                hk_w = torch.where((hk == 2) | (hk == 4), 1.5, hk_w)
                ph_w = vm * hk_w.unsqueeze(-1)
                l_ph = (bce_bin(p_log, ph) * ph_w).sum() / ph_w.sum().clamp(min=1.0)

                # 3. 互斥惩罚: DefenseFinder P9 与噬菌体置信度严格互斥
                p9_prob = torch.sigmoid(f_log[:, :, 9])
                ph_prob = torch.sigmoid(p_log)
                adv_mask = vm * kn * (y10[:, :, 9] > 0.5).to(torch.float32) * (ph < 0.5).to(torch.float32)
                l_mutex = 0.0
                if torch.any(adv_mask > 0):
                    l_mutex = (torch.relu(ph_prob + p9_prob - 0.90).pow(2) * adv_mask).sum() / adv_mask.sum().clamp(min=1.0)

                # 4. Tailocin 窗口风险头: 严格仅以真实噬菌体正窗 (0) vs Tailocin 窗 (hk==1 -> 1) 对照训练，
                #    不再混入短质粒片段，防止误击短尾部噬菌体碎片 (如 LT2 STM2234)
                win_has_phage = (ph * vm).max(dim=1).values > 0.5
                win_is_tailocin = hk == 1
                tc_mask = win_has_phage | win_is_tailocin
                l_tc = 0.0
                if torch.any(tc_mask):
                    tc_tgt = win_is_tailocin[tc_mask].to(torch.float32)
                    tc_wt = torch.where(win_is_tailocin[tc_mask], 4.0, 1.0)
                    l_tc = (nn.functional.binary_cross_entropy_with_logits(tc_log[tc_mask], tc_tgt, reduction="none") * tc_wt).mean()

                # 5. DualSkip Head B (intact_func_head): 真实核心监督 + R2 无平滑教师蒸馏 (基础窗口)
                l_b_sup = (bce_10(in_log, y10) * km).sum() / km.sum().clamp(min=1.0) / float(NUM_JUDGE_CLASSES)
                l_b_kd = (
                    nn.functional.mse_loss(in_log, r2_f, reduction="none") * base_m
                ).sum() / base_m.sum().clamp(min=1.0) / float(NUM_JUDGE_CLASSES)
                p_core = torch.sigmoid(in_log[:, :, :5]).masked_fill(~(pos < vc[:, None]).unsqueeze(-1), 0.0).max(dim=1).values
                t_core = torch.sigmoid(r2_f[:, :, :5]).masked_fill(~(pos < vc[:, None]).unsqueeze(-1), 0.0).max(dim=1).values
                l_b_wm = nn.functional.smooth_l1_loss(p_core * is_base_2d, t_core * is_base_2d)

                # 6. 窗级完整度回归 (win_core_head)
                core_rich = ((y10[:, :, :5] > 0.5).to(torch.float32) * km).max(dim=1).values.mean(dim=-1)
                has_k = (vm * kn).sum(dim=1) > 0.5
                l_wc = nn.functional.smooth_l1_loss(torch.sigmoid(wc_log[has_k]), core_rich[has_k]) if torch.any(has_k) else 0.0

                loss = (
                    1.2 * l_f_sup
                    + 0.35 * l_f_kd
                    + 1.3 * l_ph
                    + 0.65 * l_mutex
                    + 0.85 * l_tc
                    + 0.4 * l_wc
                    + 0.6 * l_b_sup
                    + 0.7 * l_b_kd
                    + 1.1 * l_b_wm
                )

            scaled_loss = scaler.scale(loss / float(grad_accum))
            assert isinstance(scaled_loss, torch.Tensor)
            scaled_loss.backward()
            if (step_idx + 1) % grad_accum == 0 or (step_idx + 1) == len(tr_loader):
                scaler.unscale_(opt)
                torch.nn.utils.clip_grad_norm_(model.parameters(), 2.0)
                scaler.step(opt)
                scaler.update()
                opt.zero_grad(set_to_none=True)

            ep_loss += float(loss.item())
            n_steps += 1
        sched.step()

        # 双验证评估：原 5,325 零泄露验证 + 新增 hard_va 特异性压制验证
        model.eval()
        all_yt, all_yp, all_km, all_pt, all_pp, all_vm = [], [], [], [], [], []
        with torch.no_grad():
            for ids, lens, st, vc, y10, ph, kn, unseen in va_loader:
                ids = ids.to(device, dtype=torch.long)
                lens = lens.to(device, dtype=torch.long)
                st = st.to(device, dtype=torch.float32)
                vc = vc.to(device, dtype=torch.long)
                with torch.amp.autocast("cuda", enabled=(device.type == "cuda"), dtype=torch.bfloat16):
                    f_log, p_log = model(ids, lens, st, vc)
                pos = torch.arange(CTX_WIN_ORFS, device=device)[None, :]
                vm = (pos < vc.to(device)[:, None]).cpu().numpy() & (unseen.numpy() > 0.5)
                km = vm & (kn.numpy() > 0.5)
                all_yt.append(y10.numpy())
                all_yp.append(torch.sigmoid(f_log).float().cpu().numpy())
                all_km.append(km.astype(np.float32))
                all_pt.append(ph.numpy())
                all_pp.append(torch.sigmoid(p_log).float().cpu().numpy())
                all_vm.append(vm.astype(np.float32))
        yt_c = np.concatenate(all_yt)
        yp_c = np.concatenate(all_yp)
        km_c = np.concatenate(all_km)
        pt_c = np.concatenate(all_pt)
        pp_c = np.concatenate(all_pp)
        vm_b = np.concatenate(all_vm) > 0.5
        mf = _compute_multilabel_metrics(yt_c, yp_c, km_c)
        ph_auroc = float(roc_auc_score((pt_c[vm_b] > 0.5).astype(np.int32), pp_c[vm_b]))

        hard_fp = 0.0
        hard_mean = 0.0
        if hva_loader is not None:
            h_probs, h_kinds = [], []
            with torch.no_grad():
                for ids, lens, st, vc, hk_b in hva_loader:
                    t_id = ids.to(device, dtype=torch.long)
                    t_ln = lens.to(device, dtype=torch.long)
                    t_st = st.to(device, dtype=torch.float32)
                    t_vc = vc.to(device, dtype=torch.long)
                    with torch.amp.autocast("cuda", enabled=(device.type == "cuda"), dtype=torch.bfloat16):
                        _, p_log = model(t_id, t_ln, t_st, t_vc)
                    pos = torch.arange(CTX_WIN_ORFS, device=device)[None, :]
                    vm_h = pos < t_vc[:, None]
                    h_probs.append(torch.sigmoid(p_log)[vm_h].float().cpu().numpy())
                    hk_expand = torch.broadcast_to(hk_b.to(device, dtype=torch.long)[:, None], p_log.shape)
                    h_kinds.append(hk_expand[vm_h].cpu().numpy())
            hp_all = np.concatenate(h_probs)
            hk_all = np.concatenate(h_kinds)
            keep_hv = hk_all != 3
            if np.any(keep_hv):
                hp = hp_all[keep_hv]
                hk_v = hk_all[keep_hv]
                cls_fps = [float(np.mean(hp[hk_v == k] >= 0.5)) for k in (1, 2, 4) if np.any(hk_v == k)]
                cls_mns = [float(np.mean(hp[hk_v == k])) for k in (1, 2, 4) if np.any(hk_v == k)]
                hard_fp = float(np.mean(cls_fps)) if cls_fps else 0.0
                hard_mean = float(np.mean(cls_mns)) if cls_mns else 0.0

        # 平衡评分：保住原 zero-overlap 精度 + 奖励子类均衡降误报率，至少预热 4 epochs 防止过早截断 tailocin 头
        score = mf["macro_f1_p08"] + 0.5 * ph_auroc - 0.35 * hard_fp
        logger.info(
            "[V4.3 Unified] Ep %d/%d loss=%.4f | Unseen: MacroF1=%.4f PhageAUROC=%.4f | HardNegVal: meanP=%.4f FPR@0.5=%.4f",
            ep,
            epochs,
            ep_loss / max(1, n_steps),
            mf["macro_f1_p08"],
            ph_auroc,
            hard_mean,
            hard_fp,
        )
        eligible = (ep >= 4) or (epochs < 4)
        if (eligible and score > best_score) or not best_sd:
            if eligible:
                best_score = score
            best_sd = {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}
            best_metrics = {
                "epoch": ep,
                "macro_f1_p08": round(float(mf["macro_f1_p08"]), 4),
                "ph_auroc": round(ph_auroc, 4),
                "hard_val_mean_p": round(hard_mean, 4),
                "hard_val_fpr": round(hard_fp, 4),
            }

    model.load_state_dict(best_sd, strict=True)
    out_seq_pt = out_root / "unified_judge_seq.pt"
    tmp_pt = out_seq_pt.with_name(f".{out_seq_pt.name}.tmp.{os.getpid()}.pt")
    torch.save(
        {
            "state_dict": {k: v.cpu() for k, v in model.state_dict().items()},
            "stat_mean": ds["stat_mean"],
            "stat_std": ds["stat_std"],
            "use_aa_seq": True,
            "arch": "unified_v4_3",
            "params": total_cnt,
            "best_val_metrics": best_metrics,
        },
        tmp_pt,
    )
    tmp_pt.replace(out_seq_pt)

    # 4. 在原零泄露验证集拟合校准双流参数 -> logit_calibrator.npz
    logger.info("拟合 V4.3 双流 logit_calibrator.npz ...")
    ck_s = torch.load(out_stat_ckpt, map_location="cpu", weights_only=False)
    m_stat = build_orf_functional_judge(
        stat_mean=ck_s["stat_mean"], stat_std=ck_s["stat_std"], use_aa_seq=False, arch=str(ck_s["arch"])
    ).to(device)
    m_stat.load_state_dict(ck_s["state_dict"], strict=True)
    m_stat.eval()
    model.eval()

    sf_l, sp_l, qf_l, qp_l, yt_l, km_l, pt_l, vm_l = [], [], [], [], [], [], [], []
    with torch.no_grad():
        for ids, lens, st, vc, y10, ph, kn, unseen in va_loader:
            t_id = ids.to(device, dtype=torch.long)
            t_ln = lens.to(device, dtype=torch.long)
            t_st = st.to(device, dtype=torch.float32)
            t_vc = vc.to(device, dtype=torch.long)
            sf, sp = m_stat(t_id, t_ln, t_st, t_vc)
            qf, qp = model(t_id, t_ln, t_st, t_vc)
            pos = torch.arange(CTX_WIN_ORFS, device=device)[None, :]
            vm = (pos < t_vc[:, None]).cpu().numpy() & (unseen.numpy() > 0.5)
            km = vm & (kn.numpy() > 0.5)
            sf_l.append(sf.float().cpu().numpy())
            sp_l.append(sp.float().cpu().numpy())
            qf_l.append(qf.float().cpu().numpy())
            qp_l.append(qp.float().cpu().numpy())
            yt_l.append(y10.numpy())
            km_l.append(km.astype(np.float32))
            pt_l.append(ph.numpy())
            vm_l.append(vm.astype(np.float32))

    # 拼接有效未见 ORF 进行 Platt/Blend 温度标定
    vm_mask = np.concatenate(vm_l) > 0.5
    cal = fit_logit_blend_and_calibrator(
        np.concatenate(sf_l)[vm_mask],
        np.concatenate(qf_l)[vm_mask],
        np.concatenate(yt_l)[vm_mask],
        np.concatenate(km_l)[vm_mask],
        np.concatenate(sp_l)[vm_mask],
        np.concatenate(qp_l)[vm_mask],
        np.concatenate(pt_l)[vm_mask],
    )
    out_cal = out_root / "logit_calibrator.npz"
    tmp_cal = out_cal.with_name(f".{out_cal.stem}.tmp.{os.getpid()}.npz")
    np.savez(
        tmp_cal,
        func_alphas=np.asarray(cal["func_alphas"], dtype=np.float32),
        phage_alpha=np.asarray([float(cal["phage_alpha"])], dtype=np.float32),
        func_bias=np.asarray(cal["func_bias"], dtype=np.float32),
        phage_bias=np.asarray([float(cal["phage_bias"])], dtype=np.float32),
    )
    tmp_cal.replace(out_cal)

    summary = {
        "schema_version": "1.0",
        "model_version": "Unified V4.3",
        "arch": "unified_v4_3",
        "dna_backbone_profile": "stage1",
        "total_params": total_cnt,
        "trainable_params": trainable_cnt,
        "best_val_metrics": best_metrics,
        "calibrator_phage_alpha": round(float(cal["phage_alpha"]), 4),
        "elapsed_sec": round(time.perf_counter() - t0, 2),
        "unified_ckpt": str(out_seq_pt),
    }
    (out_root / "unified_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("V4.3 实验权重训练与校准完成 -> %s (总耗时 %.2fs)", out_root, summary["elapsed_sec"])
    del m_stat, model
    _clear_cuda()
    return out_seq_pt


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phage-data-root", default=os.environ.get("PHAGE_DATA_ROOT", str(REPO_ROOT.parent / "Phage data")))
    ap.add_argument("--epochs", type=int, default=12)
    ap.add_argument("--batch-size", type=int, default=32)
    ap.add_argument("--grad-accum", type=int, default=4)
    args = ap.parse_args()
    train_unified_v4_3(
        Path(args.phage_data_root).resolve(),
        epochs=args.epochs,
        batch_size=args.batch_size,
        grad_accum=args.grad_accum,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

