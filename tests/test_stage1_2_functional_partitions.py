# -*- coding: utf-8 -*-
"""
Stage 1.2 功能基因分区蒸馏、三源合一客观标注、多尺度稀有病毒补强与防暴露偏差精修器单元测试。
"""
from pathlib import Path
from typing import Any
import numpy as np
import pytest
import torch

from src.phage_discovery.data.functional_partitions import (
    FUNCTIONAL_PARTITION_NAMES,
    NUM_FUNC_PARTITIONS,
    HomoscedasticMultiTaskLoss,
    build_window_and_orf_functional_targets,
    classify_protein_to_functional_partitions,
    deduplicate_sequences_kmer,
    extract_rare_multiscale_windows,
)
from src.phage_discovery.student.distilled_student_v4 import (
    _apply_refiner_augmentations,
    build_distilled_student_v4,
    build_region_context_refiner,
    extract_refiner_step_features,
    train_distilled_student_v4,
)


def test_functional_partition_schema_and_three_source_classifier() -> None:
    """验证 9 大客观功能分区定义、三源合一分类器及 unknown function 掩码豁免。"""
    assert NUM_FUNC_PARTITIONS == 9
    assert len(FUNCTIONAL_PARTITION_NAMES) == 9
    expected = (
        "head_packaging",
        "connector",
        "tail",
        "lysis",
        "integration_excision",
        "dna_rna_replication",
        "transcription_regulation",
        "moron_amg_defense",
        "transposon_plasmid_mge",
    )
    assert tuple(FUNCTIONAL_PARTITION_NAMES) == expected

    # 1. 明确有尾噬菌体包装蛋白 (P0)
    r_head = classify_protein_to_functional_partitions(
        phrog_category="head and packaging",
        phrog_annot="terminase large subunit",
    )
    assert r_head["is_phage_ortholog"] is True
    assert r_head["is_func_known"] is True
    assert r_head["func_vec"][0] == pytest.approx(1.0)
    assert float(np.sum(r_head["func_vec"])) == pytest.approx(1.0)

    # 2. PHROGs unknown function 暗物质蛋白：属于噬菌体同源蛋白，但功能未知 (is_func_known=False)
    r_unk = classify_protein_to_functional_partitions(
        phrog_category="unknown function",
        phrog_annot="hypothetical phage protein",
    )
    assert r_unk["is_phage_ortholog"] is True
    assert r_unk["is_func_known"] is False
    assert float(np.sum(r_unk["func_vec"])) == pytest.approx(0.0)

    # 3. 单纯细菌转座酶 (P8)：非噬菌体特异同源，但功能已知为 MGE/Transposon
    r_trnp = classify_protein_to_functional_partitions(
        gbk_product="IS630 family transposase",
    )
    assert r_trnp["is_phage_ortholog"] is False
    assert r_trnp["is_func_known"] is True
    assert r_trnp["func_vec"][8] == pytest.approx(1.0)

    # 4. 非有尾微病毒复制蛋白 (Microviridae gpA / Inovirus coat)
    r_micro = classify_protein_to_functional_partitions(
        diamond_title="Microviridae rolling circle replication initiation protein gpA",
    )
    assert r_micro["is_phage_ortholog"] is True
    assert r_micro["is_func_known"] is True
    assert r_micro["func_vec"][5] == pytest.approx(1.0)

    # 5. DIAMOND 物种方括号与词边界防护：非病毒转录调控/转移酶即使带 [Vibrio phage] 也不得误触发 hallmark
    r_dmnd_host = classify_protein_to_functional_partitions(
        diamond_title="WP_001234.1 LysR family transcriptional regulator [Vibrio phage VP882]",
        gbk_product="acetyltransferase",
    )
    assert r_dmnd_host["sem4_vec"][0] == pytest.approx(0.0)
    assert r_dmnd_host["is_phage_ortholog"] is False
    assert r_dmnd_host["func_vec"][6] == pytest.approx(1.0)
    assert r_dmnd_host["func_vec"][5] == pytest.approx(0.0)

    r_host_amidase = classify_protein_to_functional_partitions(
        gbk_product="N-acetylmuramoyl-L-alanine amidase",
    )
    assert r_host_amidase["func_vec"][3] == pytest.approx(0.0)


