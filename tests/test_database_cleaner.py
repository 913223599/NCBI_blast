# -*- coding: utf-8 -*-
"""数据库清理、压缩、前噬菌体掩蔽与高 N 过滤模块单元测试。"""
import csv
import json
import sqlite3
from contextlib import closing
from pathlib import Path

from src.utils.phage_dataset.cleaner import (
    clean_phage_databases,
    clean_sqlite_cds_noise,
    merge_intervals,
)
from src.utils.phage_dataset.indexer import build_phage_dataset_indexes, remove_redundant_blast_fasta
from src.utils.phage_dataset.validator import PhageCDSRecord, PhageRecordValidation


def test_merge_intervals_flank_and_clamp():
    merged = merge_intervals(
        [(100, 600), (1500, 2000), (8000, 8600)],
        max_length=8800,
        flank_bp=1000,
    )
    assert merged == [(0, 3000), (7000, 8800)]
    assert merge_intervals([], max_length=1000, flank_bp=500) == []


def test_remove_redundant_blast_fasta_safety(tmp_path: Path):
    blast_dir = tmp_path / "blastdb"
    blast_dir.mkdir(parents=True, exist_ok=True)

    fna_keep = blast_dir / "keep_only_nin.fna"
    fna_keep.write_text(">seq1\nATGC\n", encoding="utf-8")
    (blast_dir / "keep_only_nin.nin").write_bytes(b"mock_nin")
    assert remove_redundant_blast_fasta(fna_keep, blast_dir / "keep_only_nin", "nucl") == 0
    assert fna_keep.exists()

    fna_real = blast_dir / "phage_refseq_nucl.fna"
    fna_real.write_text(">seq1\nATGCATGC\n", encoding="utf-8")
    (blast_dir / "phage_refseq_nucl.00.nsq").write_bytes(b"real_nsq_data")
    reclaimed = remove_redundant_blast_fasta(fna_real, blast_dir / "phage_refseq_nucl", "nucl")
    assert reclaimed > 0
    assert not fna_real.exists()


def test_clean_sqlite_cds_noise_and_vacuum(tmp_path: Path):
    db_path = tmp_path / "phage_index.sqlite"
    with closing(sqlite3.connect(db_path)) as conn:
        conn.execute("CREATE TABLE genomes (accession TEXT PRIMARY KEY);")
        conn.execute(
            """
            CREATE TABLE cds_features (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                accession TEXT NOT NULL,
                locus_tag TEXT,
                protein_id TEXT,
                start_pos INTEGER,
                end_pos INTEGER,
                strand INTEGER,
                length_aa INTEGER,
                product TEXT
            );
            """
        )
        conn.execute("INSERT INTO genomes VALUES ('NC_000001.1');")
        conn.executemany(
            "INSERT INTO cds_features (accession, locus_tag, protein_id, start_pos, end_pos, strand, length_aa, product) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                ("NC_000001.1", "L1", "P1", 1, 60, 1, 19, "hypothetical protein"),
                ("NC_000001.1", "L2", "P2", 100, 400, 1, 100, "pseudogene tail fiber"),
                ("NC_000001.1", "L3", "P3", 500, 1400, 1, 300, "terminase large subunit"),
            ],
        )
        conn.commit()

    report = clean_sqlite_cds_noise(db_path, min_prot_aa=25)
    assert report["deleted_short_lt_min_aa"] == 1
    assert report["deleted_pseudo"] == 1
    assert report["cds_before"] == 3
    assert report["cds_after"] == 1

    with closing(sqlite3.connect(db_path)) as conn:
        remaining = conn.execute("SELECT protein_id, length_aa FROM cds_features").fetchall()
        assert remaining == [("P3", 300)]


