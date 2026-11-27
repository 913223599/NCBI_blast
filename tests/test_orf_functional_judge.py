# -*- coding: utf-8 -*-
"""
轻量 ORF 蛋白序列 + 邻域上下文功能精判模块 (OrfFunctionalJudge) 的先导单元测试。
"""
from __future__ import annotations

import numpy as np
import torch

from src.phage_discovery.student.orf_functional_judge import (
    CTX_WIN_ORFS,
    JUDGE_CLASS_NAMES,
    MAX_JUDGE_AA_LEN,
    NUM_JUDGE_CLASSES,
    ORF_JUDGE_STAT_DIM,
    build_orf_functional_judge,
    encode_aa_tokens_batch,
    encode_contig_orf_stat_features,
    predict_contig_orfs_with_judge,
    slice_contig_orf_windows,
)
import pytest

pytestmark = pytest.mark.ml


def test_judge_constants_and_aa_encoding():
    assert NUM_JUDGE_CLASSES == 10
    assert JUDGE_CLASS_NAMES[-1] == "host_defense_virulence"

    seqs = ["MKVLWAALLVTFLAGCQAKVEQAVETEPEPELRQQTEWQSGQRWELALGRFWDYLRWVQTLSEQVQEELLSSQVTQELRA", "AXB*Z", ""]
    ids, lens = encode_aa_tokens_batch(seqs, max_len=64)
    assert ids.shape == (3, 64)
    assert ids.dtype == np.uint8
    assert lens.tolist() == [64, 5, 1]
    assert int(ids[0, 0]) > 0
    assert int(ids[1, 1]) == 21  # X maps to <unk>=21
    assert int(ids[2, 0]) == 0


def test_contig_stat_features_and_window_slicing():
    orfs = [
        (100, 700, 1, "M" + "ACDEFGHIKLMNPQRSTVWY" * 9),
        (750, 1400, 1, "M" + "AVILMFYW" * 20),
        (1500, 2100, -1, "M" + "DEKRH" * 25),
    ]
    feats = encode_contig_orf_stat_features(orfs)
    assert feats.shape == (3, ORF_JUDGE_STAT_DIM)
    assert feats.dtype == np.float32
    assert np.all(np.isfinite(feats))

    # 校验切片 padding 与掩码边界
    windows = slice_contig_orf_windows(orfs, ctx_len=CTX_WIN_ORFS, stride=16)
    assert len(windows) == 1
    w = windows[0]
    assert w["valid_count"] == 3
    assert w["aa_ids"].shape == (CTX_WIN_ORFS, MAX_JUDGE_AA_LEN)
    assert w["stat_feats"].shape == (CTX_WIN_ORFS, ORF_JUDGE_STAT_DIM)


def test_judge_model_forward_padding_invariance_and_ablation_mode():
    torch.manual_seed(7)
    stat_mean = np.zeros(ORF_JUDGE_STAT_DIM, dtype=np.float32)
    stat_std = np.ones(ORF_JUDGE_STAT_DIM, dtype=np.float32)

    for use_aa_seq in (True, False):
        model = build_orf_functional_judge(
            stat_mean=stat_mean,
            stat_std=stat_std,
            use_aa_seq=use_aa_seq,
        )
        model.eval()
        aa_ids = torch.zeros((2, 8, 64), dtype=torch.long)
        aa_ids[:, :3, :10] = 3
        aa_lens = torch.ones((2, 8), dtype=torch.long) * 10
        stat_feats = torch.randn((2, 8, ORF_JUDGE_STAT_DIM), dtype=torch.float32)
        valid_counts = torch.tensor([3, 3], dtype=torch.long)

        # 修改第二条样本被 mask 的第 5..7 槽位输入，验证第 0..2 有效槽位输出完全不受影响
        stat_feats[1, 4:, :] += 50.0
        aa_ids[1, 4:, :] = 12
        stat_feats[1, :3, :] = stat_feats[0, :3, :]

        with torch.no_grad():
            f_logits, p_logits = model(aa_ids, aa_lens, stat_feats, valid_counts)
        assert f_logits.shape == (2, 8, NUM_JUDGE_CLASSES)
        assert p_logits.shape == (2, 8)
        assert torch.allclose(f_logits[0, :3], f_logits[1, :3], atol=1e-5)
        assert torch.allclose(p_logits[0, :3], p_logits[1, :3], atol=1e-5)


