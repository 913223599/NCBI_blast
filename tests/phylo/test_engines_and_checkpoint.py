# -*- coding: utf-8 -*-
"""
阶段一测试：全流程引擎调度、阶段缓存复用与真实 T5 噬菌体 Track A 回归
"""
import time
from pathlib import Path

import pytest

from src.phylo.models.schemas import PhyloJobConfig
from src.phylo.pipeline.executor import PhyloJobExecutor
from src.phylo.runtime.tool_registry import get_project_root, get_tool_registry
from src.phylo.storage.archive_store import PhyloArchiveStore

pytestmark = pytest.mark.integration


def _make_synthetic_gene_fasta(path: Path) -> None:
    seqs = {
        "Alpha_strain": "ATGCGTACGTAGCTAGCTAGCTGATCGTAGCTAGCTAGCATGCGTACGTAGCTAGCTAGCTGATCG",
        "Beta_strain": "ATGCGTACGTAGCTAGCTAGCTGATCGTAGCTAGCTAGCATGCGTACGTAGCTAGCTAGCTGATTG",
        "Gamma_strain": "ATGCGTACGTAGCTGGCTAGCTGATCGTAGTTAGCTAGCATGCGTACGTAGCTAGCTAGCTGATCG",
        "Delta_strain": "ATGCGTACGTAGCTGGCTAGCTGTTCGTAGTTAGCTAGCATGCGTCCGTAGCTAGCTAGCTGATCG",
        "Outgroup_sp": "TTACGTGCATAGCTCGCTAGCTATTCGTAGTCAGCTAGCTAGCGTACGTACCTAGGTAGCTGATCG",
    }
    with open(path, "w", encoding="utf-8") as fh:
        for k, v in seqs.items():
            fh.write(f">{k}\n{v * 3}\n")


def test_gene_track_msa_cache_and_engines(tmp_path: Path):
    reg = get_tool_registry()
    if not reg.get("mafft").available:
        pytest.skip("MAFFT 不可用")

    store = PhyloArchiveStore(base_dir=tmp_path / "phylo_store")
    executor = PhyloJobExecutor(store=store)

    fasta_path = tmp_path / "genes.fasta"
    _make_synthetic_gene_fasta(fasta_path)

    # 1. 首次运行：MAFFT + Trimmer + BioNJ (bootstrap=20)
    cfg1 = PhyloJobConfig(
        title="Synthetic_BioNJ",
        track="gene",
        msa="mafft",
        msa_strategy="fast",
        trim_gap_threshold=0.5,
        engine="bionj",
        model="jc69",
        bootstrap=20,
        threads=4,
        use_gpu=True,
        use_cache=True,
    )
    rec1 = executor.run_sync(cfg1, [fasta_path])
    assert rec1.status == "completed", rec1.error
    assert rec1.newick and "Alpha_strain" in rec1.newick
    assert rec1.metrics and rec1.metrics.leaf_count == 5

    # 2. 第二次运行同批数据切换 FastTree：应命中 MSA 缓存
    if reg.get("fasttree").available:
        cfg2 = PhyloJobConfig(
            title="Synthetic_FastTree",
            track="gene",
            msa="mafft",
            msa_strategy="fast",
            engine="fasttree",
            model="gtr",
            threads=4,
            use_cache=True,
        )
        rec2 = executor.run_sync(cfg2, [fasta_path])
        assert rec2.status == "completed", rec2.error
        msa_stage = next(s for s in rec2.stages if s.name == "msa")
        assert msa_stage.cached is True
        assert rec2.metrics and rec2.metrics.leaf_count == 5

    # 3. 验证 IQ-TREE 引擎（若可用）
    if reg.get("iqtree").available:
        cfg3 = PhyloJobConfig(
            title="Synthetic_IQTREE",
            track="gene",
            msa="mafft",
            msa_strategy="fast",
            engine="iqtree",
            model="JC",
            bootstrap=1000,
            threads=4,
            use_cache=True,
        )
        rec3 = executor.run_sync(cfg3, [fasta_path])
        assert rec3.status == "completed", rec3.error
        assert rec3.metrics and rec3.metrics.leaf_count == 5


def test_real_t5_phage_genomes_track_a(tmp_path: Path):
    """用实际阻塞旧管线 10 分钟的 4 条 114KB T5 噬菌体全基因组做 Track A 速度与正确性回归。"""
    t5_fasta = (
        get_project_root()
        / "results"
        / "tree_workspace"
        / "jobs"
        / "Tree_Job_261123_161306"
        / "input_sanitized.fasta"
    )
    if not t5_fasta.is_file():
        pytest.skip("T5 噬菌体测试数据不存在")

    reg = get_tool_registry()
    if not reg.get("mash").available:
        pytest.skip("Mash 不可用")

    store = PhyloArchiveStore(base_dir=tmp_path / "phylo_t5")
    executor = PhyloJobExecutor(store=store)
    cfg = PhyloJobConfig(
        title="T5_Phage_Genomes",
        track="auto",
        engine="bionj",
        threads=8,
        use_cache=True,
    )
    t0 = time.time()
    rec = executor.run_sync(cfg, [t5_fasta])
    elapsed = time.time() - t0

    assert rec.status == "completed", rec.error
    assert rec.resolved_track == "genome"
    assert rec.metrics and rec.metrics.leaf_count == 4
    for expected_id in [
        "T5-E1_asm_ngcs_scaffold_1",
        "T5-E2_asm_ngcs_scaffold_1",
        "T5-E5_asm_ngcs_scaffold_1",
        "T5-WT_asm_ngcs_scaffold_1",
    ]:
        assert expected_id in (rec.newick or "")
    assert elapsed < 15.0, f"Track A 耗时过高: {elapsed:.2f}s"


def test_synthetic_genome_track_a(tmp_path: Path):
    """不依赖旧目录数据的合成 20kb 长基因组 Track A (Mash + BioNJ) 必过回归测试。"""
    import random

    reg = get_tool_registry()
    if not reg.get("mash").available:
        pytest.skip("Mash 不可用")

    rng = random.Random(2026)
    base: list[str] = [rng.choice("ACGT") for _ in range(20000)]

    def _mutate(seq_list: list[str], rate: float) -> str:
        out = list(seq_list)
        n_mut = int(len(out) * rate)
        for pos in rng.sample(range(len(out)), n_mut):
            out[pos] = rng.choice([b for b in "ACGT" if b != out[pos]])
        return "".join(out)

    g1 = "".join(base)
    g2 = _mutate(base, 0.005)[:19750]
    g3 = _mutate(base, 0.02) + "".join(rng.choice("ACGT") for _ in range(350))
    g4 = "".join(rng.choice("ACGT") for _ in range(20500))

    fasta_path = tmp_path / "synthetic_genomes.fasta"
    with open(fasta_path, "w", encoding="utf-8") as fh:
        for name, seq in [("Phage_A1", g1), ("Phage_A2", g2), ("Phage_B1", g3), ("Phage_Out", g4)]:
            fh.write(f">{name}\n{seq}\n")

    store = PhyloArchiveStore(base_dir=tmp_path / "phylo_synth_g")
    executor = PhyloJobExecutor(store=store)
    rec = executor.run_sync(
        PhyloJobConfig(title="SynthGenomes", track="auto", engine="bionj", threads=4),
        [fasta_path],
    )
    assert rec.status == "completed", rec.error
    assert rec.resolved_track == "genome"
    assert rec.metrics and rec.metrics.leaf_count == 4
    for name in ("Phage_A1", "Phage_A2", "Phage_B1", "Phage_Out"):
        assert name in (rec.newick or "")
