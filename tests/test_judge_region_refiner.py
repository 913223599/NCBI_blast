# -*- coding: utf-8 -*-
"""Judge 后置境界精修、灰区碎段挽救与防御岛排雷单元测试。"""
from __future__ import annotations

import numpy as np

from src.phage_discovery.benchmark.metrics import PredictedRegion, WindowPrediction
from src.phage_discovery.inference.judge_region_refiner import (
    extract_subbin_gray_candidates,
    refine_region_boundaries_with_judge,
    rescue_and_filter_regions_with_judge,
    summarize_region_with_judge,
)


def _make_fake_orfs(n: int, step_bp: int = 1000) -> list[tuple[int, int, int, str]]:
    return [(i * step_bp + 50, i * step_bp + 850, 1, "MKVLVALAV" * 8) for i in range(n)]


def test_refine_region_boundaries_extends_phage_tail_and_stops_at_host_defense():
    orfs = _make_fake_orfs(12, step_bp=1000)
    # 0..1 强宿主，2..5 初筛命中，6..8 被切断的右翼真噬菌体基因，9..11 宿主/防御岛
    ph = np.array([0.05, 0.08, 0.90, 0.92, 0.88, 0.85, 0.72, 0.65, 0.58, 0.12, 0.08, 0.06], dtype=np.float32)
    f10 = np.zeros((12, 10), dtype=np.float32)
    f10[2, 0] = 0.85  # head
    f10[4, 2] = 0.80  # tail
    f10[6, 2] = 0.68  # tail
    f10[8, 4] = 0.72  # integrase
    f10[9, 9] = 0.82  # host defense
    f10[10, 9] = 0.75

    # 初筛区间不小心左边还吃了一半宿主 gene1，右边只框到 gene5 (2000..5850)
    raw = [PredictedRegion(contig_id="c1", start_bp=1000, end_bp=5850, peak_score=0.95, mean_score=0.80, window_count=4)]
    scored = {"c1": {"phage_probs": ph, "func10_probs": f10, "r2_core_probs": f10[:, :5]}}

    refined = refine_region_boundaries_with_judge(
        raw,
        {"c1": orfs},
        scored,
        {"c1": 15000},
        max_flank_bp=8000,
        max_step_gap_bp=1500,
        min_ext_phage_prob=0.50,
        allow_edge_trim=True,
    )
    assert len(refined) == 1
    # 左侧应裁掉宿主 gene1 收紧到 gene2 (2050)，右侧应外延吃进 gene6..8 到 8850 并止步于 defense gene9
    assert refined[0].start_bp == 2050
    assert refined[0].end_bp == 8850

    # 若提供 window_preds 且外侧主干得分已降为 0.05，则应严格阻断过扩展保护边界
    wps = [WindowPrediction("c1", 2000, 6000, 0.90), WindowPrediction("c1", 6000, 10000, 0.05)]
    guarded = refine_region_boundaries_with_judge(
        raw,
        {"c1": orfs},
        scored,
        {"c1": 15000},
        window_preds=wps,
        min_ext_backbone_score=0.22,
        min_ext_phage_prob=0.50,
        allow_edge_trim=False,
    )
    assert guarded[0].end_bp == 5850


def test_extract_subbin_gray_candidates_recovers_low_win_high_subbin_island():
    wps = [
        WindowPrediction("c1", 0, 5000, 0.05),
        WindowPrediction("c1", 2500, 7500, 0.45),
        WindowPrediction("c1", 5000, 10000, 0.52),
        WindowPrediction("c1", 7500, 12500, 0.12),
    ]
    sub = np.zeros((4, 25), dtype=np.float32)
    sub[1, 10:] = 0.95
    sub[2, :] = 0.94
    sub[3, :10] = 0.88
    cands = extract_subbin_gray_candidates(wps, sub, min_region_bp=5000, min_peak_sub_prob=0.90)
    assert len(cands) == 1
    assert cands[0].start_bp >= 4000 and cands[0].end_bp <= 10200
    assert cands[0].end_bp - cands[0].start_bp >= 5000


