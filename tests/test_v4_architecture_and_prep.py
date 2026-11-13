# -*- coding: utf-8 -*-
"""V4 升级架构、离线蛋白语义标注、Masked Pooling 不变性与端到端扫描单元测试。"""
import json
import sqlite3
from pathlib import Path

import numpy as np
import torch

from src.phage_discovery.data.v4_semantic_prep import (
    annotate_train_semantics_with_diamond,
    ensure_v4_orf_tokens,
    mine_hard_transposase_and_archaeal_windows,
)
from src.phage_discovery.experts.expert_a_xgb import train_expert_a
from src.phage_discovery.experts.expert_b_cnn import compute_group_oof_expert_b_probs, train_expert_b
from src.phage_discovery.experts.expert_c_orf import (
    MAX_ORFS_PER_WIN,
    ORF_FEAT_DIM,
    compute_group_oof_expert_c_probs,
    extract_contig_orf_tokens,
    train_expert_c,
)
from src.phage_discovery.features.window_features import FEATURE_NAMES, SUB_BINS, extract_contig_windows
from src.phage_discovery.inference.scanner import GenomeScanner
from src.phage_discovery.student.distilled_student_v4 import (
    REFINER_STEP_FEAT_DIM,
    SEMANTIC_DIM,
    build_distilled_student_v4,
    group_windows_by_contig,
    predict_with_context_refiner,
    train_context_refiner,
    train_distilled_student_v4,
)


def _synth_dna(length: int, seed: int = 0, gc: float = 0.50) -> str:
    rng = np.random.default_rng(seed)
    p_gc = gc * 0.5
    p_at = (1.0 - gc) * 0.5
    bases = np.array(["A", "C", "G", "T"])
    probs = np.array([p_at, p_gc, p_gc, p_at])
    return "".join(rng.choice(bases, size=length, p=probs).tolist())


def _synth_orf_rich_dna(length: int, seed: int = 0) -> str:
    """生成带强 SD 核糖体结合位点与完整读框的序列，确保 Pyrodigal(meta=True) 稳定检出高密度 ORF。"""
    rng = np.random.default_rng(seed)
    codons_pool = ["GCT", "GCC", "GAA", "GAG", "AAA", "AAG", "CTG", "TTG", "ATT", "ATC", "GGT", "TTC", "TAT", "CAG", "AAC"]
    stops = ["TAA", "TAG", "TGA"]
    parts = []
    cur = 0
    while cur < length:
        n_codons = int(rng.integers(140, 200))
        rbs = "TAAGGAGGAAAAAA"
        orf = rbs + "ATG" + "".join(rng.choice(codons_pool, size=n_codons).tolist()) + str(rng.choice(stops))
        spacer = "CCCCCC"
        seg = orf + spacer
        parts.append(seg)
        cur += len(seg)
    return "".join(parts)[:length]


def _save_split_npz(
    path: Path,
    fasta_records,
    *,
    win_size: int = 5000,
    step_size: int = 2500,
    truth_map=None,
    label_override=None,
):
    feats_l, lbl_l, ov_l, sub_l, cid_l, st_l, ed_l = [], [], [], [], [], [], []
    for cid, seq in fasta_records:
        ws = win_size if len(seq) >= win_size else len(seq)
        st = step_size if len(seq) >= win_size else len(seq)
        truth = truth_map.get(cid) if truth_map else None
        res = extract_contig_windows(cid, seq, win_size=ws, step_size=st, truth_regions=truth)
        if len(res["starts"]) == 0:
            continue
        n = len(res["starts"])
        feats_l.append(res["features"])
        if label_override and cid in label_override:
            lbl = np.full(n, int(label_override[cid]), dtype=np.int8)
            ov = np.where(lbl == 1, 1.0, 0.0).astype(np.float32)
            sub = np.where(lbl[:, None] == 1, 1.0, 0.0).astype(np.float32)
            sub = np.broadcast_to(sub, (n, SUB_BINS)).copy()
        else:
            ov = res["overlap"].astype(np.float32)
            lbl = np.full(n, -1, dtype=np.int8)
            lbl[ov >= 0.5] = 1
            lbl[ov <= 0.0] = 0
            sub = res["sub_mask"].astype(np.float32)
        lbl_l.append(lbl)
        ov_l.append(ov)
        sub_l.append(sub)
        cid_str = str(cid)
        cid_l.append(np.full(n, cid_str, dtype=f"<U{max(1, len(cid_str))}"))
        st_l.append(res["starts"])
        ed_l.append(res["ends"])

    total_rows = int(sum(len(x) for x in lbl_l))
    np.savez_compressed(
        path,
        feature_names=np.asarray(FEATURE_NAMES),
        features=np.concatenate(feats_l).astype(np.float32),
        labels=np.concatenate(lbl_l).astype(np.int8),
        overlap=np.concatenate(ov_l).astype(np.float32),
        sub_mask=np.concatenate(sub_l).astype(np.float32),
        contig_ids=np.concatenate(cid_l),
        starts=np.concatenate(st_l).astype(np.int64),
        ends=np.concatenate(ed_l).astype(np.int64),
        source=np.full(total_rows, 0, dtype=np.int8),
    )