def test_orf_token_iou_alignment_and_contradictory_negative_cleaning() -> None:
    """验证逐 ORF IoU>=0.8 坐标绑定、客观功能零标签泄露及多模块矛盾负样本自动屏蔽。"""
    contig_id = "SYNTH_HOST_CONTIG"
    # 窗口 0: y=1 正样本，含 3 个 ORF (head, unknown_phrog, lysis)
    # 窗口 1: y=0 负样本，含完全相同的 3 个多模块噬菌体 ORF -> 客观功能向量必须与窗口 0 相同，且 clean_label 自动变为 -1
    # 窗口 2: y=0 负样本，仅含 1 个孤立 tail 同源 ORF -> clean_label 保持 0 (作为孤立同源负例训练模型)
    starts = np.array([0, 10000, 20000], dtype=np.int64)
    ends = np.array([5000, 15000, 25000], dtype=np.int64)
    labels = np.array([1, 0, 0], dtype=np.int8)
    cids = np.array([contig_id, contig_id, contig_id])

    # 模拟窗口级 ORF Token 相对坐标与链方向: tokens (3, 36, 117), counts (3,)
    # 在 expert_c_orf 中，token[:, 0] = rel_start (s/win_len), token[:, 1] = rel_end (e/win_len), token[:, 3] = strand (+1/-1)
    tokens = np.zeros((3, 36, 117), dtype=np.float32)
    counts = np.array([3, 3, 2], dtype=np.int32)

    for w_idx in (0, 1):
        # ORF 0: 200..1100 (+1) -> head_packaging
        tokens[w_idx, 0, 0] = 200.0 / 5000.0
        tokens[w_idx, 0, 1] = 1100.0 / 5000.0
        tokens[w_idx, 0, 3] = 1.0
        # ORF 1: 1200..2100 (+1) -> unknown function PHROG
        tokens[w_idx, 1, 0] = 1200.0 / 5000.0
        tokens[w_idx, 1, 1] = 2100.0 / 5000.0
        tokens[w_idx, 1, 3] = 1.0
        # ORF 2: 2200..3100 (+1) -> endolysin (lysis)
        tokens[w_idx, 2, 0] = 2200.0 / 5000.0
        tokens[w_idx, 2, 1] = 3100.0 / 5000.0
        tokens[w_idx, 2, 3] = 1.0

    # 窗口 2: ORF 0 为 300..1200 (+1) 孤立 tail，ORF 1 为 2000..2900 (-1) 普通宿主无命中基因
    tokens[2, 0, 0] = 300.0 / 5000.0
    tokens[2, 0, 1] = 1200.0 / 5000.0
    tokens[2, 0, 3] = 1.0
    tokens[2, 1, 0] = 2000.0 / 5000.0
    tokens[2, 1, 1] = 2900.0 / 5000.0
    tokens[2, 1, 3] = -1.0

    contig_annotated_orfs = {
        contig_id: [
            # 对应窗口 0
            (200, 1100, 1, classify_protein_to_functional_partitions(phrog_category="head and packaging", phrog_annot="major head protein")),
            (1200, 2100, 1, classify_protein_to_functional_partitions(phrog_category="unknown function", phrog_annot="unknown")),
            (2200, 3100, 1, classify_protein_to_functional_partitions(phrog_category="lysis", phrog_annot="endolysin")),
            # 对应窗口 1 (多模块隐蔽原噬菌体漏标在 y=0 上)
            (10200, 11100, 1, classify_protein_to_functional_partitions(phrog_category="head and packaging", phrog_annot="major head protein")),
            (11200, 12100, 1, classify_protein_to_functional_partitions(phrog_category="unknown function", phrog_annot="unknown")),
            (12200, 13100, 1, classify_protein_to_functional_partitions(phrog_category="lysis", phrog_annot="endolysin")),
            # 对应窗口 2 (仅 1 个孤立 tail 同源基因 + 1 个无命中宿主基因)
            (20300, 21200, 1, classify_protein_to_functional_partitions(phrog_category="tail", phrog_annot="tail tube protein")),
            (22000, 22900, -1, classify_protein_to_functional_partitions()),
        ]
    }

    res = build_window_and_orf_functional_targets(
        contig_ids=cids,
        starts=starts,
        ends=ends,
        labels=labels,
        orf_tokens=tokens,
        orf_counts=counts,
        contig_annotated_orfs=contig_annotated_orfs,
        clean_contradictory_negatives=True,
    )

    # 客观性检验：窗口 0 (y=1) 与窗口 1 (y=0) 的客观功能目标完全一致，绝不因 y 不同而篡改
    np.testing.assert_allclose(res["func_targets"][0], res["func_targets"][1])
    np.testing.assert_allclose(res["orf_func_targets"][0], res["orf_func_targets"][1])

    # unknown function 槽位 (ORF 1) 检验：phage_target=1 且有效，但 func_valid=0 (豁免功能负梯度)
    assert res["orf_phage_targets"][0, 1] == pytest.approx(1.0)
    assert res["orf_phage_valid"][0, 1] == pytest.approx(1.0)
    assert res["orf_func_valid"][0, 1] == pytest.approx(0.0)
    assert res["orf_func_valid"][0, 0] == pytest.approx(1.0)
    assert res["orf_func_valid"][0, 2] == pytest.approx(1.0)

    # 矛盾负样本自动屏蔽检验：窗口 1 含多模块噬菌体基因被置为 -1，窗口 2 仅单基因孤立同源保持 0
    assert int(res["clean_labels"][0]) == 1
    assert int(res["clean_labels"][1]) == -1
    assert int(res["clean_labels"][2]) == 0

    # 普通细菌同时出现 DNA 复制 (P5) + 转录调控 (P6) + unknown_phrog，绝不得误清洗为 -1
    bact_tok = np.zeros((1, 36, 117), dtype=np.float32)
    bact_tok[0, 0, 6], bact_tok[0, 0, 7], bact_tok[0, 0, 1] = 0.05, 0.25, 1.0
    bact_tok[0, 1, 6], bact_tok[0, 1, 7], bact_tok[0, 1, 1] = 0.30, 0.50, 1.0
    bact_res = build_window_and_orf_functional_targets(
        contig_ids=np.array(["BACT_HK"]),
        starts=np.array([0], dtype=np.int64),
        ends=np.array([5000], dtype=np.int64),
        labels=np.array([0], dtype=np.int8),
        orf_tokens=bact_tok,
        orf_counts=np.array([2], dtype=np.int32),
        contig_annotated_orfs={
            "BACT_HK": [
                (250, 1250, 1, classify_protein_to_functional_partitions(gbk_product="DNA helicase")),
                (1500, 2500, 1, classify_protein_to_functional_partitions(gbk_product="LysR family transcriptional regulator")),
            ]
        },
        clean_contradictory_negatives=True,
    )
    assert int(bact_res["clean_labels"][0]) == 0


