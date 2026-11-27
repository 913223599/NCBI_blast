# -*- coding: utf-8 -*-
"""
项目全维度能力补充验证测试集：
覆盖现有模块级单测之外的关键不变量与端到端闭环：
  1. 正反双链（Reverse-Complement）对称不变量：验证 attL/attR 1bp 对齐与 SubBin 解码的正反链镜像严格等价；
  2. 极端低质量/异常序列容错：验证 mixed-case soft-masked 序列零数值偏差、长 N-gap 拼接断裂隔离及超短 (<3kb) 序列安全兜底；
  3. 超长单 Contig 故意“正中横劈前噬菌体”流式分段无缝还原：验证 chunk 边界切入前噬菌体内部时，结合全局上下文与主归属去重完整收敛为 1 条全长区段；
  4. 生产 CLI (scripts/predict_unified.py) 全产物落盘一致性闭环（regions.tsv / regions.gff3 / prophages.fna / scan_summary.json）。
"""
from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Dict, List

import numpy as np

from src.phage_discovery.benchmark.metrics import (
    PredictedRegion,
    WindowPrediction,
    decode_subwindow_probs_to_regions,
)
from src.phage_discovery.features.window_features import (
    compute_sequence_global_context,
    extract_contig_windows,
)
from src.phage_discovery.inference.att_boundary_refiner import refine_regions_with_att_sites
from src.phage_discovery.inference.unified_model import UnifiedPhageModel
import pytest

pytestmark = pytest.mark.ml

_COMP = str.maketrans("ACGTNacgtn", "TGCANtgcan")


def _revcomp(seq: str) -> str:
    return seq.translate(_COMP)[::-1]


def _synth_dna(length: int, seed: int = 17) -> str:
    rng = np.random.default_rng(seed)
    bases = np.array(["A", "C", "G", "T"])
    return "".join(bases[rng.integers(0, 4, size=length)].tolist())