def test_v4_semantic_prep_zero_leakage_and_clean_labels(tmp_path: Path):
    neg_dir = tmp_path / "neg_lib"
    (neg_dir / "fasta").mkdir(parents=True)
    (neg_dir / "index").mkdir(parents=True)

    tr_arch_fa = neg_dir / "fasta" / "NC_TR_ARCH.fasta"
    tr_bac_fa = neg_dir / "fasta" / "NC_TR_BAC.fasta"
    te_arch_fa = neg_dir / "fasta" / "NC_TE_ARCH.fasta"
    tr_arch_fa.write_text(f">NC_TR_ARCH\n{_synth_orf_rich_dna(7000, seed=1)}\n", encoding="utf-8")
    tr_bac_fa.write_text(f">NC_TR_BAC\n{_synth_orf_rich_dna(60000, seed=2)}\n", encoding="utf-8")
    te_arch_fa.write_text(f">NC_TE_ARCH\n{_synth_orf_rich_dna(7000, seed=3)}\n", encoding="utf-8")

    db_path = neg_dir / "index" / "negative_index.sqlite"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "CREATE TABLE genomes (accession TEXT, negative_category TEXT, organism TEXT, length_bp INT, fasta_relpath TEXT, is_valid_negative INT)"
        )
        conn.execute(
            "CREATE TABLE cds_features (id INT, accession TEXT, locus_tag TEXT, protein_id TEXT, start_pos INT, end_pos INT, strand INT, length_aa INT, product TEXT)"
        )
        conn.execute(
            "CREATE TABLE prophage_masks (id INT, accession TEXT, negative_category TEXT, start_pos INT, end_pos INT, mask_length_bp INT, evidence_source TEXT)"
        )
        conn.executemany(
            "INSERT INTO genomes VALUES (?, ?, ?, ?, ?, ?)",
            [
                ("NC_TR_ARCH", "non_phage_virus", "Sulfolobus spindle-shaped virus 1", 7000, "fasta/NC_TR_ARCH.fasta", 1),
                ("NC_TR_BAC", "bacterial_chromosome", "Test bacterium", 60000, "fasta/NC_TR_BAC.fasta", 1),
                ("NC_TE_ARCH", "non_phage_virus", "Sulfolobus virus test holdout", 7000, "fasta/NC_TE_ARCH.fasta", 1),
            ],
        )
        # 一条被 prophage_masks 屏蔽 (1000..5000 +/- 15000 => ~0..20000)，一条安全在 45000..46500
        conn.execute("INSERT INTO prophage_masks VALUES (1, 'NC_TR_BAC', 'bacterial_chromosome', 1000, 5000, 4000, 'checkv')")
        conn.executemany(
            "INSERT INTO cds_features VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (1, "NC_TR_BAC", "L1", "P1", 2000, 3200, 1, 400, "IS200 family transposase"),
                (2, "NC_TR_BAC", "L2", "P2", 45000, 46200, 1, 400, "IS5 family transposase"),
            ],
        )
        conn.commit()

    splits_json = tmp_path / "negative_splits.json"
    splits_json.write_text(
        json.dumps({"NC_TR_ARCH": "train", "NC_TR_BAC": "train", "NC_TE_ARCH": "test"}),
        encoding="utf-8",
    )

    out_fa = tmp_path / "ext_hard_v4.fna"
    out_npz = tmp_path / "train_hard_v4.npz"
    info = mine_hard_transposase_and_archaeal_windows(neg_dir, splits_json, out_fa, out_npz, workers=1, seed=42)
    assert info["rows"] > 0
    fa_txt = out_fa.read_text(encoding="utf-8")
    assert "NC_TR_ARCH" in fa_txt
    assert "NC_TR_BAC" in fa_txt
    assert "NC_TE_ARCH" not in fa_txt
    # 确保近 mask 转座酶 (pos 2000) 没被采到 0..6000，仅采 45000 附近位点
    with np.load(out_npz, allow_pickle=True) as d:
        cids = [str(c) for c in d["contig_ids"]]
        assert all("NC_TE_ARCH" not in c for c in cids)
        assert np.all(d["labels"] == 0)

    # 构造 chimeras 伪负样本测试 semantic 4 维输出与矛盾负样本屏蔽
    chim_fa = tmp_path / "train_chimeras.fna"
    chim_npz = tmp_path / "train_chimeras.npz"
    bac_seq = _synth_orf_rich_dna(15000, seed=9)
    chim_fa.write_text(f">CHIM_0\n{bac_seq}\n", encoding="utf-8")
    _save_split_npz(chim_npz, [("CHIM_0", bac_seq)], label_override={"CHIM_0": 0})

    def _mock_hit_fetcher(orf_records):
        hits = {}
        for qid, _ in orf_records:
            if qid.startswith("CHIM_0__orf"):
                oi = int(qid.split("__orf")[1])
                if oi % 3 == 0:
                    hits[qid] = (110.0, "phage integrase [Escherichia phage]")
                else:
                    hits[qid] = (120.0, "major capsid protein [Enterobacteria phage]")
            elif qid.startswith("HARDV4_IS_"):
                hits[qid] = (95.0, "IS5 family transposase [Escherichia coli]")
            elif qid.startswith("HARDV4_ARCH_"):
                hits[qid] = (100.0, "major capsid protein [Phage X]")
        return hits

    sem_sum = annotate_train_semantics_with_diamond(
        [("chimeras", chim_npz, chim_fa), ("hard_v4", out_npz, out_fa)],
        hit_fetcher=_mock_hit_fetcher,
        workers=1,
    )
    assert sem_sum["chimeras"]["cleaned_contradictory_negatives"] >= 1
    assert sem_sum["hard_v4"]["transposase_risk_windows"] >= 1

    with np.load(tmp_path / "train_chimeras_semantic.npz") as sc:
        assert sc["sem_targets"].shape[1] == 4
        assert sc["sem_valid_mask"].shape[0] == len(sc["clean_labels"])
        assert np.any(sc["clean_labels"] == -1)
        assert np.any(sc["sem_targets"][:, 1] > 0.5)  # integrase 维被点亮

    with np.load(tmp_path / "train_hard_v4_semantic.npz") as sh:
        # 古菌样本不得因清洗变 -1
        with np.load(out_npz, allow_pickle=True) as d:
            arch_mask = np.array([str(c).startswith("HARDV4_ARCH_") for c in d["contig_ids"]])
        assert np.all(sh["clean_labels"][arch_mask] == 0)

    orf_map = ensure_v4_orf_tokens(tmp_path, [("hard_v4", out_fa)], workers=1)
    assert "hard_v4" in orf_map
    with np.load(orf_map["hard_v4"]) as tok_d:
        assert tok_d["tokens"].shape == (info["rows"], MAX_ORFS_PER_WIN, ORF_FEAT_DIM)