def test_rare_multiscale_window_builder_and_kmer_dedup() -> None:
    """验证稀有非有尾噬菌体多尺度短/中窗采样与重复同源负样本去重。"""
    rng = np.random.default_rng(42)
    base_seq = "".join(rng.choice(list("ACGT"), size=5400))
    rare_records = [("MICRO_001", base_seq, "Microviridae")]

    windows = extract_rare_multiscale_windows(
        rare_records,
        scales_bp=(600, 1000, 1800, 3000),
        seed=42,
    )
    lens = [len(w["seq"]) for w in windows]
    assert any(win_len <= 1000 for win_len in lens)
    assert any(1000 < win_len <= 3000 for win_len in lens)

    # 验证重复/近乎完全相同序列去重（模拟 8 条重复 1,738bp 负样本切片）
    dup_seq = "".join(rng.choice(list("ACGT"), size=1738))
    other_seq = "".join(rng.choice(list("ACGT"), size=1738))
    candidates = [(f"NEG_{i}", dup_seq) for i in range(8)] + [("NEG_OTHER", other_seq)]
    deduped = deduplicate_sequences_kmer(candidates, max_jaccard=0.90)
    assert len(deduped) == 2


def test_student_v4_functional_partition_heads_and_uncertainty_loss() -> None:
    """验证双层 9 维功能分区蒸馏头、Kendall 同方差不确定性自动加权与向后兼容性。"""
    feat_mean = np.zeros(256, dtype=np.float32)
    feat_std = np.ones(256, dtype=np.float32)
    model = build_distilled_student_v4(
        256,
        feat_mean,
        feat_std,
        orf_feat_dim=117,
        func_dim=NUM_FUNC_PARTITIONS,
    )
    oh = torch.zeros((4, 4, 5000), dtype=torch.float32)
    oh[:, 0, :] = 1.0
    tb = torch.zeros((4, 256), dtype=torch.float32)
    ln = torch.tensor([5000, 3000, 1000, 800], dtype=torch.long)
    tk = torch.zeros((4, 36, 117), dtype=torch.float32)
    cn = torch.tensor([5, 3, 2, 1], dtype=torch.long)

    out = model(oh, tb, lengths=ln, orf_tokens=tk, orf_counts=cn, return_aux=True)
    assert out["win_logit"].shape == (4,)
    assert out["sub_logits"].shape == (4, 25)
    assert out["sem_logits"].shape == (4, 4)
    assert out["func_logits"].shape == (4, 9)
    assert out["orf_phage_logits"].shape == (4, 36)
    assert out["orf_func_logits"].shape == (4, 36, 9)

    mt_loss_fn = HomoscedasticMultiTaskLoss(num_tasks=3)
    losses = [
        out["win_logit"].pow(2).mean(),
        out["func_logits"].pow(2).mean(),
        out["orf_func_logits"].pow(2).mean(),
    ]
    total_l = mt_loss_fn(losses)
    total_l.backward()
    assert mt_loss_fn.log_vars.grad is not None


