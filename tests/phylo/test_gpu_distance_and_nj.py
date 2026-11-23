# -*- coding: utf-8 -*-
"""
阶段一测试：GPU/NumPy 演化距离矩阵、BioNJ/NJ 与分片 Bootstrap
"""
from pathlib import Path

import numpy as np

from src.phylo.engines.distance.matrix_gpu import DistanceMatrixCalculator, encode_alignment
from src.phylo.engines.tree.nj import NJBioNJEngine
from src.phylo.pipeline.postprocess import compute_tree_metrics


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