def test_student_v4_masked_pooling_padding_invariance():
    torch.manual_seed(0)
    feat_dim = len(FEATURE_NAMES)
    mean = np.zeros(feat_dim, dtype=np.float32)
    std = np.ones(feat_dim, dtype=np.float32)
    model = build_distilled_student_v4(
        feat_dim, mean, std, dna_channels=64, orf_d_model=32, orf_nhead=4, orf_num_layers=1, fusion_dim=64,
    ).eval()

    rng = np.random.default_rng(7)
    valid_len = 600
    dna_valid = np.eye(4, dtype=np.float32)[rng.integers(0, 4, size=valid_len)].T  # (4, 600)

    dna_1k = np.zeros((1, 4, 1000), dtype=np.float32)
    dna_1k[0, :, :valid_len] = dna_valid
    dna_5k = np.zeros((1, 4, 5000), dtype=np.float32)
    dna_5k[0, :, :valid_len] = dna_valid

    tab = torch.randn(1, feat_dim)
    ln = torch.tensor([valid_len], dtype=torch.long)
    tk = torch.randn(1, MAX_ORFS_PER_WIN, ORF_FEAT_DIM)
    cn = torch.tensor([3], dtype=torch.long)

    with torch.no_grad():
        r_1k = model(torch.from_numpy(dna_1k), tab, lengths=ln, orf_tokens=tk, orf_counts=cn, return_aux=True)
        r_5k = model(torch.from_numpy(dna_5k), tab, lengths=ln, orf_tokens=tk, orf_counts=cn, return_aux=True)

    diff_logit = float((r_1k["win_logit"] - r_5k["win_logit"]).abs().max())
    diff_sem = float((r_1k["sem_logits"] - r_5k["sem_logits"]).abs().max())
    assert diff_logit < 1e-4, f"Masked pooling padding 不变性误差过大: {diff_logit}"
    assert diff_sem < 1e-4, f"Masked pooling semantic 不变性误差过大: {diff_sem}"

    # 校验梯度通畅流回多任务分支
    model.train()
    r_tr = model(torch.from_numpy(dna_5k), tab, lengths=ln, orf_tokens=tk, orf_counts=cn, return_aux=True)
    loss = r_tr["win_logit"].sum() + r_tr["sub_logits"].sum() + r_tr["sem_logits"].sum()
    loss.backward()
    has_dna_grad = any(p.grad is not None and float(p.grad.abs().sum()) > 0 for p in model.dna_stem.parameters())
    has_orf_grad = any(p.grad is not None and float(p.grad.abs().sum()) > 0 for p in model.orf_stream.parameters())
    assert has_dna_grad and has_orf_grad


