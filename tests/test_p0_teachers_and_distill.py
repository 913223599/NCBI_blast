# -*- coding: utf-8 -*-
"""
P0 离线多教师（pyhmmer 防御/反防御/病毒域 HMM + phold 3Di 结构语义）
与 Stage 1.2 零新增参数热启动蒸馏单元测试。
"""
from __future__ import annotations

import gzip
import pickle
from pathlib import Path
from typing import Any, Dict, List, Tuple

import numpy as np
import pytest
import torch

from src.phage_discovery.data.functional_partitions import (
    NUM_FUNC_PARTITIONS,
    build_p0_teacher_calibration,
    classify_protein_with_p0_teachers,
)
from src.phage_discovery.student.distilled_student_v4 import train_distilled_student_v4
from src.phage_discovery.teachers.hmm_adversarial_teacher import (
    resolve_hmm_library_paths,
    run_chunked_hmm_teacher,
)
from src.phage_discovery.teachers.phold_teacher import (
    _split_aa_by_length_buckets,
    parse_phold_predictions_tsv,
    run_chunked_phold_teacher,
)

pytestmark = pytest.mark.ml


def _write_fake_dataset(root: Path, n_pos: int = 8, n_neg: int = 8) -> Tuple[Path, Path, Path, Path]:
    import json
    from src.phage_discovery.experts.expert_c_orf import MAX_ORFS_PER_WIN, STAGE1_ORF_FEAT_DIM

    feat_dir = root / "feat"
    data_dir = root / "data"
    feat_dir.mkdir(parents=True, exist_ok=True)
    data_dir.mkdir(parents=True, exist_ok=True)

    rng = np.random.default_rng(7)
    n = n_pos + n_neg
    labels = np.array([1] * n_pos + [0] * n_neg, dtype=np.int8)
    cids = np.array([f"CTG_{i // 4}" for i in range(n)], dtype="<U32")
    starts = np.array([(i % 4) * 2500 for i in range(n)], dtype=np.int64)
    ends = starts + 5000
    feats = rng.normal(size=(n, 32)).astype(np.float32)
    sub_mask = np.repeat(labels[:, None].astype(np.float32), 25, axis=1)

    manifest_splits: Dict[str, Any] = {}
    for split in ("train", "val", "test"):
        fa_w = data_dir / f"{split}_windows.fna"
        fa_c = data_dir / f"{split}_chimeras.fna"
        with open(fa_w, "w", encoding="utf-8") as fh:
            for cid in sorted(set(cids.tolist())):
                fh.write(f">{cid}\n" + ("ATGCTAGC" * 2000) + "\n")
        fa_c.write_text(fa_w.read_text(encoding="utf-8"), encoding="utf-8")

        win_truth = data_dir / f"{split}_windows_truth.tsv"
        with open(win_truth, "w", encoding="utf-8") as fh:
            fh.write("window_id\tlabel\twin_len\n")
            for wi, (cid, lb) in enumerate(zip(cids.tolist(), labels.tolist())):
                fh.write(f"{cid}\t{lb}\t5000\n")

        chim_truth = data_dir / f"{split}_chimeras_truth.tsv"
        with open(chim_truth, "w", encoding="utf-8") as fh:
            fh.write("contig_id\tstart_bp\tend_bp\tmode\n")
            fh.write("CTG_0\t0\t5000\tintact_single\n")
        chim_ctgs = data_dir / f"{split}_chimeras_contigs.tsv"
        with open(chim_ctgs, "w", encoding="utf-8") as fh:
            fh.write("contig_id\tcontig_len_bp\tscenario\n")
            for cid in sorted(set(cids.tolist())):
                scen = "intact_single" if cid == "CTG_0" else "pure_negative"
                fh.write(f"{cid}\t16000\t{scen}\n")

        manifest_splits[split] = {
            "windows": {"fasta": str(fa_w), "truth_tsv": str(win_truth)},
            "chimeras": {"fasta": str(fa_c), "truth_tsv": str(chim_truth), "contigs_tsv": str(chim_ctgs)},
        }

        np.savez_compressed(
            feat_dir / f"{split}_windows.npz",
            contig_ids=cids,
            starts=starts,
            ends=ends,
            labels=labels,
            features=feats,
            sub_mask=sub_mask,
        )
        np.savez_compressed(
            feat_dir / f"{split}_chimeras.npz",
            contig_ids=cids,
            starts=starts,
            ends=ends,
            labels=labels,
            features=feats,
            sub_mask=sub_mask,
        )
        tokens = np.zeros((n, MAX_ORFS_PER_WIN, STAGE1_ORF_FEAT_DIM), dtype=np.float32)
        tokens[:, 0, 1] = 1.0
        tokens[:, 0, 6] = 0.1
        tokens[:, 0, 7] = 0.3
        np.savez_compressed(
            feat_dir / f"{split}_windows_orf_tokens_stage1.npz",
            tokens=tokens,
            counts=np.ones(n, dtype=np.int32),
        )
        np.savez_compressed(
            feat_dir / f"{split}_chimeras_orf_tokens_stage1.npz",
            tokens=tokens,
            counts=np.ones(n, dtype=np.int32),
        )

    (data_dir / "benchmark_manifest.json").write_text(
        json.dumps({"splits": manifest_splits}, indent=2),
        encoding="utf-8",
    )

    np.savez_compressed(
        feat_dir / "train_windows_functional.npz",
        func_targets=np.zeros((n, NUM_FUNC_PARTITIONS), dtype=np.float32),
        func_valid_mask=np.ones((n, NUM_FUNC_PARTITIONS), dtype=np.float32),
        orf_phage_targets=np.zeros((n, MAX_ORFS_PER_WIN), dtype=np.float32),
        orf_phage_valid=np.ones((n, MAX_ORFS_PER_WIN), dtype=np.float32),
        orf_func_targets=np.zeros((n, MAX_ORFS_PER_WIN, NUM_FUNC_PARTITIONS), dtype=np.float32),
        orf_func_valid=np.ones((n, MAX_ORFS_PER_WIN), dtype=np.float32),
        sem_targets=np.zeros((n, 4), dtype=np.float32),
        clean_labels=labels,
    )
    np.savez_compressed(
        feat_dir / "train_windows_semantic.npz",
        sem_targets=np.zeros((n, 4), dtype=np.float32),
        sem_valid_mask=np.ones(n, dtype=np.float32),
        clean_labels=labels,
    )

    return feat_dir, data_dir, feat_dir, data_dir


