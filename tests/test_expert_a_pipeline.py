# -*- coding: utf-8 -*-
"""窗口特征提取、特征分片构建与 Expert A 训练评测链路单元测试（合成小样本）。"""
import csv
import random
import sqlite3
from contextlib import closing
from pathlib import Path

import numpy as np

from src.phage_discovery.benchmark.chimera_builder import build_benchmark_suite
from src.phage_discovery.data.feature_dataset import build_extra_chimera_features, build_split_features, load_split_arrays
from src.phage_discovery.experts.expert_a_xgb import summarize_report, train_expert_a
from src.phage_discovery.features.window_features import FEATURE_NAMES, SUB_BINS, extract_contig_windows


def _random_seq(rng: random.Random, length: int, gc: float) -> str:
    at = (1.0 - gc) / 2.0
    gcw = gc / 2.0
    return "".join(rng.choices("ACGT", weights=[at, gcw, gcw, at], k=length))


def _make_synthetic_dataset(root: Path) -> tuple[Path, Path]:
    rng = random.Random(11)
    pos_dir = root / "pos"
    neg_dir = root / "neg"
    (pos_dir / "fasta").mkdir(parents=True)
    (pos_dir / "preprocessed" / "splits").mkdir(parents=True)
    (neg_dir / "fasta").mkdir(parents=True)
    (neg_dir / "index").mkdir(parents=True)

    for split, n in (("train", 6), ("val", 3), ("test", 3)):
        with open(pos_dir / "preprocessed" / "splits" / f"{split}.tsv", "w", encoding="utf-8", newline="") as fh:
            w = csv.writer(fh, delimiter="\t")
            w.writerow(["accession", "cluster_id", "tax_group", "host", "length_bp"])
            for i in range(n):
                acc = f"NC_{split.upper()}_{i}.1"
                seq = _random_seq(rng, 12000, 0.62)
                (pos_dir / "fasta" / f"{acc}.fasta").write_text(f">{acc}\n{seq}\n", encoding="utf-8")
                w.writerow([acc, f"CLU_{split}_{i}", "Caudoviricetes", "E. coli", len(seq)])

    with closing(sqlite3.connect(neg_dir / "index" / "negative_index.sqlite")) as conn:
        conn.execute(
            "CREATE TABLE genomes (accession TEXT PRIMARY KEY, is_valid_negative INTEGER, negative_category TEXT, organism TEXT, length_bp INTEGER, fasta_relpath TEXT);"
        )
        conn.execute("CREATE TABLE prophage_masks (id INTEGER PRIMARY KEY AUTOINCREMENT, accession TEXT, start_pos INTEGER, end_pos INTEGER);")
        for i in range(9):
            acc = f"NZ_HOST_{i}.1"
            seq = _random_seq(rng, 160000, 0.36)
            (neg_dir / "fasta" / f"{acc}.fasta").write_text(f">{acc}\n{seq}\n", encoding="utf-8")
            conn.execute("INSERT INTO genomes VALUES (?, 1, 'bacterial_chromosome', 'Bacillus', ?, ?)", (acc, len(seq), f"fasta/{acc}.fasta"))
        conn.commit()
    return pos_dir, neg_dir


def test_extract_contig_windows_shape_and_overlap_labels():
    rng = random.Random(3)
    seq = _random_seq(rng, 20000, 0.5)
    res = extract_contig_windows("C1", seq, win_size=5000, step_size=2500, truth_regions=[(5000, 10000)])
    assert len(FEATURE_NAMES) == 185
    assert res["features"].shape[1] == len(FEATURE_NAMES)
    assert res["sub_mask"].shape == (len(res["starts"]), SUB_BINS)
    assert res["starts"][0] == 0 and res["ends"][-1] == 20000
    idx = list(res["starts"]).index(5000)
    assert res["overlap"][idx] == 1.0
    assert np.allclose(res["sub_mask"][idx], 1.0)
    assert res["overlap"][0] == 0.0
    assert np.allclose(res["sub_mask"][0], 0.0)
    assert np.all(np.isfinite(res["features"]))

    single = extract_contig_windows("W1", seq[:3000], win_size=5000, step_size=2500)
    assert len(single["starts"]) == 1
    assert single["features"][0][FEATURE_NAMES.index("ctx_is_self")] == 1.0


def test_feature_dataset_and_expert_a_end_to_end(tmp_path: Path):
    pos_dir, neg_dir = _make_synthetic_dataset(tmp_path)
    bench = tmp_path / "bench"
    train_bench = tmp_path / "train_bench"
    build_benchmark_suite(pos_dir, neg_dir, bench, splits_to_build=("val", "test"),
                          chimeras_per_split=4, pure_neg_hosts_per_split=1, windows_per_split=40, seed=5)
    build_benchmark_suite(pos_dir, neg_dir, train_bench, splits_to_build=("train",),
                          chimeras_per_split=6, pure_neg_hosts_per_split=2, windows_per_split=80, seed=5)

    feat_eval = tmp_path / "feat_eval"
    feat_train = tmp_path / "feat_train"
    s_tr = build_split_features(train_bench, "train", feat_train, workers=2)
    build_split_features(bench, "val", feat_eval, workers=2)
    build_split_features(bench, "test", feat_eval, workers=2)
    assert s_tr["windows_counts"]["rows"] == 80
    assert s_tr["chimeras_counts"]["pos"] > 0 and s_tr["chimeras_counts"]["neg"] > 0

    # 断点跳过：再次调用不重算且结果一致
    s_tr2 = build_split_features(train_bench, "train", feat_train, workers=2)
    assert s_tr2["chimeras_counts"] == s_tr["chimeras_counts"]
    arrs = load_split_arrays(feat_train, "train")
    assert arrs["features"].shape[0] == s_tr["windows_counts"]["rows"] + s_tr["chimeras_counts"]["rows"]
    assert arrs["sub_mask"].shape == (arrs["features"].shape[0], SUB_BINS)

    # 验证额外前噬菌体序列特征构建与合并
    extra_fa = tmp_path / "mined.fna"
    extra_tsv = tmp_path / "mined_truth.tsv"
    extra_fa.write_text(f">M1\n{_random_seq(random.Random(7), 15000, 0.5)}\n", encoding="utf-8")
    extra_tsv.write_text("contig_id\tstart_bp\tend_bp\nM1\t2500\t10000\n", encoding="utf-8")
    mined_info = build_extra_chimera_features(extra_fa, extra_tsv, feat_train / "train_mined.npz", workers=2)
    assert mined_info["rows"] > 0
    arrs_all = load_split_arrays(feat_train, "train", parts=("windows", "chimeras", "mined"))
    assert arrs_all["features"].shape[0] == arrs["features"].shape[0] + mined_info["rows"]

    report = train_expert_a(feat_train, feat_eval, bench, tmp_path / "model", n_estimators=60, early_stopping_rounds=20)
    summary = summarize_report(report)
    assert Path(report["model_path"]).exists()
    # GC 差异显著的合成数据：窗口 AUROC 应显著高于随机
    assert summary["test"]["win_auroc"] is not None and summary["test"]["win_auroc"] > 0.8

