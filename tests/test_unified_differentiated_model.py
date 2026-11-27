# -*- coding: utf-8 -*-
"""统一分化架构 (arch='unified') 与 UnifiedPhageModel 按需条件激活单元测试。"""
from __future__ import annotations

import numpy as np
import torch

from src.phage_discovery.benchmark.metrics import PredictedRegion, WindowPrediction
from src.phage_discovery.inference.unified_model import UnifiedPhageModel
from src.phage_discovery.student.orf_functional_judge import (
    CTX_WIN_ORFS,
    MAX_JUDGE_AA_LEN,
    NUM_JUDGE_CLASSES,
    ORF_JUDGE_STAT_DIM,
    build_orf_functional_judge,
    predict_contig_orfs_with_judge,
)
import pytest

pytestmark = pytest.mark.ml


def test_unified_judge_differentiated_experts_on_demand_and_grad_firewall():
    rng = np.random.default_rng(11)
    stat_mean = np.zeros(ORF_JUDGE_STAT_DIM, dtype=np.float32)
    stat_std = np.ones(ORF_JUDGE_STAT_DIM, dtype=np.float32)
    model = build_orf_functional_judge(
        stat_mean,
        stat_std,
        use_aa_seq=True,
        arch="unified",
        aa_mask_prob=0.1,
    )
    model.eval()

    bsz, l_seq = 2, CTX_WIN_ORFS
    aa_ids = torch.randint(1, 21, (bsz, l_seq, MAX_JUDGE_AA_LEN), dtype=torch.long)
    aa_lens = torch.randint(30, 200, (bsz, l_seq), dtype=torch.long)
    stat = torch.tensor(rng.normal(0.0, 0.5, size=(bsz, l_seq, ORF_JUDGE_STAT_DIM)), dtype=torch.float32)
    vc = torch.tensor([7, 11], dtype=torch.long)

    # 1. 按需仅激活完整度专家 intact
    out_intact = model(aa_ids, aa_lens, stat, vc, active_experts=("intact",), return_experts=True)
    assert out_intact["intact_func_logits"] is not None
    assert out_intact["func10_logits"] is None and out_intact["phage_logits"] is None
    assert out_intact["intact_func_logits"].shape == (bsz, l_seq, NUM_JUDGE_CLASSES)

    # 2. 按需仅激活排雷分区专家 defense_func
    out_def = model(aa_ids, aa_lens, stat, vc, active_experts=("defense_func",), return_experts=True)
    assert out_def["func10_logits"] is not None and out_def["phage_logits"] is not None
    assert out_def["intact_func_logits"] is None

    # 3. 篡改无效槽位不应影响有效输出（Padding 不变性）
    aa_ids2 = aa_ids.clone()
    stat2 = stat.clone()
    aa_ids2[0, 7:, :] = 18
    stat2[0, 7:, :] = 9.0
    out_both1 = model(aa_ids, aa_lens, stat, vc, return_experts=True)
    out_both2 = model(aa_ids2, aa_lens, stat2, vc, return_experts=True)
    assert torch.allclose(out_both1["func10_logits"][0, :7], out_both2["func10_logits"][0, :7], atol=1e-5)
    assert torch.allclose(out_both1["intact_func_logits"][0, :7], out_both2["intact_func_logits"][0, :7], atol=1e-5)

    # 4. 验证 detach_intact_base=True 梯度防火墙严格隔绝完整度分支反传至底座和宏观门控
    model.train()
    model.zero_grad(set_to_none=True)
    out_grad = model(aa_ids, aa_lens, stat, vc, return_experts=True, detach_intact_base=True)
    loss_only_intact = out_grad["intact_func_logits"].sum()
    loss_only_intact.backward()
    assert model.intact_func_head[0].weight.grad is not None
    assert model.stat_enc[0].weight.grad is None
    assert model.macro_fuse[0].weight.grad is None


def test_predict_contig_orfs_with_unified_judge_returns_both_differentiated_heads():
    stat_mean = np.zeros(ORF_JUDGE_STAT_DIM, dtype=np.float32)
    stat_std = np.ones(ORF_JUDGE_STAT_DIM, dtype=np.float32)
    model = build_orf_functional_judge(stat_mean, stat_std, use_aa_seq=False, arch="unified")
    orfs = [(i * 500, i * 500 + 420, 1, "MKVLVALAV" * 8) for i in range(24)]
    out = predict_contig_orfs_with_judge(model, orfs, device="cpu", batch_size=8, return_logits=True, return_intact=True)
    assert out["func10_probs"].shape == (24, NUM_JUDGE_CLASSES)
    assert out["intact_func_probs"].shape == (24, NUM_JUDGE_CLASSES)
    assert out["phage_logits"].shape == (24,)


