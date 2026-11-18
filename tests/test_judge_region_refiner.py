# -*- coding: utf-8 -*-
"""Judge 后置境界精修、灰区碎段挽救与防御岛排雷单元测试。"""
from __future__ import annotations

import numpy as np

from src.phage_discovery.benchmark.metrics import PredictedRegion, WindowPrediction
from src.phage_discovery.inference.judge_region_refiner import (
    extract_subbin_gray_candidates,
    refine_region_boundaries_bimodal,
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


def test_base_veto_blocks_dead_zero_evidence_mge_but_keeps_satellite_with_integrase():
    orfs = _make_fake_orfs(20, step_bp=1000)
    ph = np.zeros(20, dtype=np.float32)
    f10 = np.zeros((20, 10), dtype=np.float32)
    r2_core = np.zeros((20, 5), dtype=np.float32)

    # 区间 A (0..9): 零噬菌体蛋白证据的纯复制片段 (mean_ph=0.03, 仅 P5 replication，core_mods==0) -> 必拒
    ph[0:10] = 0.03
    f10[2, 5] = 0.85

    # 区间 B (10..19): 退化卫星岛 (如 bIL311_ps3: mean_ph=0.143, 含 P4 integrase) -> 绝不能误杀
    ph[10:20] = 0.143
    f10[13, 4] = 0.78
    r2_core[13, 4] = 0.75

    base = [
        PredictedRegion("c1", 0, 9900, 0.90, 0.72, 4),
        PredictedRegion("c1", 10000, 19900, 0.94, 0.80, 4),
    ]
    res, stats = rescue_and_filter_regions_with_judge(
        base,
        [],
        {"c1": orfs},
        {"c1": {"phage_probs": ph, "func10_probs": f10, "r2_core_probs": r2_core}},
    )
    assert stats["base_vetoed"] == 1
    assert stats["base_kept"] == 1
    assert len(res) == 1 and res[0].start_bp == 10000


def test_gray_tailocin_guard_blocks_pure_tail_with_single_r2_noise_but_keeps_connector_phage():
    orfs = _make_fake_orfs(20, step_bp=1000)
    ph = np.full(20, 0.85, dtype=np.float32)

    # 候选 1 (0..9): PAO1 R2/F2 pyocin 样（Head A 无 Head/Conn/Int，仅有 6 个 Tail + 1 个 Lysis，但 Head B 单 ORF 误飙 0.65/0.55）-> 拦截
    f10 = np.zeros((20, 10), dtype=np.float32)
    r2_core = np.zeros((20, 5), dtype=np.float32)
    f10[1:7, 2] = 0.99
    f10[8, 3] = 0.95
    f10[0, 0] = 0.44
    f10[0, 1] = 0.43
    r2_core[1:7, 2] = 0.99
    r2_core[0, 0] = 0.65
    r2_core[0, 1] = 0.55

    # 候选 2 (12..19): 卫星前噬菌体样（Head A/B 均显式检出 Connector=0.75 + 多个 Tail + Lysis）-> 绝不误杀
    f10[12, 1] = 0.75
    f10[13:18, 2] = 0.99
    f10[18, 3] = 0.96
    r2_core[12, 1] = 0.78
    r2_core[13:18, 2] = 0.99

    cands = [
        PredictedRegion("c1", 0, 9900, 0.88, 0.70, 4),
        PredictedRegion("c1", 12000, 19900, 0.88, 0.70, 4),
    ]
    res, stats = rescue_and_filter_regions_with_judge(
        [],
        cands,
        {"c1": orfs},
        {"c1": {"phage_probs": ph, "func10_probs": f10, "r2_core_probs": r2_core}},
    )
    assert stats["gray_rejected"] == 1
    assert stats["gray_rescued"] == 1
    assert len(res) == 1 and res[0].start_bp == 12000


def test_inovirus_gray_rescue_recovers_long_high_subbin_head_int_island_without_plasmid_leak():
    orfs = _make_fake_orfs(26, step_bp=1000)
    ph = np.zeros(26, dtype=np.float32)
    f10 = np.zeros((26, 10), dtype=np.float32)
    r2_core = np.zeros((26, 5), dtype=np.float32)

    # 候选 1 (0..12, 12.9kb): Pf4 丝状前噬菌体样（mean_ph=0.33, 仅双流双衣壳>=0.73 + Integrase>=0.95，无 Tail/Conn）-> 挽救
    ph[0:13] = 0.33
    f10[2, 0] = 0.74
    f10[9, 4] = 0.96
    r2_core[2:4, 0] = 0.72
    r2_core[9, 4] = 0.98

    # 候选 2 (14..20, 6.9kb 短古菌/质粒碎片, 缺少 r2 双衣壳) -> 拦截
    ph[14:21] = 0.40
    f10[15, 0] = 0.80
    f10[18, 4] = 0.90
    r2_core[15, 0] = 0.35
    r2_core[18, 4] = 0.92

    cands = [
        PredictedRegion("c1", 0, 12900, 0.990, 0.925, 5),
        PredictedRegion("c1", 14000, 20900, 0.995, 0.920, 3),
    ]
    res, stats = rescue_and_filter_regions_with_judge(
        [],
        cands,
        {"c1": orfs},
        {"c1": {"phage_probs": ph, "func10_probs": f10, "r2_core_probs": r2_core}},
        rescue_min_orfs=6,
    )
    assert stats["gray_rescued"] == 1
    assert stats["gray_rejected"] == 1
    assert len(res) == 1 and res[0].start_bp == 0


def test_refine_region_boundaries_bimodal_snaps_only_subbin_verified_orfs():
    # 5 条 ORF:
    # 0 [400..1600]: 左端边界在 1000，外露部分 [400..1000] 有较高 SubBin 支持 -> 应扩齐至 400
    # 1..2: 噬菌体内部高分核心
    # 3 [4200..5400]: 若另一组把右端放 4800 且 [4800..5400] SubBin 几乎归零但 ph 高 (融合嵌合假体) -> 不应拉入 5400
    # 4 [6000..7000]: 边界切进强宿主 (p9=0.80, ph=0.08, out_sub=0.05) -> 应向内裁回至 6000
    orfs: list[tuple[int, int, int, str]] = [
        (400, 1600, 1, "M" * 60),
        (1700, 2900, 1, "M" * 60),
        (3000, 4100, 1, "M" * 60),
        (4200, 5400, 1, "M" * 60),
        (6000, 7000, 1, "M" * 60),
    ]
    ph = np.array([0.92, 0.96, 0.95, 0.90, 0.08], dtype=np.float32)
    f10 = np.zeros((5, 10), dtype=np.float32)
    f10[0, 4] = 0.85
    f10[1, 0] = 0.90
    f10[2, 2] = 0.88
    f10[3, 2] = 0.80
    f10[4, 9] = 0.80
    scored = {"c1": {"phage_probs": ph, "func10_probs": f10}}

    # 情形 A: 左端 1000 劈断 ORF0 且外露 400..1000 SubBin>=0.30; 右端 4800 劈断 ORF3 但外露 4800..5400 SubBin=0.02
    prof_a = np.zeros(45, dtype=np.float32)
    prof_a[2:24] = 0.85  # 400..4800
    prof_a[2:5] = 0.35   # 400..1000 外露部分真实有过渡支持
    regs_a = [PredictedRegion("c1", 1000, 4800, 0.95, 0.90, 3)]
    out_a, cnt_a = refine_region_boundaries_bimodal(regs_a, {"c1": orfs}, scored, {"c1": 9000}, {"c1": prof_a})
    assert cnt_a == 1
    assert out_a[0].start_bp == 400
    assert out_a[0].end_bp == 4800

    # 情形 B: 右端切入强宿主 ORF4 [6000..7000] 到 6400 -> 应回退至 6000
    prof_b = np.zeros(45, dtype=np.float32)
    prof_b[2:32] = 0.88  # 400..6400
    prof_b[30:36] = 0.05 # 6000..7200 低 SubBin
    regs_b = [PredictedRegion("c1", 400, 6400, 0.95, 0.90, 3)]
    out_b, cnt_b = refine_region_boundaries_bimodal(regs_b, {"c1": orfs}, scored, {"c1": 9000}, {"c1": prof_b})
    assert cnt_b == 1
    assert out_b[0].end_bp == 6000


def test_rescue_and_bridge_recovers_spbeta_three_segment_prophage():
    # 构造 3 段 (模拟 B. subtilis SPbeta):
    # - 片段 1 [0..35000]: 35 kb 早臂 (Integrase + 12 个复制调节，无 Head)
    # - 间隔 1 [35000..52000]: 17 kb 含 3 个基因锚钉 (ph>=0.75) 无 P9 宿主壁
    # - 片段 2 [52000..65000]: 头部臂 (5 Head + 2 Tail, Lysis=0, Int=0)
    # - 间隔 2 [65000..70500]: 5.5 kb 含 3 个基因 (含 Lysis, ph>=0.80, 无 P9)
    # - 片段 3 [70500..84000] (灰区纯 Tail+Lysis 臂, 无 Head -> 独立审核易被当成纯尾拒收, 但离片段 2 仅 5.5 kb)
    orfs = []
    ph_l = []
    f10_l = []
    r2_l = []

    def _add(gs: int, ge: int, p: float, f_idx: int, c_val: float = 0.0) -> None:
        orfs.append((gs, ge, 1, "M" * 60))
        ph_l.append(p)
        row = np.zeros(10, dtype=np.float32)
        row[f_idx] = 0.88
        f10_l.append(row)
        r_row = np.zeros(5, dtype=np.float32)
        if f_idx < 5:
            r_row[f_idx] = c_val
        r2_l.append(r_row)

    # 片段 1 (0..35000): 1 个 Integrase + 12 个 replication
    _add(500, 1500, 0.95, 4, 0.90)
    for k in range(12):
        _add(3000 + k * 2500, 4200 + k * 2500, 0.90, 5, 0.0)
    # 间隔 1 (35000..52000): 3 个噬菌体锚钉
    for k in range(3):
        _add(36000 + k * 4500, 37200 + k * 4500, 0.78, 6, 0.0)
    # 片段 2 (52000..65000): 5 个 Head + 2 个 Tail (缺 Lysis)
    for k in range(5):
        _add(52500 + k * 1400, 53500 + k * 1400, 0.97, 0, 0.92)
    for k in range(2):
        _add(60500 + k * 1800, 61800 + k * 1800, 0.96, 2, 0.90)
    # 间隔 2 (65000..70500): 3 个 Lysis/辅助
    for k in range(3):
        _add(65500 + k * 1600, 66600 + k * 1600, 0.85, 3, 0.85)
    # 片段 3 (70500..84000): 6 个纯 Tail + 1 个 Lysis (无 Head/Connector -> 独立审查被 Tailocin guard 拦截，需依赖兄弟臂协同挽救)
    for k in range(6):
        _add(71000 + k * 1600, 72200 + k * 1600, 0.95, 2, 0.92)
    _add(81200, 82600, 0.92, 3, 0.88)

    scored = {
        "sp": {
            "phage_probs": np.asarray(ph_l, dtype=np.float32),
            "func10_probs": np.stack(f10_l, axis=0),
            "r2_core_probs": np.stack(r2_l, axis=0),
        }
    }
    base = [
        PredictedRegion("sp", 0, 35000, 0.97, 0.90, 12),
        PredictedRegion("sp", 52000, 65000, 0.95, 0.88, 5),
    ]
    relaxed = [
        PredictedRegion("sp", 70500, 84000, 0.88, 0.80, 5),
    ]
    res, stats = rescue_and_filter_regions_with_judge(
        base,
        relaxed,
        {"sp": orfs},
        scored,
        enable_topology_postprocess=True,
        enable_sibling_arm_rescue=True,
    )
    assert stats["sibling_rescued"] == 1
    assert stats["topology_bridged"] == 2
    assert len(res) == 1
    assert res[0].start_bp == 0 and res[0].end_bp == 84000


def test_absorb_companion_subbin_peaks_recovers_early_arm_and_blocks_redundant_head():
    from src.phage_discovery.inference.judge_region_refiner import absorb_companion_subbin_peaks

    prof = np.zeros(220, dtype=np.float32)  # 44,000 bp (200bp/bin)
    # 主结构噬菌体: [16000..26000] (bins 80..130)
    prof[80:130] = 0.95
    # 左侧隔 3000bp 窄谷 [13000..16000] 存在强伴生早区高峰 [7600..13000] (5400bp, bins 38..65)
    prof[38:65] = 0.92
    # 右侧隔 7000bp 深零谷存在另一独立含 Head 核心次级峰 [33000..38000] (bins 165..190) -> 绝不能误吸纳
    prof[165:190] = 0.94

    orfs = [
        (8000, 9200, 1, "M" * 60),     # 0: 伴生早区 Integrase P4
        (9500, 12600, 1, "M" * 60),    # 1: 伴生早区复制调控 cls5
        (13400, 14400, 1, "M" * 60),   # 2: 窄谷内过渡基因 (非宿主阻断)
        (16200, 20000, 1, "M" * 60),   # 3: 主核 Head cls0
        (20200, 25500, 1, "M" * 60),   # 4: 主核 Tail cls2
        (27000, 29000, 1, "M" * 60),   # 5: 右谷 Host 1
        (29200, 31000, 1, "M" * 60),   # 6: 右谷 Host 2
        (31200, 32600, 1, "M" * 60),   # 7: 右谷 Host 3
        (33200, 37600, 1, "M" * 60),   # 8: 右侧独立 Head 核心 cls0 (CHIM_0026 类场景)
    ]
    ph = np.array([0.90, 0.88, 0.45, 0.98, 0.97, 0.04, 0.05, 0.03, 0.96], dtype=np.float32)
    f10 = np.zeros((9, 10), dtype=np.float32)
    f10[0, 4] = 0.88
    f10[1, 5] = 0.86
    f10[2, 6] = 0.50
    f10[3, 0] = 0.95
    f10[4, 2] = 0.94
    f10[5, 9] = 0.70
    f10[6, 9] = 0.70
    f10[7, 9] = 0.70
    f10[8, 0] = 0.90
    r2 = f10[:, :5].copy()

    regs = [PredictedRegion("ctg_comp", 16000, 26000, peak_score=0.95, mean_score=0.90, window_count=6)]
    out, absorbed = absorb_companion_subbin_peaks(
        regs,
        {"ctg_comp": orfs},
        {"ctg_comp": {"phage_probs": ph, "func10_probs": f10, "r2_core_probs": r2}},
        {"ctg_comp": prof},
        {"ctg_comp": 44000},
    )
    assert absorbed == 1
    assert len(out) == 1
    assert out[0].start_bp == 7600
    assert out[0].end_bp == 26000


def test_snap_split_core_orfs_recovers_tail_cut_and_protects_tandem_junction():
    from src.phage_discovery.inference.judge_region_refiner import snap_split_core_orfs

    prof = np.zeros(200, dtype=np.float32)
    prof[30:90] = 0.92
    # 模拟 K-12 Qin 左缘渐弱但存在微弱 DNA 残余支持 (0.10 >= 0.05) 的 Tail ORF 跨界段 [4800..6000]
    prof[24:30] = 0.10
    # 前噬菌体 2 右缘外侧处于纯粹零 DNA 死区 (sub=0.00)，模拟人工拼接融合跨界 ORF [29800..31200]
    prof[100:150] = 0.92

    orfs = [
        (4800, 6200, 1, "M" * 60),     # 0: 被左缘 6000 劈断 1200bp 的 Tail (r2=0.74, out_sub=0.10)
        (17000, 18000, 1, "M" * 60),   # 1: tandem 1 最末形态基因
        (18100, 19200, 1, "M" * 60),   # 2: tandem 2 起始
        (29800, 31200, 1, "M" * 60),   # 3: 右端跨进零 DNA 死区的嵌合 ORF (out_sub=0.00 -> 严禁外吞)
    ]
    ph = np.array([0.98, 0.97, 0.96, 0.95], dtype=np.float32)
    f10 = np.zeros((4, 10), dtype=np.float32)
    f10[0, 2] = 0.45
    f10[1, 0] = 0.90
    f10[2, 2] = 0.88
    f10[3, 2] = 0.85
    r2 = np.zeros((4, 5), dtype=np.float32)
    r2[0, 2] = 0.74
    r2[1, 0] = 0.92
    r2[2, 2] = 0.88
    r2[3, 2] = 0.85

    regs = [
        PredictedRegion("ctg_s", 6000, 18000, peak_score=0.95, mean_score=0.90, window_count=6),
        PredictedRegion("ctg_s", 18000, 30000, peak_score=0.95, mean_score=0.90, window_count=6),
    ]
    out, snapped = snap_split_core_orfs(
        regs,
        {"ctg_s": orfs},
        {"ctg_s": {"phage_probs": ph, "func10_probs": f10, "r2_core_probs": r2}},
        {"ctg_s": prof},
    )
    assert snapped == 1
    assert (out[0].start_bp, out[0].end_bp) == (4800, 18000)
    assert (out[1].start_bp, out[1].end_bp) == (18000, 30000)


def test_close_flanks_to_integrase_anchors_respects_att_lock_tandem_dead_moat_and_is_filter():
    from src.phage_discovery.inference.judge_region_refiner import close_flanks_to_integrase_anchors

    prof_a = np.zeros(180, dtype=np.float32)
    prof_a[60:110] = 0.95
    prof_a[110:124] = 0.30  # 右过渡段具有 DNA 残余支持 [22000..24800]
    orfs_a = [
        (4500, 5600, 1, "M" * 60),    # 0: 左外部 IS 转座酶 (cls8=0.90, p4=0.72 -> 被鉴别过滤)
        (6000, 11800, 1, "M" * 60),   # 1: 中间冷沟宿主基因 (ph=0.08)
        (12500, 15000, 1, "M" * 60),  # 2: 主核 Head
        (18000, 21500, 1, "M" * 60),  # 3: 主核 Tail
        (22200, 24000, 1, "M" * 60),  # 4: 过渡高蛋白早期基因 (ph=0.86)
        (24100, 25100, 1, "M" * 60),  # 5: 真 Integrase 1 (cls4=0.92, cls8=0.02)
        (25250, 26000, 1, "M" * 60),  # 6: 紧邻真 Integrase 簇 2 (<=500bp 延拓)
    ]
    ph_a = np.array([0.85, 0.08, 0.98, 0.97, 0.86, 0.94, 0.92], dtype=np.float32)
    f10_a = np.zeros((7, 10), dtype=np.float32)
    f10_a[0, 8], f10_a[0, 4] = 0.90, 0.72
    f10_a[1, 9] = 0.75
    f10_a[2, 0] = 0.92
    f10_a[3, 2] = 0.90
    f10_a[4, 5] = 0.85
    f10_a[5, 4], f10_a[5, 8] = 0.92, 0.02
    f10_a[6, 4], f10_a[6, 8] = 0.90, 0.01

    prof_b = np.zeros(120, dtype=np.float32)
    prof_b[40:80] = 0.92
    orfs_b = [
        (2000, 3200, 1, "M" * 60),
        (8200, 15500, 1, "M" * 60),
    ]
    ph_b = np.array([0.95, 0.98], dtype=np.float32)
    f10_b = np.zeros((2, 10), dtype=np.float32)
    f10_b[0, 4] = 0.95
    f10_b[1, 0] = 0.95

    regs = [
        PredictedRegion("ctg_a", 12000, 22000, peak_score=0.95, mean_score=0.90, window_count=6),
        PredictedRegion("ctg_b", 8000, 16000, peak_score=0.95, mean_score=0.90, window_count=5),
    ]
    out, closed = close_flanks_to_integrase_anchors(
        regs,
        {"ctg_a": orfs_a, "ctg_b": orfs_b},
        {
            "ctg_a": {"phage_probs": ph_a, "func10_probs": f10_a, "r2_core_probs": f10_a[:, :5]},
            "ctg_b": {"phage_probs": ph_b, "func10_probs": f10_b, "r2_core_probs": f10_b[:, :5]},
        },
        {"ctg_a": prof_a, "ctg_b": prof_b},
        {"ctg_a": 36000, "ctg_b": 24000},
        locked_keys={"ctg_b:8000-16000"},
    )
    assert closed == 1
    by_c = {r.contig_id: r for r in out}
    assert (by_c["ctg_a"].start_bp, by_c["ctg_a"].end_bp) == (12000, 26000)
    assert (by_c["ctg_b"].start_bp, by_c["ctg_b"].end_bp) == (8000, 16000)


