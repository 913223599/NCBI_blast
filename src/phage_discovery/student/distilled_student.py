# -*- coding: utf-8 -*-
"""
专家集成评估（Expert A/B/C Fusion）与双流知识蒸馏学生模型（ONNX 可导出）

核心设计：
1. 防泄题 OOF 教师软目标：采用 GroupKFold（按 contig_id 严格分组），用 5 折交叉样本外预测
   生成真实的软概率分布，避免教师在训练集上过拟合造成硬标签化泄题；
2. 轻量化双流学生架构（DistilledStudentNet）：
   - Branch 1: Depthwise-Separable 1D Dilated TCN 提取原始 DNA 局部基序表征；
   - Branch 2: 内置 Feature Standardizer (mean/std register_buffer) 的 MLP 提取 4-mer+上下文+Pyrodigal 特征；
   - Gated Fusion + 多任务头，同时结合 Focal Loss (严控假阳性) 与温度缩放 KL 蒸馏；
3. 自动导出为标准 ONNX 模型并做 onnx.checker 完整性校验与吞吐计时。
"""
import argparse
import json
import logging
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from ..benchmark.model_eval import evaluate_model_scores_on_split, load_split_info, tune_decoder_on_val
from ..data.feature_dataset import load_split_arrays
from ..experts.expert_a_xgb import summarize_report
from ..experts.seq_dataset import load_window_sequences, reverse_complement_codes
from ..features.window_features import SUB_BINS

logger = logging.getLogger("phage_discovery.student.distilled_student")


def evaluate_expert_ensemble(
    score_files: Dict[str, Path],
    eval_feature_dir: Path,
    bench_dir: Path,
    out_dir: Path,
) -> Dict[str, Any]:
    """
    在 val 集上搜索最优专家加权权重与滞回解码阈值，然后在 test 集上冻结评估。
    score_files: {"ExpertA": Path(".../expert_a_scores.npz"), ...}
    """
    from sklearn.metrics import average_precision_score

    out_root = Path(out_dir).resolve()
    out_root.mkdir(parents=True, exist_ok=True)

    names = sorted(score_files.keys())
    loaded = {n: dict(np.load(score_files[n])) for n in names}

    va_win = load_split_arrays(eval_feature_dir, "val", parts=("windows",))
    va_chim = load_split_arrays(eval_feature_dir, "val", parts=("chimeras",))
    te_win = load_split_arrays(eval_feature_dir, "test", parts=("windows",))
    te_chim = load_split_arrays(eval_feature_dir, "test", parts=("chimeras",))

    va_y = np.concatenate([va_win["labels"], va_chim["labels"]])
    va_keep = va_y >= 0

    def _blend(part_key: str, weights: Tuple[float, ...]) -> np.ndarray:
        acc = np.zeros_like(loaded[names[0]][part_key], dtype=np.float32)
        for w, n in zip(weights, names):
            acc += float(w) * loaded[n][part_key].astype(np.float32)
        return acc

    def _blend_sub(part_key: str, weights: Tuple[float, ...]) -> Optional[np.ndarray]:
        sub_items = [(w, loaded[n][part_key]) for w, n in zip(weights, names) if part_key in loaded[n] and w > 0]
        if not sub_items:
            sub_items = [(1.0, loaded[n][part_key]) for n in names if part_key in loaded[n]]
        if not sub_items:
            return None
        w_sum = sum(w for w, _ in sub_items)
        acc = np.zeros_like(sub_items[0][1], dtype=np.float32)
        for w, arr in sub_items:
            acc += (float(w) / w_sum) * arr.astype(np.float32)
        return acc

    # 在单纯形上枚举步长 0.1 的权重组合（确保非空、归一化），选 val_windows+chimeras AUPRC 最高者
    weight_grid: List[Tuple[float, ...]] = []
    if len(names) == 2:
        for i in range(11):
            weight_grid.append((round(i * 0.1, 2), round(1.0 - i * 0.1, 2)))
    elif len(names) == 3:
        for i in range(11):
            for j in range(11 - i):
                k = 10 - i - j
                weight_grid.append((round(i * 0.1, 2), round(j * 0.1, 2), round(k * 0.1, 2)))
    else:
        weight_grid.append(tuple([1.0 / len(names)] * len(names)))

    best_w = weight_grid[0]
    best_ap = -1.0
    for w in weight_grid:
        scores = np.concatenate([_blend("val_windows", w), _blend("val_chimeras", w)])[va_keep]
        ap = float(average_precision_score(va_y[va_keep], scores))
        if ap > best_ap:
            best_ap = ap
            best_w = w

    va_win_sc = _blend("val_windows", best_w)
    va_chim_sc = _blend("val_chimeras", best_w)
    te_win_sc = _blend("test_windows", best_w)
    te_chim_sc = _blend("test_chimeras", best_w)
    va_chim_sub = _blend_sub("val_chimeras_sub", best_w)
    te_chim_sub = _blend_sub("test_chimeras_sub", best_w)

    decoder = tune_decoder_on_val(
        load_split_info(bench_dir, "val"), va_chim, va_chim_sc, chim_sub_probs=va_chim_sub,
    )
    val_rep = evaluate_model_scores_on_split(
        bench_dir, "val", va_win, va_win_sc, va_chim, va_chim_sc,
        decoder["seed_threshold"], decoder["extend_threshold"],
        chim_sub_probs=va_chim_sub, sub_threshold=decoder.get("sub_threshold"),
    )
    test_rep = evaluate_model_scores_on_split(
        bench_dir, "test", te_win, te_win_sc, te_chim, te_chim_sc,
        decoder["seed_threshold"], decoder["extend_threshold"],
        chim_sub_probs=te_chim_sub, sub_threshold=decoder.get("sub_threshold"),
    )

    report: Dict[str, Any] = {
        "model_name": "Ensemble_" + "_".join(names),
        "evaluated_at": datetime.now().isoformat(timespec="seconds"),
        "weights": {n: w for n, w in zip(names, best_w)},
        "val_combined_auprc": round(best_ap, 5),
        "decoder_tuned_on_val": decoder,
        "val": val_rep,
        "test": test_rep,
    }
    rep_path = out_root / "ensemble_report.json"
    tmp = rep_path.with_name(f".{rep_path.name}.tmp")
    tmp.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(rep_path)
    report["report_path"] = str(rep_path)
    return report


