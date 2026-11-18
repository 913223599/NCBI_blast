# -*- coding: utf-8 -*-
"""attL / attR 直接重复 1 bp 整合断点精密校准单元测试。"""
from __future__ import annotations

import numpy as np

from src.phage_discovery.benchmark.metrics import PredictedRegion
from src.phage_discovery.inference.att_boundary_refiner import (
    AttAlignmentHit,
    refine_regions_with_att_sites,
)


def _deterministic_dna(length: int, seed: int = 7) -> str:
    rng = np.random.default_rng(seed)
    bases = np.array(["A", "C", "G", "T"])
    return "".join(bases[rng.integers(0, 4, size=length)].tolist())


def test_att_refiner_aligns_exact_and_integrase_anchored_direct_repeat_to_1bp():
    dna_full = list(_deterministic_dna(18000, seed=101))
    att_seq = "GTCATCGACTAGGCTCAT"  # 18 bp 高熵直接重复
    true_l, true_r = 2837, 15214
    dna_full[true_l : true_l + len(att_seq)] = list(att_seq)
    dna_full[true_r - len(att_seq) : true_r] = list(att_seq)
    seq = "".join(dna_full)

    # 在内部设置含核心结构蛋白与贴近右端的整合酶 (P4)，左端设一截在边界内，不跨任何核心基因
    orfs = [
        (800, 1700, 1, "M" * 60),    # 左侧外部宿主
        (3200, 5000, 1, "M" * 60),   # 内部 Head
        (13400, 14900, 1, "M" * 60), # 紧贴 attR 的 Integrase P4
        (15800, 16900, 1, "M" * 60), # 右侧外部宿主
    ]
    ph = np.array([0.05, 0.96, 0.94, 0.04], dtype=np.float32)
    f10 = np.zeros((4, 10), dtype=np.float32)
    f10[0, 9] = 0.80
    f10[1, 0] = 0.90
    f10[2, 4] = 0.92
    f10[3, 9] = 0.85

    # 200 bp 离散粗糙预测
    raw = [PredictedRegion("ctg_att", 2600, 15400, peak_score=0.95, mean_score=0.88, window_count=6)]
    details: dict[str, AttAlignmentHit] = {}
    out, cnt = refine_regions_with_att_sites(
        raw,
        {"ctg_att": seq},
        {"ctg_att": orfs},
        {"ctg_att": {"phage_probs": ph, "func10_probs": f10}},
        details_out=details,
    )
    assert cnt == 1
    assert len(out) == 1
    assert out[0].start_bp == true_l
    assert out[0].end_bp == true_r
    key = f"ctg_att:{true_l}-{true_r}"
    assert key in details
    assert details[key].dr_len_bp == len(att_seq)
    assert details[key].near_integrase is True


def test_att_refiner_blocks_low_complexity_repeats_and_external_host_crossings():
    dna_full = list(_deterministic_dna(18000, seed=202))
    # 1) 注入纯低复杂度重复，应被过滤
    low_comp = "ATATATATATATATATATATAT"
    dna_full[2900 : 2900 + len(low_comp)] = list(low_comp)
    dna_full[14900 : 14900 + len(low_comp)] = list(low_comp)

    # 2) 注入长高质量 18bp 重复，但故意放到明显宿主基因更外侧（模拟 PAO1 Pf4 越界陷阱）
    host_trap = "CGTAGCTAGCATGCTAGC"
    dna_full[2950 : 2950 + len(host_trap)] = list(host_trap)
    dna_full[16200 : 16200 + len(host_trap)] = list(host_trap)
    seq = "".join(dna_full)

    orfs = [
        (3300, 4800, 1, "M" * 60),    # 核心噬菌体 Head
        (13400, 14600, 1, "M" * 60),  # Integrase P4
        (15100, 15900, 1, "M" * 60),  # 明确强宿主（位于预测边界 15000 与 host_trap 16200 之间）
    ]
    ph = np.array([0.95, 0.92, 0.06], dtype=np.float32)
    f10 = np.zeros((3, 10), dtype=np.float32)
    f10[0, 0] = 0.88
    f10[1, 4] = 0.90
    f10[2, 9] = 0.70

    raw = [PredictedRegion("ctg_guard", 3000, 15000, peak_score=0.92, mean_score=0.85, window_count=5)]
    out, cnt = refine_regions_with_att_sites(
        raw,
        {"ctg_guard": seq},
        {"ctg_guard": orfs},
        {"ctg_guard": {"phage_probs": ph, "func10_probs": f10}},
    )
    assert cnt == 0
    assert out[0].start_bp == 3000 and out[0].end_bp == 15000


def test_att_refiner_never_cuts_inside_core_phage_cds():
    dna_full = list(_deterministic_dna(18000, seed=303))
    trap_dr = "TGACCGATCGTAGCTAACGT"  # 20 bp
    # 故意把左端重复放在内部高置信核心 CDS (3200..5000) 正中间
    dna_full[3800 : 3800 + len(trap_dr)] = list(trap_dr)
    dna_full[14800 : 14800 + len(trap_dr)] = list(trap_dr)
    seq = "".join(dna_full)

    orfs = [
        (3200, 5000, 1, "M" * 60),
        (12500, 14200, 1, "M" * 60),
    ]
    ph = np.array([0.96, 0.94], dtype=np.float32)
    f10 = np.zeros((2, 10), dtype=np.float32)
    f10[0, 0] = 0.92
    f10[1, 2] = 0.89

    raw = [PredictedRegion("ctg_core", 3000, 14600, peak_score=0.95, mean_score=0.88, window_count=6)]
    out, cnt = refine_regions_with_att_sites(
        raw,
        {"ctg_core": seq},
        {"ctg_core": orfs},
        {"ctg_core": {"phage_probs": ph, "func10_probs": f10}},
    )
    assert cnt == 0
    assert out[0].start_bp == 3000 and out[0].end_bp == 14600


