# -*- coding: utf-8 -*-
"""阶段 1 优化先导单元测试：ORF 富编码属性、6-frame 兜底、二三肽语义、PHROGs 补全与 V4.2 向后兼容性。"""
import csv
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import torch

from src.phage_discovery.data.phrog_teacher import (
    classify_phrog_category,
    enrich_semantic_targets_with_phrog,
    load_phrog_annotations,
)
from src.phage_discovery.experts.expert_a_xgb import train_expert_a
from src.phage_discovery.experts.expert_c_orf import (
    MAX_ORFS_PER_WIN,
    ORF_FEAT_DIM,
    STAGE1_ORF_FEAT_DIM,
    _load_or_extract_part,
    build_orf_transformer,
    extract_contig_orf_tokens,
    get_orf_feat_dim,
)
from src.phage_discovery.features.peptide_features import (
    DIPEPTIDE_7X7_DIM,
    PYRODIGAL_ORF_ATTR_DIM,
    STAGE1_ORF_EXTRA_DIM,
    STAGE1_WINDOW_EXTRA_DIM,
    TRIPEPTIDE_3X3X3_DIM,
    TRIPEPTIDE_7X7X7_DIM,
    compute_best_6frame_coding_fraction,
    encode_orf_peptide_extra,
    encode_peptide_3x3x3_triad,
    encode_peptide_7x7_dipeptide,
    encode_peptide_7x7x7_triad,
    encode_pyrodigal_gene_attrs,
    find_best_6frame_orf,
)
from src.phage_discovery.features.window_features import (
    FEATURE_NAMES,
    FEATURE_NAMES_STAGE1,
    SUB_BINS,
    extract_contig_windows,
    get_feature_names,
)
from src.phage_discovery.inference.scanner import GenomeScanner
from src.phage_discovery.student.distilled_student_v4 import SEMANTIC_DIM, build_distilled_student_v4
from src.phage_discovery.student.subbin_refiner import extract_per_orf_viral_scores, project_orf_to_25bins


def _reverse_complement(seq: str) -> str:
    return seq.upper().translate(str.maketrans("ACGTNacgtn", "TGCANtgcan"))[::-1]


def _synth_orf_rich_dna(length: int, seed: int = 1) -> str:
    rng = np.random.default_rng(seed)
    codons = ["GCT", "GCC", "GAA", "GAG", "AAA", "AAG", "CTG", "TTG", "ATT", "ATC", "GGT", "TTC", "TAT", "CAG", "AAC"]
    stops = ["TAA", "TAG", "TGA"]
    out = []
    cur = 0
    while cur < length:
        seg = "TAAGGAGGAAAAAA" + "ATG" + "".join(rng.choice(codons, size=int(rng.integers(120, 180))).tolist()) + str(rng.choice(stops)) + "CCCCCC"
        out.append(seg)
        cur += len(seg)
    return "".join(out)[:length]


def _synth_no_sd_coding_dna(codons_n: int = 120, seed: int = 7) -> str:
    """生成无细菌 SD 核糖体结合位点、短于常规基因阈值的连续无终止子序列，同时确保反向链高频终止。"""
    rng = np.random.default_rng(seed)
    # TTA/CTA/TCA 正链正常编码 L/L/S，反向互补恰好对应 TAA/TAG/TGA 终止密码子
    codons = ["TTA", "CTA", "TCA", "GAA", "AAA", "TTT", "ATT", "GCT", "GGT", "TAT"]
    return "".join(rng.choice(codons, size=codons_n).tolist())


