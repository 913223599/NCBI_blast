# -*- coding: utf-8 -*-
"""train split 细菌前噬菌体矿脉抽取与 CheckV 精标分拣单元测试。"""
import json
import sqlite3
from contextlib import closing
from pathlib import Path

from src.phage_discovery.teachers.prophage_miner import (
    curate_checkv_mined_dataset,
    extract_train_prophage_candidates,
)


def test_prophage_miner_only_extracts_train_split_and_curates(tmp_path: Path):
    neg_dir = tmp_path / "neg"
    (neg_dir / "fasta").mkdir(parents=True)
    (neg_dir / "index").mkdir(parents=True)

    seq_train = "A" * 100000
    seq_test = "C" * 100000
    (neg_dir / "fasta" / "NZ_TRAIN.1.fasta").write_text(f">NZ_TRAIN.1\n{seq_train}\n", encoding="utf-8")
    (neg_dir / "fasta" / "NZ_TEST.1.fasta").write_text(f">NZ_TEST.1\n{seq_test}\n", encoding="utf-8")

    with closing(sqlite3.connect(neg_dir / "index" / "negative_index.sqlite")) as conn:
        conn.execute(
            "CREATE TABLE genomes (accession TEXT PRIMARY KEY, is_valid_negative INTEGER, negative_category TEXT, length_bp INTEGER, fasta_relpath TEXT);"
        )
        conn.execute("CREATE TABLE prophage_masks (id INTEGER PRIMARY KEY AUTOINCREMENT, accession TEXT, start_pos INTEGER, end_pos INTEGER);")
        conn.execute("INSERT INTO genomes VALUES ('NZ_TRAIN.1', 1, 'bacterial_chromosome', 100000, 'fasta/NZ_TRAIN.1.fasta')")
        conn.execute("INSERT INTO genomes VALUES ('NZ_TEST.1', 1, 'bacterial_chromosome', 100000, 'fasta/NZ_TEST.1.fasta')")
        conn.execute("INSERT INTO prophage_masks (accession, start_pos, end_pos) VALUES ('NZ_TRAIN.1', 35000, 50000)")
        conn.execute("INSERT INTO prophage_masks (accession, start_pos, end_pos) VALUES ('NZ_TEST.1', 35000, 50000)")
        conn.commit()

    splits_file = tmp_path / "negative_splits.json"
    splits_file.write_text(json.dumps({"NZ_TRAIN.1": "train", "NZ_TEST.1": "test"}), encoding="utf-8")

    out_dir = tmp_path / "mined"
    ext = extract_train_prophage_candidates(neg_dir, splits_file, out_dir, flank_bp=20000, target_split="train")
    assert ext["chromosomes_scanned"] == 1
    assert ext["candidates_extracted"] == 1
    cmap = json.loads(Path(ext["candidate_map"]).read_text(encoding="utf-8"))
    assert cmap["MINED_CAND_0001"]["source_accession"] == "NZ_TRAIN.1"

    # 模拟 CheckV contamination & quality 输出验证分拣逻辑
    cv_dir = out_dir / "checkv_raw"
    cv_dir.mkdir(parents=True)
    # 补充 1 条硬负样本候选进 FASTA
    cand_fna = Path(ext["candidates_fasta"])
    cand_fna.write_text(cand_fna.read_text(encoding="utf-8") + ">MINED_CAND_0002\n" + ("G" * 30000) + "\n", encoding="utf-8")

    (cv_dir / "quality_summary.tsv").write_text(
        "contig_id\tcheckv_quality\tcompleteness\nMINED_CAND_0001\tHigh-quality\t92.5\nMINED_CAND_0002\tNot-determined\tNA\n",
        encoding="utf-8",
    )
    (cv_dir / "contamination.tsv").write_text(
        "contig_id\tcontig_length\tviral_genes\thost_genes\tprovirus\tregion_types\tregion_coords_bp\tregion_viral_genes\n"
        "MINED_CAND_0001\t55000\t25\t40\tYes\thost,viral,host\t1-15000,15001-40000,40001-55000\t0,25,0\n"
        "MINED_CAND_0002\t30000\t1\t25\tNo\thost\t1-30000\t1\n",
        encoding="utf-8",
    )
    cur = curate_checkv_mined_dataset(cand_fna, cv_dir, out_dir)
    assert cur["verified_prophage_contigs"] == 1
    assert cur["verified_prophage_regions"] == 1
    assert cur["hard_negative_contigs"] == 1
    truth_txt = Path(cur["mined_truth_tsv"]).read_text(encoding="utf-8")
    assert "MINED_CAND_0001\t55000\tMINED_CAND_0001_R1\t15000\t40000" in truth_txt