def test_rescue_and_filter_regions_rescues_cryptic_phage_and_blocks_defense_island():
    orfs = _make_fake_orfs(20, step_bp=1000)
    ph = np.full(20, 0.15, dtype=np.float32)
    f10 = np.zeros((20, 10), dtype=np.float32)

    # base 主区段 0..4 为纯高 P9 误报（极少见 veto 测试）
    f10[:5, 9] = 0.82
    ph[:5] = 0.10

    # 灰区候选 A (6..11): 真实碎裂隐蔽前噬菌体 (6 个基因高 phage + 多功能分区)
    ph[6:12] = np.array([0.85, 0.82, 0.78, 0.88, 0.65, 0.72], dtype=np.float32)
    f10[6, 0] = 0.80  # head
    f10[8, 2] = 0.76  # tail
    f10[10, 4] = 0.82  # integration

    # 灰区候选 B (14..19): 宿主防御岛假阳性
    ph[14:20] = np.array([0.25, 0.18, 0.30, 0.15, 0.22, 0.19], dtype=np.float32)
    f10[14:18, 9] = 0.85

    base = [PredictedRegion(contig_id="c1", start_bp=0, end_bp=4900, peak_score=0.96, mean_score=0.72, window_count=4)]
    relaxed = [
        base[0],
        PredictedRegion(contig_id="c1", start_bp=6000, end_bp=11900, peak_score=0.84, mean_score=0.68, window_count=4),
        PredictedRegion(contig_id="c1", start_bp=14000, end_bp=19900, peak_score=0.83, mean_score=0.62, window_count=4),
    ]
    scored = {"c1": {"phage_probs": ph, "func10_probs": f10, "r2_core_probs": f10[:, :5]}}
    res, stats = rescue_and_filter_regions_with_judge(
        base,
        relaxed,
        {"c1": orfs},
        scored,
        min_base_clearance_bp=1000,
    )

    assert stats["base_vetoed"] == 1
    assert stats["gray_rescued"] == 1
    assert stats["gray_rejected"] == 1
    assert len(res) == 1
    assert res[0].start_bp == 6000 and res[0].end_bp == 11900


def test_summarize_region_with_judge_uses_r2_core_for_completeness():
    orfs = _make_fake_orfs(6, step_bp=1000)
    ph = np.full(6, 0.88, dtype=np.float32)
    f10 = np.zeros((6, 10), dtype=np.float32)
    f10[0, 5] = 0.70  # R3 replication
    f10[1, 6] = 0.60  # R3 transcription
    r2_core = np.zeros((6, 5), dtype=np.float32)
    r2_core[0, 0] = 0.78  # head
    r2_core[1, 1] = 0.62  # connector
    r2_core[2, 2] = 0.81  # tail
    reg = PredictedRegion(contig_id="c1", start_bp=0, end_bp=5900, peak_score=0.95, mean_score=0.88, window_count=4)
    out = summarize_region_with_judge(reg, orfs, {"phage_probs": ph, "func10_probs": f10, "r2_core_probs": r2_core})
    assert out["completeness_class"] == "complete_structural_core"
    assert out["r2_core_active_count"] == 3
    assert "dna_rna_replication" in out["active_modules"]


def test_base_veto_blocks_plasmid_par_defense_even_with_single_lysis_noise():
    orfs = _make_fake_orfs(12, step_bp=1000)
    ph = np.full(12, 0.42, dtype=np.float32)
    f10 = np.zeros((12, 10), dtype=np.float32)
    # 质粒区间：没有 head/connector/tail，含 1 个 lysis 误触使 core_mods==1，同时高 P9 防御 + 高 P8 质粒/MGE
    f10[2, 3] = 0.65  # lysis
    f10[3, 8] = 0.72  # transposon_plasmid_mge
    f10[4, 9] = 0.79  # host_defense_virulence

    # 另一个真噬菌体：虽然也带高 P9，但含有明确 head 结构核心且均值较高，绝不能误杀
    ph[6:12] = 0.65
    f10[7, 0] = 0.85  # head
    f10[9, 9] = 0.88  # high defense cargo

    base = [
        PredictedRegion("c1", 0, 5900, 0.90, 0.75, 4),
        PredictedRegion("c1", 6000, 11900, 0.92, 0.80, 4),
    ]
    scored = {"c1": {"phage_probs": ph, "func10_probs": f10, "r2_core_probs": f10[:, :5]}}
    res, stats = rescue_and_filter_regions_with_judge(base, [], {"c1": orfs}, scored)
    assert stats["base_vetoed"] == 1
    assert stats["base_kept"] == 1
    assert len(res) == 1 and res[0].start_bp == 6000