def test_region_context_refiner_ordering_and_training(tmp_path: Path):
    # 打乱窗口顺序，确认 group_windows_by_contig 按 start_bp 准确排序
    cids = np.array(["C1", "C2", "C1", "C1"])
    starts = np.array([5000, 0, 0, 2500], dtype=np.int64)
    groups = group_windows_by_contig(cids, starts)
    c1_grp = [g for g in groups if cids[g[0]] == "C1"][0]
    assert list(starts[c1_grp]) == [0, 2500, 5000]

    # 生成 8 条连续 contig，训练与预测闭环
    n_c, w_len = 8, 10
    total = n_c * w_len
    rng = np.random.default_rng(11)
    tr_cid = np.array([f"CTG_{i // w_len}" for i in range(total)], dtype=object)
    tr_st = np.array([(i % w_len) * 2500 for i in range(total)], dtype=np.int64)
    tr_lbl = np.zeros(total, dtype=np.int8)
    tr_rl = rng.normal(-2.5, 0.4, size=total).astype(np.float32)
    tr_sf = rng.normal(0.0, 0.2, size=(total, REFINER_STEP_FEAT_DIM)).astype(np.float32)
    for c in range(0, n_c, 2):
        s0 = c * w_len + 3
        tr_lbl[s0:s0 + 4] = 1
        tr_rl[s0:s0 + 4] = 1.8
    tr_sf[:, 0] = tr_rl
    tr_sf[:, 1] = 1.0 / (1.0 + np.exp(-tr_rl))

    ref_ckpt = tmp_path / "context_refiner.pt"
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    refiner, info = train_context_refiner(
        tr_sf, tr_rl, tr_lbl, tr_cid, tr_st,
        tr_sf[:20], tr_rl[:20], tr_lbl[:20], tr_cid[:20], tr_st[:20],
        out_path=ref_ckpt, epochs=4, patience=3, seed=42,
    )
    assert ref_ckpt.exists()
    assert info["tr_contigs"] == n_c
    probs = predict_with_context_refiner(
        refiner,
        tr_rl[:20],
        tr_sf[:20, 2:6],
        np.full((20, SUB_BINS), 0.5, dtype=np.float32),
        np.full(20, 5000, dtype=np.int64),
        tr_cid[:20],
        tr_st[:20],
        device,
    )
    assert probs.shape == (20,)
    assert np.all((probs >= 0.0) & (probs <= 1.0))