def test_att_refiner_uses_2100bp_default_flank_pad_to_reach_1900bp_boundary():
    dna_full = list(_deterministic_dna(22000, seed=404))
    att_seq = "GTCATCGACTAGGCTCAT"  # 18 bp
    true_l, true_r = 2500, 18920
    dna_full[true_l - 1] = "A"
    dna_full[true_l + len(att_seq)] = "A"
    dna_full[true_r - len(att_seq) - 1] = "T"
    dna_full[true_r] = "T"
    dna_full[true_l : true_l + len(att_seq)] = list(att_seq)
    dna_full[true_r - len(att_seq) : true_r] = list(att_seq)
    seq = "".join(dna_full)

    # 预测右缘滞后于真实 attR 达 1920 bp (>1650 bp 旧半径, <=2100 bp 新默认半径)
    orfs = [
        (3000, 4800, 1, "M" * 60),    # Head
        (17200, 18700, 1, "M" * 60),  # Integrase P4 贴近 true_r
    ]
    ph = np.array([0.96, 0.94], dtype=np.float32)
    f10 = np.zeros((2, 10), dtype=np.float32)
    f10[0, 0] = 0.90
    f10[1, 4] = 0.92

    raw = [PredictedRegion("ctg_pad", 2600, 17000, peak_score=0.95, mean_score=0.89, window_count=6)]
    out, cnt = refine_regions_with_att_sites(
        raw,
        {"ctg_pad": seq},
        {"ctg_pad": orfs},
        {"ctg_pad": {"phage_probs": ph, "func10_probs": f10}},
    )
    assert cnt == 1
    assert out[0].start_bp == true_l
    assert out[0].end_bp == true_r


def test_att_refiner_finds_trna_tloop_short_dr_when_enabled_and_respects_guards():
    dna_full = list(_deterministic_dna(18000, seed=505))
    short_dr = "GTACCTAGGCAT"  # 12 bp (低于主门限 14 bp)
    # 在右缘设置负链 tRNA T-loop: 上游 TGG 后接 GTTTGAAC, 下游附带 12bp 短直接重复
    true_l, true_r = 3120, 14880
    dna_full[true_r - 60 : true_r - 57] = list("TGG")
    dna_full[true_r - 40 : true_r - 32] = list("GTTTGAAC")
    dna_full[true_l - 1] = "A"
    dna_full[true_l + len(short_dr)] = "A"
    dna_full[true_r - len(short_dr) - 1] = "C"
    dna_full[true_r] = "C"
    dna_full[true_l : true_l + len(short_dr)] = list(short_dr)
    dna_full[true_r - len(short_dr) : true_r] = list(short_dr)
    seq = "".join(dna_full)

    orfs = [
        (3400, 5200, 1, "M" * 60),
        (13400, 14700, 1, "M" * 60),  # Integrase P4 紧邻右端 tRNA
    ]
    ph = np.array([0.95, 0.93], dtype=np.float32)
    f10 = np.zeros((2, 10), dtype=np.float32)
    f10[0, 0] = 0.91
    f10[1, 4] = 0.90

    raw = [PredictedRegion("ctg_trna", 3000, 15000, peak_score=0.94, mean_score=0.87, window_count=5)]
    # 1) 默认 enable_trna_short_dr=False 时保守放过 12 bp 短重复
    out_off, cnt_off = refine_regions_with_att_sites(
        raw,
        {"ctg_trna": seq},
        {"ctg_trna": orfs},
        {"ctg_trna": {"phage_probs": ph, "func10_probs": f10}},
    )
    assert cnt_off == 0
    assert (out_off[0].start_bp, out_off[0].end_bp) == (3000, 15000)

    # 2) 开启 enable_trna_short_dr=True 时成功利用 tRNA 锚点锁定 1 bp 边界
    out_on, cnt_on = refine_regions_with_att_sites(
        raw,
        {"ctg_trna": seq},
        {"ctg_trna": orfs},
        {"ctg_trna": {"phage_probs": ph, "func10_probs": f10}},
        enable_trna_short_dr=True,
        details_out=(det := {}),
    )
    assert cnt_on == 1
    assert (out_on[0].start_bp, out_on[0].end_bp) == (true_l, true_r)
    assert det[f"ctg_trna:{true_l}-{true_r}"].dr_len_bp == len(short_dr)

    # 3) 若将 short_dr 放入内部核心 CDS 内部, 即使启用 tRNA 检测也必须拦截
    dna_guard = list(dna_full)
    dna_guard[4100 : 4100 + len(short_dr)] = list(short_dr)
    dna_guard[true_l : true_l + len(short_dr)] = list("A" * len(short_dr))
    out_guard, cnt_guard = refine_regions_with_att_sites(
        raw,
        {"ctg_trna": "".join(dna_guard)},
        {"ctg_trna": orfs},
        {"ctg_trna": {"phage_probs": ph, "func10_probs": f10}},
        enable_trna_short_dr=True,
    )
    assert cnt_guard == 0
    assert (out_guard[0].start_bp, out_guard[0].end_bp) == (3000, 15000)