def test_unified_phage_model_conditional_routing_skips_inactive_host_contigs():
    class _DummyScanner:
        workers = 1

    stat_mean = np.zeros(ORF_JUDGE_STAT_DIM, dtype=np.float32)
    stat_std = np.ones(ORF_JUDGE_STAT_DIM, dtype=np.float32)
    m_stat = build_orf_functional_judge(stat_mean, stat_std, use_aa_seq=False, arch="r3")
    m_seq = build_orf_functional_judge(stat_mean, stat_std, use_aa_seq=False, arch="unified")
    bundle = {"r3_stat": m_stat, "r3_seq": m_seq, "calibrator": None, "r2_seq": None, "unified_mode": True, "device": "cpu"}

    class _StubUnified(UnifiedPhageModel):
        def _run_dna_backbone(self, contig_seqs):
            wps = [
                WindowPrediction("c_host1", 0, 5000, 0.02),
                WindowPrediction("c_phage", 0, 5000, 0.96),
                WindowPrediction("c_host2", 0, 5000, 0.03),
            ]
            sub = np.zeros((3, 25), dtype=np.float32)
            sub[1, :] = 0.96
            base_regs = [PredictedRegion("c_phage", 1000, 4800, 0.96, 0.96, 1)]
            return wps, sub, None, base_regs, {"dna_feature_sec": 0.01, "dna_infer_decode_sec": 0.01}

    model = _StubUnified(_DummyScanner(), bundle)  # type: ignore[arg-type]
    seqs = {"c_host1": "ATG" * 2000, "c_phage": "ATG" * 2000, "c_host2": "ATG" * 2000}
    pre_orfs = {
        cid: [(i * 600, i * 600 + 500, 1, "MKVLVALAV" * 8) for i in range(6)]
        for cid in seqs
    }

    # 1. 仅激活 boundary：完全不激活蛋白知识底座
    res_b = model.scan_sequences(seqs, active_experts=("boundary",), precomputed_orfs=pre_orfs)
    assert res_b.routing_stats["protein_activated_contigs"] == 0
    assert res_b.routing_stats["protein_skip_ratio"] == 1.0
    assert res_b.region_annotations == {}

    # 2. 全专家按需路由：3 条 contig 中仅激活包含区段的 c_phage（跳过 2 条纯宿主 contig）
    res_full = model.scan_sequences(seqs, precomputed_orfs=pre_orfs)
    assert res_full.routing_stats["protein_activated_contigs"] == 1
    assert abs(res_full.routing_stats["protein_skip_ratio"] - (2.0 / 3.0)) < 1e-3
    assert "c_phage:1000-4800" in res_full.region_annotations
    assert "completeness_class" in res_full.region_annotations["c_phage:1000-4800"]


def test_unified_v4_3_dualskip_and_tailocin_guard_head():
    rng = np.random.default_rng(19)
    stat_mean = np.zeros(ORF_JUDGE_STAT_DIM, dtype=np.float32)
    stat_std = np.ones(ORF_JUDGE_STAT_DIM, dtype=np.float32)
    model = build_orf_functional_judge(
        stat_mean,
        stat_std,
        use_aa_seq=False,
        arch="unified_v4_3",
    )
    model.eval()
    bsz, l_seq = 2, CTX_WIN_ORFS
    aa_ids = torch.zeros((bsz, l_seq, MAX_JUDGE_AA_LEN), dtype=torch.long)
    aa_lens = torch.zeros((bsz, l_seq), dtype=torch.long)
    stat = torch.tensor(rng.normal(0.0, 0.5, size=(bsz, l_seq, ORF_JUDGE_STAT_DIM)), dtype=torch.float32)
    vc = torch.tensor([6, 9], dtype=torch.long)

    out = model(aa_ids, aa_lens, stat, vc, return_experts=True)
    assert out["intact_func_logits"].shape == (bsz, l_seq, NUM_JUDGE_CLASSES)
    assert out["tailocin_neg_logit"].shape == (bsz,)
    assert out["e_orf"] is not None and out["h_base"] is not None

    # Padding 不变性检查
    stat2 = stat.clone()
    stat2[0, 6:, :] = 12.0
    out2 = model(aa_ids, aa_lens, stat2, vc, return_experts=True)
    assert torch.allclose(out["intact_func_logits"][0, :6], out2["intact_func_logits"][0, :6], atol=1e-5)
    assert torch.allclose(out["tailocin_neg_logit"][0], out2["tailocin_neg_logit"][0], atol=1e-5)

    # detach_intact_base 防火墙检查
    model.train()
    model.zero_grad(set_to_none=True)
    out_g = model(aa_ids, aa_lens, stat, vc, return_experts=True, detach_intact_base=True)
    out_g["intact_func_logits"].sum().backward()
    assert model.intact_dualskip_proj[0].weight.grad is not None
    assert model.intact_func_head[0].weight.grad is not None
    assert model.stat_enc[0].weight.grad is None

    # predict_contig_orfs_with_judge 对 unified_v4_3 原生识别双专家输出
    orfs = [(i * 500, i * 500 + 420, 1, "MKVLVALAV" * 8) for i in range(12)]
    pred = predict_contig_orfs_with_judge(model, orfs, device="cpu", batch_size=4, return_intact=True)
    assert pred["intact_func_probs"].shape == (12, NUM_JUDGE_CLASSES)
    assert pred["func10_probs"].shape == (12, NUM_JUDGE_CLASSES)