def test_context_refiner_exposure_bias_mitigation_with_func_coherence() -> None:
    """验证跨窗精修器融合功能模块共现度与含孤立单模块同源假阳脉冲的训练增强。"""
    n = 10
    win_logits = np.zeros(n, dtype=np.float32)
    sem_logits = np.full((n, 4), -2.0, dtype=np.float32)
    sub_probs = np.full((n, 25), 0.1, dtype=np.float32)
    lengths = np.full(n, 5000, dtype=np.int64)
    func_logits = np.full((n, 9), -2.5, dtype=np.float32)
    # 模拟第 5 窗只有单个 tail 同源基因命中，其余功能模块全负
    func_logits[5, 2] = 1.8

    sf = extract_refiner_step_features(
        win_logits, sem_logits, sub_probs, lengths, func_logits=func_logits,
    )
    assert sf.shape == (n, 15)

    rng = np.random.default_rng(7)
    labels = np.zeros(n, dtype=np.int8)
    sf_aug, rl_aug = _apply_refiner_augmentations(sf, win_logits, labels, rng)
    assert sf_aug.shape == sf.shape
    assert rl_aug.shape == win_logits.shape

    refiner = build_region_context_refiner()
    sf_t = torch.from_numpy(sf_aug[None, ...])
    rl_t = torch.from_numpy(rl_aug[None, ...])
    ln_t = torch.tensor([n], dtype=torch.long)
    out = refiner(sf_t, rl_t, seq_lens=ln_t)
    assert out.shape == (1, n)


