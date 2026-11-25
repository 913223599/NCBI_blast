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

    # 3. 放宽后大参数组合 (ref_max_count=600, ictv_reps_per_genus=20, outgroup_count=20) 正常校验且无 SQL 截断
    cands_large = curator.curate_candidates(
        query_records=[("Q1", "ATGCTAGC" * 100)],
        ani_result=ani,
        scope=DeliveryScopeConfig(
            ref_max_count=600,
            ictv_reps_per_genus=20,
            max_target_genera=10,
            outgroup_count=20,
        ),
    )
    ogs_large = [c for c in cands_large if c.role == "outgroup"]
    assert len(ogs_large) == 20
    assert len(cands_large) <= 600


def test_macro_family_host_sampling_1000_scale(tmp_path: Path):
    import pytest

    from src.phylo.delivery.host_taxonomy import map_host_to_phylum
    from src.phylo.engines.reference.ref_curator import PhageReferenceCurator
    from src.phylo.models.schemas import AniHitRecord, AniScreenResult, DeliveryScopeConfig

    idx = get_inphared_index()
    if not idx.is_available():
        pytest.skip("INPHARED TSV/SQLite database is unavailable")

    curator = PhageReferenceCurator(index=idx, cache_dir=tmp_path / "ref_cache")
    ani = AniScreenResult(
        query_ids=["MacroQuery_1"],
        top_hits=[
            AniHitRecord(
                accession="PV620261",
                wg_ani=78.5,
                genus="Warsawvirus",
                family="Autotranscriptaviridae",
            )
        ],
        candidate_genera=["Warsawvirus"],
        candidate_families=["Autotranscriptaviridae"],
        recommended_outgroup_accessions=["NC_055913"],
    )

    cands_1000 = curator.curate_candidates(
        query_records=[("MacroQuery_1", "ATGCTAGC" * 100)],
        ani_result=ani,
        scope=DeliveryScopeConfig(
            target_rank="family_order",
            sampling_mode="macro_family_host",
            ref_max_count=1000,
            ictv_reps_per_genus=3,
            max_target_genera=4,
            outgroup_count=3,
            outgroup_ids=["NC_042095"],
            treemmer_target=1000,
        ),
    )
    accs = [c.accession for c in cands_1000]
    assert len(cands_1000) == 1000
    assert len(set(accs)) == 1000
    assert any(c.accession == "MacroQuery_1" and c.role == "query" for c in cands_1000)
    assert any(c.accession == "NC_042095" and c.role == "outgroup" for c in cands_1000)

    distinct_families = {c.family for c in cands_1000 if c.family}
    distinct_host_phyla = {map_host_to_phylum(c.host) for c in cands_1000} - {"", "Others"}
    assert len(distinct_families) >= 5
    assert len(distinct_host_phyla) >= 4

    # 无 ANI 结果时也应支持直接组装宏观背景参考集
    cands_no_ani = curator.curate_candidates(
        query_records=[("MacroQuery_1", "ATGCTAGC" * 100)],
        ani_result=None,
        scope=DeliveryScopeConfig(
            target_rank="family_order",
            sampling_mode="macro_family_host",
            ref_max_count=120,
            outgroup_count=0,
        ),
    )
    assert len(cands_no_ani) == 120
    assert len({c.accession for c in cands_no_ani}) == 120


def test_dereplicator_disabled_and_high_ani_thresholds(tmp_path: Path):
    """验证 98%/99% 高阈值去冗余与 100%(pa=1.0) 关闭去冗余完整保留同种多株系。"""
    from src.phylo.models.schemas import DeliveryScopeConfig

    assert DeliveryScopeConfig(derep_ani=0.98).derep_ani == 0.98
    assert DeliveryScopeConfig(derep_ani=0.99).derep_ani == 0.99
    assert DeliveryScopeConfig(derep_ani=1.0).derep_ani == 1.0

    genomes = {}
    cands = []
    specs = [
        ("Query_Phage", "query", "Tequintavirus", True),
        ("Ref_1", "ictv_rep", "Tequintavirus", True),
        ("Ref_2", "neighbor", "Tequintavirus", False),
        ("Ref_3", "neighbor", "Tequintavirus", False),
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
                genome_length=120000 - idx * 500,
                is_ictv_classified=is_ictv,
            )
        )

    labels = [s[0] for s in specs]
    mat = [[100.0 if i == j else 20.0 for j in range(5)] for i in range(5)]
    # Ref_1 vs Ref_2: 96.0% (同种不同株系); Ref_2 vs Ref_3: 99.2% (极高度重复)
    mat[1][2] = mat[2][1] = 96.0
    mat[1][3] = mat[3][1] = 95.8
    mat[2][3] = mat[3][2] = 99.2

    derep = PhageDereplicator()
    # 1. pa_threshold=1.0 时关闭去冗余，全部 5 条保留
    kept_all, stats_all = derep.dereplicate(
        genome_paths=genomes,
        candidates=cands,
        work_dir=tmp_path / "derep_off",
        pa_threshold=1.0,
        min_length=1000,
        ani_matrix=(labels, mat),
    )
    assert len(kept_all) == 5
    assert int(stats_all["removed"]) == 0
    assert "disabled" in str(stats_all["tool"]).lower()

    # 2. pa_threshold=0.98 时保留 96.0% 同种近缘 Ref_2，仅剔除 99.2% 极高重复 Ref_3
    kept_98, stats_98 = derep._fallback_ani_cluster(
        genome_paths=genomes,
        protected={"Query_Phage", "Outgroup_Phage", "Ref_1"},
        cand_map={c.accession: c for c in cands},
        pa_threshold=0.98,
        min_length=1000,
        ani_matrix=(labels, mat),
    )
    assert {"Query_Phage", "Outgroup_Phage", "Ref_1", "Ref_2"}.issubset(set(kept_98.keys()))
    assert "Ref_3" not in kept_98
    assert int(stats_98["after"]) == 4


