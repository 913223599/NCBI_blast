# -*- coding: utf-8 -*-
"""
阶段一测试：GPU/NumPy 演化距离矩阵、BioNJ/NJ 与分片 Bootstrap
"""
from pathlib import Path

import numpy as np

from src.phylo.engines.distance.matrix_gpu import DistanceMatrixCalculator, encode_alignment
from src.phylo.engines.tree.nj import NJBioNJEngine
from src.phylo.pipeline.postprocess import compute_tree_metrics
import pytest

pytestmark = pytest.mark.integration


def _write_aligned_dna_fasta(path: Path) -> None:
    seqs = {
        "T000001": "ATGCATGCATGCATGCATGCATGCATGCATGCATGCATGC" * 5,
        "T000002": "ATGCATGCATGCATGCATGCATGCATGCTTGCATGCATGC" * 5,
        "T000003": "ATGCGTGCATGCGTGCATGCATGCATGCATGCATGCATGC" * 5,
        "T000004": "TTGCGTGCATGCGTGCGTGCATGCATGCATGGATGCATGC" * 5,
        "T000005": "TTGCGTGCATGCGTGCGTGCATTCATGCATGGATGCATGG" * 5,
    }
    with open(path, "w", encoding="utf-8") as fh:
        for k, v in seqs.items():
            fh.write(f">{k}\n{v}\n")


def test_cuda_matches_numpy_distance(tmp_path: Path):
    msa_path = tmp_path / "msa.fasta"
    _write_aligned_dna_fasta(msa_path)
    ids, encoded = encode_alignment(msa_path, mol_type="dna")
    assert len(ids) == 5

    calc_cpu = DistanceMatrixCalculator(use_gpu=False)
    calc_gpu = DistanceMatrixCalculator(use_gpu=True)

    for model in ("p-distance", "jc69", "k2p"):
        mat_cpu = calc_cpu.compute(encoded, mol_type="dna", model=model)
        mat_gpu = calc_gpu.compute(encoded, mol_type="dna", model=model)
        assert mat_cpu.shape == (5, 5)
        assert np.allclose(mat_cpu, mat_cpu.T, atol=1e-8)
        assert np.allclose(np.diag(mat_cpu), 0.0, atol=1e-8)
        assert np.allclose(mat_cpu, mat_gpu, atol=1e-5)


