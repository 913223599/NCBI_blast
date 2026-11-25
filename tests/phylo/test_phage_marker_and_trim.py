# -*- coding: utf-8 -*-
"""
阶段二/三测试：TerL PHROGs 子库抽提、ClipKIT (-m kpic) 修剪与双支持值拓扑统计
"""
from pathlib import Path

from src.phylo.engines.marker.terl_extractor import TerlExtractor
from src.phylo.engines.trimmer import AlignmentTrimmer
from src.phylo.pipeline.postprocess import (
    check_outgroup_placement,
    compute_tree_metrics,
    find_sister_taxa,
    reroot_outgroup,
)
from src.phylo.runtime.tool_registry import get_tool_registry


def test_tool_registry_detects_phage_research_tools():
    reg = get_tool_registry()
    reg.refresh()
    assert reg.get("clipkit").available, "WSL phylo_phage clipkit should be detected"
    assert reg.get("fastani").available, "WSL phylo_phage fastANI should be detected"
    assert reg.get("skani").available, "WSL phylo_phage skani should be detected"
    assert reg.get("drep").available, "WSL phylo_phage dRep should be detected"
    assert reg.get("blastn").available
    assert reg.get("prodigal-gv").available
    assert reg.get("hmmsearch").available
    assert reg.get("iqtree").available


def test_terl_phrog_subset_creation():
    ext = TerlExtractor()
    names = ext.load_terl_phrog_names()
    assert len(names) >= 40
    assert "phrog_2" in names
    hmm_path = ext.ensure_terl_hmm_db()
    assert hmm_path.is_file()
    assert hmm_path.with_suffix(".hmm.h3i").is_file()


def test_clipkit_kpic_and_numpy_fallback(tmp_path: Path):
    msa = tmp_path / "terl_msa.fasta"
    # 列1-25 高度保守+简约信息位点，列26-35 全为高gap垃圾列
    seqs = {
        "T1": "MKTLLVAVGA" * 3 + "-----A----",
        "T2": "MKTLLVAVGA" * 3 + "----------",
        "T3": "MKTLIVAVGS" * 3 + "-------G--",
        "T4": "MKTLIVAVGS" * 3 + "----------",
        "T5": "MKTLLISVGA" * 3 + "----------",
    }
    with open(msa, "w", encoding="utf-8", newline="\n") as fh:
        for k, v in seqs.items():
            fh.write(f">{k}\n{v}\n")

    out_kpic = tmp_path / "trimmed_kpic.fasta"
    _, stats_cli = AlignmentTrimmer.trim_with_mode(msa, out_kpic, mode="kpic")
    assert out_kpic.is_file()
    assert int(str(stats_cli["kept_cols"])) <= int(str(stats_cli["original_cols"]))
    assert "ClipKIT" in str(stats_cli["tool"]) or "KPIC" in str(stats_cli["tool"])

    out_np = tmp_path / "trimmed_np.fasta"
    _, kept = AlignmentTrimmer._numpy_kpic_trim(msa, out_np, smart_gap=False, min_keep_cols=10)
    assert out_np.is_file()
    assert 20 <= kept <= 32


def test_dual_support_metrics_and_outgroup_placement():
    nwk = "((Query_1:0.02,(Ref_A:0.01,Ref_B:0.02)96.5/100:0.03)91.2/98:0.08,Outgroup_X:0.25);"
    metrics = compute_tree_metrics(nwk, best_model="Q.pfam+F+I+R4", best_model_bic=18420.5)
    assert metrics.has_dual_support is True
    assert metrics.mean_support == 99.0
    assert metrics.mean_alrt == 93.85
    assert metrics.strong_ufboot_ratio == 100.0
    assert metrics.best_model == "Q.pfam+F+I+R4"
    assert metrics.best_model_bic == 18420.5

    ok_og, _ = check_outgroup_placement(nwk, ["Outgroup_X"])
    assert ok_og is True

    sisters, alrt, uf = find_sister_taxa(nwk, "Query_1")
    assert set(sisters) == {"Ref_A", "Ref_B"}
    assert alrt == 91.2
    assert uf == 98.0

    # 重定根后双支持值必须不丢失
    rerooted = reroot_outgroup(nwk, "Outgroup_X")
    m2 = compute_tree_metrics(rerooted)
    assert m2.has_dual_support is True
    assert m2.leaf_count == 4