def test_viridic_retains_full_mash_top_k_and_species_priority(tmp_path: Path):
    """验证 build_screen_result 全量透传 Mash Top-K 且 species 模式下优先填充同种/近缘高相似株。"""
    from unittest.mock import MagicMock

    from src.phylo.engines.ani.inphared_index import InpharedRecord
    from src.phylo.engines.reference.ref_curator import PhageReferenceCurator
    from src.phylo.models.schemas import DeliveryScopeConfig

    mock_index = MagicMock()
    mock_index.is_available.return_value = True

    mash_map = {}
    for i in range(1, 26):
        acc = f"ACC_{i:02d}"
        ani_val = round(98.5 - (i - 1) * 0.9, 2)
        dist = round(1.0 - ani_val / 100.0, 4)
        # 一半是已知属 Tequintavirus，一半是未划分 ICTV 属的同种/高近缘株
        genus_name = "Tequintavirus" if i % 2 == 1 else ""
        rec = InpharedRecord(
            accession=acc,
            description=f"Escherichia phage test_{i:02d}",
            genome_length=118000,
            gc_content=39.5,
            host="Escherichia",
            genus=genus_name,
            family="Demerecviridae",
            order_name="",
        )
        mash_map[acc] = (dist, ani_val, rec)

    og_recs = [
        InpharedRecord(accession="OG_01", genus="OutGenus", family="Demerecviridae", genome_length=110000),
        InpharedRecord(accession="OG_02", genus="OutGenus", family="Demerecviridae", genome_length=111000),
    ]
    ictv_reps = [
        InpharedRecord(
            accession=f"REP_{j:02d}",
            description=f"ICTV Rep {j:02d}",
            genus="Tequintavirus",
            family="Demerecviridae",
            genome_length=120000,
        )
        for j in range(1, 15)
    ]
    mock_index.get_by_accessions.side_effect = lambda accs: {
        r.accession: r for r in og_recs if r.accession in accs
    }
    mock_index.find_outgroup_candidates.return_value = og_recs
    mock_index.find_ictv_representatives.side_effect = (
        lambda genera, families, exclude_accessions=(), per_genus=3, max_total=60: [
            r for r in ictv_reps if r.accession not in set(exclude_accessions)
        ][: min(per_genus, max_total)]
    )

    calc = ViridicAniCalculator(index=mock_index)
    # 仅前 2 条进 VIRIDIC 精算矩阵，其余 23 条来自 Mash Top-K 初筛
    labels = ["Q1", "ACC_01", "ACC_02"]
    wgani_mat = [
        [100.0, 97.6, 95.8],
        [97.6, 100.0, 96.0],
        [95.8, 96.0, 100.0],
    ]
    af_mat = [
        [100.0, 96.0, 94.0],
        [96.0, 100.0, 95.0],
        [94.0, 95.0, 100.0],
    ]
    pair_details = {
        ("Q1", "ACC_01"): (97.6, 98.1, 96.0, 95.5),
        ("Q1", "ACC_02"): (95.8, 96.5, 94.0, 93.0),
    }
    scope = DeliveryScopeConfig(
        target_rank="species",
        sampling_mode="focused",
        ref_max_count=30,
        ictv_reps_per_genus=10,
        max_target_genera=3,
        outgroup_count=2,
        mash_top_k=25,
    )
    res = calc.build_screen_result(
        query_ids=["Q1"],
        mash_hits_map=mash_map,
        matrix_labels=labels,
        wgani_matrix=wgani_mat,
        af_matrix=af_mat,
        pair_details=pair_details,
        scope=scope,
        engine_used="viridic_blastn",
        engine_version="2.15",
        command_preview="blastn",
    )

    assert len(res.top_hits) == 25
    assert res.top_hits[0].accession == "ACC_01"
    assert res.top_hits[0].wg_ani == 97.6
    assert res.top_hits[1].accession == "ACC_02"
    assert res.top_hits[2].wg_ani == 0.0
    assert (res.top_hits[2].mash_ani or 0.0) > 95.0
    assert "97.60%" in res.summary_call

    curator = PhageReferenceCurator(index=mock_index, cache_dir=tmp_path / "ref_cache")
    cands = curator.curate_candidates(
        query_records=[("Q1", "ATGCTAGC" * 100)],
        ani_result=res,
        scope=scope,
    )
    accs = {c.accession for c in cands}
    # 应容纳绝大多数 top_hits（含未命名属近邻 ACC_02, ACC_04...），同时保留 query/外群/ICTV锚点
    matched_hits = [acc for acc in accs if acc.startswith("ACC_")]
    assert len(matched_hits) >= 20
    assert "ACC_22" in accs
    assert any(c.role == "outgroup" for c in cands)
    assert any(c.role == "ictv_rep" and c.accession.startswith("REP_") for c in cands)
