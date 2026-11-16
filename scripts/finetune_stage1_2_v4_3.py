# -*- coding: utf-8 -*-
"""
Stage 1.2 DNA 主干 V4.3 轻量硬负样本降温微调脚本（Step 2b）：

核心机制（防遗忘优先、精准抑制）：
1. 基于 16 核并发对 `v4_3_dna/hard_neg_slices.fna`（外源/内源 Tailocin、hotspot 质粒、ICE）
   及其随机截短 6.5–13.5kb 碎片提取与现役 Stage 1.2 严格同构的 256D Tabular + 18x117D ORF Token + 5kb DNA 编码；
2. 对原 `stage1_2_ablation` 全量 9 个分片 (`117,144` 窗) 先抽取现役生产 `stage1_2.pt` 的冻结教师 logits
   (`t_win`, `t_sub`, `t_func`, `t_sem`) 并落盘缓存（支持断点复用）；
3. 联合训练 `5 epochs`（`lr=8e-5, backbone_lr_scale=0.25`）：
   - 原样本执行强 KL/MSE Logit 锚定，锁死正样本 `v1_test / C1 / C2_12kb / Gold-8` 召回与 200bp SubBin 边界；
   - V4.3 硬负样本（含 4x 索引过采样）施加强 `win_logit -> 0` / `sub_logits -> 0` / `head/conn -> 0` 负监督；
4. 用微调后的 `stage1_2.pt` 重抽 `CONTIG_REF_PARTS + V4.3硬负例` 上下文序列特征，热启动微调 `context_refiner.pt`（加强正向保护锚定 `pos_anchor=0.60`），
   其余 `subbin_refiner.pt` 与解码阈值完整同步至 `models/full_v4_3_exp/stage1_2`。
"""
from __future__ import annotations