def test_peptide_dipeptide_and_tripeptide_encoding_distinguishes_order():
    """验证 7x7 二肽、7x7x7 Conjoint Triad 与 3x3x3 紧凑三肽可区分单氨基酸完全相同但排列顺序不同的蛋白。"""
    seq_interleaved = "ACDEFGHIKLMNPQRSTVWY" * 10
    seq_clustered = "".join(ch * 10 for ch in "ACDEFGHIKLMNPQRSTVWY")

    dp1 = encode_peptide_7x7_dipeptide(seq_interleaved)
    dp2 = encode_peptide_7x7_dipeptide(seq_clustered)
    ct1 = encode_peptide_7x7x7_triad(seq_interleaved)
    ct2 = encode_peptide_7x7x7_triad(seq_clustered)
    t27_1 = encode_peptide_3x3x3_triad(seq_interleaved)
    t27_2 = encode_peptide_3x3x3_triad(seq_clustered)

    assert dp1.shape == (DIPEPTIDE_7X7_DIM,) == (49,)
    assert ct1.shape == (TRIPEPTIDE_7X7X7_DIM,) == (343,)
    assert t27_1.shape == (TRIPEPTIDE_3X3X3_DIM,) == (27,)
    assert np.isclose(dp1.sum(), 1.0, atol=1e-5)
    assert np.isclose(ct1.sum(), 1.0, atol=1e-5)
    assert np.isclose(t27_1.sum(), 1.0, atol=1e-5)
    assert float(np.linalg.norm(dp1 - dp2)) > 0.05
    assert float(np.linalg.norm(ct1 - ct2)) > 0.05
    assert float(np.linalg.norm(t27_1 - t27_2)) > 0.05

    # 短肽 / 全未知字符边界鲁棒性
    empty_dp = encode_peptide_7x7_dipeptide("X*?")
    assert empty_dp.shape == (49,) and np.all(empty_dp == 0.0)
    assert encode_peptide_7x7x7_triad("AC").sum() == 0.0


def test_pyrodigal_attrs_and_6frame_fallback():
    """验证 Pyrodigal 编码属性映射与 6-frame 最优编码框兜底逻辑（含正反链及熵异常防呆）。"""
    fake_gene = SimpleNamespace(
        cscore=42.5,
        score=51.0,
        rscore=6.2,
        sscore=4.1,
        tscore=2.5,
        partial_begin=True,
        partial_end=False,
        rbs_motif="GGAGG",
        start_type="ATG",
    )
    attrs = encode_pyrodigal_gene_attrs(fake_gene, aa_len=180, is_fallback=0.0)
    assert attrs.shape == (PYRODIGAL_ORF_ATTR_DIM,)
    assert np.all(np.isfinite(attrs))
    assert attrs[7] == 1.0  # has_rbs_motif
    assert attrs[8] == 1.0  # is_atg_start
    assert attrs[9] == 0.0  # not fallback

    extra = encode_orf_peptide_extra("ACDEFGHIKLMNPQRSTVWY" * 4, attrs)
    assert extra.shape == (STAGE1_ORF_EXTRA_DIM,) == (87,)
    assert np.all(np.isfinite(extra))

    # 6-frame 最长无终止读框在反链同样检出且保持等比覆盖率
    fwd_dna = "TAA" + _synth_no_sd_coding_dna(codons_n=90, seed=11) + "TGA"
    rev_dna = _reverse_complement(fwd_dna)
    best_f = find_best_6frame_orf(fwd_dna, min_aa=20)
    best_r = find_best_6frame_orf(rev_dna, min_aa=20)
    assert best_f is not None and best_r is not None
    assert len(best_f[3]) >= 80 and best_f[2] == 1
    assert len(best_r[3]) >= 80 and best_r[2] == -1
    frac_f = compute_best_6frame_coding_fraction(fwd_dna)
    frac_r = compute_best_6frame_coding_fraction(rev_dna)
    assert frac_f > 0.85 and abs(frac_f - frac_r) < 1e-4