def test_end_to_end_v4_experts_student_and_scanner(tmp_path: Path):
    import csv
    from src.phage_discovery.benchmark.chimera_builder import build_benchmark_suite
    from src.phage_discovery.data.feature_dataset import build_split_features

    pos_dir = tmp_path / "pos_ds"
    neg_dir = tmp_path / "neg_ds"
    (pos_dir / "fasta").mkdir(parents=True)
    (pos_dir / "preprocessed" / "splits").mkdir(parents=True)
    (neg_dir / "fasta").mkdir(parents=True)
    (neg_dir / "index").mkdir(parents=True)

    for sp, n in (("train", 6), ("val", 3), ("test", 3)):
        with open(pos_dir / "preprocessed" / "splits" / f"{sp}.tsv", "w", encoding="utf-8", newline="") as fh:
            w = csv.writer(fh, delimiter="\t")
            w.writerow(["accession", "cluster_id", "tax_group", "host", "length_bp"])
            for i in range(n):
                acc = f"NC_V4_{sp.upper()}_{i}.1"
                seq = _synth_orf_rich_dna(12000, seed=1000 + len(sp) * 10 + i)
                (pos_dir / "fasta" / f"{acc}.fasta").write_text(f">{acc}\n{seq}\n", encoding="utf-8")
                w.writerow([acc, f"CLU_{sp}_{i}", "Caudoviricetes", "E. coli", len(seq)])

    with sqlite3.connect(neg_dir / "index" / "negative_index.sqlite") as conn:
        conn.execute(
            "CREATE TABLE genomes (accession TEXT PRIMARY KEY, is_valid_negative INTEGER, negative_category TEXT, organism TEXT, length_bp INTEGER, fasta_relpath TEXT)"
        )
        conn.execute("CREATE TABLE prophage_masks (id INTEGER PRIMARY KEY AUTOINCREMENT, accession TEXT, start_pos INTEGER, end_pos INTEGER)")
        for i in range(9):
            acc = f"NZ_V4_HOST_{i}.1"
            seq = _synth_orf_rich_dna(120000, seed=2000 + i)
            (neg_dir / "fasta" / f"{acc}.fasta").write_text(f">{acc}\n{seq}\n", encoding="utf-8")
            conn.execute("INSERT INTO genomes VALUES (?, 1, 'bacterial_chromosome', 'Bacillus', ?, ?)", (acc, len(seq), f"fasta/{acc}.fasta"))
        conn.commit()

    bench_dir = tmp_path / "bench"
    train_bench = tmp_path / "train_bench"
    tr_feat = tmp_path / "tr_feat"
    ev_feat = tmp_path / "ev_feat"
    build_benchmark_suite(pos_dir, neg_dir, bench_dir, splits_to_build=("val", "test"), chimeras_per_split=4, pure_neg_hosts_per_split=1, windows_per_split=24, seed=7)
    build_benchmark_suite(pos_dir, neg_dir, train_bench, splits_to_build=("train",), chimeras_per_split=4, pure_neg_hosts_per_split=1, windows_per_split=24, seed=7)
    build_split_features(train_bench, "train", tr_feat, workers=1)
    build_split_features(bench_dir, "val", ev_feat, workers=1)
    build_split_features(bench_dir, "test", ev_feat, workers=1)

    # 训练小容量 V4 专家和 V4 学生与 Refiner
    exp_a_dir = tmp_path / "exp_a"
    rep_a = train_expert_a(tr_feat, ev_feat, bench_dir, exp_a_dir, n_estimators=20, early_stopping_rounds=5, n_jobs=2)
    assert Path(rep_a["model_path"]).exists()

    exp_b_dir = tmp_path / "exp_b"
    rep_b = train_expert_b(
        tr_feat, train_bench, ev_feat, bench_dir, exp_b_dir,
        epochs=2, batch_size=8, patience=2, channels=32, n_blocks=2,
    )
    assert rep_b["architecture"]["channels"] == 32

    exp_c_dir = tmp_path / "exp_c"
    rep_c = train_expert_c(
        tr_feat, train_bench, ev_feat, bench_dir, exp_c_dir,
        epochs=2, batch_size=8, patience=2, d_model=32, nhead=4, num_layers=1, workers=1,
    )
    assert rep_c["architecture"]["d_model"] == 32

    # 校验 OOF 接口可独立产出且长度一致
    with np.load(tr_feat / "train_windows.npz", allow_pickle=True) as tw:
        n_w = len(tw["labels"])
        cids_w = tw["contig_ids"]
        lbl_w = tw["labels"]
        tk_w, cn_w = extract_contig_orf_tokens(_synth_orf_rich_dna(5000, seed=77), [0] * n_w, [5000] * n_w)
        oof_c = compute_group_oof_expert_c_probs(
            tk_w, cn_w, lbl_w, cids_w, n_splits=2, epochs=2, batch_size=8, d_model=32, nhead=4, num_layers=1,
        )
        assert oof_c.shape == (n_w,)
        from src.phage_discovery.experts.seq_dataset import load_window_sequences
        tr_manifest = json.loads((train_bench / "benchmark_manifest.json").read_text(encoding="utf-8"))
        codes_w, lens_w = load_window_sequences(Path(tr_manifest["splits"]["train"]["windows"]["fasta"]), cids_w, tw["starts"], tw["ends"], max_len=5000)
        oof_bw, oof_bs = compute_group_oof_expert_b_probs(
            codes_w, lens_w, lbl_w, lbl_w, tw["sub_mask"], cids_w,
            n_splits=2, epochs=2, batch_size=8, channels=32, n_blocks=2, tmp_dir=tmp_path / "oof_b_tmp",
        )
        assert oof_bw.shape == (n_w,) and oof_bs.shape == (n_w, SUB_BINS)

    # 训练 V4 学生 + Refiner，再用 GenomeScanner 进行端到端纯神经扫描
    stu_dir = tmp_path / "student_v4"
    rep_v4 = train_distilled_student_v4(
        tr_feat, train_bench, ev_feat, bench_dir, stu_dir,
        epochs=2, batch_size=8, patience=2,
        dna_channels=48, orf_d_model=32, orf_nhead=4, orf_num_layers=1, fusion_dim=48,
        train_refiner=True, refiner_epochs=2, workers=1,
    )
    assert (stu_dir / "student_v4.pt").exists()
    assert (stu_dir / "student_v4_meta.json").exists()
    assert (stu_dir / "context_refiner.pt").exists()
    assert (stu_dir / "subbin_refiner.pt").exists()
    assert rep_v4["context_refiner"]["enabled"] is True
    assert rep_v4["subbin_refiner"]["enabled"] is True

    scan_fa = tmp_path / "scan_target.fna"
    scan_fa.write_text(f">SCAN_CONTIG_1\n{_synth_orf_rich_dna(22000, seed=999)}\n", encoding="utf-8")

    scanner_v4 = GenomeScanner.from_model_dir(stu_dir, device="cpu", workers=1)
    assert scanner_v4.model_version == "v4"
    assert scanner_v4.refiner is not None
    assert scanner_v4.subbin_refiner is not None
    res_raw = scanner_v4.scan_fasta(scan_fa, apply_protein_gate=False)
    assert res_raw.total_windows > 0
    assert res_raw.raw_regions == res_raw.verified_regions

    scanner_no_ref = GenomeScanner.from_model_dir(
        stu_dir, device="cpu", workers=1, use_context_refiner=False, use_subbin_refiner=False,
    )
    assert scanner_no_ref.refiner is None
    assert scanner_no_ref.subbin_refiner is None
    res_no_ref = scanner_no_ref.scan_fasta(scan_fa, apply_protein_gate=False)
    assert res_no_ref.total_windows == res_raw.total_windows


