# -*- coding: utf-8 -*-
"""
共享底座 + 内部功能分化统一模型 (UnifiedJudge) 热启动与梯度隔离协调训练脚本。

流程：
1. 从已验证的 R3 蛋白序列模型初始化共享底座 (stat_enc + seq_enc + orf_fuse + ctx_blocks)
   与分化专家 C (macro_* + func10_head + phage_head + win_core_head)，并严格冻结底座以零损耗锁定 R3 排雷/分区能力；
2. 仅激活并微调轻量化分化专家 B (intact_func_head, ~21.9K 参数)，直连未经宏观平滑的共享底座 h_base：
   联合真实标签 P0..P9 与 R2 未平滑结构教师知识蒸馏，恢复结构完整度尖锐区分力 (Intact_AUROC)；
3. 将统一分化模型打包至 models/full_v4/orf_judge_unified/unified_judge_seq.pt，并在零泄露验证集验收。
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
from typing import Dict

import numpy as np
import torch
from torch import nn
from torch.utils.data import DataLoader, TensorDataset

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.phage_discovery.student.orf_functional_judge import (  # noqa: E402
    CTX_WIN_ORFS,
    NUM_JUDGE_CLASSES,
    build_orf_functional_judge,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("train_unified_judge")


def _extract_shared_base_embeddings(
    model: nn.Module,
    ids_arr: np.ndarray,
    lens_arr: np.ndarray,
    stat_arr: np.ndarray,
    vc_arr: np.ndarray,
    *,
    device: torch.device,
    batch_size: int = 32,
) -> np.ndarray:
    """利用冻结的共享底座抽取未经宏观门控平滑的底座表征 h_base (N, L, d_model) float16 缓存。"""
    model.eval()
    ds = TensorDataset(
        torch.from_numpy(ids_arr),
        torch.from_numpy(lens_arr),
        torch.from_numpy(stat_arr),
        torch.from_numpy(vc_arr),
    )
    loader = DataLoader(ds, batch_size=batch_size, shuffle=False)
    chunks = []
    with torch.no_grad():
        for ids, lens, st, vc in loader:
            ids = ids.to(device, dtype=torch.long)
            lens = lens.to(device, dtype=torch.long)
            st = st.to(device, dtype=torch.float32)
            vc = vc.to(device, dtype=torch.long)
            with torch.amp.autocast("cuda", enabled=(device.type == "cuda"), dtype=torch.bfloat16):
                h_base = model(ids, lens, st, vc, active_experts=(), return_experts=True)["h_base"]
            chunks.append(h_base.to(torch.float16).cpu().numpy())
    return np.concatenate(chunks, axis=0)


def _extract_r2_teacher_logits(
    r2_ckpt_path: Path,
    ids_arr: np.ndarray,
    lens_arr: np.ndarray,
    stat_arr: np.ndarray,
    vc_arr: np.ndarray,
    *,
    device: torch.device,
    batch_size: int = 32,
) -> np.ndarray:
    """提取 R2 老师未经全局平滑与偏置校准的 func10_logits (N, L, 10) float16 用于知识对齐。"""
    ck = torch.load(r2_ckpt_path, map_location=device, weights_only=False)
    m_r2 = build_orf_functional_judge(
        stat_mean=ck["stat_mean"],
        stat_std=ck["stat_std"],
        use_aa_seq=bool(ck["use_aa_seq"]),
        arch=str(ck.get("arch", "r2")),
    ).to(device)
    m_r2.load_state_dict(ck["state_dict"], strict=True)
    m_r2.eval()

    ds = TensorDataset(
        torch.from_numpy(ids_arr),
        torch.from_numpy(lens_arr),
        torch.from_numpy(stat_arr),
        torch.from_numpy(vc_arr),
    )
    loader = DataLoader(ds, batch_size=batch_size, shuffle=False)
    chunks = []
    with torch.no_grad():
        for ids, lens, st, vc in loader:
            ids = ids.to(device, dtype=torch.long)
            lens = lens.to(device, dtype=torch.long)
            st = st.to(device, dtype=torch.float32)
            vc = vc.to(device, dtype=torch.long)
            with torch.amp.autocast("cuda", enabled=(device.type == "cuda"), dtype=torch.bfloat16):
                f_log, _ = m_r2(ids, lens, st, vc)
            chunks.append(f_log.to(torch.float16).cpu().numpy())
    del m_r2
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    return np.concatenate(chunks, axis=0)


def train_unified_model(pd_root: Path, *, epochs: int = 16, batch_size: int = 256, lr: float = 1e-3) -> Path:
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    models_v4 = pd_root / "models" / "full_v4"
    r3_dir = models_v4 / "orf_judge_ablation_r3"
    r2_dir = models_v4 / "orf_judge_ablation_r2"
    uni_dir = models_v4 / "orf_judge_unified"
    uni_dir.mkdir(parents=True, exist_ok=True)

    ck_r3 = torch.load(r3_dir / "orf_judge_seq.pt", map_location="cpu", weights_only=False)
    ck_r2 = torch.load(r2_dir / "orf_judge_seq.pt", map_location="cpu", weights_only=False)

    uni_model = build_orf_functional_judge(
        stat_mean=ck_r3["stat_mean"],
        stat_std=ck_r3["stat_std"],
        use_aa_seq=True,
        arch="unified",
        aa_mask_prob=0.0,
    )
    # 1. 热启动共享底座 + 分化头 C（完全复用 R3 成熟权重），同时从 R2 func10_head 初始化分化头 B
    sd_uni = uni_model.state_dict()
    for k, v in ck_r3["state_dict"].items():
        if k in sd_uni and sd_uni[k].shape == v.shape:
            sd_uni[k] = v.clone()
    for k, v in ck_r2["state_dict"].items():
        if k.startswith("func10_head."):
            dst_k = "intact_func_head." + k[len("func10_head.") :]
            if dst_k in sd_uni and sd_uni[dst_k].shape == v.shape:
                sd_uni[dst_k] = v.clone()
    uni_model.load_state_dict(sd_uni, strict=True)
    uni_model.to(device)

    ds = np.load(pd_root / "training" / "orf_judge_ablation" / "judge_dataset.npz", allow_pickle=False)
    t0 = time.perf_counter()
    logger.info("抽取冻结共享底座 h_base (train=%d, val=%d)...", len(ds["tr_ids"]), len(ds["va_ids"]))
    tr_h = _extract_shared_base_embeddings(
        uni_model, ds["tr_ids"], ds["tr_lens"], ds["tr_stat"], ds["tr_vc"], device=device, batch_size=32
    )
    va_h = _extract_shared_base_embeddings(
        uni_model, ds["va_ids"], ds["va_lens"], ds["va_stat"], ds["va_vc"], device=device, batch_size=32
    )
    logger.info("抽取 R2 结构教师无平滑 logits 蒸馏目标...")
    tr_r2_logits = _extract_r2_teacher_logits(
        r2_dir / "orf_judge_seq.pt", ds["tr_ids"], ds["tr_lens"], ds["tr_stat"], ds["tr_vc"], device=device, batch_size=32
    )
    va_r2_logits = _extract_r2_teacher_logits(
        r2_dir / "orf_judge_seq.pt", ds["va_ids"], ds["va_lens"], ds["va_stat"], ds["va_vc"], device=device, batch_size=32
    )

    # 仅解锁完整度分化头 B，物理冻结共享底座与分化头 C 防任何性能回退
    for p in uni_model.parameters():
        p.requires_grad_(False)
    for p in uni_model.intact_func_head.parameters():
        p.requires_grad_(True)
    head_params = sum(p.numel() for p in uni_model.intact_func_head.parameters())
    logger.info("底座冻结完成，仅微调完整度分化专家头 intact_func_head (trainable_params=%d)", head_params)

    tr_vc = ds["tr_vc"]
    tr_vm = np.arange(CTX_WIN_ORFS)[None, :] < tr_vc[:, None]
    tr_km = tr_vm & (ds["tr_kn"] > 0.5)
    y10_valid = ds["tr_y10"][tr_km]
    pos_cnt = np.maximum(np.sum(y10_valid > 0.5, axis=0), 1.0)
    neg_cnt = np.maximum(len(y10_valid) - pos_cnt, 1.0)
    pw_10 = torch.tensor(np.clip(np.sqrt(neg_cnt / pos_cnt), 1.0, 6.0).astype(np.float32), device=device)

    tr_ds = TensorDataset(
        torch.from_numpy(tr_h),
        torch.from_numpy(ds["tr_vc"]),
        torch.from_numpy(ds["tr_y10"]),
        torch.from_numpy(ds["tr_kn"]),
        torch.from_numpy(tr_r2_logits),
    )
    va_ds = TensorDataset(
        torch.from_numpy(va_h),
        torch.from_numpy(ds["va_vc"]),
        torch.from_numpy(ds["va_y10"]),
        torch.from_numpy(ds["va_kn"]),
        torch.from_numpy(va_r2_logits),
        torch.from_numpy(ds["va_unseen"]),
    )
    tr_loader = DataLoader(tr_ds, batch_size=batch_size, shuffle=True)
    va_loader = DataLoader(va_ds, batch_size=batch_size, shuffle=False)

    opt = torch.optim.AdamW(uni_model.intact_func_head.parameters(), lr=lr, weight_decay=2e-4)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=max(1, epochs))
    bce_none = nn.BCEWithLogitsLoss(reduction="none", pos_weight=pw_10)

    best_val_loss = float("inf")
    best_head_sd: Dict[str, torch.Tensor] = {}
    for ep in range(1, epochs + 1):
        uni_model.intact_func_head.train()
        ep_loss = 0.0
        steps = 0
        for hb, vc, y10, kn, r2_log in tr_loader:
            hb = hb.to(device, dtype=torch.float32)
            vc = vc.to(device, dtype=torch.long)
            y10 = y10.to(device, dtype=torch.float32)
            kn = kn.to(device, dtype=torch.float32)
            r2_log = r2_log.to(device, dtype=torch.float32)

            pos = torch.arange(CTX_WIN_ORFS, device=device)[None, :]
            vm = (pos < vc[:, None]).to(torch.float32)
            km = (vm * kn).unsqueeze(-1)

            pred = uni_model.intact_func_head(hb) * vm.unsqueeze(-1)
            loss_sup = (bce_none(pred, y10) * km).sum() / km.sum().clamp(min=1.0) / float(NUM_JUDGE_CLASSES)
            # 重点强化 P0..P4 核心结构模块在局部及窗级最大值与 R2 教师的一致性
            loss_kd = (nn.functional.mse_loss(pred, r2_log, reduction="none") * vm.unsqueeze(-1)).sum() / vm.sum().clamp(min=1.0) / float(NUM_JUDGE_CLASSES)
            p_core = torch.sigmoid(pred[:, :, :5]).masked_fill(~(pos < vc[:, None]).unsqueeze(-1), 0.0).max(dim=1).values
            t_core = torch.sigmoid(r2_log[:, :, :5]).masked_fill(~(pos < vc[:, None]).unsqueeze(-1), 0.0).max(dim=1).values
            loss_win_max = nn.functional.smooth_l1_loss(p_core, t_core)
            loss = 0.6 * loss_sup + 0.8 * loss_kd + 1.2 * loss_win_max

            opt.zero_grad(set_to_none=True)
            loss.backward()
            opt.step()
            ep_loss += float(loss.item())
            steps += 1
        sched.step()

        uni_model.intact_func_head.eval()
        val_loss = 0.0
        v_steps = 0
        with torch.no_grad():
            for hb, vc, y10, kn, r2_log, unseen in va_loader:
                hb = hb.to(device, dtype=torch.float32)
                vc = vc.to(device, dtype=torch.long)
                r2_log = r2_log.to(device, dtype=torch.float32)
                pos = torch.arange(CTX_WIN_ORFS, device=device)[None, :]
                vm = (pos < vc[:, None]) & (unseen.to(device) > 0.5)
                if not torch.any(vm):
                    continue
                pred = uni_model.intact_func_head(hb)
                kd_v = (nn.functional.mse_loss(pred[:, :, :5], r2_log[:, :, :5], reduction="none") * vm.unsqueeze(-1).float()).sum() / vm.sum().clamp(min=1.0) / 5.0
                val_loss += float(kd_v.item())
                v_steps += 1
        avg_val = val_loss / max(1, v_steps)
        logger.info("[Unified intact head] Epoch %d/%d train_loss=%.4f val_core_kd=%.4f", ep, epochs, ep_loss / max(1, steps), avg_val)
        if avg_val < best_val_loss:
            best_val_loss = avg_val
            best_head_sd = {k: v.detach().cpu().clone() for k, v in uni_model.intact_func_head.state_dict().items()}

    uni_model.intact_func_head.load_state_dict(best_head_sd, strict=True)
    out_seq_pt = uni_dir / "unified_judge_seq.pt"
    tmp_pt = out_seq_pt.with_name(f".{out_seq_pt.name}.tmp.{os.getpid()}.pt")
    torch.save(
        {
            "state_dict": {k: v.cpu() for k, v in uni_model.state_dict().items()},
            "stat_mean": ck_r3["stat_mean"],
            "stat_std": ck_r3["stat_std"],
            "use_aa_seq": True,
            "arch": "unified",
            "params": sum(p.numel() for p in uni_model.parameters()),
            "best_val_core_kd": round(best_val_loss, 5),
        },
        tmp_pt,
    )
    tmp_pt.replace(out_seq_pt)

    # 同步就近拷贝 statonly 与校准器组成自包含统一文件夹（也可回退复用）
    for src_f, dst_f in [
        (r3_dir / "orf_judge_statonly.pt", uni_dir / "orf_judge_statonly.pt"),
        (r3_dir / "logit_calibrator.npz", uni_dir / "logit_calibrator.npz"),
    ]:
        if src_f.is_file():
            dst_f.write_bytes(src_f.read_bytes())

    meta = {
        "arch": "unified",
        "total_params": sum(p.numel() for p in uni_model.parameters()),
        "trainable_head_params": head_params,
        "best_val_core_kd": round(best_val_loss, 5),
        "elapsed_sec": round(time.perf_counter() - t0, 2),
        "unified_ckpt": str(out_seq_pt),
    }
    (uni_dir / "unified_summary.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("Unified 模型训练与封装完成 -> %s (总耗时 %.2fs)", out_seq_pt, meta["elapsed_sec"])
    return out_seq_pt


def main() -> int:
    parser = argparse.ArgumentParser(description="训练共享底座分化版 UnifiedJudge 模型")
    parser.add_argument("--phage-data-root", default=os.environ.get("PHAGE_DATA_ROOT", str(REPO_ROOT.parent / "Phage data")))
    parser.add_argument("--epochs", type=int, default=16)
    parser.add_argument("--batch-size", type=int, default=256)
    parser.add_argument("--lr", type=float, default=1e-3)
    args = parser.parse_args()
    train_unified_model(Path(args.phage_data_root).resolve(), epochs=args.epochs, batch_size=args.batch_size, lr=args.lr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
