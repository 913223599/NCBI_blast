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
    assert int(stats_cli["kept_cols"]) <= int(stats_cli["original_cols"])
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