def test_reverse_complement_symmetry_invariance_for_subbin_decode_and_att_refiner():
    # 1) 验证 SubBin 连续曲线解码严格遵循左右反转不变性
    seq_len = 25000
    win_preds_f: List[WindowPrediction] = []
    sub_probs_f: List[np.ndarray] = []
    # 构建 9 个 5kb 滑窗 (step=2500)
    for idx in range(9):
        s = idx * 2500
        e = s + 5000
        wp_score = 0.96 if (2 <= idx <= 5) else 0.05
        win_preds_f.append(WindowPrediction("ctg", s, e, score=wp_score))
        arr = np.full(25, 0.02, dtype=np.float32)
        if 2 <= idx <= 5:
            arr[:] = 0.94
        elif idx == 1:
            arr[18:] = 0.88  # 左过渡边缘 (s=2500 + 18*200 = 6100)
        elif idx == 6:
            arr[:7] = 0.88   # 右过渡边缘 (s=15000 + 7*200 = 16400)
        sub_probs_f.append(arr)

    regs_f = decode_subwindow_probs_to_regions(
        win_preds_f,
        np.stack(sub_probs_f, axis=0),
        sub_threshold=0.45,
        smooth_profile=False,
    )
    assert len(regs_f) == 1

    # 精确镜像所有窗口坐标及 25-bin 子序列
    win_preds_r: List[WindowPrediction] = []
    sub_probs_r: List[np.ndarray] = []
    for wp, sp_row in reversed(list(zip(win_preds_f, sub_probs_f))):
        win_preds_r.append(WindowPrediction("ctg", seq_len - wp.end_bp, seq_len - wp.start_bp, score=wp.score))
        sub_probs_r.append(sp_row[::-1].copy())

    regs_r = decode_subwindow_probs_to_regions(
        win_preds_r,
        np.stack(sub_probs_r, axis=0),
        sub_threshold=0.45,
        smooth_profile=False,
    )
    assert len(regs_r) == 1
    assert regs_r[0].start_bp == seq_len - regs_f[0].end_bp
    assert regs_r[0].end_bp == seq_len - regs_f[0].start_bp

    # 2) 验证 attL/attR 1bp 直接重复对齐严格满足正反互补不变性
    dna = list(_synth_dna(18000, seed=909))
    att = "GACTGGCATTCGATCAGT"  # 18 bp
    tl, tr = 2813, 15187
    dna[tl - 1] = "A"
    dna[tl + len(att)] = "A"
    dna[tr - len(att) - 1] = "T"
    dna[tr] = "T"
    dna[tl : tl + len(att)] = list(att)
    dna[tr - len(att) : tr] = list(att)
    fwd_seq = "".join(dna)
    rev_seq = _revcomp(fwd_seq)

    orfs_f = [
        (900, 1800, 1, "M" * 50),
        (3300, 5000, 1, "M" * 60),
        (13500, 14900, 1, "M" * 60),
        (15800, 16900, 1, "M" * 50),
    ]
    ph_f = np.array([0.04, 0.96, 0.94, 0.03], dtype=np.float32)
    f10_f = np.zeros((4, 10), dtype=np.float32)
    f10_f[0, 9] = 0.82
    f10_f[1, 0] = 0.92
    f10_f[2, 4] = 0.91
    f10_f[3, 9] = 0.85

    raw_f = [PredictedRegion("ctg", 2600, 15400, peak_score=0.95, mean_score=0.90, window_count=6)]
    out_f, cnt_f = refine_regions_with_att_sites(
        raw_f,
        {"ctg": fwd_seq},
        {"ctg": orfs_f},
        {"ctg": {"phage_probs": ph_f, "func10_probs": f10_f}},
    )
    assert cnt_f == 1 and (out_f[0].start_bp, out_f[0].end_bp) == (tl, tr)

    L = len(fwd_seq)
    orfs_r = [(L - ge, L - gs, -st, aa) for (gs, ge, st, aa) in reversed(orfs_f)]
    ph_r = ph_f[::-1].copy()
    f10_r = f10_f[::-1].copy()
    raw_r = [PredictedRegion("ctg", L - 15400, L - 2600, peak_score=0.95, mean_score=0.90, window_count=6)]
    out_r, cnt_r = refine_regions_with_att_sites(
        raw_r,
        {"ctg": rev_seq},
        {"ctg": orfs_r},
        {"ctg": {"phage_probs": ph_r, "func10_probs": f10_r}},
    )
    assert cnt_r == 1
    assert out_r[0].start_bp == L - out_f[0].end_bp
    assert out_r[0].end_bp == L - out_f[0].start_bp


def test_hostile_inputs_soft_masked_ngap_and_short_contig_stability():
    # 1) 大小写混合 soft-masked 与全大写相比应得出严格零数值差异 (且无 NaN/Inf)
    upper_seq = _synth_dna(12000, seed=42)
    mixed_seq = "".join(ch.lower() if i % 3 == 0 else ch for i, ch in enumerate(upper_seq))

    g_u_kmer, g_u_gc, _ = compute_sequence_global_context(upper_seq)
    g_m_kmer, g_m_gc, _ = compute_sequence_global_context(mixed_seq)
    assert np.allclose(g_u_kmer, g_m_kmer, atol=1e-7)
    assert abs(g_u_gc - g_m_gc) < 1e-9

    f_up = extract_contig_windows("c_u", upper_seq, feature_profile="v4")["features"]
    f_mx = extract_contig_windows("c_m", mixed_seq, feature_profile="v4")["features"]
    assert np.isfinite(f_up).all() and np.isfinite(f_mx).all()
    assert np.max(np.abs(f_up - f_mx)) < 1e-6

    # 2) 大段 N-gap 间隙绝不引发虚假 1bp att 重复碰撞，也不会触发异常
    gapped_seq = ("ACGT" * 700) + ("N" * 600) + _synth_dna(8000, seed=11) + ("N" * 600) + ("TGCA" * 700)
    res_gap, cnt_gap = refine_regions_with_att_sites(
        [PredictedRegion("ctg_gap", 2600, 12200, 0.90, 0.85, 4)],
        {"ctg_gap": gapped_seq},
        {"ctg_gap": [(4000, 6000, 1, "M" * 40)]},
        {"ctg_gap": {"phage_probs": np.array([0.92], dtype=np.float32), "func10_probs": np.ones((1, 10), dtype=np.float32) * 0.1}},
    )
    assert cnt_gap == 0 and (res_gap[0].start_bp, res_gap[0].end_bp) == (2600, 12200)

    # 3) 超短序列 (0 bp / 2000 bp < win_size) 与纯 N 序列特征提取安全兜底无 NaN
    tiny = _synth_dna(2000, seed=3)
    res_tiny = extract_contig_windows("c_tiny", tiny, feature_profile="v4")
    assert res_tiny["features"].shape[0] == 1 and np.isfinite(res_tiny["features"]).all()
    all_n = "N" * 5200
    res_n = extract_contig_windows("c_alln", all_n, feature_profile="v4")
    assert res_n["features"].shape[0] >= 1 and np.isfinite(res_n["features"]).all()