def test_scan_and_mask_negative_prophages_and_high_n_split_filter(tmp_path: Path, monkeypatch):
    pos_dir = tmp_path / "positive"
    neg_dir = tmp_path / "negative"
    (pos_dir / "index").mkdir(parents=True)
    (pos_dir / "blastdb").mkdir(parents=True)
    (pos_dir / "preprocessed" / "splits").mkdir(parents=True)
    (neg_dir / "index").mkdir(parents=True)
    (neg_dir / "fasta").mkdir(parents=True)
    (neg_dir / "blastdb").mkdir(parents=True)

    # 1. 构建正样本索引与 splits
    pos_db = pos_dir / "index" / "phage_index.sqlite"
    with closing(sqlite3.connect(pos_db)) as conn:
        conn.execute("CREATE TABLE genomes (accession TEXT PRIMARY KEY, n_percent REAL);")
        conn.execute("CREATE TABLE cds_features (id INTEGER PRIMARY KEY AUTOINCREMENT, accession TEXT, length_aa INTEGER, product TEXT);")
        conn.executemany(
            "INSERT INTO genomes VALUES (?, ?)",
            [("NC_OK_1.1", 0.1), ("NC_OK_2.1", 0.5), ("NC_BAD_N.1", 5.2)],
        )
        conn.commit()

    (pos_dir / "blastdb" / "phage_refseq_nucl.nsq").write_bytes(b"nsq")
    (pos_dir / "blastdb" / "phage_refseq_nucl.fna").write_text(">NC_OK_1.1\nATGC\n", encoding="utf-8")

    for split_name, rows in [
        ("train", [["NC_OK_1.1", "c0", "50000"], ["NC_BAD_N.1", "c1", "42000"]]),
        ("val", [["NC_OK_2.1", "c2", "38000"]]),
        ("test", []),
    ]:
        with open(pos_dir / "preprocessed" / "splits" / f"{split_name}.tsv", "w", encoding="utf-8", newline="") as fh:
            w = csv.writer(fh, delimiter="\t")
            w.writerow(["accession", "cluster_id", "length_bp"])
            w.writerows(rows)

    (pos_dir / "preprocessed" / "preprocess_manifest.json").write_text(
        json.dumps({"splits": {"train": 2, "val": 1, "test": 0}}),
        encoding="utf-8",
    )

    # 2. 构建负样本序列、索引与可疑前噬菌体基因簇
    neg_fa = neg_dir / "fasta" / "NZ_CHR1.1.fasta"
    neg_fa.write_text(">NZ_CHR1.1\n" + ("ATGC" * 10000) + "\n", encoding="utf-8")
    neg_db = neg_dir / "index" / "negative_index.sqlite"
    with closing(sqlite3.connect(neg_db)) as conn:
        conn.execute(
            """
            CREATE TABLE genomes (
                accession TEXT PRIMARY KEY,
                is_valid_negative INTEGER,
                negative_category TEXT,
                length_bp INTEGER,
                fasta_relpath TEXT
            );
            """
        )
        conn.execute(
            """
            CREATE TABLE cds_features (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                accession TEXT,
                start_pos INTEGER,
                end_pos INTEGER,
                length_aa INTEGER,
                product TEXT
            );
            """
        )
        conn.execute(
            "INSERT INTO genomes VALUES ('NZ_CHR1.1', 1, 'bacterial_chromosome', 40000, 'fasta/NZ_CHR1.1.fasta');"
        )
        conn.executemany(
            "INSERT INTO cds_features (accession, start_pos, end_pos, length_aa, product) VALUES (?, ?, ?, ?, ?)",
            [
                ("NZ_CHR1.1", 12000, 13200, 400, "terminase large subunit"),
                ("NZ_CHR1.1", 13500, 14800, 430, "phage capsid protein"),
                ("NZ_CHR1.1", 20000, 20045, 15, "short fragment"),
            ],
        )
        conn.commit()

    monkeypatch.setattr(
        "src.utils.phage_dataset.cleaner.ToolConfig.resolve_bio_tool",
        lambda name: Path("mock_blastn") if name == "blastn" else None,
    )
    monkeypatch.setattr(
        "src.utils.phage_dataset.cleaner._run_blastn_prophage_scan",
        lambda **kwargs: {"NZ_CHR1.1": [(3000, 5500, "blastn:NC_OK_1.1")]},
    )

    report = clean_phage_databases(pos_dir, neg_dir, min_prot_aa=25, max_n_percent=2.0)

    assert not (pos_dir / "blastdb" / "phage_refseq_nucl.fna").exists()
    assert report["summary"]["negative_cds_removed"] == 1
    assert report["summary"]["negative_prophage_masked_accessions"] == 1
    assert report["summary"]["negative_prophage_mask_intervals"] == 2
    assert report["summary"]["high_n_positive_filtered_count"] == 1

    with closing(sqlite3.connect(neg_db)) as conn:
        masks = conn.execute(
            "SELECT accession, start_pos, end_pos, evidence_source FROM prophage_masks ORDER BY start_pos"
        ).fetchall()
    assert masks == [
        ("NZ_CHR1.1", 2000, 6500, "blastn+cds_cluster"),
        ("NZ_CHR1.1", 11000, 15800, "blastn+cds_cluster"),
    ]

    with open(pos_dir / "preprocessed" / "splits" / "train.tsv", "r", encoding="utf-8") as fh:
        train_rows = list(csv.reader(fh, delimiter="\t"))
    assert [r[0] for r in train_rows] == ["accession", "NC_OK_1.1"]

    updated_manifest = json.loads(
        (pos_dir / "preprocessed" / "preprocess_manifest.json").read_text(encoding="utf-8")
    )
    assert updated_manifest["splits"]["train"] == 1
    assert "NC_BAD_N.1" in updated_manifest["high_n_filtering"]["filtered_accessions"]