def test_window_features_stage1_preserves_v4_prefix_and_rescues_short_fragments():
    """验证 Stage 1 特征前 185 维与 V4 完全对齐，且在短片段退化场景下补充二三肽、Pyrodigal 属性与 6-frame 兜底。"""
    assert len(FEATURE_NAMES) == 185
    assert len(FEATURE_NAMES_STAGE1) == 185 + STAGE1_WINDOW_EXTRA_DIM
    assert len(set(FEATURE_NAMES_STAGE1)) == len(FEATURE_NAMES_STAGE1)
    assert get_feature_names("v4") == FEATURE_NAMES
    assert get_feature_names("stage1") == FEATURE_NAMES_STAGE1

    seq = _synth_orf_rich_dna(5200, seed=3)
    res_v4 = extract_contig_windows("C1", seq, win_size=5000, step_size=2500, feature_profile="v4")
    res_s1 = extract_contig_windows("C1", seq, win_size=5000, step_size=2500, feature_profile="stage1")
    assert res_v4["features"].shape == (2, 185)
    assert res_s1["features"].shape == (2, 185 + STAGE1_WINDOW_EXTRA_DIM)
    assert np.allclose(res_s1["features"][:, :185], res_v4["features"], atol=1e-5)
    assert np.all(np.isfinite(res_s1["features"]))
    # Pyrodigal 正常基因存在的长窗中，二肽之和、Pyrodigal cscore 与三肽熵为正
    assert res_s1["features"][0, 185:185 + 49].sum() > 0.99
    assert float(res_s1["features"][0, FEATURE_NAMES_STAGE1.index("pep_ct_entropy")]) > 0.1
    assert float(res_s1["features"][0, FEATURE_NAMES_STAGE1.index("pyro_mean_cscore")]) != 0.0

    # 90bp 无 Pyrodigal 完整预测（len < 100bp）短片段：V4 全零，Stage 1 激活 6-frame 兜底并产出二三肽
    tiny_coding = _synth_no_sd_coding_dna(codons_n=30, seed=5)
    short_v4 = extract_contig_windows("SHORT", tiny_coding, win_size=5000, step_size=2500, feature_profile="v4")
    short_s1 = extract_contig_windows("SHORT", tiny_coding, win_size=5000, step_size=2500, feature_profile="stage1")
    aa_s = FEATURE_NAMES.index("aa_A")
    aa_e = aa_s + 22
    assert float(short_v4["features"][0, aa_s:aa_e].sum()) == 0.0
    assert float(short_s1["features"][0, aa_s:aa_e].sum()) > 0.5  # 兜底补充 aa_22
    idx_fb = FEATURE_NAMES_STAGE1.index("pyro_fallback_6frame_frac")
    assert float(short_s1["features"][0, idx_fb]) == 1.0