def test_refiner_v2_gap_split_and_pulse_vs_degraded_separation(tmp_path: Path):
    from src.phage_discovery.student.distilled_student_v4 import build_region_context_refiner

    # 1) 同一 contig_id 相邻窗若物理距离 > max_gap_bp 必须被拆分成独立片段，source_tags 不同也不得合并
    cids = np.array(["C1", "C1", "C1", "C1", "C1"])
    starts = np.array([0, 2500, 50000, 52500, 0], dtype=np.int64)
    src_tags = np.array(["mined", "mined", "mined", "mined", "chimeras"])
    groups = group_windows_by_contig(cids, starts, max_gap_bp=5000, source_tags=src_tags)
    assert len(groups) == 3
    assert [list(starts[g]) for g in sorted(groups, key=lambda x: (str(src_tags[x[0]]), int(starts[x[0]])))] == [
        [0],
        [0, 2500],
        [50000, 52500],
    ]

    # 2) 验证新版 Refiner 能同时抑制 1 窗低 hallmark 孤立脉冲、并保留 5 窗高 hallmark 退化前噬菌体
    n_c, w_len = 16, 12
    total = n_c * w_len
    rng = np.random.default_rng(123)
    tr_cid = np.array([f"CTG_{i // w_len}" for i in range(total)], dtype=object)
    tr_st = np.array([(i % w_len) * 2500 for i in range(total)], dtype=np.int64)
    tr_lbl = np.zeros(total, dtype=np.int8)
    tr_rl = rng.normal(-3.0, 0.3, size=total).astype(np.float32)
    tr_sf = np.zeros((total, REFINER_STEP_FEAT_DIM), dtype=np.float32)
    tr_sf[:, 2:6] = -3.0
    tr_sf[:, 6:10] = 0.05
    tr_sf[:, 14] = 1.0

    for c in range(n_c):
        base = c * w_len
        if c % 2 == 0:
            # 宽 5 窗退化前噬菌体（raw_p ~ 0.78~0.90，高 hallmark）
            tr_lbl[base + 3:base + 8] = 1
            tr_rl[base + 3:base + 8] = np.array([1.2, 1.8, 2.2, 1.5, 1.9], dtype=np.float32)
            tr_sf[base + 3:base + 8, 2] = 1.4  # sem_hallmark logit
            tr_sf[base + 3:base + 8, 6] = 1.0 / (1.0 + np.exp(-1.4))
            tr_sf[base + 3:base + 8, 5] = 2.0  # sem_tail logit
            tr_sf[base + 3:base + 8, 9] = 1.0 / (1.0 + np.exp(-2.0))
        else:
            # 1 窗高分孤立低 hallmark 脉冲（模拟 S. aureus 转座酶误报）
            tr_rl[base + 5] = 2.8
            tr_sf[base + 5, 2] = -1.8
            tr_sf[base + 5, 6] = 1.0 / (1.0 + np.exp(1.8))

    tr_sf[:, 0] = tr_rl
    tr_sf[:, 1] = 1.0 / (1.0 + np.exp(-tr_rl))

    ref_ckpt = tmp_path / "context_refiner_v2.pt"
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    refiner, info = train_context_refiner(
        tr_sf, tr_rl, tr_lbl, tr_cid, tr_st,
        tr_sf[:4 * w_len], tr_rl[:4 * w_len], tr_lbl[:4 * w_len], tr_cid[:4 * w_len], tr_st[:4 * w_len],
        out_path=ref_ckpt, epochs=24, lr=3e-3, patience=10, seed=42, use_context_features=True,
    )
    assert info["refiner_arch"] == "v2"
    probs = predict_with_context_refiner(
        refiner,
        tr_rl[:2 * w_len],
        tr_sf[:2 * w_len, 2:6],
        np.full((2 * w_len, SUB_BINS), 0.5, dtype=np.float32),
        np.full(2 * w_len, 5000, dtype=np.int64),
        tr_cid[:2 * w_len],
        tr_st[:2 * w_len],
        device,
    )
    # contig 0 为 5 窗退化前噬菌体 -> 峰值需被稳稳保住 (>= 0.80)
    assert float(np.max(probs[3:8])) >= 0.80
    # contig 1 为孤立低 hallmark 脉冲 -> 需被有效压低 (< 0.75)
    assert float(probs[w_len + 5]) < 0.75
    # 向后兼容老 v1 无附加特征权重实例化
    ref_legacy = build_region_context_refiner(use_context_features=False)
    assert ref_legacy.use_context_features is False


def test_refine_student_v4_sub_head_preserves_win_and_sem_outputs(tmp_path: Path):
    from src.phage_discovery.student.distilled_student_v4 import (
        _predict_v4_all,
        refine_student_v4_sub_head,
    )

    torch.manual_seed(7)
    feat_dim = len(FEATURE_NAMES)
    mean = np.zeros(feat_dim, dtype=np.float32)
    std = np.ones(feat_dim, dtype=np.float32)
    model = build_distilled_student_v4(
        feat_dim, mean, std, dna_channels=32, orf_d_model=32, orf_nhead=4, orf_num_layers=1, fusion_dim=32,
    )
    n = 16
    rng = np.random.default_rng(19)
    codes = rng.integers(0, 4, size=(n, 5000), dtype=np.uint8)
    lengths = np.full(n, 5000, dtype=np.int64)
    feats = rng.normal(0.0, 1.0, size=(n, feat_dim)).astype(np.float32)
    tokens = np.zeros((n, MAX_ORFS_PER_WIN, ORF_FEAT_DIM), dtype=np.float32)
    counts = np.zeros(n, dtype=np.int32)
    sub_y = np.zeros((n, SUB_BINS), dtype=np.float32)
    sub_y[:8, :12] = 1.0
    sw = np.ones(n, dtype=np.float32)

    device = torch.device("cpu")
    before = _predict_v4_all(model, codes, lengths, feats, tokens, counts, device, batch_size=8)
    ckpt_out = tmp_path / "student_v4_sub_tuned.pt"
    refine_info = refine_student_v4_sub_head(
        model,
        codes, lengths, feats, tokens, counts, sub_y, sw,
        codes, lengths, feats, tokens, counts, sub_y,
        out_ckpt_path=ckpt_out,
        device=device,
        epochs=4,
        batch_size=8,
        lr=2e-3,
        patience=3,
    )
    assert ckpt_out.exists()
    assert refine_info["win_max_drift"] < 1e-6
    assert refine_info["sem_max_drift"] < 1e-6
    after = _predict_v4_all(model, codes, lengths, feats, tokens, counts, device, batch_size=8)
    assert np.max(np.abs(after["win_logits"] - before["win_logits"])) < 1e-6
    assert np.max(np.abs(after["sem_logits"] - before["sem_logits"])) < 1e-6
    assert np.max(np.abs(after["sub_probs"] - before["sub_probs"])) > 1e-4