def test_resolve_hmm_library_paths_and_checkpoint_resume(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """验证 HMM 路径解析不依赖硬编码，且支持分片落盘与 Checkpoint 断点续扫。"""
    db_root = tmp_path / "database"
    (db_root / "phagescope" / "defense_systems").mkdir(parents=True)
    (db_root / "phagescope" / "defense_systems" / "dbAPIS.hmm").write_text("HMMER3/f\n", encoding="utf-8")
    (db_root / "defense_finder" / "defense-finder-models" / "profiles").mkdir(parents=True)
    (db_root / "defense_finder" / "defense-finder-models" / "profiles" / "AbiA.hmm").write_text("HMMER3/f\n", encoding="utf-8")

    libs = resolve_hmm_library_paths(db_root=db_root)
    assert "dbapis" in libs
    assert "defense_finder" in libs
    assert libs["dbapis"].is_file()

    # 模拟 5 条唯一序列，分 2 chunk 扫描并在第 1 chunk 后恢复断点
    aa_items = [(f"k{i}", "MKALDLFAGTGWGVACKALGIEEEGVELMPEAVAT") for i in range(5)]
    cache_path = tmp_path / "hmm_hits.pkl.gz"
    calls: List[int] = []

    def _fake_runner(chunk_items: List[Tuple[str, str]], libs_cfg: Dict[str, Any], **kwargs: Any) -> Dict[str, Dict[str, Any]]:
        calls.append(len(chunk_items))
        return {k: {"defense_finder": ("AbiA__AbiA", 1e-12, 65.0)} for k, _ in chunk_items}

    # 先模拟第 1 块已完成落盘
    state_init = {
        "done_chunks": 1,
        "chunk_size": 3,
        "total_items": 5,
        "hits": {f"k{i}": {"dbapis": ("AcrIIA1", 1e-20, 90.0)} for i in range(3)},
    }
    with gzip.open(cache_path, "wb") as fh:
        pickle.dump(state_init, fh)

    res = run_chunked_hmm_teacher(
        aa_items,
        cache_path,
        libs_cfg=libs,
        chunk_size=3,
        batch_runner=_fake_runner,
    )
    # 应当只补跑剩余的第 2 块（2 条），不重复扫第 1 块
    assert calls == [2]
    assert res["done_chunks"] == 2
    assert "k0" in res["hits"] and "dbapis" in res["hits"]["k0"]
    assert "k4" in res["hits"] and "defense_finder" in res["hits"]["k4"]


def test_parse_phold_tsv_and_chunked_resume(tmp_path: Path) -> None:
    """验证 phold TSV 解析区分 PHROG/ACR 与宿主耐药毒力防御（CARD/VFDB/DefenseFinder），并支持断点续跑。"""
    tsv = tmp_path / "phold_per_cds_predictions.tsv"
    tsv.write_text(
        "\t".join([
            "cds_id", "phrog", "function", "product", "annotation_confidence",
            "bitscore", "evalue", "tophit_protein",
        ])
        + "\n"
        + "\t".join(["k0", "24406", "head and packaging", "prohead", "medium", "1610.0", "3.7e-37", "protein812907"])
        + "\n"
        + "\t".join(["k1", "card", "moron, auxiliary metabolic gene and host takeover", "CARD resistance protein", "medium", "615.0", "3.0e-14", "AAA99504.1"])
        + "\n"
        + "\t".join(["k2", "vfdb", "moron, auxiliary metabolic gene and host takeover", "VFDB virulence factor protein", "low", "622.0", "6.0e-15", "VFG041502"])
        + "\n"
        + "\t".join(["k3", "No_PHROG", "unknown function", "hypothetical protein", "none", "0.0", "1.0", ""])
        + "\n",
        encoding="utf-8",
    )
    parsed = parse_phold_predictions_tsv(tsv)
    assert parsed["k0"]["source_type"] == "phrog"
    assert parsed["k0"]["phrog"] == "24406"
    assert parsed["k1"]["source_type"] == "card"
    assert parsed["k2"]["source_type"] == "vfdb"
    assert "k3" not in parsed

    # Checkpoint 断点测试
    cache_path = tmp_path / "phold_hits.pkl.gz"
    seen_chunks: List[int] = []

    def _fake_phold_chunk(sub_items: List[Tuple[str, str]], **kwargs: Any) -> Dict[str, Dict[str, Any]]:
        seen_chunks.append(len(sub_items))
        return {
            qid: {
                "source_type": "phrog",
                "phrog": "90",
                "function": "lysis",
                "product": "endolysin",
                "confidence": "high",
                "bitscore": 500.0,
                "evalue": 1e-20,
            }
            for qid, _ in sub_items
        }

    with gzip.open(cache_path, "wb") as fh:
        pickle.dump({"done_chunks": 1, "chunk_size": 2, "total_items": 4, "hits": {"k0": {"source_type": "card"}}}, fh)

    aa_items = [(f"k{i}", "MKALDLFAGTGWGVACKALGIEEEGVELMPEAVAT") for i in range(4)]
    merged = run_chunked_phold_teacher(
        aa_items,
        cache_path,
        db_dir=tmp_path,
        chunk_size=2,
        chunk_runner=_fake_phold_chunk,
    )
    assert seen_chunks == [2]
    assert merged["done_chunks"] == 2
    assert merged["hits"]["k0"]["source_type"] == "card"
    assert merged["hits"]["k3"]["phrog"] == "90"

    # 分桶逻辑与安全 batch_size 递减验证
    sample = [
        ("s1", "A" * 120),
        ("m1", "A" * 350),
        ("l1", "A" * 550),
    ]
    buckets = _split_aa_by_length_buckets(sample, base_batch_size=24)
    assert [b[0] for b in buckets] == ["short", "mid", "long"]
    assert buckets[0][1] == 24
    assert buckets[1][1] <= 12
    assert buckets[2][1] <= 6
    assert sum(len(b[2]) for b in buckets) == 3


def test_p0_protein_classification_and_adversarial_calibration() -> None:
    """验证 P0 结构补全、防御/耐药/毒力反制标定及窗口对抗权重校准逻辑。"""
    # 1. 原本三源全空，但 phold 结构命中 prohead -> 补全为 P0 + is_phage_ortholog=True
    r_prohead = classify_protein_with_p0_teachers(
        phold_hit={
            "source_type": "phrog",
            "phrog": "24406",
            "function": "head and packaging",
            "product": "prohead",
            "confidence": "medium",
            "bitscore": 1610.0,
            "evalue": 3.7e-37,
        }
    )
    assert r_prohead["is_phage_ortholog"] is True
    assert r_prohead["func_vec"][0] == pytest.approx(1.0)
    assert r_prohead["adversarial_host_flag"] is False

    # 2. 命中 dbAPIS 反防御 -> 归为噬菌体正信号 (P7 moron_amg_defense + is_phage_ortholog=True)
    r_acr = classify_protein_with_p0_teachers(
        hmm_hit={"dbapis": ("AcrIIA4", 1e-18, 78.0)}
    )
    assert r_acr["is_phage_ortholog"] is True
    assert r_acr["func_vec"][7] == pytest.approx(1.0)
    assert r_acr["adversarial_host_flag"] is False

    # 3. 命中 DefenseFinder 或 phold CARD/VFDB，即使原本没有 GBK 注释也不得被标为噬菌体 moron，而是对抗负向旗标
    r_def = classify_protein_with_p0_teachers(
        hmm_hit={"defense_finder": ("RM_Type_I__HsdR", 1e-25, 110.0)},
        phold_hit={
            "source_type": "card",
            "phrog": "card",
            "function": "moron, auxiliary metabolic gene and host takeover",
            "product": "CARD resistance protein",
            "confidence": "medium",
            "bitscore": 615.0,
            "evalue": 3.0e-14,
        },
    )
    assert r_def["is_phage_ortholog"] is False
    assert r_def["adversarial_host_flag"] is True
    assert float(r_def["func_vec"][7]) == pytest.approx(0.0)

    # 4. 窗口级对抗校准：label==0 且含宿主防御/MGE 对抗命中 + 无核心结构模块 + 旧教师误高分
    labels = np.array([1, 0, 0], dtype=np.int8)
    teacher_probs = np.array([0.92, 0.88, 0.05], dtype=np.float32)
    func_targets = np.zeros((3, NUM_FUNC_PARTITIONS), dtype=np.float32)
    func_targets[0, 0] = 1.0  # 真噬菌体含 head
    func_targets[2, 8] = 1.0  # 孤立转座子但旧教师本身不高
    adv_host_counts = np.array([0, 2, 0], dtype=np.int32)

    cal = build_p0_teacher_calibration(
        labels=labels,
        teacher_probs=teacher_probs,
        func_targets=func_targets,
        adv_host_counts=adv_host_counts,
        hard_neg_weight=1.75,
        suppression_blend=0.65,
    )
    assert cal["teacher_probs"][0] == pytest.approx(0.92)
    # 第 1 行难负例应该被下压，且样本权重提升至 1.75
    assert cal["teacher_probs"][1] < 0.88 * 0.5
    assert cal["sample_weights"][1] == pytest.approx(1.75)
    assert cal["sample_weights"][0] == pytest.approx(1.0)


def test_warm_start_distilled_student_zero_param_change(tmp_path: Path) -> None:
    """验证从已有 Stage 1.2 ckpt 热加载续训不改变任何参数规模且能正常完成。"""
    feat_dir, data_dir, eval_feat_dir, bench_dir = _write_fake_dataset(tmp_path / "ds")
    out1 = tmp_path / "m1"
    rep1 = train_distilled_student_v4(
        feat_dir, data_dir, eval_feat_dir, bench_dir, out1,
        train_parts=("windows",),
        epochs=1,
        batch_size=4,
        tune_sub_head=False,
        train_refiner=False,
        train_subbin_refiner=False,
        use_semantic=True,
        use_functional=True,
        use_homoscedastic_loss=True,
        feature_profile="stage1",
        workers=1,
    )
    ckpt1 = Path(rep1["model_path"])
    assert ckpt1.exists()

    out2 = tmp_path / "m2"
    sw = np.full(16, 1.5, dtype=np.float32)
    rep2 = train_distilled_student_v4(
        feat_dir, data_dir, eval_feat_dir, bench_dir, out2,
        train_parts=("windows",),
        epochs=1,
        batch_size=4,
        lr=3e-4,
        tune_sub_head=False,
        train_refiner=False,
        train_subbin_refiner=False,
        use_semantic=True,
        use_functional=True,
        use_homoscedastic_loss=True,
        feature_profile="stage1",
        init_student_ckpt=ckpt1,
        backbone_lr_scale=0.25,
        sample_weights_override=sw,
        workers=1,
    )
    assert rep2["params"] == rep1["params"]
    assert rep2["warm_started_from"] == str(ckpt1.resolve())
    sd1 = torch.load(ckpt1, map_location="cpu", weights_only=True)
    sd2 = torch.load(Path(rep2["model_path"]), map_location="cpu", weights_only=True)
    assert set(sd1.keys()) == set(sd2.keys())
    # feat_mean 与 feat_std 必须与原模型保持严格一致
    assert torch.allclose(sd1["feat_mean"], sd2["feat_mean"])
    assert torch.allclose(sd1["feat_std"], sd2["feat_std"])