def test_orf_tokens_stage1_cache_isolation_and_subbin_compatibility(tmp_path: Path):
    """验证 Stage 1 ORF Token 维度 (117d)、前 30 维向后对齐 SubBin、6-frame 兜底非空以及缓存隔离。"""
    assert ORF_FEAT_DIM == 30
    assert STAGE1_ORF_FEAT_DIM == 117
    assert get_orf_feat_dim("v4") == 30
    assert get_orf_feat_dim("stage1") == 117

    seq = _synth_orf_rich_dna(5200, seed=9)
    tk_v4, cn_v4 = extract_contig_orf_tokens(seq, [0, 200], [5000, 5200], feature_profile="v4")
    tk_s1, cn_s1 = extract_contig_orf_tokens(seq, [0, 200], [5000, 5200], feature_profile="stage1")
    assert tk_v4.shape == (2, MAX_ORFS_PER_WIN, 30)
    assert tk_s1.shape == (2, MAX_ORFS_PER_WIN, 117)
    assert np.array_equal(cn_v4, cn_s1)
    assert np.allclose(tk_s1[:, :, :30], tk_v4, atol=1e-5)

    # 短编码片段 6-frame 兜底避免 OrfStream 退化为 empty_emb (counts == 0)
    tiny_coding = _synth_no_sd_coding_dna(codons_n=30, seed=13)
    tk_t4, cn_t4 = extract_contig_orf_tokens(tiny_coding, [0], [len(tiny_coding)], feature_profile="v4")
    tk_ts1, cn_ts1 = extract_contig_orf_tokens(tiny_coding, [0], [len(tiny_coding)], feature_profile="stage1")
    assert int(cn_t4[0]) == 0
    assert int(cn_ts1[0]) == 1
    assert float(tk_ts1[0, 0, 39]) == 1.0  # is_fallback_6frame flag

    # OrfTransformer 与 SubBin 25-bin 投影兼容
    orf_net = build_orf_transformer(orf_feat_dim=STAGE1_ORF_FEAT_DIM)
    out = orf_net(torch.from_numpy(tk_s1), torch.from_numpy(cn_s1))
    assert out.shape == (2,)
    bins = project_orf_to_25bins(tk_s1, cn_s1, np.ones((2, MAX_ORFS_PER_WIN), dtype=np.float32))
    assert bins.shape == (2, SUB_BINS, 10)

    # 缓存文件隔离：_load_or_extract_part("stage1") 写入 _orf_tokens_stage1.npz
    feat_dir = tmp_path / "feat"
    feat_dir.mkdir(parents=True, exist_ok=True)
    fa = feat_dir / "train_demo.fna"
    fa.write_text(f">C1\n{seq}\n", encoding="utf-8")
    np.savez_compressed(
        feat_dir / "train_demo.npz",
        features=extract_contig_windows("C1", seq, feature_profile="stage1")["features"],
        labels=np.array([1, 1], dtype=np.int8),
        overlap=np.array([1.0, 1.0], dtype=np.float32),
        sub_mask=np.ones((2, SUB_BINS), dtype=np.float32),
        contig_ids=np.array(["C1", "C1"]),
        starts=np.array([0, 200], dtype=np.int64),
        ends=np.array([5000, 5200], dtype=np.int64),
        source=np.array([0, 0], dtype=np.int8),
    )
    _, tk_cached, _ = _load_or_extract_part(
        feat_dir, feat_dir, "train", "demo", feat_dir, workers=1, fasta_override=fa, feature_profile="stage1",
    )
    assert (feat_dir / "train_demo_orf_tokens_stage1.npz").exists()
    assert not (feat_dir / "train_demo_orf_tokens_v2.npz").exists()
    assert tk_cached.shape == (2, MAX_ORFS_PER_WIN, STAGE1_ORF_FEAT_DIM)