import argparse
import concurrent.futures
import gc
import json
import logging
import os
import shutil
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
import torch
import torch.nn.functional as F
from sklearn.metrics import average_precision_score

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.phage_discovery.data.feature_dataset import iter_fasta  # noqa: E402
from src.phage_discovery.experts.expert_c_orf import MAX_ORFS_PER_WIN, extract_contig_orf_tokens  # noqa: E402
from src.phage_discovery.experts.seq_dataset import encode_dna, reverse_complement_codes  # noqa: E402
from src.phage_discovery.features.window_features import SUB_BINS, extract_contig_windows  # noqa: E402
from src.phage_discovery.student.distilled_student import _focal_bce_with_logits, _sub_bce_dice_loss  # noqa: E402
from src.phage_discovery.student.distilled_student_v4 import (  # noqa: E402
    CONTIG_REF_PARTS,
    REFINER_STEP_FEAT_DIM,
    _apply_refiner_augmentations,
    _load_v4_part,
    _predict_v4_all,
    build_distilled_student_v4,
    build_region_context_refiner,
    extract_refiner_step_features,
    group_windows_by_contig,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("finetune_stage1_2_v4_3")


def _clear_cuda() -> None:
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()


def _extract_hard_slice_worker(args: Tuple[str, str, int]) -> Dict[str, Any]:
    cid, seq, kind = args
    wres = extract_contig_windows(cid, seq, win_size=5000, step_size=2500, truth_regions=None, feature_profile="stage1")
    starts = wres["starts"]
    ends = wres["ends"]
    feats = wres["features"]
    if len(starts) == 0:
        return {"n": 0}
    tk, cn = extract_contig_orf_tokens(seq, starts, ends, feature_profile="stage1")
    codes = np.zeros((len(starts), 5000), dtype=np.uint8)
    lens = np.zeros(len(starts), dtype=np.int32)
    for idx, (s, e) in enumerate(zip(starts, ends)):
        sub = seq[int(s) : int(e)]
        L = min(5000, len(sub))
        if L > 0:
            codes[idx, :L] = encode_dna(sub[:L])
        lens[idx] = L
    return {
        "n": len(starts),
        "codes": codes,
        "lengths": lens,
        "features": feats.astype(np.float32),
        "tokens": tk.astype(np.float32),
        "counts": cn.astype(np.int32),
        "cids": np.array([cid] * len(starts), dtype=object),
        "starts": np.asarray(starts, dtype=np.int64),
        "ends": np.asarray(ends, dtype=np.int64),
        "kinds": np.full(len(starts), int(kind), dtype=np.int32),
    }


def build_or_load_hard_dna_cache(pd_root: Path, *, workers: int = 16) -> Dict[str, np.ndarray]:
    dna_dir = pd_root / "training" / "v4_3_dna"
    cache_p = dna_dir / "s12_hard_v4_3_cache.npz"
    if cache_p.is_file():
        logger.info("复用 Stage 1.2 硬负切片缓存: %s", cache_p)
        z = np.load(cache_p, allow_pickle=True)
        return {k: z[k] for k in z.files}

    manifest_p = dna_dir / "hard_neg_manifest.json"
    fna_p = dna_dir / "hard_neg_slices.fna"
    kind_map = {str(r["contig_id"]): int(r["kind"]) for r in json.loads(manifest_p.read_text(encoding="utf-8"))}

    rng = np.random.default_rng(20261116)
    tasks: List[Tuple[str, str, int]] = []
    for cid, seq in iter_fasta(fna_p):
        if len(seq) < 3000:
            continue
        k = kind_map.get(cid, 2)
        tasks.append((cid, seq, k))
        # 对长序列附加随机 6.5–13.5kb 碎片，强化短 Contig 场景（如 B1）抑制
        if len(seq) >= 16000:
            n_frag = 2 if k in (1, 2) else 1
            for fi in range(n_frag):
                flen = int(rng.integers(6500, 13800))
                if len(seq) <= flen:
                    continue
                st = int(rng.integers(0, len(seq) - flen + 1))
                tasks.append((f"{cid}_hfrag{fi}_{flen}", seq[st : st + flen], k))

    logger.info("16核并发提取 V4.3 DNA 硬负切片窗口 (%d 条区段+短碎片)...", len(tasks))
    parts: List[Dict[str, Any]] = []
    safe_w = max(2, min(16, int(workers)))
    with concurrent.futures.ProcessPoolExecutor(max_workers=safe_w) as ex:
        for res in ex.map(_extract_hard_slice_worker, tasks, chunksize=4):
            if res.get("n", 0) > 0:
                parts.append(res)

    out = {
        "codes": np.concatenate([p["codes"] for p in parts], axis=0),
        "lengths": np.concatenate([p["lengths"] for p in parts], axis=0),
        "features": np.concatenate([p["features"] for p in parts], axis=0),
        "tokens": np.concatenate([p["tokens"] for p in parts], axis=0),
        "counts": np.concatenate([p["counts"] for p in parts], axis=0),
        "cids": np.concatenate([p["cids"] for p in parts], axis=0),
        "starts": np.concatenate([p["starts"] for p in parts], axis=0),
        "ends": np.concatenate([p["ends"] for p in parts], axis=0),
        "kinds": np.concatenate([p["kinds"] for p in parts], axis=0),
    }
    tmp = cache_p.with_name(f".{cache_p.stem}.tmp.{os.getpid()}.npz")
    np.savez(tmp, **out)
    tmp.replace(cache_p)
    logger.info("V4.3 DNA 硬负窗口构建完成: %d 窗 -> %s", len(out["codes"]), cache_p)
    return out


def _build_base_fasta_map(pd_root: Path) -> Dict[str, Path]:
    tdir = pd_root / "training"
    return {
        "windows": tdir / "full_v2" / "train_windows.fna",
        "chimeras": tdir / "full_v2" / "train_chimeras.fna",
        "mined": pd_root / "teachers" / "train_prophage_mined" / "mined_chimeras.fna",
        "hard_neg": tdir / "full_v3" / "ext_hard_neg.fna",
        "ext_rare": tdir / "full_v3" / "ext_rare.fna",
        "ext_windows": tdir / "full_v3" / "ext_windows.fna",
        "ext_mined": tdir / "full_v3" / "ext_mined.fna",
        "hard_v4": tdir / "full_v4" / "ext_hard_v4.fna",
        "rare_multiscale": tdir / "stage1_2_ablation" / "train_rare_multiscale.fna",
    }


def _finetune_context_refiner_v4_3(
    tr_sf: np.ndarray,
    tr_wl: np.ndarray,
    tr_y: np.ndarray,
    tr_cids: np.ndarray,
    tr_starts: np.ndarray,
    tr_tags: np.ndarray,
    va_sf: np.ndarray,
    va_wl: np.ndarray,
    va_y: np.ndarray,
    va_cids: np.ndarray,
    va_starts: np.ndarray,
    init_ref_ckpt: Path,
    out_ref_ckpt: Path,
    *,
    device: torch.device,
    epochs: int = 6,
    lr: float = 8e-5,
) -> Dict[str, Any]:
    """从现役 context_refiner.pt 热启动，在原区段 + V4.3 硬负切片上温和微调。"""
    rng = np.random.default_rng(42)
    refiner = build_region_context_refiner(max_delta=2.2, use_context_features=True).to(device)
    refiner.load_state_dict(torch.load(init_ref_ckpt, map_location="cpu", weights_only=True), strict=True)

    tr_groups = [
        g
        for g in group_windows_by_contig(tr_cids, tr_starts, max_gap_bp=5000, source_tags=tr_tags)
        if len(g) >= 2
    ]
    va_groups = [
        g
        for g in group_windows_by_contig(va_cids, va_starts, max_gap_bp=5000)
        if len(g) >= 2
    ]

    opt = torch.optim.AdamW(refiner.parameters(), lr=lr, weight_decay=1e-2)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=max(1, epochs))
    va_keep = va_y >= 0
    best_sc = -1e9
    best_ap = -1.0
    batch_sz = 16

    for ep in range(1, epochs + 1):
        refiner.train()
        order = rng.permutation(len(tr_groups))
        ep_loss = 0.0
        n_used = 0
        for bi in range(0, len(tr_groups), batch_sz):
            b_idxs = order[bi : bi + batch_sz]
            max_w = max(len(tr_groups[k]) for k in b_idxs)
            sf_b = np.zeros((len(b_idxs), max_w, REFINER_STEP_FEAT_DIM), dtype=np.float32)
            rl_b = np.zeros((len(b_idxs), max_w), dtype=np.float32)
            y_b = np.zeros((len(b_idxs), max_w), dtype=np.float32)
            vm_b = np.zeros((len(b_idxs), max_w), dtype=np.float32)
            wt_b = np.ones((len(b_idxs), max_w), dtype=np.float32)
            lens_b = np.zeros((len(b_idxs),), dtype=np.int64)
            for row, gi in enumerate(b_idxs):
                g = tr_groups[gi]
                ln = len(g)
                lens_b[row] = ln
                is_hard_g = str(tr_tags[g[0]]).startswith("v4_3")
                if is_hard_g:
                    sf_b[row, :ln] = tr_sf[g]
                    rl_b[row, :ln] = tr_wl[g]
                    wt_b[row, :ln] = 2.5
                else:
                    sf_aug, rl_aug = _apply_refiner_augmentations(tr_sf[g], tr_wl[g], tr_y[g], rng)
                    sf_b[row, :ln] = sf_aug
                    rl_b[row, :ln] = rl_aug
                lbl = tr_y[g]
                vm_b[row, :ln] = (lbl >= 0).astype(np.float32)
                y_b[row, :ln] = np.maximum(lbl, 0).astype(np.float32)

            sf_t = torch.from_numpy(sf_b).to(device)
            rl_t = torch.from_numpy(rl_b).to(device)
            y_t = torch.from_numpy(y_b).to(device)
            vm_t = torch.from_numpy(vm_b).to(device)
            wt_t = torch.from_numpy(wt_b).to(device)
            ln_t = torch.from_numpy(lens_b).to(device)

            opt.zero_grad(set_to_none=True)
            ref_logits = refiner(sf_t, rl_t, seq_lens=ln_t)
            bce_raw = F.binary_cross_entropy_with_logits(ref_logits, y_t, reduction="none")
            w_cls = torch.where(y_t > 0.5, 1.35, 1.0) * vm_t * wt_t
            loss_cls = (bce_raw * w_cls).sum() / w_cls.sum().clamp(min=1.0)
            # 强正向锚定：坚决不准把真实高分前噬菌体拉低
            pos_mask = y_t * vm_t
            loss_pos = 0.60 * (F.relu(rl_t - ref_logits) ** 2 * pos_mask).sum() / pos_mask.sum().clamp(min=1.0)
            loss_reg = 0.08 * (((ref_logits - rl_t) * vm_t) ** 2).sum() / vm_t.sum().clamp(min=1.0)
            loss = loss_cls + loss_pos + loss_reg
            loss.backward()
            torch.nn.utils.clip_grad_norm_(refiner.parameters(), 1.0)
            opt.step()
            ep_loss += float(loss.item()) * len(b_idxs)
            n_used += len(b_idxs)
        sched.step()

        refiner.eval()
        va_ref = va_wl.copy()
        with torch.no_grad():
            for g in va_groups:
                rl_l = refiner(
                    torch.from_numpy(va_sf[g][None, ...]).to(device),
                    torch.from_numpy(va_wl[g][None, ...]).to(device),
                    seq_lens=torch.tensor([len(g)], dtype=torch.long, device=device),
                ).squeeze(0).cpu().numpy()
                va_ref[g] = rl_l
        va_lk = np.clip(va_ref[va_keep], -20.0, 20.0)
        va_pk = 1.0 / (1.0 + np.exp(-va_lk))
        va_yk = np.maximum(va_y[va_keep], 0).astype(np.float64)
        va_bce = float(np.mean(np.maximum(va_lk, 0.0) - va_lk * va_yk + np.log1p(np.exp(-np.abs(va_lk)))))
        ap = float(average_precision_score(va_y[va_keep], va_pk))
        val_sc = ap - 0.12 * va_bce
        logger.info("  [ContextRefiner V4.3] Ep %d/%d loss=%.4f val_auprc=%.5f val_bce=%.5f", ep, epochs, ep_loss / max(1, n_used), ap, va_bce)
        if val_sc > best_sc:
            best_sc, best_ap = val_sc, ap
            tmp = out_ref_ckpt.with_name(f".{out_ref_ckpt.stem}.tmp.pt")
            torch.save(refiner.state_dict(), tmp)
            tmp.replace(out_ref_ckpt)
    del refiner
    _clear_cuda()
    return {"best_val_auprc": round(best_ap, 5), "best_val_score": round(best_sc, 5)}