def compute_group_oof_xgb_probs(
    features: np.ndarray,
    labels: np.ndarray,
    contig_ids: np.ndarray,
    n_splits: int = 5,
    n_estimators: int = 600,
    sample_weights: Optional[np.ndarray] = None,
) -> np.ndarray:
    """
    使用 GroupKFold（严格按 contig_id 分组，同 contig 的相邻滑窗永不跨折）
    生成样本外无泄题软标签概率，用于知识蒸馏。
    """
    import torch
    import xgboost as xgb
    from sklearn.model_selection import GroupKFold

    unique_groups = int(np.unique(contig_ids).size)
    k = min(n_splits, max(2, unique_groups))
    gkf = GroupKFold(n_splits=k)
    oof = np.zeros(len(labels), dtype=np.float32)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    cpu_cnt = os.cpu_count() or 4

    for tr_idx, va_idx in gkf.split(features, labels, groups=contig_ids):
        y_fold = labels[tr_idx]
        n_pos = max(1, int(np.sum(y_fold == 1)))
        n_neg = max(1, int(np.sum(y_fold == 0)))
        w = np.where(y_fold == 1, 0.5 / n_pos, 0.5 / n_neg).astype(np.float32)
        if sample_weights is not None:
            w *= sample_weights[tr_idx].astype(np.float32)
        w *= len(y_fold) / max(1e-6, float(w.sum()))

        clf = xgb.XGBClassifier(
            n_estimators=n_estimators,
            max_depth=6,
            learning_rate=0.05,
            subsample=0.85,
            colsample_bytree=0.75,
            reg_lambda=2.0,
            tree_method="hist",
            device=device,
            n_jobs=max(1, cpu_cnt - 2),
        )
        clf.fit(features[tr_idx], y_fold, sample_weight=w, verbose=False)
        clf.set_params(device="cpu")
        oof[va_idx] = clf.predict_proba(features[va_idx])[:, 1].astype(np.float32)

    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    return np.clip(oof, 1e-4, 1.0 - 1e-4)