def test_phrog_teacher_backfill_high_specificity(tmp_path: Path):
    """验证 PHROGs 注释映射严格区分高特异结构域（head/connector/tail/lysis）与泛化假阳风险域（unknown function）。"""
    tsv = tmp_path / "phrog_annot_v4.tsv"
    with open(tsv, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, delimiter="\t")
        w.writerow(["phrog", "color", "annot", "category"])
        w.writerow(["10", "#3e83f6", "major head protein", "head and packaging"])
        w.writerow(["14", "#07e9a2", "minor tail protein", "tail"])
        w.writerow(["99", "#cccccc", "hypothetical protein", "unknown function"])
        w.writerow(["205", "#999999", "IS3 family transposase", "other"])

    annots = load_phrog_annotations(tsv)
    assert classify_phrog_category("phrog_10", annots) == "phrog_hallmark"
    assert classify_phrog_category("phrog_14", annots) == "phrog_tail_lysis"
    assert classify_phrog_category("phrog_99", annots) == "phrog_unknown"
    assert classify_phrog_category("phrog_205", annots) == "transposase"

    # 准备 2 个窗口：窗 0 有未知噬菌体衣壳+尾蛋白（DIAMOND 全零），窗 1 为仅有 unknown function 的宿主负样本
    seq_pos = _synth_orf_rich_dna(2600, seed=21)
    seq_neg = _synth_orf_rich_dna(2600, seed=22)
    fa = tmp_path / "train_demo.fna"
    fa.write_text(f">POS_CONTIG\n{seq_pos}\n>NEG_CONTIG\n{seq_neg}\n", encoding="utf-8")

    in_feat_dir = tmp_path / "in_feat"
    out_sem_dir = tmp_path / "out_sem"
    in_feat_dir.mkdir(parents=True, exist_ok=True)
    out_sem_dir.mkdir(parents=True, exist_ok=True)

    np.savez_compressed(
        in_feat_dir / "train_demo.npz",
        features=np.zeros((2, 185), dtype=np.float32),
        labels=np.array([1, 0], dtype=np.int8),
        overlap=np.array([1.0, 0.0], dtype=np.float32),
        sub_mask=np.zeros((2, SUB_BINS), dtype=np.float32),
        contig_ids=np.array(["POS_CONTIG", "NEG_CONTIG"]),
        starts=np.array([0, 0], dtype=np.int64),
        ends=np.array([2600, 2600], dtype=np.int64),
        source=np.array([0, 0], dtype=np.int8),
    )
    np.savez_compressed(
        in_feat_dir / "train_demo_semantic.npz",
        sem_targets=np.zeros((2, 4), dtype=np.float32),
        sem_valid_mask=np.ones(2, dtype=np.float32),
        hallmark_counts=np.zeros(2, dtype=np.int16),
        transposase_counts=np.zeros(2, dtype=np.int16),
        clean_labels=np.array([1, 0], dtype=np.int8),
    )

    def _mock_mmseqs_hits(orf_records):
        hits = {}
        for oid, _ in orf_records:
            if oid.startswith("POS_CONTIG__orf0"):
                hits[oid] = (120.0, "phrog_10", 0.9, 1e-30)
            elif oid.startswith("POS_CONTIG__orf1"):
                hits[oid] = (95.0, "phrog_14", 0.8, 1e-20)
            elif oid.startswith("NEG_CONTIG__orf0"):
                hits[oid] = (80.0, "phrog_99", 0.9, 1e-18)
        return hits

    summary = enrich_semantic_targets_with_phrog(
        part_specs=[("demo", in_feat_dir / "train_demo.npz", fa, in_feat_dir / "train_demo_semantic.npz")],
        out_dir=out_sem_dir,
        annot_tsv=tsv,
        hit_fetcher=_mock_mmseqs_hits,
        workers=1,
    )
    assert summary["demo"]["backfilled_hallmark_windows"] == 1
    with np.load(out_sem_dir / "train_demo_semantic.npz", allow_pickle=False) as d:
        sem = d["sem_targets"]
        # 窗 0 获得 hallmark 与 tail_lysis 回填，且仅由 unknown function 命中的负样本窗 1 不被污染
        assert float(sem[0, 0]) >= 0.60
        assert float(sem[0, 3]) >= 0.55
        assert float(sem[1, 0]) == 0.0
        assert float(sem[1, 3]) == 0.0
        assert int(d["clean_labels"][1]) == 0


