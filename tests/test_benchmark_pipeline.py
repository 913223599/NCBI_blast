# -*- coding: utf-8 -*-
"""前噬菌体测试流程与基准构建/评测引擎单元测试。"""
import csv
import json
import sqlite3
from contextlib import closing
from pathlib import Path

from src.phage_discovery.benchmark.chimera_builder import (
    build_benchmark_suite,
    compute_clean_intervals,
    split_negative_genomes_by_category,
)
from src.phage_discovery.benchmark.metrics import (
    TruthRegion,
    WindowPrediction,
    compute_region_metrics,
    compute_window_metrics,
    decode_window_scores_to_regions,
)
from src.phage_discovery.benchmark.runner import run_composition_baseline


def test_compute_clean_intervals_and_negative_split_isolation(tmp_path: Path):
    clean = compute_clean_intervals(10000, [(1000, 2500), (6000, 7500)], min_segment_bp=1500)
    assert clean == [(2500, 6000), (7500, 10000)]

    neg_db = tmp_path / "negative_index.sqlite"
    with closing(sqlite3.connect(neg_db)) as conn:
        conn.execute(
            "CREATE TABLE genomes (accession TEXT PRIMARY KEY, is_valid_negative INTEGER, negative_category TEXT);"
        )
        rows = [(f"NZ_CHR_{i:02d}.1", 1, "bacterial_chromosome") for i in range(20)]
        rows += [(f"NZ_PLS_{i:02d}.1", 1, "plasmid") for i in range(20)]
        conn.executemany("INSERT INTO genomes VALUES (?, ?, ?)", rows)
        conn.commit()

    splits_1 = split_negative_genomes_by_category(neg_db, seed=123)
    splits_2 = split_negative_genomes_by_category(neg_db, seed=123)
    assert splits_1 == splits_2
    assert set(splits_1.values()) == {"train", "val", "test"}
    assert len(splits_1) == 40


def test_window_and_region_metrics_with_hysteresis_decoder():
    win_metrics = compute_window_metrics([1, 1, 0, 0, 0], [0.95, 0.80, 0.20, 0.10, 0.05], threshold=0.5)
    assert win_metrics["auroc"] == 1.0
    assert win_metrics["f1"] == 1.0
    assert win_metrics["recall_at_fpr_0_5pct"] == 1.0

    # 构造两个 contig：C1 存在真实前噬菌体 [10000, 25000)，C2 为纯阴性对照却有一个误报岛
    preds = [
        WindowPrediction("C1", 0, 5000, 0.10),
        WindowPrediction("C1", 5000, 10000, 0.20),
        WindowPrediction("C1", 10000, 15000, 0.90),
        WindowPrediction("C1", 15000, 20000, 0.88),
        WindowPrediction("C1", 20000, 25000, 0.60),
        WindowPrediction("C1", 25000, 30000, 0.15),
        WindowPrediction("C2", 0, 5000, 0.91),
        WindowPrediction("C2", 5000, 10000, 0.55),
    ]
    decoded = decode_window_scores_to_regions(preds, seed_threshold=0.85, extend_threshold=0.50, min_region_bp=3000)
    assert len(decoded) == 2
    assert (decoded[0].contig_id, decoded[0].start_bp, decoded[0].end_bp) == ("C1", 10000, 25000)

    truths = [TruthRegion("C1", 10500, 24500)]
    rm = compute_region_metrics(truths, decoded, contig_lengths={"C1": 100000, "C2": 500000}, iou_threshold=0.5)
    assert rm["primary"]["tp"] == 1
    assert rm["primary"]["fp"] == 1
    assert rm["primary"]["fn"] == 0
    assert rm["primary"]["breakpoint_mae_bp"] == 500.0
    assert rm["pure_negative_false_positives"] == 1
    assert rm["pure_negative_fp_per_mb"] == 2.0


def test_end_to_end_benchmark_builder_and_baseline_runner(tmp_path: Path):
    pos_dir = tmp_path / "pos"
    neg_dir = tmp_path / "neg"
    out_dir = tmp_path / "bench"

    (pos_dir / "fasta").mkdir(parents=True)
    (pos_dir / "preprocessed" / "splits").mkdir(parents=True)
    (neg_dir / "fasta").mkdir(parents=True)
    (neg_dir / "index").mkdir(parents=True)

    # 生成高 GC 噬菌体模拟序列与低 GC 细菌主干，以便组成异常度测试有效运行
    phage_seq = ("GGCC" * 3000)
    for split in ("val", "test"):
        acc = f"NC_PH_{split.upper()}.1"
        (pos_dir / "fasta" / f"{acc}.fasta").write_text(f">{acc}\n{phage_seq}\n", encoding="utf-8")
        with open(pos_dir / "preprocessed" / "splits" / f"{split}.tsv", "w", encoding="utf-8", newline="") as fh:
            w = csv.writer(fh, delimiter="\t")
            w.writerow(["accession", "cluster_id", "tax_group", "host", "length_bp"])
            w.writerow([acc, f"CLU_{split}", "Caudoviricetes", "Escherichia coli", len(phage_seq)])

    host_seq = ("AATT" * 40000)  # 160 kb 纯 AT 细菌背景
    neg_db = neg_dir / "index" / "negative_index.sqlite"
    with closing(sqlite3.connect(neg_db)) as conn:
        conn.execute(
            """
            CREATE TABLE genomes (
                accession TEXT PRIMARY KEY,
                is_valid_negative INTEGER,
                negative_category TEXT,
                organism TEXT,
                length_bp INTEGER,
                fasta_relpath TEXT
            );
            """
        )
        conn.execute(
            "CREATE TABLE prophage_masks (id INTEGER PRIMARY KEY AUTOINCREMENT, accession TEXT, start_pos INTEGER, end_pos INTEGER);"
        )
        for i in range(1, 10):
            acc = f"NZ_BACT_{i:02d}.1"
            (neg_dir / "fasta" / f"{acc}.fasta").write_text(f">{acc}\n{host_seq}\n", encoding="utf-8")
            conn.execute(
                "INSERT INTO genomes VALUES (?, 1, 'bacterial_chromosome', 'Bacillus', ?, ?)",
                (acc, len(host_seq), f"fasta/{acc}.fasta"),
            )
            # 在末尾放一段掩蔽以检验避让逻辑，前 145 kb 保持干净 >= 120 kb
            conn.execute("INSERT INTO prophage_masks (accession, start_pos, end_pos) VALUES (?, ?, ?)", (acc, 145000, 155000))
        conn.commit()

    manifest = build_benchmark_suite(
        positive_dir=pos_dir,
        negative_dir=neg_dir,
        output_dir=out_dir,
        splits_to_build=("val", "test"),
        chimeras_per_split=4,
        pure_neg_hosts_per_split=2,
        windows_per_split=40,
        seed=7,
    )
    assert (out_dir / "benchmark_manifest.json").exists()
    assert manifest["splits"]["test"]["windows"]["total_windows"] == 40
    assert manifest["splits"]["test"]["chimeras"]["total_contigs"] == 6

    report = run_composition_baseline(out_dir, split_name="test", threads=1)
    assert Path(report["report_json"]).exists()
    assert Path(report["report_md"]).exists()
    assert report["window_benchmark"]["overall"]["auroc"] is not None
    # 因为注入了 GC=100% 噬菌体进入纯 AT 宿主，4-mer/GC 基线应当准确报警其中大部分前噬菌体
    assert report["chimera_benchmark"]["overall"]["primary"]["recall"] > 0.0

