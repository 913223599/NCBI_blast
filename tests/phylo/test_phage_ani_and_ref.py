# -*- coding: utf-8 -*-
"""
阶段一/二测试：INPHARED 索引、VIRIDIC-wgANI 公式与分片、去冗余与 Treemmer 降采样
"""
from pathlib import Path

from src.phylo.engines.ani.inphared_index import InpharedIndex, get_inphared_index
from src.phylo.engines.ani.viridic_ani import (
    HspSegment,
    ViridicAniCalculator,
    classify_ictv_threshold,
    compute_viridic_pair_metrics,
)
from src.phylo.engines.reference.dereplicator import PhageDereplicator
from src.phylo.engines.reference.treemmer_pruner import TreemmerPruner
from src.phylo.models.schemas import ReferenceCandidate


def test_inphared_index_build_and_query():
    idx: InpharedIndex = get_inphared_index()
    assert idx.is_available(), "database/pharokka_db/9Aug2025_data.tsv should exist"
    idx.ensure_built()
    recs = idx.get_by_accessions(["PV620261", "NC_001330.1"])
    assert "PV620261" in recs
    assert recs["PV620261"].genus == "Warsawvirus"
    assert recs["PV620261"].family == "Autotranscriptaviridae"

    reps = idx.find_ictv_representatives(
        genera=["Warsawvirus"], families=["Autotranscriptaviridae"], per_genus=3, max_total=12
    )
    assert len(reps) >= 3
    outgroups = idx.find_outgroup_candidates(
        target_genera=["Warsawvirus"],
        target_families=["Autotranscriptaviridae"],
        target_orders=["Autographivirales"],
        limit=3,
    )
    assert len(outgroups) >= 1
    assert all(og.genus != "Warsawvirus" for og in outgroups)


def test_viridic_formula_and_overlap_dedup(tmp_path: Path):
    # 存在重叠的 HSP 不得导致 AF > 100%
    hsps_ab = [
        HspSegment(q_start=1, q_end=500, nident=480, align_len=500),
        HspSegment(q_start=250, q_end=750, nident=475, align_len=500),
    ]
    hsps_ba = [
        HspSegment(q_start=1, q_end=750, nident=720, align_len=750),
    ]
    wg, aln_ani, af_a, af_b = compute_viridic_pair_metrics(1000, 1000, hsps_ab, hsps_ba)
    assert 70.0 <= wg <= 76.0
    assert af_a == 75.0
    assert af_b == 75.0
    assert aln_ani >= 94.0

    # ICTV 分级与模糊带 / 嵌合判断
    c_sp, m_sp = classify_ictv_threshold(96.2, 97.1, 98.0, 96.5)
    assert c_sp == "same_species" and not m_sp

    c_amb, _ = classify_ictv_threshold(71.4, 82.0, 80.0, 81.0)
    assert c_amb == "genus_boundary_ambiguous"

    c_nov, m_nov = classify_ictv_threshold(35.0, 88.5, 38.0, 41.0)
    assert c_nov == "novel_genus_candidate" and m_nov is True

    # 用真实 WSL blastn 计算合成高相似度基因组矩阵
    fa_a = tmp_path / "Phage_A.fasta"
    fa_b = tmp_path / "Phage_B.fasta"
    fa_c = tmp_path / "Phage_C.fasta"
    base = "ATGCTAGCTAGCATCGATCGATCGATAGCATCGATCGTAGCTAGCTA" * 80
    fa_a.write_text(f">Phage_A\n{base}\n", encoding="utf-8", newline="\n")
    fa_b.write_text(f">Phage_B\n{base[:3000]}" + "GGGG" * 190 + "\n", encoding="utf-8", newline="\n")
    fa_c.write_text(f">Phage_C\n{'TTTTCCCCAAAAGGGG' * 200}\n", encoding="utf-8", newline="\n")

    calc = ViridicAniCalculator()
    labels, wgani_mat, af_mat, details, _ver, cmd_prev = calc.compute_matrix_from_fastas(
        {"Phage_A": fa_a, "Phage_B": fa_b, "Phage_C": fa_c},
        work_dir=tmp_path / "viridic",
        engine="viridic_blastn",
        threads=4,
    )
    assert labels == ["Phage_A", "Phage_B", "Phage_C"]
    assert "blastn" in cmd_prev
    assert wgani_mat[0][0] == 100.0
    assert wgani_mat[0][1] > 70.0
    assert wgani_mat[0][2] < 30.0
    assert (tmp_path / "viridic" / "ani_checkpoint.json").is_file()


