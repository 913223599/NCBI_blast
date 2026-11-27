# -*- coding: utf-8 -*-
"""
蛋白序列解析与多 FASTA 相似度检索单元测试及端到端 BLAST 验证套件。
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

from src.analysis.protein_search import SearchConfig, run_protein_fasta_search
from src.analysis.protein_search.blast_runner import compute_parallel_plan
from src.analysis.protein_search.fasta_parser import (
    classify_file_sequences,
    parse_query_proteins,
)
import pytest

pytestmark = pytest.mark.offline

# 简单反向翻译密码子表（用于合成可控一致性的测试 DNA）
_AA_TO_CODON = {
    "A": "GCG", "C": "TGC", "D": "GAT", "E": "GAA", "F": "TTC",
    "G": "GGC", "H": "CAT", "I": "ATT", "K": "AAA", "L": "CTG",
    "M": "ATG", "N": "AAC", "P": "CCG", "Q": "CAG", "R": "CGT",
    "S": "AGC", "T": "ACC", "V": "GTG", "W": "TGG", "Y": "TAT",
}


def _back_translate(protein_seq: str) -> str:
    return "".join(_AA_TO_CODON[aa] for aa in protein_seq)


def _mutate_protein(protein_seq: str, keep_every_n: int, mod_keep: int) -> str:
    """保留部分位点并确定性替换其余位点，用于构造目标一致性区间蛋白。"""
    alt_pool = "ARNDCQEGHILKMFPSTWYV"
    chars = list(protein_seq)
    for i, ch in enumerate(chars):
        if i % keep_every_n >= mod_keep:
            idx = (alt_pool.index(ch) + 7) % len(alt_pool)
            chars[i] = alt_pool[idx]
    return "".join(chars)


def test_compute_parallel_plan_preserves_host_cores() -> None:
    """验证多核并行规划遵循核心保留红线，不会打满主机所有逻辑核心。"""
    workers_32, threads_32 = compute_parallel_plan(num_shards=8, cpu_count=32)
    assert workers_32 >= 2
    assert workers_32 * threads_32 <= 28

    workers_8, threads_8 = compute_parallel_plan(num_shards=4, cpu_count=8)
    assert workers_8 * threads_8 <= 6

    workers_1, threads_1 = compute_parallel_plan(num_shards=1, cpu_count=32)
    assert workers_1 == 1
    assert 1 <= threads_1 <= 16


def test_classify_file_sequences_distinguishes_dna_protein_and_3di() -> None:
    """验证 DNA、Protein 与 3Di 结构编码序列的准确分类。"""
    dna_recs = [("c1", "ATGCGTACGTAGCTAGCTAGCATGCGTACGTAGCTA" * 5)]
    assert classify_file_sequences(dna_recs, "genome.fasta") == ["dna"]

    prot_recs = [
        ("p1", "MEKFKFIDLFSGIGGFHQAMEQLGGECVLASEIDKYAVETYKENYNMDSHIDIRDLKVDD"),
        ("p2", "MTYTPYTMKDVHDSSDRALFTVISTFAGGGGSSTGYRLAGGKLLAINEFVEEARITYHQN"),
    ]
    assert classify_file_sequences(prot_recs, "phold_aa.fasta") == ["protein", "protein"]

    # 同时测试按文件名识别 3Di 及按序列内容启发式识别 3Di
    three_di_recs = [
        (f"s{i}", "DPPPPPPDPPDDDDDDCVVCVVVVVVCVVVDFDFDDQPDVVVVVVVVVVVVVDDDDDPPP")
        for i in range(6)
    ]
    assert classify_file_sequences(three_di_recs, "phold_3di.fasta") == ["3di"] * 6
    assert classify_file_sequences(three_di_recs, "unnamed_struct.fasta") == ["3di"] * 6


def test_parse_query_proteins_preserves_duplicate_content_entries(tmp_path: Path) -> None:
    """验证查询蛋白解析保留全部独立条目（包括序列相同但 ID 不同的条目）及 UTF-8 BOM 兼容。"""
    q_file = tmp_path / "queries.fasta"
    seq = "MEKFKFIDLFSGIGGFHQAMEQLGGECVLASEIDKYAVETYKENYNMDSHIDIRDLKVDD"
    q_file.write_bytes(
        ("\ufeff>prot_A methylase alpha\n" + seq + "\n>prot_B methylase dup\n" + seq + "\n").encode(
            "utf-8"
        )
    )
    recs = parse_query_proteins(q_file)
    assert len(recs) == 2
    assert recs[0].query_id == "prot_A"
    assert recs[1].query_id == "prot_B"
    assert recs[0].sha256_prefix == recs[1].sha256_prefix
    assert recs[0].safe_id == "Q_0001"
    assert recs[1].safe_id == "Q_0002"


def test_end_to_end_sharded_blast_marking_and_checkpoint_resume(tmp_path: Path) -> None:
    """
    端到端集成测试：
    - 中文/全角符号文件名与 multi-FASTA
    - tblastn (DNA) + blastp (Protein) + 3Di 自动跳过
    - >30% 精准标记与 <=30% 不误标
    - 分片落盘、Checkpoint 断点续跑、统一 -dbsize E-value 一致性
    """
    query_seq = (
        "MEKFKFIDLFSGIGGFHQAMEQLGGECVLASEIDKYAVETYKENYNMDSHIDIRDLKVDD"
        "VPEHDVLCAGFPCQAFSKAGKQEGFDDETRGTLFFEIERIIKHHHPPYIVLENVRNLASH"
    )  # 120 aa
    query_fasta = tmp_path / "查询蛋白.fasta"
    query_fasta.write_text(f">TestMethylase_01 synthetic query\n{query_seq}\n", encoding="utf-8")

    target_dir = tmp_path / "目标序列_目录"
    target_dir.mkdir()

    # 1. 阳性 DNA 文件（含中文及全角括号，2 条 contig：第1条约75%一致性，第2条无关序列）
    homolog_prot_75 = _mutate_protein(query_seq, keep_every_n=4, mod_keep=3)
    pos_dna_seq = "AATTCCGGTTAACCGGTTAA" + _back_translate(homolog_prot_75) + "TTAACCGGAATTCCGGTTAA"
    neg_dna_seq = ("ATGCTAGCTTGACGATCGTTACGATCGTAGCTGACTGATCGTAGCTGACGTAGCTGACGT" * 8)
    (target_dir / "样本1_阳性（测试）.fasta").write_text(
        f">contig_pos_1 circular=true\n{pos_dna_seq}\n>contig_neg_2 decoy\n{neg_dna_seq}\n",
        encoding="utf-8",
    )

    # 2. 阴性 DNA 文件（完全无关序列）
    (target_dir / "sample_neg_dna.fasta").write_text(
        f">neg_scaffold_1\n{('CGTACGTAGCTGACTGACTGATCGTAGCTAGCTGATCG' * 15)}\n",
        encoding="utf-8",
    )

    # 3. 蛋白目标文件（含 1 条约 60% 一致性蛋白 + 1 条无关蛋白）
    homolog_prot_60 = _mutate_protein(query_seq, keep_every_n=5, mod_keep=3)
    unrelated_prot = "M" + ("ACDEFGHIKLMNPQRSTVWY" * 6)
    (target_dir / "phold_aa.fasta").write_text(
        f">CDS_0001_homolog\n{homolog_prot_60}\n>CDS_0002_unrelated\n{unrelated_prot}\n",
        encoding="utf-8",
    )

    # 4. 3Di 结构编码文件（应自动跳过）
    (target_dir / "phold_3di.fasta").write_text(
        ">CDS_0001_3di\n" + ("DPPPPPPDDDDDVVVVVVVVPPPPPDDDDD" * 4) + "\n",
        encoding="utf-8",
    )

    # 第一次运行：故意在含空格与中文的输出路径下强制 shard_max_files=1 形成多分片
    out_sharded = tmp_path / "out sharded 含空格目录"
    cfg_sharded = SearchConfig(
        query_fasta=query_fasta,
        target_dir=target_dir,
        output_dir=out_sharded,
        min_pident=30.0,
        max_evalue=1e-5,
        blast_evalue=1e-3,
        min_align_len=30,
        shard_max_files=1,
        resume=True,
    )
    res1 = run_protein_fasta_search(cfg_sharded)

    assert res1.query_count == 1
    assert res1.target_file_count == 4
    assert res1.dna_file_count == 2
    assert res1.protein_file_count == 1
    assert res1.skipped_3di_file_count == 1
    assert res1.marked_hit_file_count == 2
    assert res1.marked_hit_sequence_count == 2
    assert res1.shards_total == 3
    assert res1.shards_resumed == 0

    # 检查 checkpoint.json 完整性
    ckpt = json.loads((out_sharded / "_work" / "checkpoint.json").read_text(encoding="utf-8"))
    assert len(ckpt["shards"]) == 3
    assert all(v["status"] == "completed" for v in ckpt["shards"].values())

    # 检查文件级标记表
    with res1.output_files["marked_files_summary_tsv"].open("r", encoding="utf-8") as f:
        rows = {r["file_name"]: r for r in csv.DictReader(f, delimiter="\t")}
    assert rows["样本1_阳性（测试）.fasta"]["mark_label"] == "[HIT>30%]"
    assert rows["样本1_阳性（测试）.fasta"]["hit_records_gt30"] == "1"
    assert float(rows["样本1_阳性（测试）.fasta"]["max_pident"]) > 60.0
    assert rows["phold_aa.fasta"]["mark_label"] == "[HIT>30%]"
    assert float(rows["phold_aa.fasta"]["max_pident"]) > 45.0
    assert rows["sample_neg_dna.fasta"]["mark_label"] == "[NO_HIT]"
    assert rows["phold_3di.fasta"]["mark_label"] == "[SKIPPED_3DI]"

    # 检查带标记 FASTA 输出
    marked_fasta_txt = res1.output_files["marked_hit_sequences_fasta"].read_text(encoding="utf-8")
    assert "[HIT>30%|file=样本1_阳性（测试）.fasta|" in marked_fasta_txt
    assert "[HIT>30%|file=phold_aa.fasta|" in marked_fasta_txt
    assert "contig_neg_2" not in marked_fasta_txt
    assert "CDS_0002_unrelated" not in marked_fasta_txt

    # 检查断点续跑：第二次执行全部 3 个分片均被复用
    res2 = run_protein_fasta_search(cfg_sharded)
    assert res2.shards_resumed == 3
    assert res2.marked_hit_file_count == res1.marked_hit_file_count

    # 对比验证单分片（全库）vs 多分片（带 -dbsize）的 E-value 一致性
    out_single = tmp_path / "out_single"
    cfg_single = SearchConfig(
        query_fasta=query_fasta,
        target_dir=target_dir,
        output_dir=out_single,
        min_pident=30.0,
        max_evalue=1e-5,
        blast_evalue=1e-3,
        min_align_len=30,
        shard_max_files=100,
        resume=False,
    )
    res_single = run_protein_fasta_search(cfg_single)
    assert res_single.shards_total == 2  # 1 DNA + 1 Protein

    with res1.output_files["blast_hits_gt30_tsv"].open("r", encoding="utf-8") as f1:
        hits_sharded = {
            (r["target_file"], r["target_seq_id"]): float(r["evalue"])
            for r in csv.DictReader(f1, delimiter="\t")
        }
    with res_single.output_files["blast_hits_gt30_tsv"].open("r", encoding="utf-8") as f2:
        hits_single = {
            (r["target_file"], r["target_seq_id"]): float(r["evalue"])
            for r in csv.DictReader(f2, delimiter="\t")
        }
    assert hits_sharded.keys() == hits_single.keys()
    for key in hits_sharded:
        ev_sh = hits_sharded[key]
        ev_sg = hits_single[key]
        if ev_sg > 0:
            ratio = ev_sh / ev_sg
            assert 0.5 <= ratio <= 2.0, f"E-value 偏差过大: {key} sharded={ev_sh} single={ev_sg}"
        else:
            assert ev_sh == 0.0
