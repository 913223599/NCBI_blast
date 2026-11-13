# -*- coding: utf-8 -*-
"""Expert B 序列编码/模型训练与 CheckV 教师解析器单元测试。"""
import random
import sqlite3
from contextlib import closing
from pathlib import Path

import numpy as np

from src.phage_discovery.benchmark.chimera_builder import build_benchmark_suite
from src.phage_discovery.data.feature_dataset import build_split_features
from src.phage_discovery.experts.expert_b_cnn import train_expert_b
from src.phage_discovery.experts.seq_dataset import encode_dna, reverse_complement_codes
from src.phage_discovery.teachers.checkv_teacher import parse_checkv_viral_regions, to_wsl_path


def test_seq_dataset_encode_and_rc():
    seq = "ACGNT"
    codes = encode_dna(seq)
    assert codes.tolist() == [0, 1, 2, 4, 3]
    rc = reverse_complement_codes(codes[None, :], np.array([5], dtype=np.int32))
    # ACGNT -> reverse complement -> ANCGT -> [0, 4, 1, 2, 3]
    assert rc[0].tolist() == [0, 4, 1, 2, 3]


def test_checkv_parser_and_wsl_path(tmp_path: Path):
    assert to_wsl_path(Path(r"F:\Phage data\test.fna")) == "/mnt/f/Phage data/test.fna"
    contam = tmp_path / "contamination.tsv"
    contam.write_text(
        "contig_id\tcontig_length\tprovirus\tviral_genes\thost_genes\tregion_types\tregion_coords_bp\n"
        "C1\t100000\tYes\t20\t50\thost,viral,host\t1-30000,30001-65000,65001-100000\n"
        "C2\t20000\tNo\t15\t0\tviral\t1-20000\n"
        "C_NEG\t100000\tNo\t0\t90\thost\t1-100000\n",
        encoding="utf-8",
    )
    regions = parse_checkv_viral_regions(contam)
    assert [(r.contig_id, r.start_bp, r.end_bp) for r in regions] == [
        ("C1", 30000, 65000),
        ("C2", 0, 20000),
    ]


def _rand_seq(rng: random.Random, length: int, gc: float) -> str:
    at = (1.0 - gc) / 2.0
    gcw = gc / 2.0
    return "".join(rng.choices("ACGT", weights=[at, gcw, gcw, at], k=length))


def test_expert_b_smoke_train_and_eval(tmp_path: Path):
    import csv

    rng = random.Random(21)
    pos_dir = tmp_path / "pos"
    neg_dir = tmp_path / "neg"
    (pos_dir / "fasta").mkdir(parents=True)
    (pos_dir / "preprocessed" / "splits").mkdir(parents=True)
    (neg_dir / "fasta").mkdir(parents=True)
    (neg_dir / "index").mkdir(parents=True)

    for split, n in (("train", 4), ("val", 2), ("test", 2)):
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
        for i in range(6):
            acc = f"NZ_BACT_{i}.1"
            seq = _rand_seq(rng, 140000, 0.35)
            (neg_dir / "fasta" / f"{acc}.fasta").write_text(f">{acc}\n{seq}\n", encoding="utf-8")
            conn.execute("INSERT INTO genomes VALUES (?, 1, 'bacterial_chromosome', 'Bacillus', ?, ?)", (acc, len(seq), f"fasta/{acc}.fasta"))
        conn.commit()

    bench = tmp_path / "bench"
    train_bench = tmp_path / "train_bench"
    build_benchmark_suite(pos_dir, neg_dir, bench, splits_to_build=("val", "test"),
                          chimeras_per_split=3, pure_neg_hosts_per_split=1, windows_per_split=30, seed=9)
    build_benchmark_suite(pos_dir, neg_dir, train_bench, splits_to_build=("train",),
                          chimeras_per_split=4, pure_neg_hosts_per_split=1, windows_per_split=40, seed=9)

    feat_tr = tmp_path / "feat_tr"
    feat_ev = tmp_path / "feat_ev"
    build_split_features(train_bench, "train", feat_tr, workers=2)
    build_split_features(bench, "val", feat_ev, workers=2)
    build_split_features(bench, "test", feat_ev, workers=2)

    rep = train_expert_b(
        feat_tr, train_bench, feat_ev, bench, tmp_path / "model_b",
        epochs=2, batch_size=16, patience=2, seed=9,
    )
    assert Path(rep["model_path"]).exists()
    assert (tmp_path / "model_b" / "expert_b_scores.npz").exists()
    assert rep["test"]["window_benchmark"]["overall"]["auroc"] is not None

