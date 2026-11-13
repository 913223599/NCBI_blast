# -*- coding: utf-8 -*-
"""
Expert C：ORF 语法拓扑序列专家（Pyrodigal 基因 Token + Transformer Encoder）

设计特点：
1. 训练与推理同源：统一使用 Pyrodigal (meta=True) 从原始 DNA 预测 ORF，不依赖不同来源的 GenBank 注释；
2. 每个基因 Token 编码 30 维特征：8 维基因拓扑语法（长度、链向、GC 及其上下文偏离、基因间隔/重叠、相对位置）
   + 20 维标准氨基酸频率 + 2 维理化统计（疏水残基占比、带电残基占比）；
3. 轻量化 2 层 TransformerEncoder（d_model=64, nhead=4）建模连续 ORF 操纵子排布语法；
4. 自动多核提取 ORF Token 并保存模型、评分及完整 v1 val/test 报告。
"""
import argparse
import concurrent.futures
import json
import logging
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from ..benchmark.model_eval import evaluate_model_scores_on_split, load_split_info, tune_decoder_on_val
from ..data.feature_dataset import iter_fasta, load_split_arrays

logger = logging.getLogger("phage_discovery.experts.expert_c_orf")

AA_ALPHABET = "ACDEFGHIKLMNPQRSTVWY"
_AA_LUT = np.full(256, -1, dtype=np.int16)
for _idx, _aa in enumerate(AA_ALPHABET):
    _AA_LUT[ord(_aa)] = _idx
_HYDROPHOBIC = set("AVILMFYW")
_CHARGED = set("DEKRH")

ORF_FEAT_DIM = 30
MAX_ORFS_PER_WIN = 36
_GF = None


def _get_gf():
    global _GF
    if _GF is None:
        import pyrodigal

        _GF = pyrodigal.GeneFinder(meta=True, mask=True)
    return _GF


def _encode_protein_22(aa_seq: str) -> np.ndarray:
    """编码 20 维标准氨基酸频率 + 疏水性比例 + 带电比例。"""
    out = np.zeros(22, dtype=np.float32)
    if not aa_seq:
        return out
    arr = np.frombuffer(aa_seq.encode("ascii", errors="replace"), dtype=np.uint8)
    idx = _AA_LUT[arr]
    valid = idx[idx >= 0]
    n = max(1, len(aa_seq))
    if valid.size > 0:
        out[:20] = np.bincount(valid, minlength=20).astype(np.float32) / float(n)
    hydro = sum(1 for ch in aa_seq if ch in _HYDROPHOBIC)
    charged = sum(1 for ch in aa_seq if ch in _CHARGED)
    out[20] = hydro / float(n)
    out[21] = charged / float(n)
    return out