def test_streaming_direct_cut_across_prophage_recovers_single_intact_region(tmp_path: Path):
    """
    构造 30 kb 超长 Contig 并放置跨中心切割点 (15,000 bp) 的真实形态区段 [10,400 .. 19,600]，
    以 chunk_max_bp=15,000 / long_contig_overlap_bp=6,000 强制在区段中央切分两段扫描，
    验证流式拼接去重仲裁严格恢复 1 条完整区间且不发生分裂或重复报警。
    """
    class _StubScanner:
        model_version = "v4"
        feature_profile = "v4"
        win_size = 5000
        step_size = 2500
        workers = 1
        seed_threshold = 0.85
        extend_threshold = 0.50
        sub_threshold = 0.45
        merge_gap_bp = 3000
        min_region_bp = 3000
        plateau_min_windows = 0
        plateau_second_threshold = None
        smooth_sub_profile = False
        refine_pad_bp = 3000

    seq = _synth_dna(30000, seed=2029)
    fa_path = tmp_path / "cut_across.fna"
    fa_path.write_text(f">chr_cut\n{seq}\n", encoding="utf-8")

    class _CutBackboneModel(UnifiedPhageModel):
        def _run_dna_backbone(self, contig_seqs: Dict[str, str], *, executor=None):
            del executor
            base_regs: List[PredictedRegion] = []
            win_preds: List[WindowPrediction] = []
            probs_rows: List[np.ndarray] = []
            for cid, sub_s in contig_seqs.items():
                offset = seq.index(sub_s)
                loc_l = max(0, 10400 - offset)
                loc_r = min(len(sub_s), 19600 - offset)
                win_preds.append(WindowPrediction(cid, 0, min(5000, len(sub_s)), 0.92 if loc_r - loc_l >= 3000 else 0.05))
                probs_rows.append(np.full(25, 0.90 if loc_r - loc_l >= 3000 else 0.01, dtype=np.float32))
                if loc_r - loc_l >= 3000:
                    base_regs.append(PredictedRegion(cid, loc_l, loc_r, peak_score=0.95, mean_score=0.90, window_count=4))
            return win_preds, np.stack(probs_rows, axis=0), None, base_regs, {"dna_feature_sec": 0.01, "dna_infer_decode_sec": 0.01}

    upm = _CutBackboneModel(dna_scanner=_StubScanner(), judge_bundle=None, active_experts=("boundary",))  # type: ignore[arg-type]

    out_dir = tmp_path / "stream_out"
    res = upm.scan_fasta_streaming(
        fa_path,
        out_dir,
        chunk_max_bp=15000,
        long_contig_overlap_bp=6000,
        resume=False,
        export_outputs=True,
    )
    assert len(res.regions) == 1
    assert (res.regions[0].start_bp, res.regions[0].end_bp) == (10400, 19600)
    assert (out_dir / "regions.tsv").is_file()
    assert (out_dir / "prophages.fna").is_file()
    extracted = "".join(ln.strip() for ln in (out_dir / "prophages.fna").read_text(encoding="utf-8").splitlines()[1:])
    assert extracted == seq[10400:19600]


