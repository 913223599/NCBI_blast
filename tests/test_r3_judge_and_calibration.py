# -*- coding: utf-8 -*-
"""R3 操纵子宏观门控、窗级完整度监督与零泄露 Logit 校准单元测试。"""
from __future__ import annotations

import numpy as np
import torch

from src.phage_discovery.student.judge_calibration import (
    apply_blended_logit_calibration,
    apply_logit_calibration,
    blend_with_stage1_2_cross_modal,
    fit_logit_blend_and_calibrator,
    fit_logit_calibrator_on_val,
    probs_to_logits,
)
from src.phage_discovery.student.orf_functional_judge import (
    CTX_WIN_ORFS,
    MAX_JUDGE_AA_LEN,
    NUM_JUDGE_CLASSES,
    ORF_JUDGE_STAT_DIM,
    build_orf_functional_judge,
    predict_contig_orfs_with_judge,
)


def test_r3_judge_macro_gate_padding_invariance_and_win_core_head():
    rng = np.random.default_rng(7)
    stat_mean = np.zeros(ORF_JUDGE_STAT_DIM, dtype=np.float32)
    stat_std = np.ones(ORF_JUDGE_STAT_DIM, dtype=np.float32)
    model = build_orf_functional_judge(
        stat_mean,
        stat_std,
        use_aa_seq=True,
        arch="r3",
        aa_mask_prob=0.1,
    )
    model.eval()

    bsz, l_seq = 2, CTX_WIN_ORFS
    aa_ids = torch.randint(1, 21, (bsz, l_seq, MAX_JUDGE_AA_LEN), dtype=torch.long)
    aa_lens = torch.randint(30, 260, (bsz, l_seq), dtype=torch.long)
    stat = torch.tensor(rng.normal(0.0, 0.5, size=(bsz, l_seq, ORF_JUDGE_STAT_DIM)), dtype=torch.float32)
    vc = torch.tensor([9, 14], dtype=torch.long)

    f1, p1, d1, w1 = model(aa_ids, aa_lens, stat, vc, return_seq_distill=True, return_win_core=True)
    assert f1.shape == (bsz, l_seq, NUM_JUDGE_CLASSES)
    assert p1.shape == (bsz, l_seq)
    assert d1.shape == (bsz, l_seq, 1024)
    assert w1.shape == (bsz,)
    assert torch.isfinite(f1).all() and torch.isfinite(p1).all() and torch.isfinite(w1).all()

    # 篡改无效槽位不应影响前 9 个有效 ORF 输出和 win_core 预测
    aa_ids2 = aa_ids.clone()
    stat2 = stat.clone()
    aa_ids2[0, 9:, :] = 19
    stat2[0, 9:, :] = 8.0
    f2, p2, _, w2 = model(aa_ids2, aa_lens, stat2, vc, return_seq_distill=True, return_win_core=True)
    assert torch.allclose(f1[0, :9], f2[0, :9], atol=1e-5)
    assert torch.allclose(p1[0, :9], p2[0, :9], atol=1e-5)
    assert torch.allclose(w1[0], w2[0], atol=1e-5)

    # 梯度反向传播完整畅通
    model.train()
    ft, pt, dt, wt = model(aa_ids, aa_lens, stat, vc, return_seq_distill=True, return_win_core=True)
    loss = ft.sum() + pt.sum() + 0.1 * dt.sum() + wt.sum()
    loss.backward()
    assert model.win_core_head[0].weight.grad is not None
    assert model.macro_film_scale.weight.grad is not None