def test_student_v4_and_scanner_support_both_legacy_and_stage1_models(tmp_path: Path):
    """验证 StudentV4、SubBin 投影与 GenomeScanner 同时支持 Stage 1 扩展维度与既有 V4.2 模型维度。"""
    # 1) Stage 1 模型前向/反向与扫描闭环
    feat_dim_s1 = len(FEATURE_NAMES_STAGE1)
    model_s1 = build_distilled_student_v4(
        feat_dim_s1,
        np.zeros(feat_dim_s1, dtype=np.float32),
        np.ones(feat_dim_s1, dtype=np.float32),
        dna_channels=32,
        orf_d_model=32,
        orf_nhead=2,
        orf_num_layers=1,
        fusion_dim=64,
        sem_dim=SEMANTIC_DIM,
        orf_feat_dim=STAGE1_ORF_FEAT_DIM,
    )
    dna = torch.randn(2, 4, 500)
    tab = torch.randn(2, feat_dim_s1)
    tk = torch.randn(2, MAX_ORFS_PER_WIN, STAGE1_ORF_FEAT_DIM)
    cn = torch.tensor([3, 1], dtype=torch.long)
    out = model_s1(dna, tab, lengths=torch.tensor([500, 300]), orf_tokens=tk, orf_counts=cn, return_aux=True)
    assert out["win_logit"].shape == (2,)
    out["win_logit"].sum().backward()
    scores_orf = extract_per_orf_viral_scores(model_s1, tk.detach().numpy(), cn.numpy(), torch.device("cpu"))
    assert scores_orf.shape == (2, MAX_ORFS_PER_WIN)

    s1_dir = tmp_path / "model_s1"
    s1_dir.mkdir(parents=True, exist_ok=True)
    torch.save(model_s1.state_dict(), s1_dir / "student_v4.pt")
    (s1_dir / "student_v4_meta.json").write_text(
        json.dumps(
            {
                "model_version": "v4",
                "feature_profile": "stage1",
                "feat_dim": feat_dim_s1,
                "orf_feat_dim": STAGE1_ORF_FEAT_DIM,
                "max_len": 1200,
                "dna_channels": 32,
                "orf_d_model": 32,
                "orf_nhead": 2,
                "orf_num_layers": 1,
                "fusion_dim": 64,
                "sem_dim": SEMANTIC_DIM,
            }
        ),
        encoding="utf-8",
    )
    scanner_s1 = GenomeScanner.from_model_dir(s1_dir, device="cpu", workers=1)
    assert scanner_s1.feature_profile == "stage1"
    assert scanner_s1.orf_feat_dim == STAGE1_ORF_FEAT_DIM
    res_s1 = scanner_s1.scan_sequences({"S1_CONTIG": _synth_orf_rich_dna(1200, seed=31)})
    assert res_s1.total_windows == 1

    # 2) Legacy V4.2 元数据缺省 feature_profile/orf_feat_dim 时自动回落为 v4 / 30d
    model_v4 = build_distilled_student_v4(
        185,
        np.zeros(185, dtype=np.float32),
        np.ones(185, dtype=np.float32),
        dna_channels=32,
        orf_d_model=32,
        orf_nhead=2,
        orf_num_layers=1,
        fusion_dim=64,
        sem_dim=SEMANTIC_DIM,
    )
    legacy_dir = tmp_path / "model_v4_legacy"
    legacy_dir.mkdir(parents=True, exist_ok=True)
    torch.save(model_v4.state_dict(), legacy_dir / "student_v4.pt")
    (legacy_dir / "student_v4_meta.json").write_text(
        json.dumps(
            {
                "model_version": "v4",
                "feat_dim": 185,
                "max_len": 1200,
                "dna_channels": 32,
                "orf_d_model": 32,
                "orf_nhead": 2,
                "orf_num_layers": 1,
                "fusion_dim": 64,
                "sem_dim": SEMANTIC_DIM,
            }
        ),
        encoding="utf-8",
    )
    scanner_legacy = GenomeScanner.from_model_dir(legacy_dir, device="cpu", workers=1)
    assert scanner_legacy.feature_profile == "v4"
    assert scanner_legacy.orf_feat_dim == 30
    res_leg = scanner_legacy.scan_sequences({"LEGACY_CONTIG": _synth_orf_rich_dna(1200, seed=32)})
    assert res_leg.total_windows == 1