def test_indexer_filters_short_cds_and_keeps_fastas_when_blastdb_disabled(tmp_path: Path):
    data_dir = tmp_path / "Phage data"
    (data_dir / "fasta").mkdir(parents=True)
    (data_dir / "gbk").mkdir(parents=True)
    fa = data_dir / "fasta" / "NC_999.1.fasta"
    fa.write_text(">NC_999.1\n" + ("ATG" * 100) + "\n", encoding="utf-8")
    gbk = data_dir / "gbk" / "NC_999.1.gbk"
    gbk.write_text("LOCUS       NC_999\n//\n", encoding="utf-8")

    rec = PhageRecordValidation(
        accession="NC_999.1",
        status="passed",
        is_phage=True,
        phage_confidence="high",
        phage_tax_group="Caudoviricetes",
        phage_evidence=["taxonomy_phage_keyword"],
        organism="Test phage",
        host="Escherichia coli",
        taxonomy="Viruses; Caudoviricetes",
        description="Test phage genome",
        length_bp=300,
        gc_percent=50.0,
        n_percent=0.0,
        topology="linear",
        molecule_type="dsDNA",
        cds_count=2,
        translated_cds_count=2,
        trna_count=0,
        has_integrase=False,
        has_terminase=True,
        has_lysin=False,
        has_capsid=False,
        has_tail=False,
        fasta_sha256="a" * 64,
        gbk_sha256="b" * 64,
        fasta_path=str(fa),
        gbk_path=str(gbk),
        cds_items=[
            PhageCDSRecord("NC_999.1", "L_SHORT", "P_SHORT", 1, 30, 1, 10, "tiny peptide", "M" * 10),
            PhageCDSRecord("NC_999.1", "L_LONG", "P_LONG", 40, 280, 1, 80, "terminase", "M" * 80),
        ],
    )

    manifest = build_phage_dataset_indexes(data_dir, [rec], build_blast_db=False, min_prot_aa=25)
    assert Path(manifest["artifacts"]["nucl_fasta"]).exists()
    prot_text = Path(manifest["artifacts"]["prot_fasta"]).read_text(encoding="utf-8")
    assert "P_LONG" in prot_text
    assert "P_SHORT" not in prot_text

    with closing(sqlite3.connect(manifest["artifacts"]["sqlite_index"])) as conn:
        cds_ids = [r[0] for r in conn.execute("SELECT protein_id FROM cds_features").fetchall()]
    assert cds_ids == ["P_LONG"]