def test_predict_unified_cli_end_to_end_exports_consistent_bio_artifacts(tmp_path: Path, monkeypatch):
    import scripts.predict_unified as cli_mod

    dna = list(_synth_dna(20000, seed=808))
    att = "AGTCATGCTGACGTAGCT"
    true_l, true_r = 4123, 15890
    dna[true_l - 1] = "A"
    dna[true_l + len(att)] = "A"
    dna[true_r - len(att) - 1] = "T"
    dna[true_r] = "T"
    dna[true_l : true_l + len(att)] = list(att)
    dna[true_r - len(att) : true_r] = list(att)
    pos_seq = "".join(dna)
    neg_seq = _synth_dna(12000, seed=809)

    fa_in = tmp_path / "cli_input.fasta"
    fa_in.write_text(f">pos_ctg\n{pos_seq}\n>neg_ctg\n{neg_seq}\n", encoding="utf-8")

    class _StubScanner:
        model_version = "v4"
        feature_profile = "v4"
        win_size = 5000
        step_size = 2500
        workers = 1
        seed_threshold = 0.85
        extend_threshold = 0.50
        sub_threshold = 0.45
        merge_gap_bp = 3000
        min_region_bp = 3000
        plateau_min_windows = 0
        plateau_second_threshold = None
        smooth_sub_profile = False
        refine_pad_bp = 3000

    class _DummyModel(UnifiedPhageModel):
        @classmethod
        def from_models_root(cls, *args, **kwargs):
            del args, kwargs
            m = cls(dna_scanner=_StubScanner(), judge_bundle={"unified_mode": True, "judge_arch": "unified_v4_3"})  # type: ignore[arg-type]
            m.model_version = "Unified V4.3"
            m.judge_arch = "unified_v4_3"
            return m

        def _run_dna_backbone(self, contig_seqs, executor=None):
            del contig_seqs, executor
            wps = [
                WindowPrediction("pos_ctg", 4000, 9000, 0.96),
                WindowPrediction("neg_ctg", 0, 5000, 0.02),
            ]
            sp = np.zeros((2, 25), dtype=np.float32)
            sp[0] = 0.92
            regs = [PredictedRegion("pos_ctg", 4000, 16000, 0.96, 0.92, 5)]
            return wps, sp, None, regs, {"dna_feature_sec": 0.01, "dna_infer_decode_sec": 0.01}

    orfs_map = {
        "pos_ctg": [
            (1000, 2200, 1, "M" * 40),
            (4600, 6800, 1, "M" * 60),
            (13800, 15500, 1, "M" * 60),
            (16800, 18000, 1, "M" * 40),
        ]
    }
    ph = np.array([0.05, 0.97, 0.95, 0.03], dtype=np.float32)
    f10 = np.zeros((4, 10), dtype=np.float32)
    f10[0, 9] = 0.85
    f10[1, 0] = 0.94
    f10[2, 4] = 0.93
    f10[3, 9] = 0.88

    import src.phage_discovery.inference.unified_model as um_mod

    monkeypatch.setattr(cli_mod, "UnifiedPhageModel", _DummyModel)
    monkeypatch.setattr(um_mod, "extract_contig_orfs_pyrodigal", lambda *a, **kw: orfs_map)
    monkeypatch.setattr(
        um_mod,
        "score_contigs_with_judge_bundle",
        lambda *a, **kw: {"pos_ctg": {"phage_probs": ph, "func10_probs": f10, "r2_core_probs": f10[:, :5]}},
    )

    out_dir = tmp_path / "cli_out"
    rc = cli_mod.main([
        "--fasta", str(fa_in),
        "--out-dir", str(out_dir),
        "--models-root", str(tmp_path),
        "--chunk-mb", "0",
        "--workers", "1",
        "--device", "cpu",
    ])
    assert rc == 0

    rows = list(csv.DictReader((out_dir / "regions.tsv").open("r", encoding="utf-8"), delimiter="\t"))
    assert len(rows) == 1
    assert rows[0]["contig_id"] == "pos_ctg"
    assert (int(rows[0]["start_bp"]), int(rows[0]["end_bp"])) == (true_l, true_r)

    gff_lines = [ln for ln in (out_dir / "regions.gff3").read_text(encoding="utf-8").splitlines() if ln and not ln.startswith("#")]
    assert len(gff_lines) == 1
    cols = gff_lines[0].split("\t")
    assert cols[0] == "pos_ctg" and int(cols[3]) == true_l + 1 and int(cols[4]) == true_r

    fna_seq = "".join(ln.strip() for ln in (out_dir / "prophages.fna").read_text(encoding="utf-8").splitlines()[1:])
    assert fna_seq == pos_seq[true_l:true_r]

    summary = json.loads((out_dir / "scan_summary.json").read_text(encoding="utf-8"))
    rs = summary["routing_stats"]["rescue_stats"]
    assert rs["att_aligned"] == 1
    assert "companion_absorbed" in rs and "core_orfs_snapped" in rs and "integrase_closed" in rs