def test_expert_a_xgb_handles_stage1_256_dim_importance(tmp_path: Path):
    """验证 Expert A 在 256 维 Stage 1 特征上记录完整特征名 Top25 且不触发索引越界。"""
    feat_dim = len(FEATURE_NAMES_STAGE1)
    rng = np.random.default_rng(123)
    bench_dir = tmp_path / "bench"
    tr_feat = tmp_path / "tr_feat"
    ev_feat = tmp_path / "ev_feat"
    out_dir = tmp_path / "out_a"
    for d in (bench_dir, tr_feat, ev_feat):
        d.mkdir(parents=True, exist_ok=True)

    # 极简 truth / contigs TSV（供 val/test eval）
    fa_val = bench_dir / "val_chimeras.fna"
    fa_te = bench_dir / "test_chimeras.fna"
    fa_val.write_text(">VC1\n" + "A" * 5000 + "\n", encoding="utf-8")
    fa_te.write_text(">TC1\n" + "A" * 5000 + "\n", encoding="utf-8")

    for sp, cid in (("val", "VC1"), ("test", "TC1")):
        t_tsv = bench_dir / f"{sp}_chimeras_truth.tsv"
        c_tsv = bench_dir / f"{sp}_chimeras_contigs.tsv"
        t_tsv.write_text("contig_id\tstart_bp\tend_bp\tphage_acc\tphage_tax\tscenarios\n", encoding="utf-8")
        c_tsv.write_text(f"contig_id\tcontig_len_bp\tscenario\ttruth_count\n{cid}\t5000\tpure_negative_host\t0\n", encoding="utf-8")
        wt_tsv = bench_dir / f"{sp}_windows_truth.tsv"
        wt_tsv.write_text(
            "window_id\tlabel\tsource_accession\tsource_category\ttax_group\twin_len\tstart_bp\tend_bp\tstrand\tgc_percent\n"
            + "\n".join(
                f"{sp}_W{i}\t{i % 2}\tACC{i}\t{'phage_refseq' if i % 2 else 'bacterial_chromosome'}\tCaudoviricetes\t5000\t0\t5000\t1\t50.0"
                for i in range(6)
            )
            + "\n",
            encoding="utf-8",
        )

    manifest = {
        "splits": {
            sp: {
                "windows": {"truth_tsv": str(bench_dir / f"{sp}_windows_truth.tsv")},
                "chimeras": {
                    "truth_tsv": str(bench_dir / f"{sp}_chimeras_truth.tsv"),
                    "contigs_tsv": str(bench_dir / f"{sp}_chimeras_contigs.tsv"),
                    "fasta": str(bench_dir / f"{sp}_chimeras.fna"),
                },
            }
            for sp in ("val", "test")
        }
    }
    (bench_dir / "benchmark_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    def _make_split(path: Path, n: int, cid_prefix: str, is_chim: bool = False):
        x = rng.normal(size=(n, feat_dim)).astype(np.float32)
        y = np.array([i % 2 for i in range(n)], dtype=np.int8)
        # 在新增 Conjoint Triad 最后一维注入强区分信号，促使 XGBoost 选中 >= 185 索引列
        x[:, -1] = np.where(y == 1, 5.0, -5.0)
        cids = np.array([f"{cid_prefix}_{i}" if not is_chim else cid_prefix for i in range(n)])
        np.savez_compressed(
            path,
            feature_names=np.asarray(FEATURE_NAMES_STAGE1),
            features=x,
            labels=y,
            overlap=np.where(y == 1, 1.0, 0.0).astype(np.float32),
            sub_mask=np.zeros((n, SUB_BINS), dtype=np.float32),
            contig_ids=cids,
            starts=np.zeros(n, dtype=np.int64),
            ends=np.full(n, 5000, dtype=np.int64),
            source=np.zeros(n, dtype=np.int8),
        )

    _make_split(tr_feat / "train_windows.npz", 40, "TRW")
    for sp, cid in (("val", "VC1"), ("test", "TC1")):
        _make_split(ev_feat / f"{sp}_windows.npz", 6, f"{sp}_W")
        _make_split(ev_feat / f"{sp}_chimeras.npz", 2, cid, is_chim=True)

    rep = train_expert_a(
        tr_feat, ev_feat, bench_dir, out_dir, n_estimators=20, early_stopping_rounds=10, train_parts=("windows",), n_jobs=2,
    )
    top_names = [name for name, _ in rep["top25_gain_features"]]
    assert any(name in FEATURE_NAMES_STAGE1[185:] for name in top_names)