def test_bionj_and_sharded_bootstrap(tmp_path: Path):
    msa_path = tmp_path / "msa.fasta"
    _write_aligned_dna_fasta(msa_path)
    out_nwk = tmp_path / "bionj.nwk"

    engine = NJBioNJEngine()
    engine.build_from_msa(
        msa_fasta=msa_path,
        output_nwk=out_nwk,
        work_dir=tmp_path,
        mol_type="dna",
        model="jc69",
        method="bionj",
        bootstrap=30,
        threads=4,
        use_gpu=True,
        dist_matrix_npy=tmp_path / "dm.npy",
        dist_matrix_csv=tmp_path / "dm.csv",
        id_map={"T000001": "Alpha", "T000002": "Beta", "T000003": "Gamma", "T000004": "Delta", "T000005": "Epsilon"},
    )

    assert out_nwk.is_file()
    assert (tmp_path / "bootstrap_replicates.nwk").is_file()
    rep_lines = [line for line in (tmp_path / "bootstrap_replicates.nwk").read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(rep_lines) == 30
    assert (tmp_path / "dm.csv").is_file()

    nwk = out_nwk.read_text(encoding="utf-8").strip()
    metrics = compute_tree_metrics(nwk)
    assert metrics.leaf_count == 5
    assert metrics.mean_support is not None
    assert 0.0 <= metrics.mean_support <= 100.0


def test_distance_matrix_cancel_and_small_workload(tmp_path: Path):
    import threading
    import pytest
    from src.phylo.models.errors import PhyloCancelledError

    msa_path = tmp_path / "msa.fasta"
    _write_aligned_dna_fasta(msa_path)
    _, encoded = encode_alignment(msa_path, mol_type="dna")

    cancel_ev = threading.Event()
    cancel_ev.set()
    calc = DistanceMatrixCalculator(use_gpu=True, cancel_event=cancel_ev)
    with pytest.raises(PhyloCancelledError):
        calc.compute(encoded, mol_type="dna", model="k2p")


def test_nj_save_distance_csv_and_build_from_matrix(tmp_path: Path):
    import numpy as np

    labels = ["Phage_A", "Phage_B", "Phage_C", "Outgroup_D"]
    mat = np.array(
        [
            [0.0, 0.1, 0.2, 0.8],
            [0.1, 0.0, 0.25, 0.85],
            [0.2, 0.25, 0.0, 0.9],
            [0.8, 0.85, 0.9, 0.0],
        ],
        dtype=np.float64,
    )
    csv_path = NJBioNJEngine.save_distance_csv(labels, mat, tmp_path / "proteome_dist.csv")
    assert csv_path.is_file()
    lines = csv_path.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "Taxon,Phage_A,Phage_B,Phage_C,Outgroup_D"
    assert len(lines) == 5

    out_nwk = NJBioNJEngine().build_from_matrix(
        labels, mat, tmp_path / "proteome.nwk", method="bionj"
    )
    assert out_nwk.is_file()
    nwk_text = out_nwk.read_text(encoding="utf-8")
    for lbl in labels:
        assert lbl in nwk_text


def test_cuda_tree_clustering_matches_cpu_nj_bionj_upgma(tmp_path: Path):
    from src.phylo.engines.tree.nj import (
        _parse_newick_leaves_splits,
        should_use_cuda_for_tree,
    )
    from src.phylo.pipeline.postprocess import parse_newick
    from src.phylo.runtime.resource_guard import GpuGuard

    n = 80
    labels = [f"T{i:03d}" for i in range(n)]
    rng = np.random.default_rng(2026)
    coords = rng.normal(size=(n, 8))
    diff = coords[:, None, :] - coords[None, :, :]
    sym_dist = np.sqrt((diff * diff).sum(axis=-1))
    np.fill_diagonal(sym_dist, 0.0)

    assert should_use_cuda_for_tree(20, True) is False
    gpu_info = GpuGuard.probe()
    if gpu_info["available"] and gpu_info["free_vram_mb"] >= 512:
        assert should_use_cuda_for_tree(n, True) is True

    bit_by_id = {name: (1 << idx) for idx, name in enumerate(labels)}
    full_mask = (1 << n) - 1
    engine = NJBioNJEngine()

    for method in ("bionj", "nj", "upgma"):
        cpu_nwk_path = tmp_path / f"{method}_cpu.nwk"
        gpu_nwk_path = tmp_path / f"{method}_gpu.nwk"
        engine.build_from_matrix(labels, sym_dist, cpu_nwk_path, method=method, use_gpu=False)
        engine.build_from_matrix(labels, sym_dist, gpu_nwk_path, method=method, use_gpu=True)

        cpu_nwk = cpu_nwk_path.read_text(encoding="utf-8").strip()
        gpu_nwk = gpu_nwk_path.read_text(encoding="utf-8").strip()

        cpu_splits = _parse_newick_leaves_splits(cpu_nwk, bit_by_id, full_mask)
        gpu_splits = _parse_newick_leaves_splits(gpu_nwk, bit_by_id, full_mask)
        assert cpu_splits == gpu_splits

        m_cpu = compute_tree_metrics(cpu_nwk)
        m_gpu = compute_tree_metrics(gpu_nwk)
        assert m_cpu.leaf_count == n
        assert m_gpu.leaf_count == n
        assert m_cpu.total_branch_length is not None
        assert m_gpu.total_branch_length is not None
        assert abs(m_cpu.total_branch_length - m_gpu.total_branch_length) < 1e-4

        if method == "upgma":
            root = parse_newick(gpu_nwk)
            depths: list[float] = []

            def _collect(node, acc: float, out_depths: list[float]) -> None:
                if node.is_leaf:
                    out_depths.append(acc)
                    return
                for ch in node.children:
                    _collect(ch, acc + max(0.0, float(ch.length or 0.0)), out_depths)

            _collect(root, 0.0, depths)
            assert len(depths) == n
            assert max(depths) - min(depths) < 1e-4