def _synth_test_dna(bp: int, seed: int) -> str:
    rng = np.random.default_rng(seed)
    codons = ["ATG", "GCT", "GCC", "GAA", "AAG", "CTG", "GGA", "TTC", "AAC", "GAC", "TAA"]
    parts = ["ATG"] + [codons[int(i)] for i in rng.integers(0, len(codons) - 1, size=max(1, bp // 3))]
    return "".join(parts)[:bp]


def test_end_to_end_stage1_2_functional_distillation_and_scanner(tmp_path: Path) -> None:
    """端到端校验 Stage 1.2 9D功能蒸馏训练、Kendall自动加权与扫描器模块导出闭环。"""
    import csv
    import json
    import sqlite3
    from src.phage_discovery.benchmark.chimera_builder import build_benchmark_suite
    from src.phage_discovery.data.feature_dataset import build_split_features
    from src.phage_discovery.experts.expert_c_orf import _load_or_extract_part
    from src.phage_discovery.inference.scanner import GenomeScanner

    pos_dir = tmp_path / "pos_ds"
    neg_dir = tmp_path / "neg_ds"
    (pos_dir / "fasta").mkdir(parents=True)
    (pos_dir / "preprocessed" / "splits").mkdir(parents=True)
    (neg_dir / "fasta").mkdir(parents=True)
    (neg_dir / "index").mkdir(parents=True)

    for sp, n in (("train", 4), ("val", 2), ("test", 2)):
        with open(pos_dir / "preprocessed" / "splits" / f"{sp}.tsv", "w", encoding="utf-8", newline="") as fh:
            w = csv.writer(fh, delimiter="\t")
            w.writerow(["accession", "cluster_id", "tax_group", "host", "length_bp"])
            for i in range(n):
                acc = f"NC_S12_{sp.upper()}_{i}.1"
                seq = _synth_test_dna(12000, seed=100 + len(sp) * 10 + i)
                (pos_dir / "fasta" / f"{acc}.fasta").write_text(f">{acc}\n{seq}\n", encoding="utf-8")
                w.writerow([acc, f"CLU_{sp}_{i}", "Caudoviricetes", "E. coli", len(seq)])

    with sqlite3.connect(neg_dir / "index" / "negative_index.sqlite") as conn:
        conn.execute(
            "CREATE TABLE genomes (accession TEXT PRIMARY KEY, is_valid_negative INTEGER, negative_category TEXT, organism TEXT, length_bp INTEGER, fasta_relpath TEXT)"
        )
        conn.execute(
            "CREATE TABLE prophage_masks (id INTEGER PRIMARY KEY AUTOINCREMENT, accession TEXT, start_pos INTEGER, end_pos INTEGER)"
        )
        for i in range(9):
            acc = f"NZ_S12_HOST_{i}.1"
            seq = _synth_test_dna(120000, seed=200 + i)
            (neg_dir / "fasta" / f"{acc}.fasta").write_text(f">{acc}\n{seq}\n", encoding="utf-8")
            conn.execute(
                "INSERT INTO genomes VALUES (?, 1, 'bacterial_chromosome', 'Bacillus', ?, ?)",
                (acc, len(seq), f"fasta/{acc}.fasta"),
            )
        conn.commit()

    bench_dir = tmp_path / "bench"
    train_bench = tmp_path / "train_bench"
    tr_feat = tmp_path / "tr_feat"
    ev_feat = tmp_path / "ev_feat"
    build_benchmark_suite(
        pos_dir, neg_dir, bench_dir,
        splits_to_build=("val", "test"),
        chimeras_per_split=2, pure_neg_hosts_per_split=1, windows_per_split=16, seed=7,
    )
    build_benchmark_suite(
        pos_dir, neg_dir, train_bench,
        splits_to_build=("train",),
        chimeras_per_split=2, pure_neg_hosts_per_split=1, windows_per_split=16, seed=7,
    )
    build_split_features(train_bench, "train", tr_feat, workers=1)
    build_split_features(bench_dir, "val", ev_feat, workers=1)
    build_split_features(bench_dir, "test", ev_feat, workers=1)

    from src.phage_discovery.data.feature_dataset import iter_fasta
    from src.phage_discovery.features.window_features import (
        FEATURE_NAMES_STAGE1,
        extract_contig_windows_for_spans,
    )

    tr_manifest = json.loads((train_bench / "benchmark_manifest.json").read_text(encoding="utf-8"))
    ev_manifest = json.loads((bench_dir / "benchmark_manifest.json").read_text(encoding="utf-8"))

    def _upgrade_split_to_stage1(feat_root: Path, manifest: dict[str, Any], split: str) -> None:
        for part in ("windows", "chimeras"):
            npz_path = feat_root / f"{split}_{part}.npz"
            fa_path = Path(manifest["splits"][split][part]["fasta"])
            seq_map = {cid: seq for cid, seq in iter_fasta(fa_path)}
            with np.load(npz_path, allow_pickle=True) as d:
                payload = {k: d[k] for k in d.files}
            cids = payload["contig_ids"]
            starts = payload["starts"]
            ends = payload["ends"]
            feats_new = np.zeros((len(cids), len(FEATURE_NAMES_STAGE1)), dtype=np.float32)
            by_cid: dict[str, list[int]] = {}
            for idx, cid in enumerate(cids):
                by_cid.setdefault(str(cid), []).append(idx)
            for cid, idxs in by_cid.items():
                sp_list = [(int(starts[i]), int(ends[i])) for i in idxs]
                res_s1 = extract_contig_windows_for_spans(
                    cid, seq_map[cid], sp_list, feature_profile="stage1",
                )
                for local_i, g_i in enumerate(idxs):
                    feats_new[g_i] = res_s1["features"][local_i]
            payload["features"] = feats_new
            payload["feature_names"] = np.asarray(FEATURE_NAMES_STAGE1)
            np.savez_compressed(npz_path, **payload)

    _upgrade_split_to_stage1(tr_feat, tr_manifest, "train")
    _upgrade_split_to_stage1(ev_feat, ev_manifest, "val")
    _upgrade_split_to_stage1(ev_feat, ev_manifest, "test")

    win_fa = Path(tr_manifest["splits"]["train"]["windows"]["fasta"])
    chim_fa = Path(tr_manifest["splits"]["train"]["chimeras"]["fasta"])
    fa_by_part = {"windows": win_fa, "chimeras": chim_fa}

    for part in ("windows", "chimeras"):
        d, tokens, counts = _load_or_extract_part(
            tr_feat,
            train_bench,
            "train",
            part,
            tr_feat,
            workers=1,
            fasta_override=fa_by_part[part],
            feature_profile="stage1",
        )
        cids = d["contig_ids"]
        starts = d["starts"]
        ends = d["ends"]
        labels = d["labels"]

        contig_orfs: dict[str, list[dict[str, Any]]] = {}
        for wi in range(len(labels)):
            cid = str(cids[wi])
            ws, we = int(starts[wi]), int(ends[wi])
            wlen = max(1, we - ws)
            cnt = int(counts[wi])
            lst = contig_orfs.setdefault(cid, [])
            for k in range(cnt):
                gs = ws + int(round(float(tokens[wi, k, 6]) * wlen))
                ge = ws + int(round(float(tokens[wi, k, 7]) * wlen))
                st = 1 if float(tokens[wi, k, 1]) >= 0.0 else -1
                if int(labels[wi]) == 1 and k == 0:
                    cls = classify_protein_to_functional_partitions(phrog_category="tail")
                elif int(labels[wi]) == 1 and k == 1:
                    cls = classify_protein_to_functional_partitions(phrog_category="lysis")
                else:
                    cls = classify_protein_to_functional_partitions()
                lst.append((gs, ge, st, cls))

        tgt = build_window_and_orf_functional_targets(
            cids, starts, ends, labels, tokens, counts, contig_orfs,
        )
        np.savez_compressed(tr_feat / f"train_{part}_functional.npz", **tgt)

    stu_dir = tmp_path / "student_stage1_2"
    rep = train_distilled_student_v4(
        tr_feat,
        train_bench,
        ev_feat,
        bench_dir,
        stu_dir,
        train_parts=("windows", "chimeras"),
        epochs=2,
        batch_size=8,
        patience=2,
        dna_channels=48,
        orf_d_model=32,
        orf_nhead=4,
        orf_num_layers=1,
        fusion_dim=48,
        use_semantic=True,
        use_functional=True,
        use_homoscedastic_loss=True,
        tune_sub_head=False,
        train_refiner=True,
        refiner_epochs=2,
        train_subbin_refiner=True,
        subbin_epochs=2,
        feature_profile="stage1",
        workers=1,
    )
    meta = json.loads((stu_dir / "student_v4_meta.json").read_text(encoding="utf-8"))
    assert meta["func_dim"] == NUM_FUNC_PARTITIONS
    assert meta["use_homoscedastic_loss"] is True
    assert rep["architecture"]["func_dim"] == NUM_FUNC_PARTITIONS
    assert isinstance(rep.get("learned_task_weights"), list) and len(rep["learned_task_weights"]) == 6

    scanner = GenomeScanner.from_model_dir(
        stu_dir,
        seed_threshold=0.001,
        extend_threshold=0.001,
        sub_threshold=0.001,
        min_region_bp=400,
        workers=1,
    )
    scan_seq = _synth_test_dna(15000, seed=999)
    scan_res = scanner.scan_sequences(
        {"SYN_CTG": scan_seq},
        apply_protein_gate=False,
        collect_functional_partitions=True,
    )
    assert len(scan_res.raw_regions) >= 1
    assert len(scan_res.region_functional_modules) >= 1
    first_mod = next(iter(scan_res.region_functional_modules.values()))
    assert set(first_mod["module_scores"].keys()) == set(FUNCTIONAL_PARTITION_NAMES)
    assert isinstance(first_mod["active_modules"], list)
    assert isinstance(first_mod["orfs"], list)


def test_collect_region_functional_modules_avoids_single_window_peak_inflation() -> None:
    """验证区段功能模块聚合融合逐 ORF 证据与窗口均值，不被孤立单窗高分尖峰虚高抬破阈值。"""
    from src.phage_discovery.benchmark.metrics import PredictedRegion, WindowPrediction
    from src.phage_discovery.inference.scanner import _collect_region_functional_modules

    wins = [
        WindowPrediction("CTG_FUNC", 0, 5000, 0.90),
        WindowPrediction("CTG_FUNC", 2500, 7500, 0.92),
        WindowPrediction("CTG_FUNC", 5000, 10000, 0.88),
    ]
    regs = [PredictedRegion("CTG_FUNC", 0, 10000, 0.92, 0.90, 3)]

    # 窗口0 在 connector(idx=1) 上有孤立尖峰 (logit=+4.0 -> p~0.98)，窗口1/2 很低；
    # 全区 integration_excision(idx=4) 中高值 (logit=+0.2 -> p~0.55) 且存在 1 个高置信 ORF。
    func_logits = np.full((3, 9), -3.0, dtype=np.float32)
    func_logits[0, 1] = 4.0
    func_logits[:, 4] = 0.2

    tokens = np.zeros((3, 4, 10), dtype=np.float32)
    counts = np.array([2, 1, 1], dtype=np.int32)
    # ORF coordinates (rel_start=col6, rel_end=col7, strand=col1)
    tokens[0, 0, 1], tokens[0, 0, 6], tokens[0, 0, 7] = 1.0, 0.05, 0.20
    tokens[0, 1, 1], tokens[0, 1, 6], tokens[0, 1, 7] = -1.0, 0.30, 0.45
    tokens[1, 0, 1], tokens[1, 0, 6], tokens[1, 0, 7] = 1.0, 0.20, 0.40
    tokens[2, 0, 1], tokens[2, 0, 6], tokens[2, 0, 7] = 1.0, 0.40, 0.65

    orf_phage = np.full((3, 4), 0.1, dtype=np.float32)
    orf_phage[0, 0] = 0.97
    orf_func = np.full((3, 4, 9), 0.03, dtype=np.float32)
    orf_func[0, 0, 4] = 0.96

    res = _collect_region_functional_modules(
        wins,
        regs,
        {"func_logits": func_logits, "orf_phage_probs": orf_phage, "orf_func_probs": orf_func},
        tokens,
        counts,
        module_threshold=0.45,
    )
    rec = res["CTG_FUNC:0-10000"]
    assert rec["module_scores"]["connector"] < 0.45
    assert "connector" not in rec["active_modules"]
    assert "integration_excision" in rec["active_modules"]
    assert rec["orf_module_counts"]["integration_excision"] == 1
    assert rec["structural_completeness_hint"] == "cryptic_or_incomplete"


def test_collect_region_functional_modules_requires_head_orf_for_complete_core() -> None:
    """无 head_packaging 实证 ORF 时，不得仅凭窗均值或次优概率漂移判定为 complete_structural_core。"""
    from src.phage_discovery.benchmark.metrics import PredictedRegion, WindowPrediction
    from src.phage_discovery.inference.scanner import _collect_region_functional_modules

    wins = [
        WindowPrediction("CTG_HEAD_GATE", 0, 5000, 0.92),
        WindowPrediction("CTG_HEAD_GATE", 2500, 7500, 0.94),
    ]
    regs = [PredictedRegion("CTG_HEAD_GATE", 0, 7500, 0.94, 0.93, 2)]

    tokens = np.zeros((2, 3, 10), dtype=np.float32)
    counts = np.array([2, 1], dtype=np.int32)
    tokens[0, 0, 1], tokens[0, 0, 6], tokens[0, 0, 7] = 1.0, 0.10, 0.30
    tokens[0, 1, 1], tokens[0, 1, 6], tokens[0, 1, 7] = 1.0, 0.40, 0.65
    tokens[1, 0, 1], tokens[1, 0, 6], tokens[1, 0, 7] = -1.0, 0.50, 0.80

    # Case A: head_packaging(idx=0) 窗口概率极高 (~0.92)，但所有 ORF 的 head_packaging 概率均低于 0.45，
    # 只有 tail(idx=2) 和 integration_excision(idx=4) 存在实证 ORF（类似 DLP12 / NZ_CP097190.1:808k）
    func_logits_a = np.full((2, 9), -3.0, dtype=np.float32)
    func_logits_a[:, 0] = 2.5
    func_logits_a[:, 2] = 1.5
    orf_phage_a = np.full((2, 3), 0.90, dtype=np.float32)
    orf_func_a = np.full((2, 3, 9), 0.02, dtype=np.float32)
    orf_func_a[0, 0, 0] = 0.25
    orf_func_a[0, 0, 2] = 0.92
    orf_func_a[0, 1, 0] = 0.20
    orf_func_a[0, 1, 4] = 0.88
    orf_func_a[1, 0, 0] = 0.15
    orf_func_a[1, 0, 2] = 0.90

    res_a = _collect_region_functional_modules(
        wins,
        regs,
        {"func_logits": func_logits_a, "orf_phage_probs": orf_phage_a, "orf_func_probs": orf_func_a},
        tokens,
        counts,
        module_threshold=0.45,
    )["CTG_HEAD_GATE:0-7500"]
    assert res_a["module_scores"]["head_packaging"] >= 0.45
    assert res_a["orf_module_counts"]["head_packaging"] == 0
    assert "head_packaging" not in res_a["active_modules"]
    assert res_a["structural_completeness_hint"] == "cryptic_or_incomplete"

    # Case B: 某 ORF 的次优概率使 orf_max_vec[0]=0.48 >= 0.45，但主导模块仍是 tail(0.92)，head ORF 计数依然为 0
    orf_func_b = orf_func_a.copy()
    orf_func_b[0, 0, 0] = 0.48
    res_b = _collect_region_functional_modules(
        wins,
        regs,
        {"func_logits": func_logits_a, "orf_phage_probs": orf_phage_a, "orf_func_probs": orf_func_b},
        tokens,
        counts,
        module_threshold=0.45,
    )["CTG_HEAD_GATE:0-7500"]
    assert res_b["orf_module_counts"]["head_packaging"] == 0
    assert res_b["structural_completeness_hint"] == "cryptic_or_incomplete"

    # Case C: 真实具备 >=1 head_packaging ORF 与 >=1 tail ORF 时，正确判定 complete_structural_core
    orf_func_c = orf_func_a.copy()
    orf_func_c[0, 1, 0] = 0.93
    orf_func_c[0, 1, 4] = 0.05
    res_c = _collect_region_functional_modules(
        wins,
        regs,
        {"func_logits": func_logits_a, "orf_phage_probs": orf_phage_a, "orf_func_probs": orf_func_c},
        tokens,
        counts,
        module_threshold=0.45,
    )["CTG_HEAD_GATE:0-7500"]
    assert res_c["orf_module_counts"]["head_packaging"] >= 1
    assert res_c["orf_module_counts"]["tail"] >= 1
    assert "head_packaging" in res_c["active_modules"]
    assert res_c["structural_completeness_hint"] == "complete_structural_core"


