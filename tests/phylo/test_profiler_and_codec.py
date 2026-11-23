# -*- coding: utf-8 -*-
"""
阶段一测试：序列画像、安全短 ID 编解码与树拓扑后处理
"""
from pathlib import Path

from src.phylo.core.id_codec import IdCodec
from src.phylo.core.profiler import SequenceProfiler
from src.phylo.pipeline.postprocess import (
    compute_tree_metrics,
    parse_newick,
    reroot_midpoint,
    reroot_outgroup,
)


def test_id_codec_dedup_and_restore():
    raw_ids = ["Strain A", "Strain A", "Sample:1(test)", "Strain_B"]
    dedup = IdCodec.deduplicate_ids(raw_ids)
    assert dedup == ["Strain A", "Strain A_2", "Sample:1(test)", "Strain_B"]

    codec = IdCodec()
    mapping = codec.build_mapping(dedup)
    assert list(mapping.keys()) == ["T000001", "T000002", "T000003", "T000004"]

    raw_nwk = "((T000001:0.01,T000002:0.02)95:0.03,(T000003:0.04,T000004:0.05)88:0.02);"
    restored = IdCodec.restore_newick(raw_nwk, mapping)
    assert "'Strain A':0.01" in restored
    assert "'Strain A_2':0.02" in restored
    assert "'Sample:1(test)':0.04" in restored
    assert "Strain_B:0.05" in restored
    assert ")95:0.03" in restored


def test_profiler_track_recommendation():
    short_records = [
        ("seq1", "ATGCGTACGTAGCTAGCTAG" * 15),
        ("seq2", "ATGCGTACGTAGCTAGCTGG" * 14 + "ATGCG"),
        ("seq3", "ATGCGTACGTAGCTAGCGAG" * 15),
        ("seq4", "ATGCGTACGTAGTTAGCTAG" * 15),
    ]
    prof_gene = SequenceProfiler.profile_records(short_records)
    assert prof_gene.mol_type == "dna"
    assert prof_gene.recommended_track == "gene"
    assert prof_gene.recommended_msa == "mafft"

    genome_records = [
        ("phage1", ("ATGCGTACGT" * 2000)),
        ("phage2", ("ATGCGTACGT" * 1950)),
        ("phage3", ("ATGCGTACGA" * 2050)),
        ("phage4", ("ATGCGTTCGT" * 2000)),
    ]
    prof_genome = SequenceProfiler.profile_records(genome_records)
    assert prof_genome.recommended_track == "genome"
    assert prof_genome.recommended_msa == "none"
    assert any("全基因组无对齐" in w for w in prof_genome.warnings)


def test_postprocess_reroot_and_metrics():
    nwk = "((A:0.1,B:0.1)90:0.2,C:0.5,D:0.4);"
    mid = reroot_midpoint(nwk)
    root_mid = parse_newick(mid)
    assert len(root_mid.children) == 2

    out = reroot_outgroup(nwk, "C")
    root_out = parse_newick(out)
    assert len(root_out.children) == 2
    leaf_names_direct = {c.name for c in root_out.children if c.is_leaf}
    assert "C" in leaf_names_direct

    metrics = compute_tree_metrics(mid)
    assert metrics.leaf_count == 4
    assert metrics.is_rooted is True
    assert abs(metrics.total_branch_length - 1.3) < 1e-4


def test_profiler_multifile_shared_scaffold_header(tmp_path: Path):
    """多个独立基因组文件内部均含相同 header (>ngcs_scaffold_1) 时，自动提取清晰文件名 ID 避免重名冲突。"""
    files = []
    for name in ("T5-E1_asm_ngcs_scaffold_1.fasta", "T5-E2_asm_ngcs_scaffold_1.fasta", "T5-WT_asm_ngcs_scaffold_1.fasta"):
        p = tmp_path / name
        p.write_text(f">ngcs_scaffold_1 length=1000\n{'ATGCGTACGT' * 100}\n", encoding="utf-8")
        files.append(p)

    prof, records = SequenceProfiler.profile_files(files)
    assert prof.sequence_count == 3
    assert prof.duplicate_id_count == 0
    assert [r[0] for r in records] == [
        "T5-E1_asm_ngcs_scaffold_1",
        "T5-E2_asm_ngcs_scaffold_1",
        "T5-WT_asm_ngcs_scaffold_1",
    ]


def test_deterministic_sanitized_order_independent(tmp_path: Path):
    """乱序输入相同序列集时，content_hash 与短 ID 映射必须完全一致，避免 StageCache 错位。"""
    recs_a = [
        ("Zebra", "ATGCGTACGT" * 5),
        ("Alpha", "TTGCGTACGT" * 5),
        ("Middle", "GCGCGTACGT" * 5),
    ]
    recs_b = list(reversed(recs_a))

    prof_a = SequenceProfiler.profile_records(recs_a)
    prof_b = SequenceProfiler.profile_records(recs_b)
    assert prof_a.content_hash == prof_b.content_hash

    _, codec_a = SequenceProfiler.write_sanitized_fasta(recs_a, tmp_path / "a.fa", tmp_path / "a.json")
    _, codec_b = SequenceProfiler.write_sanitized_fasta(recs_b, tmp_path / "b.fa", tmp_path / "b.json")
    assert codec_a.short_to_orig == codec_b.short_to_orig
    assert codec_a.short_to_orig["T000001"] == "Alpha"


def test_fasttree_and_mrbayes_support_normalization(tmp_path: Path):
    from src.phylo.engines.tree.fasttree import normalize_fasttree_support
    from src.phylo.engines.tree.mrbayes import MrBayesEngine

    raw_ft = "((T1:0.1,T2:0.2)0.953:0.1,(T3:0.3,T4:0.4)0.800:0.1)1.000;"
    norm_ft = normalize_fasttree_support(raw_ft)
    assert ")95:" in norm_ft
    assert ")80:" in norm_ft
    assert ")100;" in norm_ft

    nex_tree = tmp_path / "test.con.tre"
    nex_tree.write_text(
        "#NEXUS\nbegin trees;\ntranslate\n1 T1,\n2 T2,\n3 T3,\n4 T4;\n"
        "tree con = ((1:0.1,2:0.1)[&prob=0.985,prob_stddev=0.01]:0.2,(3:0.1,4:0.1)[&prob=0.72]:0.2);\nend;\n",
        encoding="utf-8",
    )
    extracted = MrBayesEngine._extract_newick_from_nexus(nex_tree)
    assert ")98:0.2" in extracted
    assert ")72:0.2" in extracted
    assert "T1:0.1" in extracted