def test_predict_contig_orfs_with_judge_handles_long_contig():
    stat_mean = np.zeros(ORF_JUDGE_STAT_DIM, dtype=np.float32)
    stat_std = np.ones(ORF_JUDGE_STAT_DIM, dtype=np.float32)
    model = build_orf_functional_judge(stat_mean=stat_mean, stat_std=stat_std, use_aa_seq=True)
    orfs = [
        (i * 800 + 1, i * 800 + 601, 1 if i % 2 == 0 else -1, "M" + "ACDEFGHIKLMNPQRSTVWY" * 8)
        for i in range(45)
    ]
    res = predict_contig_orfs_with_judge(model, orfs, device="cpu", ctx_len=16, stride=8, batch_size=8)
    assert res["phage_probs"].shape == (45,)
    assert res["func10_probs"].shape == (45, NUM_JUDGE_CLASSES)
    assert np.all((res["phage_probs"] >= 0.0) & (res["phage_probs"] <= 1.0))
    assert np.all((res["func10_probs"] >= 0.0) & (res["func10_probs"] <= 1.0))


def test_r1_judge_padding_invariance_and_eval_determinism():
    """R1 架构：校验相对操纵子拓扑偏置、序列自注意力与先功能后鉴伪耦合头满足严格 Padding 不变性与 eval 确定性。"""
    torch.manual_seed(11)
    stat_mean = np.zeros(ORF_JUDGE_STAT_DIM, dtype=np.float32)
    stat_std = np.ones(ORF_JUDGE_STAT_DIM, dtype=np.float32)

    for use_aa_seq in (True, False):
        model = build_orf_functional_judge(
            stat_mean=stat_mean,
            stat_std=stat_std,
            use_aa_seq=use_aa_seq,
            arch="r1",
            aa_mask_prob=0.15,
        )
        model.eval()
        aa_ids = torch.zeros((2, 10, 64), dtype=torch.long)
        aa_ids[:, :4, :16] = 4
        aa_lens = torch.ones((2, 10), dtype=torch.long) * 16
        stat_feats = torch.randn((2, 10, ORF_JUDGE_STAT_DIM), dtype=torch.float32)
        stat_feats[:, :4, 98] = 0.5
        stat_feats[:, :4, 99] = torch.tensor([1.0, 1.0, -1.0, 1.0])
        stat_feats[:, :4, 100:102] = 0.2
        valid_counts = torch.tensor([4, 4], dtype=torch.long)

        # 污染无效 padding 槽位 5..9
        stat_feats[1, :4, :] = stat_feats[0, :4, :]
        aa_ids[1, :4, :] = aa_ids[0, :4, :]
        stat_feats[1, 5:, :] += 80.0
        aa_ids[1, 5:, :] = 15

        with torch.no_grad():
            f1, p1 = model(aa_ids, aa_lens, stat_feats, valid_counts)
            f2, p2 = model(aa_ids, aa_lens, stat_feats, valid_counts)

        assert f1.shape == (2, 10, NUM_JUDGE_CLASSES)
        assert p1.shape == (2, 10)
        assert torch.allclose(f1[0, :4], f1[1, :4], atol=1e-5)
        assert torch.allclose(p1[0, :4], p1[1, :4], atol=1e-5)
        assert torch.allclose(f1, f2, atol=1e-6)
        assert torch.allclose(p1, p2, atol=1e-6)


def test_r1_judge_backward_and_contig_predict():
    """R1 架构：校验 train 模式随机掩码、反传梯度完整与长 contig 推理接口。"""
    torch.manual_seed(23)
    stat_mean = np.zeros(ORF_JUDGE_STAT_DIM, dtype=np.float32)
    stat_std = np.ones(ORF_JUDGE_STAT_DIM, dtype=np.float32)
    model = build_orf_functional_judge(
        stat_mean=stat_mean,
        stat_std=stat_std,
        use_aa_seq=True,
        arch="r1",
        aa_mask_prob=0.15,
    )
    model.train()
    aa_ids = torch.randint(1, 20, (2, 6, 48), dtype=torch.long)
    aa_lens = torch.full((2, 6), 40, dtype=torch.long)
    stat_feats = torch.randn((2, 6, ORF_JUDGE_STAT_DIM), dtype=torch.float32)
    stat_feats[:, :, 99] = 1.0
    valid_counts = torch.tensor([6, 4], dtype=torch.long)

    f_log, p_log = model(aa_ids, aa_lens, stat_feats, valid_counts)
    loss = f_log.square().mean() + p_log.square().mean()
    loss.backward()
    has_grad = [p.grad is not None and torch.isfinite(p.grad).all() for p in model.parameters() if p.requires_grad]
    assert all(has_grad)

    model.eval()
    orfs = [
        (i * 650 + 1, i * 650 + 580, 1 if i < 20 else -1, "M" + "ACDEFGHIKLMNPQRSTVWY" * 9)
        for i in range(40)
    ]
    res = predict_contig_orfs_with_judge(model, orfs, device="cpu", ctx_len=16, stride=8, batch_size=8)
    assert res["phage_probs"].shape == (40,)
    assert res["func10_probs"].shape == (40, NUM_JUDGE_CLASSES)
    assert np.all(np.isfinite(res["phage_probs"]))
    assert np.all(np.isfinite(res["func10_probs"]))