def test_iqtree3_report_regex_and_faa_clean_parsing(tmp_path: Path):
    import re
    from src.phylo.core.profiler import extract_records_from_files
    from src.phylo.delivery.qc_auditor import PhageDeliveryQcAuditor
    from src.phylo.models.schemas import AniHitRecord

    # 1. IQ-TREE 3.1.1 .iqtree 行格式正则验证
    rep_sample = (
        "Best-fit model according to BIC: LG+I+R2\n"
        "Bayesian information criterion (BIC) score: 15545.4122\n"
    )
    m_best = re.search(
        r"(?:Best-fit model(?:\s+according to [A-Z]+)?|Model of substitution):\s*([^\s]+)",
        rep_sample,
    )
    m_bic = re.search(
        r"Bayesian information criterion \(BIC\) score:\s*([0-9.+\-eE]+)",
        rep_sample,
    )
    assert m_best is not None and m_best.group(1) == "LG+I+R2"
    assert m_bic is not None and round(float(m_bic.group(1)), 2) == 15545.41

    # 2. .faa 文件提取不得附加 terl_proteins:: 前缀，且通用 NODE_ 装配头应采用文件名
    faa = tmp_path / "terl_proteins.faa"
    faa.write_text(">T5-E1\nMKTLLVAV\n>NC_001\nMKTLIVAV\n", encoding="utf-8")
    recs = extract_records_from_files([faa])
    assert [r[0] for r in recs] == ["T5-E1", "NC_001"]

    contig_fa = tmp_path / "附件2霍氏肠杆菌噬菌体2基因组序列.fasta"
    contig_fa.write_text(">NODE_1_length_72566_cov_126.27\nATGCTAGC\n", encoding="utf-8")
    recs_cn = extract_records_from_files([contig_fa])
    assert recs_cn[0][0] == "附件2霍氏肠杆菌噬菌体2基因组序列"

    # 3. 英文学术结论绝不混入中文字符
    _zh, en = PhageDeliveryQcAuditor._draft_taxonomic_statements(
        primary_q="T5-E1",
        ani_top=AniHitRecord(accession="MZ501054", wg_ani=100.0, af_query=100.0, af_ref=100.0, genus="Vequintavirus"),
        sisters=["NC_001"],
        sister_genera=["Vequintavirus"],
        q_alrt=None,
        q_uf=None,
        best_model="LG+I+R2",
        marker_mode="terl",
        consistent=True,
    )
    assert not any("\u4e00" <= ch <= "\u9fff" for ch in en)