def test_predict_contig_orfs_with_judge_returns_logits():
    stat_mean = np.zeros(ORF_JUDGE_STAT_DIM, dtype=np.float32)
    stat_std = np.ones(ORF_JUDGE_STAT_DIM, dtype=np.float32)
    model = build_orf_functional_judge(stat_mean, stat_std, use_aa_seq=False, arch="r3")
    orfs = [(i * 500, i * 500 + 420, 1, "MKVLVALAV" * 10) for i in range(40)]
    out = predict_contig_orfs_with_judge(model, orfs, device="cpu", batch_size=8, return_logits=True)
    assert out["phage_logits"].shape == (40,)
    assert out["func10_logits"].shape == (40, NUM_JUDGE_CLASSES)
    assert np.isfinite(out["phage_logits"]).all() and np.isfinite(out["func10_logits"]).all()


def test_judge_calibration_rescues_sparse_threshold_and_cross_modal_keeps_p9():
    rng = np.random.default_rng(123)
    n_val = 400
    n_cls = NUM_JUDGE_CLASSES
    yt = np.zeros((n_val, n_cls), dtype=np.float32)
    # 模拟类 8 极稀疏（正样本整体 logit 被系统性压偏到 -1.2 以下，导致 0.5 阈值全归零）
    yt[:25, 8] = 1.0
    yt[20:100, 0] = 1.0
    km = np.ones(n_val, dtype=np.float32)

    val_stat_f = rng.normal(-2.5, 0.4, size=(n_val, n_cls)).astype(np.float32)
    val_seq_f = rng.normal(-2.5, 0.4, size=(n_val, n_cls)).astype(np.float32)
    val_stat_f[:25, 8] = rng.normal(-0.8, 0.25, size=25)
    val_seq_f[:25, 8] = rng.normal(-0.6, 0.25, size=25)
    val_stat_f[20:100, 0] = rng.normal(1.2, 0.3, size=80)
    val_seq_f[20:100, 0] = rng.normal(1.6, 0.3, size=80)

    ph_t = np.zeros(n_val, dtype=np.float32)
    ph_t[:150] = 1.0
    val_stat_p = rng.normal(-1.0, 0.5, size=n_val).astype(np.float32)
    val_seq_p = rng.normal(-1.0, 0.5, size=n_val).astype(np.float32)
    val_stat_p[:150] = rng.normal(1.3, 0.4, size=150)
    val_seq_p[:150] = rng.normal(1.5, 0.4, size=150)

    cal = fit_logit_blend_and_calibrator(
        val_stat_f,
        val_seq_f,
        yt,
        km,
        val_stat_p,
        val_seq_p,
        ph_t,
    )
    assert cal["val_func_f1_after"][8] > 0.70
    assert cal["val_func_f1_before"][8] == 0.0

    # 独立 apply 验证
    pf_cal, pp_cal = apply_blended_logit_calibration(val_stat_f, val_seq_f, val_stat_p, val_seq_p, cal)
    assert pf_cal.shape == (n_val, n_cls) and pp_cal.shape == (n_val,)
    assert np.mean(pf_cal[:25, 8] >= 0.5) > 0.8

    # 验证单模型直接校准也保持接口可用
    cal_single = fit_logit_calibrator_on_val(val_seq_f, yt, km, val_seq_p, ph_t)
    pf_s, _ = apply_logit_calibration(val_seq_f, val_seq_p, cal_single)
    assert np.mean(pf_s[:25, 8] >= 0.5) > 0.8

    # 验证跨模态 DNA Stage1.2 协同不会稀释 P9
    s12_f9 = np.full((10, 9), 0.1, dtype=np.float32)
    s12_ph = np.full(10, 0.9, dtype=np.float32)
    jf10 = np.full((10, 10), 0.2, dtype=np.float32)
    jf10[:, 9] = 0.88
    jph = np.full(10, 0.3, dtype=np.float32)
    fused_f10, fused_ph = blend_with_stage1_2_cross_modal(jf10, jph, s12_f9, s12_ph, s12_phage_weight=0.25)
    assert np.allclose(fused_f10[:, 9], 0.88, atol=1e-4)
    assert np.all((fused_ph > 0.3) & (fused_ph < 0.9))
    assert probs_to_logits(np.array([0.5], dtype=np.float32))[0] == 0.0