def finetune_stage1_2_v4_3(
    pd_root: Path,
    *,
    epochs: int = 5,
    batch_size: int = 64,
    lr: float = 8e-5,
    workers: int = 16,
) -> Path:
    t0 = time.perf_counter()
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    v4_s12_dir = pd_root / "models" / "full_v4" / "stage1_2"
    exp_s12_dir = pd_root / "models" / "full_v4_3_exp" / "stage1_2"
    exp_s12_dir.mkdir(parents=True, exist_ok=True)
    meta = json.loads((v4_s12_dir / "stage1_2_meta.json").read_text(encoding="utf-8"))

    # 1. 构建/读取 V4.3 DNA 硬负窗口
    hard = build_or_load_hard_dna_cache(pd_root, workers=workers)
    n_hard = len(hard["codes"])

    # 2. 加载原版 Stage 1.2 全量 9 个分片训练数据（117k 窗）
    s12_feat_dir = pd_root / "training" / "stage1_2_ablation" / "features"
    f_map = _build_base_fasta_map(pd_root)
    parts_order = ("windows", "chimeras", "mined", "hard_neg", "ext_rare", "ext_windows", "ext_mined", "hard_v4", "rare_multiscale")
    loaded: List[Dict[str, Any]] = []
    tags_l: List[np.ndarray] = []
    for p in parts_order:
        if not (s12_feat_dir / f"train_{p}.npz").is_file():
            continue
        pdata = _load_v4_part(
            s12_feat_dir,
            pd_root / "training" / "full_v2",
            "train",
            p,
            max_len=5000,
            workers=workers,
            fasta_override=f_map.get(p),
            use_semantic=True,
            use_functional=True,
            feature_profile="stage1",
        )
        loaded.append(pdata)
        tags_l.append(np.full(len(pdata["clean_labels"]), p, dtype=object))

    base_codes = np.concatenate([p["codes"] for p in loaded])
    base_lens = np.concatenate([p["lengths"] for p in loaded])
    base_feats = np.concatenate([p["arrs"]["features"] for p in loaded])
    base_tokens = np.concatenate([p["tokens"] for p in loaded])
    base_counts = np.concatenate([p["counts"] for p in loaded])
    base_sub = np.concatenate([p["arrs"]["sub_mask"] for p in loaded]).astype(np.float32)
    base_orig_y = np.concatenate([p["orig_labels"] for p in loaded])
    base_clean_y = np.concatenate([p["clean_labels"] for p in loaded])
    base_cids = np.concatenate([p["arrs"]["contig_ids"] for p in loaded])
    base_starts = np.concatenate([p["arrs"]["starts"] for p in loaded])
    base_tags = np.concatenate(tags_l)
    del loaded, tags_l
    gc.collect()

    use_row = (base_clean_y >= 0) | ((base_clean_y == -1) & (base_orig_y == -1))
    tr_codes = base_codes[use_row]
    tr_lens = base_lens[use_row]
    tr_feats = base_feats[use_row]
    tr_tokens = base_tokens[use_row]
    tr_counts = base_counts[use_row]
    tr_sub = base_sub[use_row]
    tr_y = base_clean_y[use_row]
    n_base_tr = len(tr_y)

    # 3. 加载生产 stage1_2.pt 抽取原样本教师锚点缓存（避免重复推理）
    init_ckpt = v4_s12_dir / "stage1_2.pt"
    init_sd = torch.load(init_ckpt, map_location="cpu", weights_only=True)
    feat_mean = init_sd["feat_mean"].numpy().astype(np.float32)
    feat_std = init_sd["feat_std"].numpy().astype(np.float32)

    anchor_p = pd_root / "training" / "v4_3_dna" / "s12_teacher_anchors_f16.npz"
    if not anchor_p.is_file():
        logger.info("抽取现役 Stage 1.2 教师防遗忘锚点 (%d 窗)...", n_base_tr)
        t_model = build_distilled_student_v4(
            tr_feats.shape[1],
            feat_mean,
            feat_std,
            dna_channels=int(meta.get("dna_channels", 160)),
            orf_d_model=int(meta.get("orf_d_model", 128)),
            orf_nhead=int(meta.get("orf_nhead", 4)),
            orf_num_layers=int(meta.get("orf_num_layers", 3)),
            fusion_dim=int(meta.get("fusion_dim", 256)),
            orf_feat_dim=int(tr_tokens.shape[-1]),
            func_dim=9,
        ).to(device)
        t_model.load_state_dict(init_sd, strict=True)
        t_pred = _predict_v4_all(t_model, tr_codes, tr_lens, tr_feats, tr_tokens, tr_counts, device, batch_size=128)
        tmp_ac = anchor_p.with_name(f".{anchor_p.stem}.tmp.{os.getpid()}.npz")
        np.savez(
            tmp_ac,
            t_win=t_pred["win_logits"].astype(np.float16),
            t_sub=t_pred["sub_logits"].astype(np.float16),
            t_func=t_pred["func_logits"].astype(np.float16),
            t_sem=t_pred["sem_logits"].astype(np.float16),
        )
        tmp_ac.replace(anchor_p)
        del t_model, t_pred
        _clear_cuda()

    ac = np.load(anchor_p, allow_pickle=False)
    t_win, t_sub, t_func, t_sem = ac["t_win"], ac["t_sub"], ac["t_func"], ac["t_sem"]

    # 拼接硬负样本至单块数组（仅增 ~3k-4k 行，低内存占用）
    all_codes = np.concatenate([tr_codes, hard["codes"]], axis=0)
    all_lens = np.concatenate([tr_lens, hard["lengths"]], axis=0)
    all_feats = np.concatenate([tr_feats, hard["features"]], axis=0)
    all_tokens = np.concatenate([tr_tokens, hard["tokens"]], axis=0)
    all_counts = np.concatenate([tr_counts, hard["counts"]], axis=0)
    all_sub = np.concatenate([tr_sub, np.zeros((n_hard, SUB_BINS), dtype=np.float32)], axis=0)
    all_y = np.concatenate([tr_y, np.zeros(n_hard, dtype=np.int8)], axis=0)
    all_is_v43 = np.concatenate([np.zeros(n_base_tr, dtype=np.int8), np.ones(n_hard, dtype=np.int8)], axis=0)
    all_kind = np.concatenate([np.zeros(n_base_tr, dtype=np.int32), hard["kinds"]], axis=0)

    del tr_codes, tr_lens, tr_feats, tr_tokens, tr_counts, tr_sub
    gc.collect()

    # 零泄露 val（原 val windows + val chimeras）
    eval_feat_dir = pd_root / "benchmarks" / "v1_stage1" / "features"
    bench_dir = pd_root / "benchmarks" / "v1"
    va_w = _load_v4_part(eval_feat_dir, bench_dir, "val", "windows", 5000, workers, use_semantic=False, feature_profile="stage1")
    va_c = _load_v4_part(eval_feat_dir, bench_dir, "val", "chimeras", 5000, workers, use_semantic=False, feature_profile="stage1")
    va_codes = np.concatenate([va_w["codes"], va_c["codes"]])
    va_lens = np.concatenate([va_w["lengths"], va_c["lengths"]])
    va_feats = np.concatenate([va_w["arrs"]["features"], va_c["arrs"]["features"]])
    va_tokens = np.concatenate([va_w["tokens"], va_c["tokens"]])
    va_counts = np.concatenate([va_w["counts"], va_c["counts"]])
    va_y = np.concatenate([va_w["orig_labels"], va_c["orig_labels"]])
    va_keep = va_y >= 0

    # 4. 热启动构建可微调 Stage 1.2 学生模型
    model = build_distilled_student_v4(
        all_feats.shape[1],
        feat_mean,
        feat_std,
        dna_channels=int(meta.get("dna_channels", 160)),
        orf_d_model=int(meta.get("orf_d_model", 128)),
        orf_nhead=int(meta.get("orf_nhead", 4)),
        orf_num_layers=int(meta.get("orf_num_layers", 3)),
        fusion_dim=int(meta.get("fusion_dim", 256)),
        orf_feat_dim=int(all_tokens.shape[-1]),
        func_dim=9,
    ).to(device)
    model.load_state_dict(init_sd, strict=True)

    head_prefixes = ("win_head.", "sem_head.", "func_head.", "orf_phage_head.", "orf_func_head.", "func_win_residual.", "sub_head.")
    bb_params = [p for n, p in model.named_parameters() if not n.startswith(head_prefixes)]
    hd_params = [p for n, p in model.named_parameters() if n.startswith(head_prefixes)]
    opt = torch.optim.AdamW(
        [
            {"params": bb_params, "lr": lr * 0.25, "weight_decay": 1e-2},
            {"params": hd_params, "lr": lr, "weight_decay": 1e-2},
        ]
    )

    # 每个 epoch 混入全量原样本 + 4x 过采样 V4.3 硬负索引
    base_indices = np.arange(n_base_tr, dtype=np.int64)
    hard_indices = np.arange(n_base_tr, n_base_tr + n_hard, dtype=np.int64)
    epoch_indices = np.concatenate([base_indices, np.tile(hard_indices, 4)], axis=0)
    steps_per_ep = max(1, int(np.ceil(len(epoch_indices) / batch_size)))
    sched = torch.optim.lr_scheduler.OneCycleLR(
        opt,
        max_lr=[lr * 0.25, lr],
        total_steps=max(1, epochs * steps_per_ep),
    )
    scaler = torch.amp.GradScaler("cuda", enabled=(device.type == "cuda"))
    rng = np.random.default_rng(42)

    pos_cnt = float(np.sum(tr_y == 1))
    neg_cnt = float(np.sum(tr_y == 0))
    pos_w = float(np.clip(neg_cnt / max(1.0, pos_cnt), 0.5, 4.0))

    out_s12_pt = exp_s12_dir / "stage1_2.pt"
    best_score = -1e9
    for ep in range(1, epochs + 1):
        model.train()
        order = rng.permutation(epoch_indices)
        ep_loss = 0.0
        for bi in range(steps_per_ep):
            idx = order[bi * batch_size : (bi + 1) * batch_size]
            b_codes = all_codes[idx].copy()
            b_len = all_lens[idx]
            b_sub = all_sub[idx].copy()
            rc_mask = (b_len == 5000) | (b_sub.min(axis=1) == b_sub.max(axis=1))
            if rng.random() < 0.5 and np.any(rc_mask):
                b_codes[rc_mask] = reverse_complement_codes(b_codes[rc_mask], b_len[rc_mask])
                full_only = rc_mask & (b_len == 5000)
                b_sub[full_only] = b_sub[full_only, ::-1]

            c_t = torch.from_numpy(b_codes.astype(np.int64)).to(device)
            oh = F.one_hot(c_t, num_classes=5)[..., :4].permute(0, 2, 1).float()
            ln_t = torch.from_numpy(b_len.astype(np.int64)).to(device)
            tb_t = torch.from_numpy(all_feats[idx]).to(device)
            tk_t = torch.from_numpy(all_tokens[idx]).to(device)
            cn_t = torch.from_numpy(all_counts[idx].astype(np.int64)).to(device)

            is_v43 = torch.from_numpy(all_is_v43[idx] > 0).to(device)
            is_base = ~is_v43
            yb_raw = all_y[idx]
            win_valid = torch.from_numpy((yb_raw >= 0).astype(np.float32)).to(device)
            yb = torch.from_numpy(np.maximum(yb_raw, 0).astype(np.float32)).to(device)
            sb = torch.from_numpy(b_sub).to(device)
            b_kind = torch.from_numpy(all_kind[idx]).to(device)

            # 取原样本教师锚点（V4.3 行填 0 不参与 anchor）
            safe_idx = np.where(idx < n_base_tr, idx, 0)
            tw_t = torch.from_numpy(t_win[safe_idx].astype(np.float32)).to(device)
            ts_t = torch.from_numpy(t_sub[safe_idx].astype(np.float32)).to(device)
            tf_t = torch.from_numpy(t_func[safe_idx].astype(np.float32)).to(device)
            tm_t = torch.from_numpy(t_sem[safe_idx].astype(np.float32)).to(device)

            opt.zero_grad(set_to_none=True)
            with torch.amp.autocast("cuda", enabled=(device.type == "cuda"), dtype=torch.float16):
                out_d = model(oh, tb_t, lengths=ln_t, orf_tokens=tk_t, orf_counts=cn_t, return_aux=True)
            w_log = out_d["win_logit"].float()
            s_log = out_d["sub_logits"].float()
            f_log = out_d["func_logits"].float()
            m_log = out_d["sem_logits"].float()

            loss = w_log.new_tensor(0.0)
            if torch.any(is_base):
                bm = is_base.to(torch.float32)
                l_anchor_w = ((w_log - tw_t) ** 2 * bm).sum() / bm.sum().clamp(min=1.0)
                l_anchor_s = ((s_log - ts_t) ** 2 * bm[:, None]).mean(dim=1)
                l_anchor_s = (l_anchor_s * bm).sum() / bm.sum().clamp(min=1.0)
                l_anchor_f = ((f_log - tf_t) ** 2 * bm[:, None]).mean(dim=1)
                l_anchor_f = (l_anchor_f * bm).sum() / bm.sum().clamp(min=1.0)
                l_anchor_m = ((m_log - tm_t) ** 2 * bm[:, None]).mean(dim=1)
                l_anchor_m = (l_anchor_m * bm).sum() / bm.sum().clamp(min=1.0)
                l_focal = _focal_bce_with_logits(
                    w_log, yb, pos_weight=pos_w, gamma=2.0, valid_mask=win_valid * bm,
                )
                l_sub = _sub_bce_dice_loss(s_log, sb, sample_weight=bm)
                loss = loss + 0.9 * l_anchor_w + 0.9 * l_anchor_s + 0.45 * l_anchor_f + 0.25 * l_anchor_m + 0.35 * l_focal + 0.25 * l_sub

            if torch.any(is_v43):
                hm = is_v43.to(torch.float32)
                hw = torch.where(b_kind == 1, 4.0, torch.where(b_kind == 2, 3.0, 2.5)) * hm
                l_hw = (F.binary_cross_entropy_with_logits(w_log, torch.zeros_like(w_log), reduction="none") * hw).sum() / hm.sum().clamp(min=1.0)
                l_hs = (F.binary_cross_entropy_with_logits(s_log, torch.zeros_like(s_log), reduction="none").mean(dim=1) * hw).sum() / hm.sum().clamp(min=1.0)
                # 对 Tailocin 与非噬菌体均明确压制 DNA 侧伪衣壳/连接蛋白 (P0, P1) 幻觉，不动 Tail/Lysis (P2, P3)
                l_hh = (F.binary_cross_entropy_with_logits(f_log[:, :2], torch.zeros_like(f_log[:, :2]), reduction="none").mean(dim=1) * hw).sum() / hm.sum().clamp(min=1.0)
                # 对质粒/ICE 压制全核心 P0..P4
                is_pl = is_v43 & (b_kind != 1)
                l_hpl = 0.0
                if torch.any(is_pl):
                    l_hpl = F.binary_cross_entropy_with_logits(f_log[is_pl, :5], torch.zeros_like(f_log[is_pl, :5]))
                loss = loss + 1.2 * l_hw + 0.55 * l_hs + 0.45 * l_hh + 0.35 * l_hpl

            scaler.scale(loss).backward()
            scaler.unscale_(opt)
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            scale_b = scaler.get_scale()
            scaler.step(opt)
            scaler.update()
            if not (device.type == "cuda" and scaler.get_scale() < scale_b):
                sched.step()
            ep_loss += float(loss.item())

        va_pred = _predict_v4_all(model, va_codes[va_keep], va_lens[va_keep], va_feats[va_keep], va_tokens[va_keep], va_counts[va_keep], device, batch_size=128)
        ap = float(average_precision_score(va_y[va_keep], va_pred["win_probs"]))
        h_pred = _predict_v4_all(model, hard["codes"], hard["lengths"], hard["features"], hard["tokens"], hard["counts"], device, batch_size=128)
        h_mean = float(np.mean(h_pred["win_probs"]))
        h_fp = float(np.mean(h_pred["win_probs"] >= 0.5))
        sc = ap - 0.12 * h_fp
        logger.info(
            "[Stage1.2 V4.3] Ep %d/%d loss=%.4f | Val_AUPRC=%.5f | HardDNA: meanP=%.4f FP@0.5=%.4f",
            ep,
            epochs,
            ep_loss / steps_per_ep,
            ap,
            h_mean,
            h_fp,
        )
        if sc > best_score:
            best_score = sc
            tmp_pt = out_s12_pt.with_name(f".{out_s12_pt.stem}.tmp.pt")
            torch.save(model.state_dict(), tmp_pt)
            tmp_pt.replace(out_s12_pt)

    model.load_state_dict(torch.load(out_s12_pt, map_location=device, weights_only=True))
    logger.info("Stage 1.2 主干微调完成 -> %s", out_s12_pt)

    # 5. 微调 context_refiner.pt（保持 256 -> 15D 同架构，加强正样本保护）
    del all_codes, all_feats, all_tokens, all_counts, all_sub, all_y, all_is_v43, all_kind
    gc.collect()

    ref_mask = np.isin(base_tags, CONTIG_REF_PARTS)
    ref_codes = np.concatenate([base_codes[ref_mask], hard["codes"]], axis=0)
    ref_lens = np.concatenate([base_lens[ref_mask], hard["lengths"]], axis=0)
    ref_feats = np.concatenate([base_feats[ref_mask], hard["features"]], axis=0)
    ref_tokens = np.concatenate([base_tokens[ref_mask], hard["tokens"]], axis=0)
    ref_counts = np.concatenate([base_counts[ref_mask], hard["counts"]], axis=0)
    ref_y = np.concatenate([base_clean_y[ref_mask], np.zeros(n_hard, dtype=np.int8)], axis=0)
    ref_cids = np.concatenate([base_cids[ref_mask], hard["cids"]], axis=0)
    ref_starts = np.concatenate([base_starts[ref_mask], hard["starts"]], axis=0)
    ref_tags = np.concatenate([base_tags[ref_mask], np.full(n_hard, "v4_3_hard", dtype=object)], axis=0)

    del base_codes, base_lens, base_feats, base_tokens, base_counts, base_sub, base_clean_y, base_orig_y, base_cids, base_starts, base_tags
    gc.collect()

    tr_c_pred = _predict_v4_all(model, ref_codes, ref_lens, ref_feats, ref_tokens, ref_counts, device, batch_size=128)
    va_c_pred = _predict_v4_all(model, va_c["codes"], va_c["lengths"], va_c["arrs"]["features"], va_c["tokens"], va_c["counts"], device, batch_size=128)
    del model, ref_codes, ref_feats, ref_tokens, ref_counts
    _clear_cuda()

    tr_sf = extract_refiner_step_features(tr_c_pred["win_logits"], tr_c_pred["sem_logits"], tr_c_pred["sub_probs"], ref_lens, max_len=5000, func_logits=tr_c_pred.get("func_logits"))
    va_sf = extract_refiner_step_features(va_c_pred["win_logits"], va_c_pred["sem_logits"], va_c_pred["sub_probs"], va_c["lengths"], max_len=5000, func_logits=va_c_pred.get("func_logits"))

    out_ref_pt = exp_s12_dir / "context_refiner.pt"
    ref_info = _finetune_context_refiner_v4_3(
        tr_sf,
        tr_c_pred["win_logits"],
        ref_y,
        ref_cids,
        ref_starts,
        ref_tags,
        va_sf,
        va_c_pred["win_logits"],
        va_c["orig_labels"],
        va_c["arrs"]["contig_ids"],
        va_c["arrs"]["starts"],
        v4_s12_dir / "context_refiner.pt",
        out_ref_pt,
        device=device,
        epochs=6,
        lr=8e-5,
    )

    # 6. 平滑复制 subbin_refiner 与元信息/阈值文件至沙盒 stage1_2 目录
    for fname in ("subbin_refiner.pt", "stage1_2_report.json", "stage1_2_scores.npz"):
        src_f = v4_s12_dir / fname
        if src_f.is_file():
            shutil.copy2(src_f, exp_s12_dir / fname)

    meta_out = dict(meta)
    meta_out["student_ckpt"] = str(out_s12_pt)
    meta_out["refiner_ckpt"] = str(out_ref_pt)
    meta_out["subbin_ckpt"] = str(exp_s12_dir / "subbin_refiner.pt")
    meta_out["v4_3_dna_finetune"] = {
        "hard_neg_windows": int(n_hard),
        "epochs": int(epochs),
        "lr": float(lr),
        "refiner_eval": ref_info,
        "elapsed_sec": round(time.perf_counter() - t0, 2),
    }
    (exp_s12_dir / "stage1_2_meta.json").write_text(json.dumps(meta_out, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("Stage 1.2 V4.3 沙盒全套落盘完成 -> %s (总耗时 %.2fs)", exp_s12_dir, time.perf_counter() - t0)
    return out_s12_pt


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phage-data-root", default=os.environ.get("PHAGE_DATA_ROOT", str(REPO_ROOT.parent / "Phage data")))
    ap.add_argument("--epochs", type=int, default=5)
    ap.add_argument("--batch-size", type=int, default=64)
    ap.add_argument("--lr", type=float, default=8e-5)
    ap.add_argument("--workers", type=int, default=16)
    args = ap.parse_args()
    finetune_stage1_2_v4_3(
        Path(args.phage_data_root).resolve(),
        epochs=args.epochs,
        batch_size=args.batch_size,
        lr=args.lr,
        workers=args.workers,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())