def test_gray_rescue_rejects_p4_p5_p6_plasmid_and_keeps_tail_cryptic_phage():
    orfs = _make_fake_orfs(16, step_bp=1000)
    ph = np.full(16, 0.20, dtype=np.float32)
    f10 = np.zeros((16, 10), dtype=np.float32)

    # 候选 A (0..6): 纯质粒/MGE 碎片，仅有 integration(P4)+replication(P5)+transcription(P6)，无形态蛋白
    ph[0:7] = 0.82
    f10[1, 4] = 0.85
    f10[3, 5] = 0.88
    f10[5, 6] = 0.78

    # 候选 B (9..15): 真实隐蔽前噬菌体片段（类似 CPS-53），含 tail(P2)+transcription(P6)+moron(P7)
    ph[9:16] = 0.68
    f10[10, 2] = 0.75
    f10[12, 6] = 0.70
    f10[14, 7] = 0.65

    relaxed = [
        PredictedRegion("c1", 0, 6900, 0.82, 0.70, 3),
        PredictedRegion("c1", 9000, 15900, 0.82, 0.68, 3),
    ]
    scored = {"c1": {"phage_probs": ph, "func10_probs": f10, "r2_core_probs": f10[:, :5]}}
    res, stats = rescue_and_filter_regions_with_judge([], relaxed, {"c1": orfs}, scored)
    assert stats["gray_rescued"] == 1
    assert stats["gray_rejected"] == 1
    assert len(res) == 1 and res[0].start_bp == 9000


def test_cross_head_mge_veto_blocks_ice_and_keeps_phage_with_r2_head():
    orfs = _make_fake_orfs(20, step_bp=1000)
    ph = np.full(20, 0.60, dtype=np.float32)
    f10 = np.zeros((20, 10), dtype=np.float32)
    r2_core = np.zeros((20, 5), dtype=np.float32)

    # 区间 A (0..9): 复杂耐药移动岛 ICE — Head B 认定零形态 (P0..P3 < 0.5)，Head A P8/P9 高且均值 < 0.72
    f10[2, 8] = 0.68
    f10[4:7, 9] = 0.75  # max_p9 >= 0.45, mean_p9 >= 0.18
    r2_core[5, 4] = 0.90  # 仅含 integrase

    # 区间 B (10..19): 真噬菌体带防御与 MGE 货载，Head B 识别出明确 Head (r2 P0 >= 0.50)，绝不误杀
    f10[12, 8] = 0.65
    f10[14:17, 9] = 0.70
    r2_core[13, 0] = 0.82

    base = [
        PredictedRegion("c1", 0, 9900, 0.92, 0.72, 4),
        PredictedRegion("c1", 10000, 19900, 0.94, 0.75, 4),
    ]
    scored = {"c1": {"phage_probs": ph, "func10_probs": f10, "r2_core_probs": r2_core}}
    res, stats = rescue_and_filter_regions_with_judge(base, [], {"c1": orfs}, scored)
    assert stats["base_vetoed"] == 1
    assert stats["base_kept"] == 1
    assert len(res) == 1 and res[0].start_bp == 10000