def _extract_contig_orfs_worker(
    item: Tuple[str, str, List[Tuple[int, int, int]]],
) -> List[Tuple[int, np.ndarray, int]]:
    """
    输入 (contig_id, seq, [(row_idx, start_bp, end_bp), ...])，对整条 contig 预测一次基因，
    然后映射至各窗口，返回 [(row_idx, token_matrix(MAX_ORFS, 30), valid_count), ...]。
    """
    _, seq, win_items = item
    seq = seq.upper()
    n_seq = max(1, len(seq))
    ctx_gc = (seq.count("G") + seq.count("C")) / float(n_seq)

    genes_info: List[Tuple[int, int, int, float, np.ndarray]] = []
    if len(seq) >= 100:
        gf = _get_gf()
        found = gf.find_genes(seq.encode("ascii", errors="replace"))
        for g in found:
            s0 = int(g.begin) - 1
            e0 = int(g.end)
            sub = seq[s0:e0]
            sub_len = max(1, len(sub))
            gc = (sub.count("G") + sub.count("C")) / float(sub_len)
            aa = g.translate()
            genes_info.append((s0, e0, int(g.strand), gc, _encode_protein_22(aa)))
        genes_info.sort(key=lambda t: t[0])

    outputs: List[Tuple[int, np.ndarray, int]] = []
    for row_idx, ws, we in win_items:
        wlen = max(1, we - ws)
        in_win = [g for g in genes_info if ws <= (g[0] + g[1]) // 2 < we][:MAX_ORFS_PER_WIN]
        mat = np.zeros((MAX_ORFS_PER_WIN, ORF_FEAT_DIM), dtype=np.float32)
        for ti, (gs, ge, strand, gc, aa_vec) in enumerate(in_win):
            glen = max(1, ge - gs)
            prev_end = in_win[ti - 1][1] if ti > 0 else ws
            gap = gs - prev_end
            overlap = max(0, prev_end - gs)
            topo = np.array([
                float(np.log1p(glen)),
                float(strand),
                gc,
                gc - ctx_gc,
                float(np.log1p(max(0, gap))),
                float(np.log1p(overlap)),
                (gs - ws) / float(wlen),
                (ge - ws) / float(wlen),
            ], dtype=np.float32)
            mat[ti, :8] = topo
            mat[ti, 8:] = aa_vec
        outputs.append((row_idx, mat, len(in_win)))
    return outputs


def extract_orf_tensors_for_part(
    fasta_path: Path,
    arrs: Dict[str, np.ndarray],
    workers: Optional[int] = None,
) -> Tuple[np.ndarray, np.ndarray]:
    """按特征分片窗口坐标提取全套 ORF Token 张量 (N, MAX_ORFS, 30) 与有效基因数 (N,)。"""
    n_rows = len(arrs["starts"])
    tokens = np.zeros((n_rows, MAX_ORFS_PER_WIN, ORF_FEAT_DIM), dtype=np.float32)
    counts = np.zeros(n_rows, dtype=np.int32)

    by_contig: Dict[str, List[Tuple[int, int, int]]] = {}
    for idx, (cid, s, e) in enumerate(zip(arrs["contig_ids"], arrs["starts"], arrs["ends"])):
        by_contig.setdefault(str(cid), []).append((idx, int(s), int(e)))

    tasks = [
        (cid, seq, by_contig[cid])
        for cid, seq in iter_fasta(fasta_path)
        if cid in by_contig
    ]
    cpu_cnt = os.cpu_count() or 4
    n_workers = workers if workers is not None else max(1, cpu_cnt - 2)

    if n_workers > 1 and len(tasks) > 1:
        with concurrent.futures.ProcessPoolExecutor(max_workers=n_workers) as ex:
            for chunk in ex.map(_extract_contig_orfs_worker, tasks, chunksize=4):
                for row_idx, mat, cnt in chunk:
                    tokens[row_idx] = mat
                    counts[row_idx] = cnt
    else:
        for item in tasks:
            for row_idx, mat, cnt in _extract_contig_orfs_worker(item):
                tokens[row_idx] = mat
                counts[row_idx] = cnt

    return tokens, counts


def build_orf_transformer(d_model: int = 128, nhead: int = 8, num_layers: int = 3):
    import torch
    from torch import nn

    class OrfSyntenyExpert(nn.Module):
        def __init__(self):
            super().__init__()
            self.proj = nn.Sequential(
                nn.Linear(ORF_FEAT_DIM, d_model),
                nn.LayerNorm(d_model),
                nn.GELU(),
            )
            self.pos_emb = nn.Parameter(torch.randn(1, MAX_ORFS_PER_WIN, d_model) * 0.02)
            enc_layer = nn.TransformerEncoderLayer(
                d_model=d_model, nhead=nhead, dim_feedforward=d_model * 3,
                dropout=0.15, activation="gelu", batch_first=True, norm_first=True,
            )
            self.encoder = nn.TransformerEncoder(enc_layer, num_layers=num_layers, enable_nested_tensor=False)
            self.attn_score = nn.Linear(d_model, 1)
            self.head = nn.Sequential(
                nn.Linear(d_model * 3 + 1, 128),
                nn.GELU(),
                nn.Dropout(0.2),
                nn.Linear(128, 1),
            )

        def forward(self, tokens, counts):
            bsz, seq_len, _ = tokens.shape
            pos = torch.arange(seq_len, device=tokens.device)[None, :]
            valid_mask = pos < counts[:, None]  # (B, L)
            has_any = counts > 0

            h = self.proj(tokens) + self.pos_emb[:, :seq_len, :]
            safe_pad_mask = ~valid_mask
            safe_pad_mask = safe_pad_mask & (~(torch.arange(seq_len, device=tokens.device)[None, :] == 0) | has_any[:, None])
            h = self.encoder(h, src_key_padding_mask=safe_pad_mask)

            vm = valid_mask.unsqueeze(-1).to(h.dtype)
            mean_pool = (h * vm).sum(dim=1) / vm.sum(dim=1).clamp(min=1.0)
            max_pool = h.masked_fill(~valid_mask.unsqueeze(-1), -1e4).max(dim=1).values
            max_pool = torch.where(has_any[:, None], max_pool, torch.zeros_like(max_pool))

            attn_logits = self.attn_score(h).squeeze(-1).masked_fill(~valid_mask, -1e4)
            attn_w = torch.softmax(attn_logits, dim=-1).unsqueeze(-1)
            attn_pool = torch.where(has_any[:, None], (h * attn_w).sum(dim=1), torch.zeros_like(mean_pool))

            count_feat = torch.log1p(counts.float()).unsqueeze(-1)
            return self.head(torch.cat([mean_pool, max_pool, attn_pool, count_feat], dim=-1)).squeeze(-1)

    return OrfSyntenyExpert()


def _predict_orf(model, tokens: np.ndarray, counts: np.ndarray, device, batch_size: int = 256) -> np.ndarray:
    import torch

    model.eval()
    out = np.zeros(len(counts), dtype=np.float32)
    with torch.no_grad():
        for i in range(0, len(counts), batch_size):
            tk = torch.from_numpy(tokens[i:i + batch_size]).to(device)
            cn = torch.from_numpy(counts[i:i + batch_size]).to(device)
            out[i:i + batch_size] = torch.sigmoid(model(tk, cn)).float().cpu().numpy()
    return out


def _load_or_extract_part(
    feature_dir: Path,
    manifest_dir: Path,
    split: str,
    part: str,
    cache_dir: Path,
    workers: Optional[int],
    fasta_override: Optional[Path] = None,
) -> Tuple[Dict[str, np.ndarray], np.ndarray, np.ndarray]:
    arrs = load_split_arrays(feature_dir, split, parts=(part,))
    cache_path = cache_dir / f"{split}_{part}_orf_tokens_v2.npz"
    if cache_path.exists():
        with np.load(cache_path) as data:
            return arrs, data["tokens"], data["counts"]
    if fasta_override is not None:
        fasta = Path(fasta_override)
    else:
        manifest = json.loads((Path(manifest_dir) / "benchmark_manifest.json").read_text(encoding="utf-8"))
        fasta = Path(manifest["splits"][split][part]["fasta"])
    tokens, counts = extract_orf_tensors_for_part(fasta, arrs, workers=workers)
    cache_dir.mkdir(parents=True, exist_ok=True)
    tmp = cache_path.with_name(f".{cache_path.stem}.tmp.npz")
    np.savez_compressed(tmp, tokens=tokens, counts=counts)
    tmp.replace(cache_path)
    return arrs, tokens, counts


def train_expert_c(
    train_feature_dir: Path,
    train_dir: Path,
    eval_feature_dir: Path,
    bench_dir: Path,
    out_dir: Path,
    epochs: int = 20,
    batch_size: int = 128,
    lr: float = 1e-3,
    patience: int = 5,
    extra_mined_fasta: Optional[Path] = None,
    workers: Optional[int] = None,
    seed: int = 42,
) -> Dict[str, Any]:
    import torch
    from sklearn.metrics import average_precision_score

    torch.manual_seed(seed)
    rng = np.random.default_rng(seed)
    out_root = Path(out_dir).resolve()
    out_root.mkdir(parents=True, exist_ok=True)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    t_ext = time.perf_counter()
    tr_w = _load_or_extract_part(train_feature_dir, train_dir, "train", "windows", Path(train_feature_dir), workers)
    tr_c = _load_or_extract_part(train_feature_dir, train_dir, "train", "chimeras", Path(train_feature_dir), workers)
    tr_parts = [tr_w, tr_c]
    mined_npz = Path(train_feature_dir) / "train_mined.npz"
    if extra_mined_fasta is not None and Path(extra_mined_fasta).exists() and mined_npz.exists():
        tr_m = _load_or_extract_part(
            train_feature_dir, train_dir, "train", "mined", Path(train_feature_dir), workers,
            fasta_override=Path(extra_mined_fasta),
        )
        if len(tr_m[0]["labels"]) > 0:
            tr_parts.append(tr_m)
    va_w = _load_or_extract_part(eval_feature_dir, bench_dir, "val", "windows", Path(eval_feature_dir), workers)
    va_c = _load_or_extract_part(eval_feature_dir, bench_dir, "val", "chimeras", Path(eval_feature_dir), workers)
    te_w = _load_or_extract_part(eval_feature_dir, bench_dir, "test", "windows", Path(eval_feature_dir), workers)
    te_c = _load_or_extract_part(eval_feature_dir, bench_dir, "test", "chimeras", Path(eval_feature_dir), workers)
    extract_sec = round(time.perf_counter() - t_ext, 2)

    tk_tr = np.concatenate([p[1] for p in tr_parts])
    cn_tr = np.concatenate([p[2] for p in tr_parts])
    y_tr = np.concatenate([p[0]["labels"] for p in tr_parts]).astype(np.int8)
    keep = y_tr >= 0
    tk_tr, cn_tr, y_tr = tk_tr[keep], cn_tr[keep], y_tr[keep]

    va_tk = np.concatenate([va_w[1], va_c[1]])
    va_cn = np.concatenate([va_w[2], va_c[2]])
    va_y = np.concatenate([va_w[0]["labels"], va_c[0]["labels"]])
    va_keep = va_y >= 0

    model = build_orf_transformer().to(device)
    n_params = int(sum(p.numel() for p in model.parameters()))
    opt = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=1e-2)
    steps_per_ep = int(np.ceil(len(y_tr) / batch_size))
    sched = torch.optim.lr_scheduler.OneCycleLR(opt, max_lr=lr, total_steps=epochs * steps_per_ep)
    pos_weight = torch.tensor(float(np.sum(y_tr == 0)) / max(1.0, float(np.sum(y_tr == 1))), device=device)
    loss_fn = torch.nn.BCEWithLogitsLoss(pos_weight=pos_weight)

    best_ap = -1.0
    best_ep = -1
    bad_ep = 0
    history = []
    ckpt_path = out_root / "expert_c_orf.pt"
    if device.type == "cuda":
        torch.cuda.reset_peak_memory_stats()

    t0 = time.perf_counter()
    for ep in range(1, epochs + 1):
        model.train()
        order = rng.permutation(len(y_tr))
        ep_loss = 0.0
        for bi in range(steps_per_ep):
            idx = order[bi * batch_size:(bi + 1) * batch_size]
            tk = torch.from_numpy(tk_tr[idx]).to(device)
            cn = torch.from_numpy(cn_tr[idx]).to(device)
            yb = torch.from_numpy(y_tr[idx].astype(np.float32)).to(device)
            opt.zero_grad(set_to_none=True)
            loss = loss_fn(model(tk, cn), yb)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()
            sched.step()
            ep_loss += float(loss.item()) * len(idx)

        va_sc = _predict_orf(model, va_tk[va_keep], va_cn[va_keep], device)
        ap = float(average_precision_score(va_y[va_keep], va_sc))
        history.append({"epoch": ep, "train_loss": round(ep_loss / len(y_tr), 5), "val_auprc": round(ap, 5)})
        logger.info(f"epoch {ep}: loss={ep_loss / len(y_tr):.4f} val_auprc={ap:.4f}")
        if ap > best_ap:
            best_ap, best_ep, bad_ep = ap, ep, 0
            tmp = out_root / ".expert_c_orf.tmp.pt"
            torch.save(model.state_dict(), tmp)
            tmp.replace(ckpt_path)
        else:
            bad_ep += 1
            if bad_ep >= patience:
                break

    train_sec = round(time.perf_counter() - t0, 2)
    peak_mb = round(torch.cuda.max_memory_allocated() / (1024 * 1024), 1) if device.type == "cuda" else 0.0
    model.load_state_dict(torch.load(ckpt_path, map_location=device, weights_only=True))

    va_win_sc = _predict_orf(model, va_w[1], va_w[2], device)
    va_chim_sc = _predict_orf(model, va_c[1], va_c[2], device)
    decoder = tune_decoder_on_val(load_split_info(bench_dir, "val"), va_c[0], va_chim_sc)

    t1 = time.perf_counter()
    te_win_sc = _predict_orf(model, te_w[1], te_w[2], device)
    te_chim_sc = _predict_orf(model, te_c[1], te_c[2], device)
    infer_sec = round(time.perf_counter() - t1, 3)

    np.savez_compressed(
        out_root / "expert_c_scores.npz",
        val_windows=va_win_sc, val_chimeras=va_chim_sc,
        test_windows=te_win_sc, test_chimeras=te_chim_sc,
    )

    val_report = evaluate_model_scores_on_split(bench_dir, "val", va_w[0], va_win_sc, va_c[0], va_chim_sc,
                                                decoder["seed_threshold"], decoder["extend_threshold"])
    test_report = evaluate_model_scores_on_split(bench_dir, "test", te_w[0], te_win_sc, te_c[0], te_chim_sc,
                                                 decoder["seed_threshold"], decoder["extend_threshold"])
    del model, tk_tr, cn_tr
    if device.type == "cuda":
        torch.cuda.empty_cache()

    report: Dict[str, Any] = {
        "model_name": "ExpertC_ORFTransformer",
        "trained_at": datetime.now().isoformat(timespec="seconds"),
        "device": str(device),
        "params": n_params,
        "extract_sec": extract_sec,
        "train_rows": int(len(y_tr)),
        "best_epoch": best_ep,
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
    rep_path = out_root / "expert_c_report.json"
    tmp_rep = out_root / ".expert_c_report.tmp.json"
    tmp_rep.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_rep.replace(rep_path)
    report["report_path"] = str(rep_path)
    return report


def main() -> int:
    from .expert_a_xgb import summarize_report

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="训练 Expert C (ORF 语法拓扑 Transformer)")
    parser.add_argument("--train-feature-dir", required=True)
    parser.add_argument("--train-dir", required=True)
    parser.add_argument("--eval-feature-dir", required=True)
    parser.add_argument("--bench-dir", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--epochs", type=int, default=20)
    parser.add_argument("--extra-mined-fasta", default=None)
    args = parser.parse_args()
    rep = train_expert_c(
        Path(args.train_feature_dir), Path(args.train_dir), Path(args.eval_feature_dir),
        Path(args.bench_dir), Path(args.out_dir), epochs=args.epochs,
        extra_mined_fasta=Path(args.extra_mined_fasta) if args.extra_mined_fasta else None,
    )
    summary = summarize_report({**rep, "best_iteration": rep["best_epoch"]})
    summary["extract_sec"] = rep["extract_sec"]
    summary["train_sec"] = rep["train_sec"]
    summary["peak_gpu_mem_mb"] = rep["peak_gpu_mem_mb"]
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