def test_unified_model_orchestrates_companion_coresnap_att_and_integrase_pipeline(monkeypatch):
    """
    全管线协同验证：在单一 Contig 上同时触发伴生次级峰吸纳、核心形态断口校准与未锁定整合酶极点闭环，
    且确认与已精准 att 对齐区域之间的保护锁正常工作。
    """
    import src.phage_discovery.inference.unified_model as um_mod

    dna = list(_synth_dna(48000, seed=31415))
    # Contig 上存在 1 条真实主前噬菌体:
    # - 左侧伴生早区高峰 [9000..14200] (5.2kb, 无冗余 Head), 隔 [14200..17400] (3.2kb 窄低谷)
    # - 主结构核 [17400..27400] (Head + Tail, 但 Tail 在 17400 附近被轻微劈断)
    # - 右侧未锁死 att, 外接连续早期蛋白与真 Integrase 极点直达 34200
    seq = "".join(dna)

    class _StubScanner:
        model_version = "v4"
        feature_profile = "v4"
        win_size = 5000
        step_size = 2500
        workers = 1
        seed_threshold = 0.85
        extend_threshold = 0.50
        sub_threshold = 0.45
        merge_gap_bp = 3000
        min_region_bp = 3000
        plateau_min_windows = 0
        plateau_second_threshold = None
        smooth_sub_profile = False
        refine_pad_bp = 3000

    # 构建 200bp 分辨率子块曲线 (240 bins = 48,000 bp)
    sub_bins = np.zeros(240, dtype=np.float32)
    sub_bins[45:71] = 0.92   # [9000..14200] 伴生早期次级强峰
    sub_bins[87:137] = 0.95  # [17400..27400] 主核
    sub_bins[137:158] = 0.25 # [27400..31600] 右侧早期过渡 DNA 残余支持

    # 将 sub_bins 映射到每 2500 bp 滑窗 25-bin 矩阵
    wps: List[WindowPrediction] = []
    sp_rows: List[np.ndarray] = []
    for pos in range(0, 48000 - 5000 + 1, 2500):
        b0 = pos // 200
        win_sub = sub_bins[b0 : b0 + 25].copy()
        wp_sc = 0.96 if np.max(win_sub) > 0.80 else 0.04
        wps.append(WindowPrediction("ctg_full_pipe", pos, pos + 5000, wp_sc))
        sp_rows.append(win_sub)

    class _PipeModel(UnifiedPhageModel):
        def _run_dna_backbone(self, contig_seqs: Dict[str, str], *, executor=None):
            del contig_seqs, executor
            base = [PredictedRegion("ctg_full_pipe", 17400, 27400, 0.96, 0.90, 5)]
            return wps, np.stack(sp_rows, axis=0), None, base, {"dna_feature_sec": 0.01, "dna_infer_decode_sec": 0.01}

    orfs = [
        (9300, 12000, 1, "M" * 50),    # 0: 伴生峰早期调控 (cls5)
        (12200, 14000, 1, "M" * 50),   # 1: 伴生峰 (cls6)
        (15000, 16200, 1, "M" * 50),   # 2: 窄低谷内非强宿主过渡基因
        (17800, 21000, 1, "M" * 60),   # 3: 主核 Head
        (23000, 26800, 1, "M" * 60),   # 4: 主核 Tail
        (27600, 31200, 1, "M" * 60),   # 5: 右外高分早期基因 (ph=0.88)
        (31500, 34200, 1, "M" * 60),   # 6: 右外极点真 Integrase (cls4 > cls8)
    ]
    ph = np.array([0.88, 0.86, 0.45, 0.98, 0.97, 0.88, 0.95], dtype=np.float32)
    f10 = np.zeros((7, 10), dtype=np.float32)
    f10[0, 5] = 0.85
    f10[1, 6] = 0.82
    f10[2, 6] = 0.45
    f10[3, 0] = 0.94
    f10[4, 2] = 0.92
    f10[5, 5] = 0.85
    f10[6, 4], f10[6, 8] = 0.94, 0.02

    monkeypatch.setattr(um_mod, "extract_contig_orfs_pyrodigal", lambda *a, **kw: {"ctg_full_pipe": orfs})
    monkeypatch.setattr(
        um_mod,
        "score_contigs_with_judge_bundle",
        lambda *a, **kw: {"ctg_full_pipe": {"phage_probs": ph, "func10_probs": f10, "r2_core_probs": f10[:, :5]}},
    )

    upm = _PipeModel(dna_scanner=_StubScanner(), judge_bundle={"unified_mode": True, "judge_arch": "unified_v4_3"})  # type: ignore[arg-type]
    res = upm.scan_sequences({"ctg_full_pipe": seq})

    assert len(res.regions) == 1
    assert res.regions[0].start_bp == 9000   # 伴生次级早区峰已吸纳
    assert res.regions[0].end_bp == 34200    # 右侧通过真 Integrase 极点完成闭环延拓
    rs = res.routing_stats["rescue_stats"]
    assert rs["companion_absorbed"] == 1
    assert rs["integrase_closed"] == 1