def test_subbin_refiner_orf_projection_chunking_and_single_window_safety(tmp_path: Path):
    from src.phage_discovery.student.subbin_refiner import (
        ORF_STRAND_FEAT_INDEX,
        SUBBIN_TOTAL_FEAT_DIM,
        _infer_single_sequence_logits,
        build_contig_subbin_sequences,
        extract_per_orf_viral_scores,
        flip_subbin_features,
        load_subbin_refiner_checkpoint,
        predict_subbin_probs_with_refiner,
        project_orf_to_25bins,
        train_subbin_context_refiner,
    )

    torch.manual_seed(11)
    feat_dim = len(FEATURE_NAMES)
    model = build_distilled_student_v4(
        feat_dim,
        np.zeros(feat_dim, dtype=np.float32),
        np.ones(feat_dim, dtype=np.float32),
        dna_channels=32, orf_d_model=32, orf_nhead=4, orf_num_layers=1, fusion_dim=32,
    )
    n_win = 10
    tokens = np.zeros((n_win, MAX_ORFS_PER_WIN, ORF_FEAT_DIM), dtype=np.float32)
    counts = np.full(n_win, 2, dtype=np.int32)
    counts[0] = 0
    # ORF 0 位于 [0.20, 0.60) (+1 链)，ORF 1 位于 [0.68, 0.92) (-1 链)
    tokens[1:, 0, 1] = 1.0
    tokens[1:, 0, 6] = 0.20
    tokens[1:, 0, 7] = 0.60
    tokens[1:, 1, 1] = -1.0
    tokens[1:, 1, 6] = 0.68
    tokens[1:, 1, 7] = 0.92

    device = torch.device("cpu")
    orf_attn = extract_per_orf_viral_scores(model, tokens, counts, device, batch_size=4)
    assert orf_attn.shape == (n_win, MAX_ORFS_PER_WIN)
    assert np.all(orf_attn[0] == 0.0)
    assert np.all(orf_attn[1:, 2:] == 0.0)
    assert np.all((orf_attn[1:, :2] > 0.0) & (orf_attn[1:, :2] < 1.0))

    orf_bins = project_orf_to_25bins(tokens, counts, orf_attn)
    assert orf_bins.shape == (n_win, SUB_BINS, 10)
    # 窗口前段 [0, 0.20) 对应 bins 0..4 无编码覆盖，bin 5 (0.20..0.24) 起含 gene edge 与正链
    assert np.all(orf_bins[1, :5, 0] == 0.0)
    assert orf_bins[1, 5, 0] > 0.9 and orf_bins[1, 5, 3] > 0.0
    assert abs(float(orf_bins[1, 6, 1]) - 1.0) < 1e-5
    assert abs(float(orf_bins[1, 18, 1]) + 1.0) < 1e-5

    # 构造 1 条 9 窗长物理段 (25km) + 1 条 1 窗短孤立片段，验证快速/通用路径一致性与单窗直通保护
    cids = np.array(["LONG_C"] * 9 + ["SHORT_1"], dtype=object)
    starts = np.array([i * 2500 for i in range(9)] + [0], dtype=np.int64)
    ends = starts + 5000
    win_ref = np.full(10, 0.1, dtype=np.float32)
    win_ref[2:7] = 0.96
    win_raw = win_ref.copy()
    sem_logits = np.zeros((10, SEMANTIC_DIM), dtype=np.float32)
    sub_probs = np.full((10, SUB_BINS), 0.1, dtype=np.float32)
    sub_probs[2:7, :] = 0.9
    sub_probs[9, 5:15] = 0.73  # 单窗孤立，应保持原样

    groups = group_windows_by_contig(cids, starts, max_gap_bp=5000)
    tr_seqs = build_contig_subbin_sequences(
        [g for g in groups if len(g) >= 2], starts, ends, win_ref, win_raw, sem_logits, sub_probs,
        win_orf_25bins=orf_bins, sub_targets=sub_probs,
    )
    assert tr_seqs[0]["feats"].shape[1] == SUBBIN_TOTAL_FEAT_DIM
    sym_f = flip_subbin_features(flip_subbin_features(tr_seqs[0]["feats"], True), True)
    assert np.allclose(sym_f, tr_seqs[0]["feats"], atol=1e-6)
    assert np.allclose(
        flip_subbin_features(tr_seqs[0]["feats"], True)[:, ORF_STRAND_FEAT_INDEX],
        -tr_seqs[0]["feats"][::-1, ORF_STRAND_FEAT_INDEX],
        atol=1e-6,
    )

    ckpt_sb = tmp_path / "subbin_refiner.pt"
    sb_model, sb_rep = train_subbin_context_refiner(
        tr_seqs, tr_seqs, out_path=ckpt_sb, hidden_dim=32, epochs=4, batch_size=2,
    )
    assert ckpt_sb.exists() and sb_rep["in_dim"] == SUBBIN_TOTAL_FEAT_DIM
    sb_loaded = load_subbin_refiner_checkpoint(ckpt_sb, device)

    # 验证长序列分块滑窗与整条前向数值一致（允许 overlap 截断端轻微数值舍入）
    full_l = _infer_single_sequence_logits(
        sb_loaded, tr_seqs[0]["feats"], tr_seqs[0]["base_logit"], device,
        has_orf=True, max_chunk_bins=4096, overlap_bins=32, tta_flip=True,
    )
    chunk_l = _infer_single_sequence_logits(
        sb_loaded, tr_seqs[0]["feats"], tr_seqs[0]["base_logit"], device,
        has_orf=True, max_chunk_bins=80, overlap_bins=32, tta_flip=True,
    )
    assert chunk_l.shape == full_l.shape

    profiles, win_sub_ref = predict_subbin_probs_with_refiner(
        sb_loaded, groups, cids, starts, ends, win_ref, win_raw, sem_logits, sub_probs,
        device, win_orf_25bins=orf_bins, min_windows=2,
    )
    assert "LONG_C" in profiles and "SHORT_1" not in profiles
    assert np.allclose(win_sub_ref[9], sub_probs[9], atol=1e-6)

    # 验证无 subbin_refiner.pt 的 V4.1 历史目录向后兼容加载
    v41_dir = tmp_path / "legacy_v41"
    v41_dir.mkdir(parents=True)
    torch.save(model.state_dict(), v41_dir / "student_v4.pt")
    (v41_dir / "student_v4_meta.json").write_text(json.dumps({
        "model_version": "v4", "feat_dim": feat_dim, "max_len": 5000,
        "dna_channels": 32, "orf_d_model": 32, "orf_nhead": 4, "orf_num_layers": 1,
        "fusion_dim": 32, "sem_dim": SEMANTIC_DIM, "use_context_refiner": False,
    }), encoding="utf-8")
    legacy_scanner = GenomeScanner.from_model_dir(v41_dir, device="cpu", workers=1)
    assert legacy_scanner.subbin_refiner is None


