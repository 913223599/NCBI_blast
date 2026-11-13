# -*- coding: utf-8 -*-
"""Expert C (ORF Transformer)、专家融合集成与双流蒸馏学生模型 (含 ONNX 导出) 单元测试。"""
import random
import sqlite3
from contextlib import closing
from pathlib import Path

import numpy as np

from src.phage_discovery.benchmark.chimera_builder import build_benchmark_suite
from src.phage_discovery.benchmark.metrics import WindowPrediction, decode_subwindow_probs_to_regions
from src.phage_discovery.data.feature_dataset import build_split_features
from src.phage_discovery.experts.expert_a_xgb import train_expert_a
from src.phage_discovery.experts.expert_c_orf import build_orf_transformer, train_expert_c
from src.phage_discovery.features.window_features import SUB_BINS
from src.phage_discovery.student.distilled_student import (
    compute_group_oof_xgb_probs,
    evaluate_expert_ensemble,
    train_distilled_student,
)


def _rand_seq(rng: random.Random, length: int, gc: float) -> str:
    at = (1.0 - gc) / 2.0
    gcw = gc / 2.0
    return "".join(rng.choices("ACGT", weights=[at, gcw, gcw, at], k=length))


def test_decode_subwindow_probs_refines_boundaries():
    preds = []
    subs = []
    # 构建 40000bp contig，滑窗 5000bp / step 2500bp，真实前噬菌体为 [10200, 22400)
    for ws in range(0, 35001, 2500):
        we = ws + 5000
        ov = max(0, min(we, 22400) - max(ws, 10200)) / 5000.0
        w_score = 0.95 if ov >= 0.4 else 0.05
        preds.append(WindowPrediction("C_REF", ws, we, w_score))
        sub = np.zeros(SUB_BINS, dtype=np.float32)
        for k in range(SUB_BINS):
            bs = ws + k * 200
            be = bs + 200
            if min(be, 22400) > max(bs, 10200):
                sub[k] = 0.92
            else:
                sub[k] = 0.08
        subs.append(sub)
    regions = decode_subwindow_probs_to_regions(
        preds, np.vstack(subs), seed_threshold=0.80, extend_threshold=0.50, sub_threshold=0.45,
    )
    assert len(regions) == 1
    assert abs(regions[0].start_bp - 10200) <= 200
    assert abs(regions[0].end_bp - 22400) <= 200


def test_orf_transformer_handles_zero_orf_window():
    import torch

    m = build_orf_transformer().eval()
    tokens = torch.zeros(2, 24, 30, dtype=torch.float32)
    counts = torch.tensor([0, 3], dtype=torch.int64)
    tokens[1, :3] = 0.5
    out = m(tokens, counts)
    assert out.shape == (2,)
    assert torch.all(torch.isfinite(out))


def test_expert_c_ensemble_and_student_onnx_end_to_end(tmp_path: Path):
    import csv

    rng = random.Random(31)
    pos_dir = tmp_path / "pos"
    neg_dir = tmp_path / "neg"
    (pos_dir / "fasta").mkdir(parents=True)
    (pos_dir / "preprocessed" / "splits").mkdir(parents=True)
    (neg_dir / "fasta").mkdir(parents=True)
    (neg_dir / "index").mkdir(parents=True)

    for split, n in (("train", 6), ("val", 3), ("test", 3)):
        with open(pos_dir / "preprocessed" / "splits" / f"{split}.tsv", "w", encoding="utf-8", newline="") as fh:
            w = csv.writer(fh, delimiter="\t")
            w.writerow(["accession", "cluster_id", "tax_group", "host", "length_bp"])
            for i in range(n):
                acc = f"NC_{split}_{i}.1"
                seq = _rand_seq(rng, 10000, 0.65)
                (pos_dir / "fasta" / f"{acc}.fasta").write_text(f">{acc}\n{seq}\n", encoding="utf-8")
                w.writerow([acc, f"CLU_{split}_{i}", "Caudoviricetes", "E. coli", len(seq)])

    with closing(sqlite3.connect(neg_dir / "index" / "negative_index.sqlite")) as conn:
        conn.execute(
            "CREATE TABLE genomes (accession TEXT PRIMARY KEY, is_valid_negative INTEGER, negative_category TEXT, organism TEXT, length_bp INTEGER, fasta_relpath TEXT);"
        )
        conn.execute("CREATE TABLE prophage_masks (id INTEGER PRIMARY KEY AUTOINCREMENT, accession TEXT, start_pos INTEGER, end_pos INTEGER);")
        for i in range(9):
            acc = f"NZ_BACT_{i}.1"
            seq = _rand_seq(rng, 140000, 0.35)
            (neg_dir / "fasta" / f"{acc}.fasta").write_text(f">{acc}\n{seq}\n", encoding="utf-8")
            conn.execute("INSERT INTO genomes VALUES (?, 1, 'bacterial_chromosome', 'Bacillus', ?, ?)", (acc, len(seq), f"fasta/{acc}.fasta"))
        conn.commit()

    bench = tmp_path / "bench"
    train_bench = tmp_path / "train_bench"
    build_benchmark_suite(pos_dir, neg_dir, bench, splits_to_build=("val", "test"),
                          chimeras_per_split=3, pure_neg_hosts_per_split=1, windows_per_split=30, seed=13)
    build_benchmark_suite(pos_dir, neg_dir, train_bench, splits_to_build=("train",),
                          chimeras_per_split=5, pure_neg_hosts_per_split=1, windows_per_split=40, seed=13)

    feat_tr = tmp_path / "feat_tr"
    feat_ev = tmp_path / "feat_ev"
    build_split_features(train_bench, "train", feat_tr, workers=2)
    build_split_features(bench, "val", feat_ev, workers=2)
    build_split_features(bench, "test", feat_ev, workers=2)

    # 验证 GroupKFold OOF 不崩溃且概率在 (0,1)
    x_dummy = np.random.default_rng(1).normal(size=(24, 16)).astype(np.float32)
    y_dummy = np.array([0, 1] * 12, dtype=np.int32)
    g_dummy = np.array([f"C{i // 4}" for i in range(24)])
    oof = compute_group_oof_xgb_probs(x_dummy, y_dummy, g_dummy, n_splits=3, n_estimators=20)
    assert oof.shape == (24,) and float(oof.min()) > 0.0 and float(oof.max()) < 1.0

    # 跑通 Expert A, Expert C, Ensemble 及 Distilled Student + ONNX 导出
    train_expert_a(feat_tr, feat_ev, bench, tmp_path / "exp_a", n_estimators=40, early_stopping_rounds=10)
    rep_c = train_expert_c(feat_tr, train_bench, feat_ev, bench, tmp_path / "exp_c", epochs=2, batch_size=32, workers=2)
    assert Path(rep_c["model_path"]).exists()

    ens = evaluate_expert_ensemble(
        {"ExpertA": tmp_path / "exp_a" / "expert_a_scores.npz", "ExpertC": tmp_path / "exp_c" / "expert_c_scores.npz"},
        feat_ev, bench, tmp_path / "ens",
    )
    assert sum(ens["weights"].values()) > 0.99

    rep_s = train_distilled_student(
        feat_tr, train_bench, feat_ev, bench, tmp_path / "student",
        epochs=2, batch_size=32,
    )
    assert Path(rep_s["onnx_path"]).exists()
    assert rep_s["onnx_size_mb"] > 0
    assert rep_s["test"]["window_benchmark"]["overall"]["auroc"] is not None