def test_dereplicator_and_treemmer_preserve_protected(tmp_path: Path):
    # 验证聚类去冗余与 Treemmer 绝对不删除 query 和 outgroup
    genomes = {}
    cands = []
    specs = [
        ("Query_Phage", "query", "TargetGenus", True),
        ("Ref_1", "ictv_rep", "TargetGenus", True),
        ("Ref_2", "neighbor", "TargetGenus", False),
        ("Ref_3", "neighbor", "TargetGenus", False),
        ("Outgroup_Phage", "outgroup", "OutGenus", True),
    ]
    for idx, (acc, role, genus, is_ictv) in enumerate(specs):
        p = tmp_path / f"{acc}.fasta"
        p.write_text(f">{acc}\n" + ("ATGC" * 500) + "\n", encoding="utf-8")
        genomes[acc] = p
        cands.append(
            ReferenceCandidate(
                accession=acc,
                role=role,  # type: ignore[arg-type]
                genus=genus,
                genome_length=2000 + idx * 10,
                is_ictv_classified=is_ictv,
            )
        )

    labels = [s[0] for s in specs]
    # 构造 Ref_1/Ref_2/Ref_3 高于 90% 相似的矩阵
    mat = [[100.0 if i == j else 20.0 for j in range(5)] for i in range(5)]
    for i in (1, 2, 3):
        for j in (1, 2, 3):
            mat[i][j] = 95.0 if i != j else 100.0

    derep = PhageDereplicator()
    kept, stats = derep._fallback_ani_cluster(
        genome_paths=genomes,
        protected={"Query_Phage", "Outgroup_Phage", "Ref_1"},
        cand_map={c.accession: c for c in cands},
        pa_threshold=0.90,
        min_length=1000,
        ani_matrix=(labels, mat),
    )
    assert "Query_Phage" in kept
    assert "Outgroup_Phage" in kept
    assert "Ref_1" in kept
    assert int(stats["after"]) == 3

    # 验证 Treemmer 等效修剪保护叶子
    nwk = "((Query_Phage:0.01,Ref_1:0.01):0.05,((Ref_2:0.002,Ref_3:0.003):0.04,Outgroup_Phage:0.2):0.1);"
    pruned = TreemmerPruner.prune_newick_leaves(
        nwk, target_count=3, protected={"Query_Phage", "Outgroup_Phage"}
    )
    assert "Query_Phage" in pruned
    assert "Outgroup_Phage" in pruned
    assert len(pruned) == 3


def test_ref_curator_respects_custom_counts_and_manual_outgroups(tmp_path: Path):
    """验证参考群上限、每属代表数、覆盖属数、自动外群数量与手动指定外群均按配置生效。"""
    from src.phylo.engines.reference.ref_curator import PhageReferenceCurator
    from src.phylo.models.schemas import AniHitRecord, AniScreenResult, DeliveryScopeConfig

    curator = PhageReferenceCurator(cache_dir=tmp_path / "ref_cache")
    ani = AniScreenResult(
        query_ids=["Q1"],
        top_hits=[
            AniHitRecord(
                accession="AY587007",
                description="Escherichia phage T5",
                wg_ani=92.0,
                genus="Tequintavirus",
                family="Demerecviridae",
            )
        ],
        candidate_genera=["Tequintavirus", "Epseptimavirus", "Sugarlandvirus"],
        candidate_families=["Demerecviridae"],
        recommended_outgroup_accessions=["NC_055913"],
    )

    # 1. outgroup_count=0 且无手动外群时不纳入自动外群
    cands_no_og = curator.curate_candidates(
        query_records=[("Q1", "ATGCTAGC" * 100)],
        ani_result=ani,
        scope=DeliveryScopeConfig(
            ref_max_count=20,
            ictv_reps_per_genus=2,
            max_target_genera=2,
            outgroup_count=0,
        ),
    )
    assert [c for c in cands_no_og if c.role == "outgroup"] == []

    # 2. outgroup_count=4 自动从本地 INPHARED 补足外群，且手动外群与受控总数均生效
    cands_custom = curator.curate_candidates(
        query_records=[("Q1", "ATGCTAGC" * 100)],
        ani_result=ani,
        scope=DeliveryScopeConfig(
            ref_max_count=25,
            ictv_reps_per_genus=2,
            max_target_genera=3,
            outgroup_count=4,
            outgroup_ids=["NC_042095"],
        ),
    )
    ogs = [c for c in cands_custom if c.role == "outgroup"]
    assert any(c.accession == "NC_042095" for c in ogs)
    assert len(ogs) == 4
    assert len(cands_custom) <= 25
    reps = [c for c in cands_custom if c.role == "ictv_rep"]
    assert len(reps) >= 2
    assert any(c.description for c in reps)