def build_distilled_student(feat_dim: int, feat_mean: np.ndarray, feat_std: np.ndarray):
    """构建双流门控 + 200bp 亚窗口边界分割学生网络（内置特征归一化 buffer，可直出 ONNX）。"""
    import torch
    from torch import nn

    class DWSepBlock(nn.Module):
        def __init__(self, ch: int, dilation: int):
            super().__init__()
            self.dw = nn.Conv1d(ch, ch, kernel_size=5, padding=2 * dilation, dilation=dilation, groups=ch)
            self.pw = nn.Conv1d(ch, ch, kernel_size=1)
            self.bn = nn.BatchNorm1d(ch)
            self.act = nn.GELU()

        def forward(self, x):
            return self.act(x + self.bn(self.pw(self.dw(x))))

    class DistilledStudentNet(nn.Module):
        def __init__(self):
            super().__init__()
            self.register_buffer("feat_mean", torch.from_numpy(feat_mean.astype(np.float32)))
            self.register_buffer("feat_std", torch.from_numpy(np.maximum(feat_std, 1e-5).astype(np.float32)))

            # Stream 1: Multi-Scale Depthwise-Separable DNA TCN (5000 -> 1250 -> 250 -> 25 bins)
            self.dna_stage1 = nn.Sequential(
                nn.Conv1d(4, 48, kernel_size=12, stride=4, padding=4),  # 5000 -> 1250
                nn.BatchNorm1d(48),
                nn.GELU(),
                DWSepBlock(48, 1),
                DWSepBlock(48, 2),
                nn.MaxPool1d(5),  # 1250 -> 250
            )
            self.dna_stage2 = nn.Sequential(
                nn.Conv1d(48, 96, kernel_size=7, padding=3),
                nn.BatchNorm1d(96),
                nn.GELU(),
                DWSepBlock(96, 1),
                DWSepBlock(96, 2),
                DWSepBlock(96, 4),
                DWSepBlock(96, 8),
            )
            self.dna_proj = nn.Sequential(nn.Linear(192, 128), nn.LayerNorm(128), nn.GELU())
            self.sub_pool = nn.AvgPool1d(kernel_size=10, stride=10)  # 250 -> 25 bins (ONNX 友好)

            # Stream 2: 185-dim Codon/AA/Flank/Context Residual MLP
            self.tab_net = nn.Sequential(
                nn.Linear(feat_dim, 256),
                nn.LayerNorm(256),
                nn.GELU(),
                nn.Dropout(0.15),
                nn.Linear(256, 128),
                nn.LayerNorm(128),
                nn.GELU(),
            )

            # Cross-Modal Gated Fusion + Window & Boundary Heads
            self.gate = nn.Sequential(nn.Linear(256, 128), nn.Sigmoid())
            self.win_head = nn.Sequential(
                nn.Linear(256, 128),
                nn.GELU(),
                nn.Dropout(0.15),
                nn.Linear(128, 1),
            )
            self.sub_head = nn.Sequential(
                nn.Conv1d(96 + 128, 96, kernel_size=3, padding=1),
                nn.BatchNorm1d(96),
                nn.GELU(),
                nn.Conv1d(96, 1, kernel_size=1),
            )

        def forward(self, dna_oh: torch.Tensor, tab_feats: torch.Tensor) -> Tuple[torch.Tensor, torch.Tensor]:
            h_dna = self.dna_stage2(self.dna_stage1(dna_oh))
            dna_emb = self.dna_proj(torch.cat([h_dna.mean(-1), h_dna.amax(-1)], dim=-1))

            norm_tab = (tab_feats - self.feat_mean) / self.feat_std
            tab_emb = self.tab_net(norm_tab)

            cat = torch.cat([dna_emb, tab_emb], dim=-1)
            g = self.gate(cat)
            fused = torch.cat([g * dna_emb + (1.0 - g) * tab_emb, tab_emb], dim=-1)
            win_logit = self.win_head(fused).squeeze(-1)

            h_sub = self.sub_pool(h_dna)  # (B, 96, 25)
            tab_exp = tab_emb.unsqueeze(-1).expand(-1, -1, h_sub.shape[-1])
            sub_logits = self.sub_head(torch.cat([h_sub, tab_exp], dim=1)).squeeze(1)
            return win_logit, sub_logits

    return DistilledStudentNet()