def test_proteome_streaming_sg_upgma_and_checkpoint(tmp_path: Path):
    import numpy as np
    from src.phylo.engines.marker.proteome_tree import ProteomeTreeEngine
    from src.phylo.engines.tree.nj import NJBioNJEngine
    from src.phylo.pipeline.postprocess import parse_newick

    # 1. 验证连续与乱序非连续两种 DIAMOND BLASTp TSV 的流式聚合 100% 一致
    idx_map = {"G1": 0, "G2": 1, "G3": 2}
    tsv_sorted = tmp_path / "sorted_blastp.tsv"
    tsv_sorted.write_text(
        "\n".join(
            [
                "G1__P1\tG1__P1\t200.0",
                "G1__P1\tG2__P1\t150.0",
                "G1__P1\tG2__P2\t180.0",
                "G1__P2\tG1__P2\t100.0",
                "G2__P1\tG2__P1\t300.0",
                "G2__P1\tG1__P1\t160.0",
                "G3__P1\tG3__P1\t250.0",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    tsv_shuffled = tmp_path / "shuffled_blastp.tsv"
    tsv_shuffled.write_text(
        "\n".join(
            [
                "G1__P1\tG2__P1\t150.0",
                "G2__P1\tG2__P1\t300.0",
                "G1__P1\tG1__P1\t200.0",
                "G3__P1\tG3__P1\t250.0",
                "G1__P1\tG2__P2\t180.0",
                "G2__P1\tG1__P1\t160.0",
                "G1__P2\tG1__P2\t100.0",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    mat_a = ProteomeTreeEngine.accumulate_blastp_tsv_streaming(tsv_sorted, idx_map)
    mat_b = ProteomeTreeEngine.accumulate_blastp_tsv_streaming(tsv_shuffled, idx_map)
    assert np.allclose(mat_a, mat_b)
    assert mat_a[0, 0] == 300.0
    assert mat_a[0, 1] == 180.0
    assert mat_a[1, 0] == 160.0

    # 2. 验证 log_sg 与 one_minus_sg 距离矩阵性质
    dist_log = ProteomeTreeEngine.compute_sg_distance_matrix(mat_a, distance_mode="log_sg")
    dist_one = ProteomeTreeEngine.compute_sg_distance_matrix(mat_a, distance_mode="one_minus_sg")
    assert np.allclose(dist_log, dist_log.T)
    assert np.allclose(dist_one, dist_one.T)
    assert np.allclose(np.diag(dist_log), 0.0)
    assert np.allclose(np.diag(dist_one), 0.0)
    assert 0.0 < dist_one[0, 1] < 1.0

    # 3. 验证 UPGMA 输出严格超度量树（60 株规模所有叶子到根路径长度相等）
    n_taxa = 60
    labels = [f"Phage_{i:02d}" for i in range(n_taxa)]
    rng = np.random.default_rng(7)
    raw = rng.uniform(0.05, 0.95, size=(n_taxa, n_taxa))
    sym_dist = 0.5 * (raw + raw.T)
    np.fill_diagonal(sym_dist, 0.0)

    nwk_path = tmp_path / "upgma_60.nwk"
    nj = NJBioNJEngine()
    nj.build_from_matrix(labels, sym_dist, nwk_path, method="upgma")
    root = parse_newick(nwk_path.read_text(encoding="utf-8"))

    leaf_depths: list[float] = []

    def _collect_depths(node, acc: float) -> None:
        if node.is_leaf:
            leaf_depths.append(acc)
            return
        for ch in node.children:
            _collect_depths(ch, acc + max(0.0, float(ch.length or 0.0)))

    _collect_depths(root, 0.0)
    assert len(leaf_depths) == n_taxa
    assert max(leaf_depths) - min(leaf_depths) < 1e-4


def test_mafft_strategy_auto_downgrade_and_multithread_flags(tmp_path: Path):
    from src.phylo.engines.msa.aligner import MultiSequenceAligner
    from src.phylo.runtime.tool_registry import get_tool_registry

    strat_auto, flags_auto, note_auto = MultiSequenceAligner.resolve_mafft_args("auto", 28, seq_count=562)
    assert strat_auto == "auto"
    assert note_auto is None
    assert "--auto" in flags_auto
    assert flags_auto[-6:] == ["--thread", "28", "--threadtb", "28", "--threadit", "28"]

    strat_down, flags_down, note_down = MultiSequenceAligner.resolve_mafft_args("linsi", 28, seq_count=562)
    assert strat_down == "auto"
    assert note_down is not None and "562" in note_down
    assert "--auto" in flags_down

    strat_keep, flags_keep, note_keep = MultiSequenceAligner.resolve_mafft_args("linsi", 28, seq_count=80)
    assert strat_keep == "linsi"
    assert note_keep is None
    assert "--localpair" in flags_keep and "--maxiterate" in flags_keep
    assert "--threadtb" in flags_keep and "--threadit" in flags_keep

    reg = get_tool_registry()
    if reg.get("mafft").available:
        in_fa = tmp_path / "terl_small.faa"
        in_fa.write_text(
            ">S1\nMKTLLVAVGAAK\n>S2\nMKTLIVAVGAAK\n>S3\nMKTLLVAVGSAR\n>S4\nMKTLLISVGAAK\n",
            encoding="utf-8",
            newline="\n",
        )
        aligner = MultiSequenceAligner()
        out_auto = tmp_path / "aligned_auto.faa"
        aligner.align(in_fa, out_auto, tool="mafft", strategy="auto", threads=4)
        assert out_auto.is_file() and ">S1" in out_auto.read_text(encoding="utf-8")

        out_linsi = tmp_path / "aligned_linsi.faa"
        aligner.align(in_fa, out_linsi, tool="mafft", strategy="linsi", threads=4)
        assert out_linsi.is_file() and ">S4" in out_linsi.read_text(encoding="utf-8")


def test_iqtree_protein_fast_mset_and_full_mfp_flags(tmp_path: Path):
    from src.phylo.engines.tree.iqtree import (
        IQTreeEngine,
        PROTEIN_FAST_CMAX,
        PROTEIN_FAST_MSET,
    )
    from src.phylo.pipeline.executor import PhyloJobExecutor
    from src.phylo.runtime.tool_registry import get_tool_registry

    m_fast, flags_fast, note_fast = IQTreeEngine.resolve_model_flags("MFP", "protein")
    assert m_fast == "MFP"
    assert flags_fast == ["-mset", PROTEIN_FAST_MSET, "-cmax", str(PROTEIN_FAST_CMAX)]
    assert note_fast is not None

    m_auto, flags_auto, _ = IQTreeEngine.resolve_model_flags("auto", "protein")
    assert m_auto == "MFP"
    assert flags_auto == ["-mset", PROTEIN_FAST_MSET, "-cmax", str(PROTEIN_FAST_CMAX)]

    m_full, flags_full, _ = IQTreeEngine.resolve_model_flags("MFP_FULL", "protein")
    assert m_full == "MFP"
    assert flags_full == []

    m_lg, flags_lg, _ = IQTreeEngine.resolve_model_flags("LG+G", "protein")
    assert m_lg == "LG+G"
    assert flags_lg == []

    m_dna, flags_dna, _ = IQTreeEngine.resolve_model_flags("MFP", "dna")
    assert m_dna == "MFP"
    assert flags_dna == []

    caps = PhyloJobExecutor().get_capabilities()
    assert "MFP" in caps.engines["iqtree"].models_protein
    assert "MFP_FULL" in caps.engines["iqtree"].models_protein

    if get_tool_registry().get("iqtree").available:
        faa = tmp_path / "terl_smoke.faa"
        faa.write_text(
            ">S1\nMKTLLVAVGAAKDRSTVWYQMFGHIKLNPQ\n"
            ">S2\nMKTLIVAVGAAKDRSTVWYQMFGHIKLNPQ\n"
            ">S3\nMKTLVVAAGSAKDRSSVWYQLFGHVKLNPQ\n"
            ">S4\nMRTLIISAGSARDKTSVWYQLYGHLKLNPE\n",
            encoding="utf-8",
            newline="\n",
        )
        out_nwk = tmp_path / "iqtree_smoke.nwk"
        iq = IQTreeEngine()
        iq.build(
            msa_fasta=faa,
            output_nwk=out_nwk,
            work_dir=tmp_path,
            mol_type="protein",
            model="MFP",
            bootstrap=0,
            alrt=0,
            threads=4,
            seed=42,
        )
        assert f"-mset {PROTEIN_FAST_MSET} -cmax {PROTEIN_FAST_CMAX}" in iq.last_command
        assert out_nwk.is_file()
        assert iq.last_best_model is not None and len(iq.last_best_model) > 0
        metrics = compute_tree_metrics(out_nwk.read_text(encoding="utf-8"))
        assert metrics.leaf_count == 4