def test_gray_tailocin_guard_blocks_monocin_but_keeps_tail_with_connector():
    orfs = _make_fake_orfs(24, step_bp=1000)
    ph = np.full(24, 0.85, dtype=np.float32)
    f10 = np.zeros((24, 10), dtype=np.float32)
    r2_core = np.zeros((24, 5), dtype=np.float32)

    # 灰区候选 A (0..7): 纯 Tailocin（4 个强 Tail + Lysis，但无 Head/Connector/Integrase）
    f10[1:5, 2] = 0.92
    f10[6, 3] = 0.85
    r2_core[1:5, 2] = 0.94
    r2_core[6, 3] = 0.88

    # 灰区候选 B (12..19): 类似 LT2 STM4200 的真退化尾元件（含 4 个 Tail + 明确 Connector >= 0.45）
    f10[13:17, 2] = 0.95
    f10[17, 1] = 0.78
    f10[18, 3] = 0.90
    r2_core[13:17, 2] = 0.96
    r2_core[17, 1] = 0.81

    relaxed = [
        PredictedRegion("c1", 0, 7900, 0.86, 0.78, 3),
        PredictedRegion("c1", 12000, 19900, 0.88, 0.80, 3),
    ]
    scored = {"c1": {"phage_probs": ph, "func10_probs": f10, "r2_core_probs": r2_core}}
    res, stats = rescue_and_filter_regions_with_judge([], relaxed, {"c1": orfs}, scored)
    assert stats["gray_rejected"] == 1
    assert stats["gray_rescued"] == 1
    assert len(res) == 1 and res[0].start_bp == 12000


def test_elastic_and_short_morph_rescue_without_admitting_4orf_noise():
    orfs = _make_fake_orfs(32, step_bp=1000)
    ph = np.full(32, 0.10, dtype=np.float32)
    f10 = np.zeros((32, 10), dtype=np.float32)
    r2_core = np.zeros((32, 5), dtype=np.float32)

    # A (0..7, 8 ORFs): 类似 Sakai Sp17，边缘 P8=0.90 且 f10 tail=0.54 (<0.55)、P9 边缘高，但有 >=3 模块且 Head B 补齐 P2=0.60
    ph[0:8] = 0.80
    f10[0, 2] = 0.54  # 单独不足 0.55
    f10[1, 3] = 0.95  # lysis
    f10[2, 5] = 0.92  # replication
    f10[7, 4] = 0.79  # integration (>=3 模块)
    f10[3, 8] = 0.90  # P8 edge noise
    f10[4:7, 9] = 0.42
    r2_core[0, 2] = 0.60  # Head B 识别出 tail (>=0.55)

    # B (12..17, 6 ORFs): 类似 STM2234，只有 1 个有效模块但高尾无防御无 MGE
    ph[12:18] = np.array([0.65, 0.70, 0.68, 0.58, 0.62, 0.68], dtype=np.float32)
    f10[13, 2] = 0.83
    r2_core[13, 2] = 0.62

    # C (22..25, 4 ORFs): 超短 4-ORF 噪点，即便高 tail 也应被 n>=6 规则挡回（不触发 A3/B2 误报）
    ph[22:26] = 0.75
    f10[23, 2] = 0.80
    r2_core[23, 2] = 0.75

    relaxed = [
        PredictedRegion("c1", 0, 7900, 0.92, 0.85, 3),
        PredictedRegion("c1", 12000, 17900, 0.88, 0.81, 2),
        PredictedRegion("c1", 22000, 25900, 0.85, 0.80, 2),
    ]
    scored = {"c1": {"phage_probs": ph, "func10_probs": f10, "r2_core_probs": r2_core}}
    res, stats = rescue_and_filter_regions_with_judge([], relaxed, {"c1": orfs}, scored, rescue_min_orfs=6)
    assert stats["gray_rescued"] == 2
    assert stats["gray_rejected"] == 1
    assert [(r.start_bp, r.end_bp) for r in res] == [(0, 7900), (12000, 17900)]