def test_model_registry_discovers_unified_v4_3_calibration_threshold(tmp_path: Path):
    from src.analysis.phage_finder.model_registry import discover_available_models

    uni_root = tmp_path / "models" / "full_v4"
    s12 = uni_root / "stage1_2"
    judge = uni_root / "orf_judge_unified"
    s12.mkdir(parents=True)
    judge.mkdir(parents=True)

    (s12 / "stage1_2.pt").write_bytes(b"pt")
    (s12 / "context_refiner.pt").write_bytes(b"ctx")
    (s12 / "subbin_refiner.pt").write_bytes(b"sub")
    (s12 / "stage1_2_meta.json").write_text(
        json.dumps({"params": 150000, "feature_profile": "stage1", "func_dim": 10, "use_subbin_refiner": True}),
        encoding="utf-8",
    )
    (s12 / "stage1_2_report.json").write_text(
        json.dumps({"decoder_tuned_on_val": {"seed_threshold": 0.95, "extend_threshold": 0.30, "sub_threshold": 0.45}}),
        encoding="utf-8",
    )
    (judge / "unified_judge_seq.pt").write_bytes(b"jseq")
    (judge / "orf_judge_statonly.pt").write_bytes(b"jstat")
    (judge / "unified_summary.json").write_text(
        json.dumps({"arch": "unified_v4_3", "schema_version": "1.0", "total_params": 200000, "model_version": "Unified V4.3"}),
        encoding="utf-8",
    )

    found = discover_available_models(project_root=tmp_path)
    uni_items = [m for m in found if m["has_unified_judge"]]
    assert len(uni_items) == 1
    assert uni_items[0]["version"] == "Unified V4.3"
    assert abs(float(uni_items[0]["decoder_defaults"]["sub_threshold"]) - 0.45) < 1e-6