def _focal_bce_with_logits(
    logits, targets, pos_weight: float = 1.0, gamma: float = 2.0, valid_mask=None, sample_weight=None,
):
    import torch
    import torch.nn.functional as F

    bce = F.binary_cross_entropy_with_logits(logits, targets, reduction="none")
    prob = torch.sigmoid(logits)
    pt = torch.where(targets >= 0.5, prob, 1.0 - prob)
    w = torch.where(targets >= 0.5, pos_weight, 1.0)
    if sample_weight is not None:
        w = w * sample_weight
    loss = w * ((1.0 - pt) ** gamma) * bce
    if valid_mask is not None:
        return (loss * valid_mask).sum() / valid_mask.sum().clamp(min=1.0)
    return loss.mean()


def _kd_bce_loss(
    student_logits, teacher_probs, temperature: float = 2.0, valid_mask=None, sample_weight=None,
):
    import torch
    import torch.nn.functional as F

    t_logits = torch.logit(torch.clamp(teacher_probs, 1e-4, 1.0 - 1e-4))
    soft_targets = torch.sigmoid(t_logits / temperature)
    loss = (temperature ** 2) * F.binary_cross_entropy_with_logits(
        student_logits / temperature, soft_targets, reduction="none",
    )
    if sample_weight is not None:
        loss = loss * sample_weight
    if valid_mask is not None:
        return (loss * valid_mask).sum() / valid_mask.sum().clamp(min=1.0)
    return loss.mean()


def _sub_bce_dice_loss(sub_logits, sub_targets, sample_weight=None):
    import torch
    import torch.nn.functional as F

    bce_elem = F.binary_cross_entropy_with_logits(sub_logits, sub_targets, reduction="none").mean(dim=1)
    probs = torch.sigmoid(sub_logits)
    inter = (probs * sub_targets).sum(dim=1)
    union = probs.sum(dim=1) + sub_targets.sum(dim=1)
    dice = 1.0 - (2.0 * inter + 1.0) / (union + 1.0)
    per_sample = 0.65 * bce_elem + 0.35 * dice
    if sample_weight is not None:
        return (per_sample * sample_weight).sum() / sample_weight.sum().clamp(min=1.0)
    return per_sample.mean()


def _predict_student(
    model, codes: np.ndarray, lengths: np.ndarray, feats: np.ndarray, device, batch_size: int = 128,
) -> Tuple[np.ndarray, np.ndarray]:
    import torch

    model.eval()
    n = len(feats)
    out = np.zeros(n, dtype=np.float32)
    out_sub = np.zeros((n, SUB_BINS), dtype=np.float32)
    rc = reverse_complement_codes(codes, lengths)
    max_len = codes.shape[1]
    with torch.no_grad(), torch.autocast(device_type=device.type, dtype=torch.float16, enabled=device.type == "cuda"):
        for i in range(0, n, batch_size):
            c1 = torch.from_numpy(codes[i:i + batch_size].astype(np.int64)).to(device)
            oh1 = torch.nn.functional.one_hot(c1, num_classes=5)[..., :4].permute(0, 2, 1).float()
            c2 = torch.from_numpy(rc[i:i + batch_size].astype(np.int64)).to(device)
            oh2 = torch.nn.functional.one_hot(c2, num_classes=5)[..., :4].permute(0, 2, 1).float()
            tb = torch.from_numpy(feats[i:i + batch_size]).to(device)
            ln = torch.from_numpy(lengths[i:i + batch_size]).to(device)
            w1, s1 = model(oh1, tb)
            w2, s2 = model(oh2, tb)
            p1, p2 = torch.sigmoid(w1), torch.sigmoid(w2)
            out[i:i + batch_size] = ((p1 + p2) / 2.0).float().cpu().numpy()
            sp1 = torch.sigmoid(s1)
            sp2 = torch.flip(torch.sigmoid(s2), dims=[1])
            sp = torch.where((ln == max_len).unsqueeze(1), (sp1 + sp2) / 2.0, sp1)
            out_sub[i:i + batch_size] = sp.float().cpu().numpy()
    return out, out_sub


