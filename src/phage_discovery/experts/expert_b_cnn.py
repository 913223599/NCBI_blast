# -*- coding: utf-8 -*-
"""
Expert B：端到端原始碱基序列专家（PyTorch 1D 膨胀残差卷积，RTX 4070 小显存友好）

- 输入：5 kb 窗口 one-hot（N/填充位全零），掩码均值池化 + 最大池化，避免填充稀释；
- 训练：反向互补随机增强、AMP 混合精度、类别平衡加权 BCE、AdamW + 余弦退火，按 val AUPRC 早停；
- 推理：正向与反向互补得分平均（RC 等变）；
- 显存：batch_size 默认 64，每个 epoch 结束与训练完成后执行 torch.cuda.empty_cache()。
"""
import argparse
import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import numpy as np

from ..benchmark.model_eval import evaluate_model_scores_on_split, load_split_info, tune_decoder_on_val
from ..data.feature_dataset import load_split_arrays
from ..features.window_features import SUB_BINS
from .seq_dataset import load_window_sequences, reverse_complement_codes

logger = logging.getLogger("phage_discovery.experts.expert_b_cnn")


def build_model(channels: int = 128, n_blocks: int = 6):
    import torch
    from torch import nn

    class ResBlock(nn.Module):
        def __init__(self, ch: int, dilation: int):
            super().__init__()
            self.conv1 = nn.Conv1d(ch, ch, kernel_size=5, padding=2 * dilation, dilation=dilation)
            self.bn1 = nn.BatchNorm1d(ch)
            self.conv2 = nn.Conv1d(ch, ch, kernel_size=5, padding=2 * dilation, dilation=dilation)
            self.bn2 = nn.BatchNorm1d(ch)
            self.act = nn.GELU()

        def forward(self, x):
            h = self.act(self.bn1(self.conv1(x)))
            h = self.bn2(self.conv2(h))
            return self.act(x + h)

    class SeqExpert(nn.Module):
        def __init__(self):
            super().__init__()
            half_blocks = max(1, n_blocks // 2)
            self.stem = nn.Sequential(
                nn.Conv1d(4, channels, kernel_size=15, padding=7),
                nn.BatchNorm1d(channels),
                nn.GELU(),
                nn.MaxPool1d(4),  # 5000 -> 1250
            )
            self.stage1 = nn.Sequential(*[ResBlock(channels, 2 ** (i % 3)) for i in range(half_blocks)])
            self.down2 = nn.Sequential(
                nn.Conv1d(channels, channels, kernel_size=9, padding=4),
                nn.BatchNorm1d(channels),
                nn.GELU(),
                nn.MaxPool1d(5),  # 1250 -> 250 (20 bp/step)
            )
            self.stage2 = nn.Sequential(*[ResBlock(channels, 2 ** (i % 3)) for i in range(n_blocks - half_blocks)])
            self.gru = nn.GRU(
                channels, channels // 2, num_layers=2, batch_first=True, bidirectional=True, dropout=0.15,
            )
            self.win_head = nn.Sequential(
                nn.Linear(channels * 2, 128),
                nn.GELU(),
                nn.Dropout(0.2),
                nn.Linear(128, 1),
            )
            self.sub_pool = nn.AdaptiveAvgPool1d(SUB_BINS)
            self.sub_head = nn.Sequential(
                nn.Conv1d(channels, 64, kernel_size=3, padding=1),
                nn.GELU(),
                nn.Conv1d(64, 1, kernel_size=1),
            )

        def forward(self, x, lengths):
            h = self.stage2(self.down2(self.stage1(self.stem(x))))
            h_seq, _ = self.gru(h.permute(0, 2, 1))
            h = h + h_seq.permute(0, 2, 1)
            t = h.shape[-1]
            valid = torch.clamp((lengths.float() / 20.0).ceil().long(), min=1, max=t)
            mask = (torch.arange(t, device=h.device)[None, :] < valid[:, None]).unsqueeze(1).to(h.dtype)
            mean_pool = (h * mask).sum(-1) / mask.sum(-1).clamp(min=1.0)
            max_pool = h.masked_fill(mask == 0, -1e4).max(-1).values
            win_logit = self.win_head(torch.cat([mean_pool, max_pool], dim=1)).squeeze(-1)
            sub_logits = self.sub_head(self.sub_pool(h)).squeeze(1)
            return win_logit, sub_logits

    return SeqExpert()


def _one_hot_batch(codes_np: np.ndarray, device):
    import torch

    codes = torch.from_numpy(codes_np.astype(np.int64)).to(device, non_blocking=True)
    oh = torch.nn.functional.one_hot(codes, num_classes=5)[..., :4]
    return oh.permute(0, 2, 1).float()


def _load_part(feature_dir: Path, bench_or_train_dir: Path, split: str, part: str, max_len: int):
    arrs = load_split_arrays(feature_dir, split, parts=(part,))
    manifest = json.loads((Path(bench_or_train_dir) / "benchmark_manifest.json").read_text(encoding="utf-8"))
    fasta = Path(manifest["splits"][split][part]["fasta"])
    codes, lengths = load_window_sequences(fasta, arrs["contig_ids"], arrs["starts"], arrs["ends"], max_len=max_len)
    return arrs, codes, lengths


def predict_scores(model, codes: np.ndarray, lengths: np.ndarray, device, batch_size: int = 128) -> np.ndarray:
    win_sc, _ = predict_scores_and_subprobs(model, codes, lengths, device, batch_size=batch_size)
    return win_sc


def predict_scores_and_subprobs(
    model, codes: np.ndarray, lengths: np.ndarray, device, batch_size: int = 128,
) -> Tuple[np.ndarray, np.ndarray]:
    import torch

    model.eval()
    n = len(lengths)
    out = np.zeros(n, dtype=np.float32)
    out_sub = np.zeros((n, SUB_BINS), dtype=np.float32)
    rc = reverse_complement_codes(codes, lengths)
    max_len = codes.shape[1]
    with torch.no_grad(), torch.autocast(device_type=device.type, dtype=torch.float16, enabled=device.type == "cuda"):
        for i in range(0, n, batch_size):
            ln = torch.from_numpy(lengths[i:i + batch_size]).to(device)
            w1, s1 = model(_one_hot_batch(codes[i:i + batch_size], device), ln)
            w2, s2 = model(_one_hot_batch(rc[i:i + batch_size], device), ln)
            p1, p2 = torch.sigmoid(w1), torch.sigmoid(w2)
            out[i:i + batch_size] = ((p1 + p2) / 2.0).float().cpu().numpy()
            sp1 = torch.sigmoid(s1)
            sp2 = torch.flip(torch.sigmoid(s2), dims=[1])
            full_mask = (ln == max_len).unsqueeze(1)
            sp = torch.where(full_mask, (sp1 + sp2) / 2.0, sp1)
            out_sub[i:i + batch_size] = sp.float().cpu().numpy()
    return out, out_sub


def train_expert_b(
    train_feature_dir: Path,
    train_dir: Path,
    eval_feature_dir: Path,
    bench_dir: Path,
    out_dir: Path,
    epochs: int = 14,
    batch_size: int = 64,
    lr: float = 1e-3,
    patience: int = 4,
    max_len: int = 5000,
    extra_mined_fasta: Optional[Path] = None,
    seed: int = 42,
) -> Dict[str, Any]:
    import torch
    from sklearn.metrics import average_precision_score

    torch.manual_seed(seed)
    rng = np.random.default_rng(seed)
    out_root = Path(out_dir).resolve()
    out_root.mkdir(parents=True, exist_ok=True)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    # 训练集 = 独立窗口 + 嵌合体滑窗（及可选 CheckV 真实前噬菌体切片）
    parts_tr = [_load_part(train_feature_dir, train_dir, "train", p, max_len) for p in ("windows", "chimeras")]
    mined_npz = Path(train_feature_dir) / "train_mined.npz"
    if extra_mined_fasta is not None and Path(extra_mined_fasta).exists() and mined_npz.exists():
        m_arrs = load_split_arrays(train_feature_dir, "train", parts=("mined",))
        if len(m_arrs["labels"]) > 0:
            m_codes, m_len = load_window_sequences(
                Path(extra_mined_fasta), m_arrs["contig_ids"], m_arrs["starts"], m_arrs["ends"], max_len=max_len,
            )
            parts_tr.append((m_arrs, m_codes, m_len))

    all_codes_tr = np.concatenate([p[1] for p in parts_tr])
    all_len_tr = np.concatenate([p[2] for p in parts_tr])
    all_y_tr = np.concatenate([p[0]["labels"] for p in parts_tr]).astype(np.int8)
    all_sub_tr = np.concatenate([p[0]["sub_mask"] for p in parts_tr]).astype(np.float32)

    keep = all_y_tr >= 0
    codes_tr, len_tr, y_tr, sub_tr = all_codes_tr[keep], all_len_tr[keep], all_y_tr[keep], all_sub_tr[keep]
    # 边界过渡窗 (-1) 的精确 sub_mask 也一起用于微调 200bp 断点分割头
    boundary_idx = np.where(all_y_tr == -1)[0]
    if boundary_idx.size > 0:
        codes_tr = np.concatenate([codes_tr, all_codes_tr[boundary_idx]])
        len_tr = np.concatenate([len_tr, all_len_tr[boundary_idx]])
        y_tr = np.concatenate([y_tr, all_y_tr[boundary_idx]])
        sub_tr = np.concatenate([sub_tr, all_sub_tr[boundary_idx]])
    del all_codes_tr, all_len_tr, all_y_tr, all_sub_tr, parts_tr

    va_win = _load_part(eval_feature_dir, bench_dir, "val", "windows", max_len)
    va_chim = _load_part(eval_feature_dir, bench_dir, "val", "chimeras", max_len)
    va_codes = np.concatenate([va_win[1], va_chim[1]])
    va_len = np.concatenate([va_win[2], va_chim[2]])
    va_y = np.concatenate([va_win[0]["labels"], va_chim[0]["labels"]])
    va_keep = va_y >= 0

    model = build_model().to(device)
    n_params = int(sum(p.numel() for p in model.parameters()))
    opt = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=1e-2)
    steps_per_epoch = int(np.ceil(len(y_tr) / batch_size))
    sched = torch.optim.lr_scheduler.OneCycleLR(opt, max_lr=lr, total_steps=epochs * steps_per_epoch)
    scaler = torch.amp.GradScaler("cuda", enabled=device.type == "cuda")
    pos_cnt = float(np.sum(y_tr == 1))
    neg_cnt = float(np.sum(y_tr == 0))
    pos_weight = torch.tensor(neg_cnt / max(1.0, pos_cnt), device=device)
    win_loss_fn = torch.nn.BCEWithLogitsLoss(pos_weight=pos_weight, reduction="none")
    sub_loss_fn = torch.nn.BCEWithLogitsLoss()

    best_ap = -1.0
    best_epoch = -1
    bad_epochs = 0
    history = []
    ckpt_path = out_root / "expert_b_cnn.pt"
    t0 = time.perf_counter()
    if device.type == "cuda":
        torch.cuda.reset_peak_memory_stats()

    for epoch in range(1, epochs + 1):
        model.train()
        order = rng.permutation(len(y_tr))
        ep_loss = 0.0
        for bi in range(steps_per_epoch):
            idx = order[bi * batch_size:(bi + 1) * batch_size]
            b_codes = codes_tr[idx].copy()
            b_len = len_tr[idx]
            b_sub = sub_tr[idx].copy()
            # 仅对满长窗口或纯正/纯负窗口同步做反向互补与 bin 翻转
            rc_mask = (b_len == max_len) | (b_sub.min(axis=1) == b_sub.max(axis=1))
            if rng.random() < 0.5 and np.any(rc_mask):
                b_codes[rc_mask] = reverse_complement_codes(b_codes[rc_mask], b_len[rc_mask])
                full_only = rc_mask & (b_len == max_len)
                b_sub[full_only] = b_sub[full_only, ::-1]
            x = _one_hot_batch(b_codes, device)
            ln = torch.from_numpy(b_len).to(device)
            yb_raw = y_tr[idx]
            win_valid = torch.from_numpy((yb_raw >= 0).astype(np.float32)).to(device)
            yb = torch.from_numpy(np.maximum(yb_raw, 0).astype(np.float32)).to(device)
            sb = torch.from_numpy(b_sub).to(device)
            opt.zero_grad(set_to_none=True)
            with torch.autocast(device_type=device.type, dtype=torch.float16, enabled=device.type == "cuda"):
                w_logit, s_logits = model(x, ln)
                loss_w = (win_loss_fn(w_logit, yb) * win_valid).sum() / win_valid.sum().clamp(min=1.0)
                loss_s = sub_loss_fn(s_logits, sb)
                loss = 0.7 * loss_w + 0.3 * loss_s
            scaler.scale(loss).backward()
            scaler.unscale_(opt)
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            scale_before = scaler.get_scale()
            scaler.step(opt)
            scaler.update()
            if not (device.type == "cuda" and scaler.get_scale() < scale_before):
                sched.step()
            ep_loss += float(loss.item()) * len(idx)

        va_scores = predict_scores(model, va_codes[va_keep], va_len[va_keep], device)
        ap = float(average_precision_score(va_y[va_keep], va_scores))
        history.append({"epoch": epoch, "train_loss": round(ep_loss / len(y_tr), 5), "val_auprc": round(ap, 5)})
        logger.info(f"epoch {epoch}: loss={ep_loss / len(y_tr):.4f} val_auprc={ap:.4f}")
        if device.type == "cuda":
            torch.cuda.empty_cache()
        if ap > best_ap:
            best_ap, best_epoch, bad_epochs = ap, epoch, 0
            tmp = out_root / ".expert_b_cnn.tmp.pt"
            torch.save(model.state_dict(), tmp)
            tmp.replace(ckpt_path)
        else:
            bad_epochs += 1
            if bad_epochs >= patience:
                break

    train_sec = round(time.perf_counter() - t0, 2)
    peak_mb = round(torch.cuda.max_memory_allocated() / (1024 * 1024), 1) if device.type == "cuda" else 0.0
    model.load_state_dict(torch.load(ckpt_path, map_location=device, weights_only=True))
    del codes_tr, len_tr, sub_tr

    va_win_scores = predict_scores(model, va_win[1], va_win[2], device)
    va_chim_scores, va_chim_sub = predict_scores_and_subprobs(model, va_chim[1], va_chim[2], device)
    decoder = tune_decoder_on_val(
        load_split_info(bench_dir, "val"), va_chim[0], va_chim_scores, chim_sub_probs=va_chim_sub,
    )

    te_win = _load_part(eval_feature_dir, bench_dir, "test", "windows", max_len)
    te_chim = _load_part(eval_feature_dir, bench_dir, "test", "chimeras", max_len)
    t1 = time.perf_counter()
    te_win_scores = predict_scores(model, te_win[1], te_win[2], device)
    te_chim_scores, te_chim_sub = predict_scores_and_subprobs(model, te_chim[1], te_chim[2], device)
    infer_sec = round(time.perf_counter() - t1, 3)

    # 保存窗口得分及 200bp 亚窗口边界概率，供后续专家融合与学生蒸馏使用
    np.savez_compressed(
        out_root / "expert_b_scores.npz",
        val_windows=va_win_scores, val_chimeras=va_chim_scores, val_chimeras_sub=va_chim_sub,
        test_windows=te_win_scores, test_chimeras=te_chim_scores, test_chimeras_sub=te_chim_sub,
    )

    val_report = evaluate_model_scores_on_split(
        bench_dir, "val", va_win[0], va_win_scores, va_chim[0], va_chim_scores,
        decoder["seed_threshold"], decoder["extend_threshold"],
        chim_sub_probs=va_chim_sub, sub_threshold=decoder.get("sub_threshold"),
    )
    test_report = evaluate_model_scores_on_split(
        bench_dir, "test", te_win[0], te_win_scores, te_chim[0], te_chim_scores,
        decoder["seed_threshold"], decoder["extend_threshold"],
        chim_sub_probs=te_chim_sub, sub_threshold=decoder.get("sub_threshold"),
    )
    del model
    if device.type == "cuda":
        torch.cuda.empty_cache()

    report: Dict[str, Any] = {
        "model_name": "ExpertB_ResBiGRU_SubSeg",
        "trained_at": datetime.now().isoformat(timespec="seconds"),
        "device": str(device),
        "params": n_params,
        "train_rows": int(np.sum(y_tr >= 0)),
        "train_boundary_sub_rows": int(np.sum(y_tr == -1)),
        "best_epoch": best_epoch,
        "best_val_auprc": round(best_ap, 5),
        "history": history,
        "train_sec": train_sec,
        "peak_gpu_mem_mb": peak_mb,
        "test_inference_sec": infer_sec,
        "decoder_tuned_on_val": decoder,
        "val": val_report,
        "test": test_report,
        "model_path": str(ckpt_path),
    }
    rep_path = out_root / "expert_b_report.json"
    tmp_rep = out_root / ".expert_b_report.tmp.json"
    tmp_rep.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_rep.replace(rep_path)
    report["report_path"] = str(rep_path)
    return report


def main() -> int:
    from .expert_a_xgb import summarize_report

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="训练 Expert B (1D 膨胀残差 CNN) 并在基准上评测")
    parser.add_argument("--train-feature-dir", required=True)
    parser.add_argument("--train-dir", required=True, help="训练集目录（含 benchmark_manifest.json 与 train FASTA）")
    parser.add_argument("--eval-feature-dir", required=True)
    parser.add_argument("--bench-dir", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--epochs", type=int, default=14)
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--extra-mined-fasta", default=None)
    args = parser.parse_args()
    report = train_expert_b(
        Path(args.train_feature_dir), Path(args.train_dir), Path(args.eval_feature_dir),
        Path(args.bench_dir), Path(args.out_dir), epochs=args.epochs, batch_size=args.batch_size,
        extra_mined_fasta=Path(args.extra_mined_fasta) if args.extra_mined_fasta else None,
    )
    summary = summarize_report({**report, "best_iteration": report["best_epoch"]})
    summary["peak_gpu_mem_mb"] = report["peak_gpu_mem_mb"]
    summary["train_sec"] = report["train_sec"]
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