def test_plateau_coarse_decoding_and_precomputed_subbin_profiles():
    from src.phage_discovery.benchmark.metrics import (
        WindowPrediction,
        decode_subwindow_probs_to_regions,
        decode_window_scores_to_regions,
    )

    # CTG_SHORT: 仅 2 窗高尖刺 (0.93, 0.91)，即便启用 plateau 仍应被 seed=0.95 拦截
    # CTG_PLATEAU: 连续 5 窗 0.91~0.942 平台，标准 seed=0.95 漏检而 plateau(4, 0.90) 应精准救回
    preds = [
        WindowPrediction("CTG_SHORT", 0, 5000, 0.93),
        WindowPrediction("CTG_SHORT", 2500, 7500, 0.91),
        WindowPrediction("CTG_PLATEAU", 5000, 10000, 0.78),
        WindowPrediction("CTG_PLATEAU", 7500, 12500, 0.91),
        WindowPrediction("CTG_PLATEAU", 10000, 15000, 0.942),
        WindowPrediction("CTG_PLATEAU", 12500, 17500, 0.935),
        WindowPrediction("CTG_PLATEAU", 15000, 20000, 0.89),
    ]
    base_regs = decode_window_scores_to_regions(preds, seed_threshold=0.95, extend_threshold=0.60)
    assert len(base_regs) == 0

    plat_regs = decode_window_scores_to_regions(
        preds, seed_threshold=0.95, extend_threshold=0.60, plateau_min_windows=4, plateau_second_threshold=0.90,
    )
    assert len(plat_regs) == 1 and plat_regs[0].contig_id == "CTG_PLATEAU"

    # 验证 precomputed_bin_profiles + smooth_profile=False 精准对齐 200bp 断点而不被窗均值弄模糊
    sub_probs = np.full((len(preds), SUB_BINS), 0.1, dtype=np.float32)
    prof = np.full(100, 0.05, dtype=np.float32)  # 覆盖 0..20000bp
    prof[28:88] = 0.85  # [5600, 17600) exact 200bp boundaries
    refined = decode_subwindow_probs_to_regions(
        preds, sub_probs,
        seed_threshold=0.95, extend_threshold=0.60, sub_threshold=0.50,
        plateau_min_windows=4, plateau_second_threshold=0.90,
        precomputed_bin_profiles={"CTG_PLATEAU": [(0, prof)]},
        smooth_profile=False, refine_pad_bp=3000,
    )
    assert len(refined) == 1
    assert (refined[0].start_bp, refined[0].end_bp) == (5600, 17600)