def test_complementary_bridge_merges_spbeta_pair_and_skips_independent_island():
    orfs = _make_fake_orfs(160, step_bp=1000)
    ph = np.full(160, 0.85, dtype=np.float32)
    f10 = np.zeros((160, 10), dtype=np.float32)
    r2_core = np.zeros((160, 5), dtype=np.float32)

    # SPbeta 左臂 (0..40, 40kb): 缺 Head (0), 有 12 个 P5/P6 与 2 个 Int
    f10[2:14, 5] = 0.80
    r2_core[18:20, 4] = 0.85
    # gap (40..55, 15kb): 大部分低分但有 3 个高置信桥钉 >= 0.70
    ph[40:55] = 0.15
    ph[45] = 0.78
    ph[49] = 0.86
    ph[51] = 0.95
    # SPbeta 右臂 (55..95, 40kb): 含 >=3 Head, >=5 Tail, >=1 Lysis 但无 Integrase
    r2_core[57:62, 0] = 0.92
    r2_core[65:73, 2] = 0.90
    r2_core[76, 3] = 0.88

    # 独立完备噬菌体 C (105..140) 与相邻独立 12kb 卫星岛 D (148..160): 不应桥接
    # 实际上 gap=8000, D=12kb (<30kb) 且 C 本身已经有 Head+Tail+Lysis+Int 全套
    r2_core[107:110, 0] = 0.90
    r2_core[112:118, 2] = 0.90
    r2_core[120, 3] = 0.85
    r2_core[125, 4] = 0.85
    ph[140:148] = 0.80
    r2_core[150, 4] = 0.90

    base = [
        PredictedRegion("c1", 0, 39900, 0.95, 0.85, 10),
        PredictedRegion("c1", 55000, 94900, 0.98, 0.90, 10),
        PredictedRegion("c1", 105000, 139900, 0.96, 0.88, 9),
        PredictedRegion("c1", 148000, 159900, 0.90, 0.75, 4),
    ]
    scored = {"c1": {"phage_probs": ph, "func10_probs": f10, "r2_core_probs": r2_core}}
    res, stats = rescue_and_filter_regions_with_judge(base, [], {"c1": orfs}, scored)
    assert stats["topology_bridged"] == 1
    assert [(r.start_bp, r.end_bp) for r in res] == [(0, 94900), (105000, 139900), (148000, 159900)]


def test_tandem_split_separates_dual_core_and_protects_jumbo_phage():
    # Contig 1 (c_tan): 100kb 串联双噬菌体 (Sp11+Sp12 样)
    orfs_tan = _make_fake_orfs(100, step_bp=1000)
    ph_tan = np.full(100, 0.92, dtype=np.float32)
    f10_tan = np.zeros((100, 10), dtype=np.float32)
    r2_tan = np.zeros((100, 5), dtype=np.float32)
    r2_tan[15:20, 0] = 0.95  # 第一簇 Head (5 ORFs)
    ph_tan[38:44] = 0.15     # 中间深谷 (6 ORFs < 0.35)
    r2_tan[45:49, 4] = 0.88  # 中间 Integrase 界桩 (4 ORFs >= 0.70)
    r2_tan[65:70, 0] = 0.95  # 第二簇 Head (5 ORFs)，间距 45kb >= 25kb

    # Contig 2 (c_jumbo): 100kb 巨型单株噬菌体（两处远距 P0 簇但全段高 phage_prob 且无中间整合酶界桩）
    orfs_jmb = _make_fake_orfs(100, step_bp=1000)
    ph_jmb = np.full(100, 0.94, dtype=np.float32)
    f10_jmb = np.zeros((100, 10), dtype=np.float32)
    r2_jmb = np.zeros((100, 5), dtype=np.float32)
    r2_jmb[10:15, 0] = 0.95
    r2_jmb[70:75, 0] = 0.95

    base = [
        PredictedRegion("c_tan", 0, 99900, 0.99, 0.88, 25),
        PredictedRegion("c_jumbo", 0, 99900, 0.99, 0.92, 25),
    ]
    res, stats = rescue_and_filter_regions_with_judge(
        base,
        [],
        {"c_tan": orfs_tan, "c_jumbo": orfs_jmb},
        {
            "c_tan": {"phage_probs": ph_tan, "func10_probs": f10_tan, "r2_core_probs": r2_tan},
            "c_jumbo": {"phage_probs": ph_jmb, "func10_probs": f10_jmb, "r2_core_probs": r2_jmb},
        },
    )
    assert stats["topology_split"] == 1
    tan_segs = [r for r in res if r.contig_id == "c_tan"]
    jmb_segs = [r for r in res if r.contig_id == "c_jumbo"]
    assert len(tan_segs) == 2
    assert tan_segs[0].end_bp == tan_segs[1].start_bp
    assert 43000 <= tan_segs[0].end_bp <= 46000
    assert len(jmb_segs) == 1 and jmb_segs[0].end_bp == 99900