def _load_seq_and_feat(
    feature_dir: Path, manifest_dir: Path, split: str, part: str, max_len: int, fasta_override: Optional[Path] = None,
):
    arrs = load_split_arrays(feature_dir, split, parts=(part,))
    if fasta_override is not None:
        fasta = Path(fasta_override)
    else:
        manifest = json.loads((Path(manifest_dir) / "benchmark_manifest.json").read_text(encoding="utf-8"))
        fasta = Path(manifest["splits"][split][part]["fasta"])
    codes, lengths = load_window_sequences(fasta, arrs["contig_ids"], arrs["starts"], arrs["ends"], max_len=max_len)
    return arrs, codes, lengths


def train_distilled_student(
    train_feature_dir: Path,
    train_dir: Path,
    eval_feature_dir: Path,
    bench_dir: Path,
    out_dir: Path,
    epochs: int = 22,
    batch_size: int = 64,
    lr: float = 1.2e-3,
    kd_alpha: float = 0.45,
    sub_weight: float = 0.35,
    temperature: float = 2.0,
    max_len: int = 5000,
    patience: int = 6,
    extra_mined_fasta: Optional[Path] = None,
    extra_sources: Optional[Sequence[Tuple[str, Path, float]]] = None,
    seed: int = 42,
) -> Dict[str, Any]:
    """训练高精度双流蒸馏+200bp边界分割学生模型，导出 ONNX 并完成完整基准评测。"""
    import onnx
    import torch
    from sklearn.metrics import average_precision_score

    torch.manual_seed(seed)
    rng = np.random.default_rng(seed)
    out_root = Path(out_dir).resolve()
    out_root.mkdir(parents=True, exist_ok=True)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    tr_w = _load_seq_and_feat(train_feature_dir, train_dir, "train", "windows", max_len)
    tr_c = _load_seq_and_feat(train_feature_dir, train_dir, "train", "chimeras", max_len)
    tr_parts = [tr_w, tr_c]
    tr_weights = [
        np.ones(len(tr_w[0]["labels"]), dtype=np.float32),
        np.ones(len(tr_c[0]["labels"]), dtype=np.float32),
    ]

    resolved_extras: List[Tuple[str, Path, float]] = []
    if extra_sources:
        resolved_extras.extend([(str(p), Path(fp), float(w)) for p, fp, w in extra_sources])
    elif extra_mined_fasta is not None:
        resolved_extras.append(("mined", Path(extra_mined_fasta), 1.0))

    for part_name, fasta_p, part_w in resolved_extras:
        part_npz = Path(train_feature_dir) / f"train_{part_name}.npz"
        if fasta_p.exists() and part_npz.exists():
            tr_ext = _load_seq_and_feat(
                train_feature_dir, train_dir, "train", part_name, max_len, fasta_override=fasta_p,
            )
            n_ext = len(tr_ext[0]["labels"])
            if n_ext > 0:
                tr_parts.append(tr_ext)
                tr_weights.append(np.full(n_ext, float(part_w), dtype=np.float32))
                logger.info(f"并入扩展分片 train_{part_name}: rows={n_ext}, sample_weight={part_w}")

    feats_all = np.concatenate([p[0]["features"] for p in tr_parts])
    y_all = np.concatenate([p[0]["labels"] for p in tr_parts]).astype(np.int8)
    sub_all = np.concatenate([p[0]["sub_mask"] for p in tr_parts]).astype(np.float32)
    cids_all = np.concatenate([p[0]["contig_ids"] for p in tr_parts])
    codes_all = np.concatenate([p[1] for p in tr_parts])
    len_all = np.concatenate([p[2] for p in tr_parts])
    sw_all = np.concatenate(tr_weights)
    del tr_parts, tr_w, tr_c, tr_weights

    keep = y_all >= 0
    feats_tr = feats_all[keep]
    y_tr = y_all[keep]
    cids_tr = cids_all[keep]
    codes_tr = codes_all[keep]
    len_tr = len_all[keep]
    sub_tr = sub_all[keep]
    sw_tr = sw_all[keep]

    # 生成严格防泄露 5 折 GroupKFold 样本外教师软标签（仅在确定标签窗口 fit）
    t_oof = time.perf_counter()
    teacher_probs_clean = compute_group_oof_xgb_probs(
        feats_tr, y_tr.astype(np.int32), cids_tr, n_splits=5, sample_weights=sw_tr,
    )
    oof_sec = round(time.perf_counter() - t_oof, 2)

    # 并入边界过渡窗 (-1) 专门监督 200bp 边界分割头
    bnd_idx = np.where(y_all == -1)[0]
    if bnd_idx.size > 0:
        feats_tr = np.concatenate([feats_tr, feats_all[bnd_idx]])
        y_tr = np.concatenate([y_tr, y_all[bnd_idx]])
        codes_tr = np.concatenate([codes_tr, codes_all[bnd_idx]])
        len_tr = np.concatenate([len_tr, len_all[bnd_idx]])
        sub_tr = np.concatenate([sub_tr, sub_all[bnd_idx]])
        sw_tr = np.concatenate([sw_tr, sw_all[bnd_idx]])
        teacher_probs_tr = np.concatenate([teacher_probs_clean, np.full(bnd_idx.size, 0.5, dtype=np.float32)])
    else:
        teacher_probs_tr = teacher_probs_clean
    del feats_all, y_all, sub_all, cids_all, codes_all, len_all, sw_all

    va_w = _load_seq_and_feat(eval_feature_dir, bench_dir, "val", "windows", max_len)
    va_c = _load_seq_and_feat(eval_feature_dir, bench_dir, "val", "chimeras", max_len)
    va_feats = np.concatenate([va_w[0]["features"], va_c[0]["features"]])
    va_codes = np.concatenate([va_w[1], va_c[1]])
    va_len = np.concatenate([va_w[2], va_c[2]])
    va_y = np.concatenate([va_w[0]["labels"], va_c[0]["labels"]])
    va_keep = va_y >= 0

    clean_mask = y_tr >= 0
    feat_mean = feats_tr[clean_mask].mean(axis=0)
    feat_std = feats_tr[clean_mask].std(axis=0)
    model = build_distilled_student(feats_tr.shape[1], feat_mean, feat_std).to(device)
    n_params = int(sum(p.numel() for p in model.parameters()))

    opt = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=1e-2)
    steps_per_ep = int(np.ceil(len(y_tr) / batch_size))
    sched = torch.optim.lr_scheduler.OneCycleLR(opt, max_lr=lr, total_steps=epochs * steps_per_ep)
    scaler = torch.amp.GradScaler("cuda", enabled=device.type == "cuda")
    neg_mass = float(np.sum(sw_tr[y_tr == 0]))
    pos_mass = max(1e-6, float(np.sum(sw_tr[y_tr == 1])))
    pos_weight = neg_mass / pos_mass

    ckpt_path = out_root / "student_distilled.pt"
    best_ap = -1.0
    best_ep = -1
    bad_ep = 0
    history = []
    if device.type == "cuda":
        torch.cuda.reset_peak_memory_stats()

    t0 = time.perf_counter()
    for ep in range(1, epochs + 1):
        model.train()
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

            c_t = torch.from_numpy(b_codes.astype(np.int64)).to(device, non_blocking=True)
            oh = torch.nn.functional.one_hot(c_t, num_classes=5)[..., :4].permute(0, 2, 1).float()
            tb = torch.from_numpy(feats_tr[idx]).to(device, non_blocking=True)
            yb_raw = y_tr[idx]
            win_valid = torch.from_numpy((yb_raw >= 0).astype(np.float32)).to(device, non_blocking=True)
            yb = torch.from_numpy(np.maximum(yb_raw, 0).astype(np.float32)).to(device, non_blocking=True)
            tp = torch.from_numpy(teacher_probs_tr[idx]).to(device, non_blocking=True)
            sb = torch.from_numpy(b_sub).to(device, non_blocking=True)
            wb = torch.from_numpy(sw_tr[idx]).to(device, non_blocking=True)

            opt.zero_grad(set_to_none=True)
            with torch.autocast(device_type=device.type, dtype=torch.float16, enabled=device.type == "cuda"):
                win_logits, sub_logits = model(oh, tb)
                loss_sup = _focal_bce_with_logits(
                    win_logits, yb, pos_weight=pos_weight, gamma=2.0, valid_mask=win_valid, sample_weight=wb,
                )
                loss_kd = _kd_bce_loss(
                    win_logits, tp, temperature=temperature, valid_mask=win_valid, sample_weight=wb,
                )
                loss_sub = _sub_bce_dice_loss(sub_logits, sb, sample_weight=wb)
                loss = (1.0 - kd_alpha) * loss_sup + kd_alpha * loss_kd + sub_weight * loss_sub

            scaler.scale(loss).backward()
            scaler.unscale_(opt)
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            scale_before = scaler.get_scale()
            scaler.step(opt)
            scaler.update()
            if not (device.type == "cuda" and scaler.get_scale() < scale_before):
                sched.step()
            ep_loss += float(loss.item()) * len(idx)

        va_sc, _ = _predict_student(model, va_codes[va_keep], va_len[va_keep], va_feats[va_keep], device)
        ap = float(average_precision_score(va_y[va_keep], va_sc))
        history.append({"epoch": ep, "train_loss": round(ep_loss / len(y_tr), 5), "val_auprc": round(ap, 5)})
        logger.info(f"student epoch {ep}: loss={ep_loss / len(y_tr):.4f} val_auprc={ap:.4f}")
        if device.type == "cuda":
            torch.cuda.empty_cache()

        if ap > best_ap:
            best_ap, best_ep, bad_ep = ap, ep, 0
            tmp = out_root / ".student_distilled.tmp.pt"
            torch.save(model.state_dict(), tmp)
            tmp.replace(ckpt_path)
        else:
            bad_ep += 1
            if bad_ep >= patience:
                break

    train_sec = round(time.perf_counter() - t0, 2)
    peak_mb = round(torch.cuda.max_memory_allocated() / (1024 * 1024), 1) if device.type == "cuda" else 0.0
    model.load_state_dict(torch.load(ckpt_path, map_location=device, weights_only=True))
    del codes_tr, len_tr, feats_tr, sub_tr

    va_win_sc, _ = _predict_student(model, va_w[1], va_w[2], va_w[0]["features"], device)
    va_chim_sc, va_chim_sub = _predict_student(model, va_c[1], va_c[2], va_c[0]["features"], device)
    decoder = tune_decoder_on_val(
        load_split_info(bench_dir, "val"), va_c[0], va_chim_sc, chim_sub_probs=va_chim_sub,
    )

    te_w = _load_seq_and_feat(eval_feature_dir, bench_dir, "test", "windows", max_len)
    te_c = _load_seq_and_feat(eval_feature_dir, bench_dir, "test", "chimeras", max_len)
    t1 = time.perf_counter()
    te_win_sc, _ = _predict_student(model, te_w[1], te_w[2], te_w[0]["features"], device)
    te_chim_sc, te_chim_sub = _predict_student(model, te_c[1], te_c[2], te_c[0]["features"], device)
    infer_sec = round(time.perf_counter() - t1, 3)

    np.savez_compressed(
        out_root / "student_scores.npz",
        val_windows=va_win_sc, val_chimeras=va_chim_sc, val_chimeras_sub=va_chim_sub,
        test_windows=te_win_sc, test_chimeras=te_chim_sc, test_chimeras_sub=te_chim_sub,
    )

    val_rep = evaluate_model_scores_on_split(
        bench_dir, "val", va_w[0], va_win_sc, va_c[0], va_chim_sc,
        decoder["seed_threshold"], decoder["extend_threshold"],
        chim_sub_probs=va_chim_sub, sub_threshold=decoder.get("sub_threshold"),
    )
    test_rep = evaluate_model_scores_on_split(
        bench_dir, "test", te_w[0], te_win_sc, te_c[0], te_chim_sc,
        decoder["seed_threshold"], decoder["extend_threshold"],
        chim_sub_probs=te_chim_sub, sub_threshold=decoder.get("sub_threshold"),
    )

    # 导出双输出 ONNX（窗口概率 + 200bp 边界分割）并执行结构完整性校验
    onnx_path = out_root / "student_model.onnx"
    tmp_onnx = out_root / ".student_model.tmp.onnx"
    model_cpu = model.to("cpu").eval()
    dummy_dna = torch.zeros(1, 4, max_len, dtype=torch.float32)
    dummy_tab = torch.zeros(1, te_w[0]["features"].shape[1], dtype=torch.float32)
    torch.onnx.export(
        model_cpu,
        (dummy_dna, dummy_tab),
        str(tmp_onnx),
        input_names=["dna_one_hot", "window_features"],
        output_names=["phage_logit", "sub_logits"],
        dynamic_axes={
            "dna_one_hot": {0: "batch"},
            "window_features": {0: "batch"},
            "phage_logit": {0: "batch"},
            "sub_logits": {0: "batch"},
        },
        opset_version=17,
    )
    onnx_model = onnx.load(str(tmp_onnx))
    onnx.checker.check_model(onnx_model)
    tmp_onnx.replace(onnx_path)
    onnx_size_mb = round(onnx_path.stat().st_size / (1024 * 1024), 3)

    del model, model_cpu
    if torch.cuda.is_available():
        torch.cuda.empty_cache()

    total_test_mb = float(test_rep["chimera_benchmark"]["overall"].get("total_scanned_mb") or 20.862)
    est_sec_per_5mb = round((infer_sec / total_test_mb) * 5.0, 3)

    report: Dict[str, Any] = {
        "model_name": "StudentPro_Distilled_SubSeg",
        "trained_at": datetime.now().isoformat(timespec="seconds"),
        "device": str(device),
        "params": n_params,
        "onnx_path": str(onnx_path),
        "onnx_size_mb": onnx_size_mb,
        "oof_teacher_sec": oof_sec,
        "train_sec": train_sec,
        "peak_gpu_mem_mb": peak_mb,
        "test_inference_sec": infer_sec,
        "est_sec_per_5mb": est_sec_per_5mb,
        "train_rows": int(np.sum(y_tr >= 0)),
        "train_boundary_sub_rows": int(np.sum(y_tr == -1)),
        "best_epoch": best_ep,
        "best_val_auprc": round(best_ap, 5),
        "history": history,
        "decoder_tuned_on_val": decoder,
        "val": val_rep,
        "test": test_rep,
        "model_path": str(ckpt_path),
    }
    rep_path = out_root / "student_report.json"
    tmp_rep = out_root / ".student_report.tmp.json"
    tmp_rep.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_rep.replace(rep_path)
    report["report_path"] = str(rep_path)
    return report


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="集成评估或训练双流蒸馏学生模型")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_ens = sub.add_parser("ensemble")
    p_ens.add_argument("--scores", nargs="+", required=True, help="格式 Name=path/to/scores.npz")
    p_ens.add_argument("--eval-feature-dir", required=True)
    p_ens.add_argument("--bench-dir", required=True)
    p_ens.add_argument("--out-dir", required=True)

    p_stu = sub.add_parser("train-student")
    p_stu.add_argument("--train-feature-dir", required=True)
    p_stu.add_argument("--train-dir", required=True)
    p_stu.add_argument("--eval-feature-dir", required=True)
    p_stu.add_argument("--bench-dir", required=True)
    p_stu.add_argument("--out-dir", required=True)
    p_stu.add_argument("--epochs", type=int, default=22)
    p_stu.add_argument("--batch-size", type=int, default=64)
    p_stu.add_argument("--extra-mined-fasta", default=None)

    args = parser.parse_args()
    if args.cmd == "ensemble":
        score_map = {}
        for item in args.scores:
            name, path_str = item.split("=", 1)
            score_map[name] = Path(path_str)
        rep = evaluate_expert_ensemble(score_map, Path(args.eval_feature_dir), Path(args.bench_dir), Path(args.out_dir))
        print(json.dumps({"weights": rep["weights"], **summarize_report({**rep, "device": "fusion", "train_rows": 0, "best_iteration": 0})}, ensure_ascii=False, indent=2))
        return 0

    rep = train_distilled_student(
        Path(args.train_feature_dir), Path(args.train_dir), Path(args.eval_feature_dir),
        Path(args.bench_dir), Path(args.out_dir), epochs=args.epochs, batch_size=args.batch_size,
        extra_mined_fasta=Path(args.extra_mined_fasta) if args.extra_mined_fasta else None,
    )
    summary = summarize_report({**rep, "best_iteration": rep["best_epoch"]})
    summary["onnx_size_mb"] = rep["onnx_size_mb"]
    summary["est_sec_per_5mb"] = rep["est_sec_per_5mb"]
    summary["peak_gpu_mem_mb"] = rep["peak_gpu_mem_mb"]
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

