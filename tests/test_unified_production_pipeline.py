# -*- coding: utf-8 -*-
"""UnifiedPhageModel 流式分片、断点续跑与标准产物导出单元测试。"""
from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np

from src.phage_discovery.benchmark.metrics import PredictedRegion
from src.phage_discovery.inference.report_exporter import export_unified_scan_outputs
from src.phage_discovery.inference.unified_model import UnifiedPhageModel, plan_long_contig_segments
import pytest

pytestmark = pytest.mark.ml


class _FakeStreamingScanner:
    """模拟最小 DNA 扫描器用于验证流式分片与断点续跑逻辑。"""

    def __init__(self):
        self.win_size = 5000
        self.step_size = 2500
        self.model_version = "v4"
        self.feature_profile = "base"
        self.workers = 2
        self.seed_threshold = 0.80
        self.extend_threshold = 0.60
        self.sub_threshold = 0.50
        self.merge_gap_bp = 3000
        self.min_region_bp = 3000
        self.plateau_min_windows = 2
        self.plateau_second_threshold = 0.45
        self.smooth_sub_profile = True
        self.refine_pad_bp = 2000
        self.seen_contig_batches: List[List[str]] = []

    def _predict_windows_with_profiles(
        self,
        codes_arr: np.ndarray,
        len_arr: np.ndarray,
        feats_arr: np.ndarray,
        *,
        orf_tokens=None,
        orf_counts=None,
        contig_ids=None,
        starts=None,
        ends=None,
        return_orf_preds: bool = False,
    ) -> Tuple[np.ndarray, np.ndarray, None]:
        del codes_arr, len_arr, feats_arr, orf_tokens, orf_counts, starts, ends, return_orf_preds
        assert contig_ids is not None
        cids_arr = contig_ids
        n = len(cids_arr)
        self.seen_contig_batches.append(sorted(set(str(x) for x in cids_arr)))
        win_scores = np.zeros(n, dtype=np.float32)
        sub_probs = np.zeros((n, 25), dtype=np.float32)
        for idx, cid in enumerate(cids_arr):
            if str(cid).startswith("phage"):
                win_scores[idx] = 0.92
                sub_probs[idx, :] = 0.92
            else:
                win_scores[idx] = 0.05
                sub_probs[idx, :] = 0.05
        return win_scores, sub_probs, None


def _write_test_fasta(path: Path, seqs: Dict[str, str]) -> Path:
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        for cid, seq in seqs.items():
            fh.write(f">{cid}\n{seq}\n")
    return path


def test_report_exporter_writes_valid_tsv_gff3_fasta_and_summary(tmp_path: Path):
    seqs: Dict[str, str] = {
        "contigA": "A" * 100 + "CGTA" * 500 + "T" * 100,
        "contigB": "G" * 2000,
    }
    regs = [
        PredictedRegion("contigA", 100, 2100, peak_score=0.96, mean_score=0.89, window_count=2),
    ]
    anns = {
        "contigA:100-2100": {
            "n_orfs": 4,
            "mean_phage_prob": 0.8912,
            "max_p9_defense_prob": 0.1200,
            "r2_core_completeness_sum": 3.45,
            "r2_core_active_count": 3,
            "completeness_class": "complete_structural_core",
            "active_modules": ["head_packaging", "tail", "lysis"],
        }
    }
    out_paths = export_unified_scan_outputs(
        tmp_path,
        regions=regs,
        region_annotations=anns,
        contig_seqs=seqs,
        routing_stats={"total_contigs": 2, "protein_skip_ratio": 0.5},
        timings_sec={"total_sec": 1.23},
        total_bp=len(seqs["contigA"]) + len(seqs["contigB"]),
        total_windows=3,
    )
    assert out_paths["tsv"].is_file()
    assert out_paths["gff3"].is_file()
    assert out_paths["fasta"].is_file()
    assert out_paths["summary"].is_file()

    with out_paths["tsv"].open("r", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh, delimiter="\t"))
    assert len(rows) == 1
    assert rows[0]["contig_id"] == "contigA"
    assert rows[0]["start_bp"] == "100" and rows[0]["end_bp"] == "2100"
    assert rows[0]["completeness_class"] == "complete_structural_core"

    gff_lines = [ln for ln in out_paths["gff3"].read_text(encoding="utf-8").splitlines() if ln and not ln.startswith("#")]
    assert len(gff_lines) == 1
    cols = gff_lines[0].split("\t")
    assert cols[0] == "contigA" and cols[2] == "prophage"
    # GFF3 为 1-based inclusive 坐标
    assert cols[3] == "101" and cols[4] == "2100"

    fa_text = out_paths["fasta"].read_text(encoding="utf-8")
    assert ">contigA:100-2100" in fa_text
    assert "".join(fa_text.splitlines()[1:]) == seqs["contigA"][100:2100]

    summary = json.loads(out_paths["summary"].read_text(encoding="utf-8"))
    assert summary["region_count"] == 1
    assert summary["routing_stats"]["protein_skip_ratio"] == 0.5


def test_streaming_scan_matches_single_pass_and_resumes_from_checkpoint(tmp_path: Path, monkeypatch):
    import concurrent.futures

    def _fake_extract_worker(task):
        cid, seq, win_size, step_size, _eo, _fp = task
        del win_size, step_size
        n_win = max(1, len(seq) // 5000)
        starts = [i * 2500 for i in range(n_win)]
        ends = [min(len(seq), s + 5000) for s in starts]
        return {
            "contig_id": cid,
            "starts": starts,
            "ends": ends,
            "features": np.zeros((n_win, 10), dtype=np.float32),
        }

    pool_init_calls = []

    class _SpyPool(concurrent.futures.ThreadPoolExecutor):
        def __init__(self, max_workers=None, **kwargs):
            del kwargs
            pool_init_calls.append(max_workers)
            super().__init__(max_workers=max_workers)

    monkeypatch.setattr("src.phage_discovery.inference.unified_model._extract_contig_worker", _fake_extract_worker)
    monkeypatch.setattr("src.phage_discovery.inference.unified_model.concurrent.futures.ProcessPoolExecutor", _SpyPool)

    seqs: Dict[str, str] = {
        "host_1": "ACGT" * 2000,
        "phage_1": "ATGC" * 2000,
        "host_2": "CGTA" * 2000,
        "phage_2": "GCTA" * 2000,
    }
    fa = _write_test_fasta(tmp_path / "sample.fna", seqs)

    scanner = _FakeStreamingScanner()
    upm = UnifiedPhageModel(dna_scanner=scanner, judge_bundle=None, active_experts=("boundary",))  # type: ignore[arg-type]

    full_res = upm.scan_fasta(fa)
    pool_init_calls.clear()

    out_stream = tmp_path / "stream_out"
    stream_res = upm.scan_fasta_streaming(fa, out_stream, chunk_max_bp=12000, resume=False)

    # 3 个 Chunk (8k, 16k->[phage_1], [host_2, phage_2]) 共只创建 1 次持久执行池
    assert len(pool_init_calls) == 1
    assert [(r.contig_id, r.start_bp, r.end_bp) for r in stream_res.regions] == [
        (r.contig_id, r.start_bp, r.end_bp) for r in full_res.regions
    ]
    assert (out_stream / "checkpoint.json").is_file()
    assert (out_stream / "chunks.jsonl").is_file()
    assert (out_stream / "regions.tsv").is_file()
    assert (out_stream / "regions.gff3").is_file()
    assert (out_stream / "prophages.fna").is_file()
    assert (out_stream / "scan_summary.json").is_file()

    # 模拟中断后断点续跑：保留前 2 条 contig 的 checkpoint，清空后面两行 chunks
    ckpt_path = out_stream / "checkpoint.json"
    ckpt = json.loads(ckpt_path.read_text(encoding="utf-8"))
    ckpt["completed_contigs"] = ["host_1", "phage_1"]
    ckpt_path.write_text(json.dumps(ckpt, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = (out_stream / "chunks.jsonl").read_text(encoding="utf-8").splitlines()
    kept_lines = [ln for ln in lines if json.loads(ln)["contig_id"] in {"host_1", "phage_1"}]
    (out_stream / "chunks.jsonl").write_text("\n".join(kept_lines) + "\n", encoding="utf-8")

    scanner.seen_contig_batches.clear()
    resumed_res = upm.scan_fasta_streaming(fa, out_stream, chunk_max_bp=12000, resume=True)
    # 恢复时不得重复扫描已完成的前两条 contig
    seen_flat = {c for batch in scanner.seen_contig_batches for c in batch}
    assert "host_1" not in seen_flat and "phage_1" not in seen_flat
    assert "host_2" in seen_flat and "phage_2" in seen_flat
    assert [(r.contig_id, r.start_bp, r.end_bp) for r in resumed_res.regions] == [
        (r.contig_id, r.start_bp, r.end_bp) for r in full_res.regions
    ]


def test_predict_unified_cli_parser_defaults():
    from scripts.predict_unified import _default_models_root, _parse_experts, build_arg_parser

    parser = build_arg_parser()
    args = parser.parse_args(["--fasta", "a.fna", "--out-dir", "out_dir", "--chunk-mb", "12"])
    assert args.chunk_mb == 12.0
    assert _parse_experts(args.experts) == ("boundary", "gray_rescue", "defense_func", "intact")
    assert _default_models_root().name == "full_v4"


def test_streaming_scan_splits_ultra_long_single_contig_with_resume_and_dedup(tmp_path: Path, monkeypatch):
    import concurrent.futures

    segments = plan_long_contig_segments(32000, chunk_max_bp=12000, win_size=5000, overlap_bp=5000)
    assert segments == [(0, 12000), (7000, 19000), (14000, 26000), (20000, 32000)]

    class _PatternScanner(_FakeStreamingScanner):
        def _predict_windows_with_profiles(
            self,
            codes_arr: np.ndarray,
            len_arr: np.ndarray,
            feats_arr: np.ndarray,
            *,
            orf_tokens=None,
            orf_counts=None,
            contig_ids=None,
            starts=None,
            ends=None,
            return_orf_preds: bool = False,
        ) -> Tuple[np.ndarray, np.ndarray, None]:
            del codes_arr, len_arr, orf_tokens, orf_counts, starts, ends, return_orf_preds
            assert contig_ids is not None
            cids_arr = contig_ids
            self.seen_contig_batches.append(sorted(set(str(x) for x in cids_arr)))
            # feats_arr[:, 0] 携带了窗口级置信度，feats_arr[:, 1..25] 为精确的逐 200bp bin 真实信号
            win_scores = feats_arr[:, 0].astype(np.float32)
            sub_probs = feats_arr[:, 1:26].astype(np.float32)
            return win_scores, sub_probs, None

    def _seq_based_extract_worker(task):
        cid, seq, win_size, step_size = task[:4]
        starts, ends = [], []
        pos = 0
        n = len(seq)
        while pos < n:
            e = min(n, pos + win_size)
            if e - pos < win_size // 2 and starts:
                starts.append(max(0, n - win_size))
                ends.append(n)
                break
            starts.append(pos)
            ends.append(e)
            if e == n:
                break
            pos += step_size

        feats = np.full((len(starts), 26), 0.05, dtype=np.float32)
        for wi, (s, e) in enumerate(zip(starts, ends)):
            wlen = max(1, e - s)
            wseq = seq[s:e]
            t_bins = 0
            for bi in range(25):
                bs = (wlen * bi) // 25
                be = (wlen * (bi + 1)) // 25
                seg = wseq[bs:be]
                if seg and ((seg.count("T") + seg.count("C")) / len(seg)) >= 0.7:
                    feats[wi, 1 + bi] = 0.95
                    t_bins += 1
            feats[wi, 0] = 0.94 if t_bins >= 10 else 0.05
        return {"contig_id": cid, "starts": starts, "ends": ends, "features": feats}

    class _SpyPool(concurrent.futures.ThreadPoolExecutor):
        pass

    monkeypatch.setattr("src.phage_discovery.inference.unified_model._extract_contig_worker", _seq_based_extract_worker)
    monkeypatch.setattr("src.phage_discovery.inference.unified_model.concurrent.futures.ProcessPoolExecutor", _SpyPool)

    # A 区间 [8400, 14400] (6kb, 对齐 200bp 网格且横跨段 0 切口 12000，在段 1 [7000,19000] 安全内部)
    # B 区间 [22000, 27000] (5kb, 横跨段 2 切口 26000，在段 3 [20000,32000] 安全内部)
    chars = list("AG" * 16000)
    for i in range(8400, 14400):
        chars[i] = "T"
    for i in range(22000, 27000):
        chars[i] = "C"
    long_seq = "".join(chars)
    assert len(long_seq) == 32000

    fa = _write_test_fasta(tmp_path / "long_chr.fna", {"long_chr": long_seq})
    scanner = _PatternScanner()
    upm = UnifiedPhageModel(dna_scanner=scanner, judge_bundle=None, active_experts=("boundary",))  # type: ignore[arg-type]

    full_res = upm.scan_fasta(fa)
    scanner.seen_contig_batches.clear()

    out_dir = tmp_path / "long_stream"
    res = upm.scan_fasta_streaming(
        fa,
        out_dir,
        chunk_max_bp=12000,
        long_contig_overlap_bp=5000,
        resume=False,
    )

    assert res.total_bp == 32000
    assert res.contigs_bp == {"long_chr": 32000}
    assert res.routing_stats["segmented_long_contigs"] == 1
    assert [(r.start_bp, r.end_bp) for r in res.regions] == [(8400, 14400), (22000, 27000)]
    assert [(r.start_bp, r.end_bp) for r in res.regions] == [(r.start_bp, r.end_bp) for r in full_res.regions]

    chunk_lines = [json.loads(ln) for ln in (out_dir / "chunks.jsonl").read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(chunk_lines) == 4
    assert all(rec["record_type"] == "segment" for rec in chunk_lines)

    summary = json.loads((out_dir / "scan_summary.json").read_text(encoding="utf-8"))
    assert summary["schema_version"] == "1.0"
    assert summary["region_count"] == 2

    # 模拟第 2 段结束后崩溃中断：恢复时只运行剩余第 2、3 分段
    ckpt_path = out_dir / "checkpoint.json"
    ckpt = json.loads(ckpt_path.read_text(encoding="utf-8"))
    ckpt["completed_contigs"] = []
    ckpt["completed_segments"] = {"long_chr": [0, 1]}
    ckpt_path.write_text(json.dumps(ckpt, ensure_ascii=False, indent=2), encoding="utf-8")
    kept_lines = [ln for ln in (out_dir / "chunks.jsonl").read_text(encoding="utf-8").splitlines() if json.loads(ln)["segment_idx"] in (0, 1)]
    (out_dir / "chunks.jsonl").write_text("\n".join(kept_lines) + "\n", encoding="utf-8")

    scanner.seen_contig_batches.clear()
    resumed = upm.scan_fasta_streaming(
        fa,
        out_dir,
        chunk_max_bp=12000,
        long_contig_overlap_bp=5000,
        resume=True,
    )
    resumed_seg_keys = {c for batch in scanner.seen_contig_batches for c in batch}
    assert resumed_seg_keys == {"long_chr__seg_2", "long_chr__seg_3"}
    assert [(r.start_bp, r.end_bp) for r in resumed.regions] == [(8400, 14400), (22000, 27000)]


def test_pyrodigal_single_pass_reuse_in_unified_pipeline(monkeypatch):
    import pyrodigal
    import src.phage_discovery.experts.expert_c_orf as ec_mod
    import src.phage_discovery.features.window_features as wf_mod
    from src.phage_discovery.inference.judge_region_refiner import extract_contig_orfs_pyrodigal
    from src.phage_discovery.student.orf_functional_judge import ORF_JUDGE_STAT_DIM, build_orf_functional_judge

    # 构造带清晰标准 ORFs 的 6.5 kb 序列
    orf_unit = "ATG" + "GCTAAAGGTACTGAAGTTCTGCGTACCATC" * 18 + "TAA" + "AACCGGTTAACCGGTT"
    seq = (orf_unit * 12)[:6500]
    expected_orfs = extract_contig_orfs_pyrodigal({"ctg1": seq}, workers=1)["ctg1"]
    assert len(expected_orfs) >= 5

    # 重置进程内单例以安装可计数 Pyrodigal 包装器
    wf_mod._GENE_FINDER = None
    ec_mod._GF = None
    orig_gf_cls = pyrodigal.GeneFinder
    call_counter = {"count": 0}

    class _CountingGeneFinder:
        def __init__(self, *args, **kwargs):
            self._inner = orig_gf_cls(*args, **kwargs)

        def find_genes(self, *args, **kwargs):
            call_counter["count"] += 1
            return self._inner.find_genes(*args, **kwargs)

    monkeypatch.setattr(pyrodigal, "GeneFinder", _CountingGeneFinder)

    class _MockStage1Scanner:
        win_size = 5000
        step_size = 2500
        model_version = "v4"
        feature_profile = "stage1"
        workers = 1
        seed_threshold = 0.80
        extend_threshold = 0.50
        sub_threshold = 0.50
        merge_gap_bp = 3000
        min_region_bp = 3000
        plateau_min_windows = 2
        plateau_second_threshold = 0.45
        smooth_sub_profile = True
        refine_pad_bp = 2000

        def _predict_windows_with_profiles(
            self,
            codes_arr: np.ndarray,
            len_arr: np.ndarray,
            feats_arr: np.ndarray,
            *,
            orf_tokens=None,
            orf_counts=None,
            contig_ids=None,
            starts=None,
            ends=None,
            return_orf_preds: bool = False,
        ):
            del codes_arr, len_arr, starts, ends, return_orf_preds
            assert contig_ids is not None
            assert feats_arr.shape[1] == 256
            assert orf_tokens is not None and orf_tokens.shape[-1] == 117
            assert orf_counts is not None and int(orf_counts[0]) > 0
            n = len(contig_ids)
            return np.full(n, 0.94, dtype=np.float32), np.full((n, 25), 0.94, dtype=np.float32), None

    stat_mean = np.zeros(ORF_JUDGE_STAT_DIM, dtype=np.float32)
    stat_std = np.ones(ORF_JUDGE_STAT_DIM, dtype=np.float32)
    bundle = {
        "r3_stat": build_orf_functional_judge(stat_mean, stat_std, use_aa_seq=False, arch="r3"),
        "r3_seq": build_orf_functional_judge(stat_mean, stat_std, use_aa_seq=False, arch="unified_v4_3"),
        "calibrator": None,
        "r2_seq": None,
        "unified_mode": True,
        "judge_arch": "unified_v4_3",
        "model_version": "Unified V4.3",
        "device": "cpu",
    }

    upm = UnifiedPhageModel(dna_scanner=_MockStage1Scanner(), judge_bundle=bundle)  # type: ignore[arg-type]
    res = upm.scan_sequences({"ctg1": seq})

    assert call_counter["count"] == 1
    assert res.routing_stats["pyrodigal_reused_contigs"] == 1
    assert res.routing_stats["model_version"] == "Unified V4.3"
    assert res.routing_stats["judge_arch"] == "unified_v4_3"

    # 测试结束后清理测试替换的全局单例
    wf_mod._GENE_FINDER = None
    ec_mod._GF = None


def test_unified_model_applies_bimodal_and_att_boundary_refinement():
    """验证 UnifiedPhageModel 端到端链路能协同调用 attL/attR 1bp 对齐并回填统计与注释。"""
    import numpy as np
    from src.phage_discovery.student.orf_functional_judge import (
        ORF_JUDGE_STAT_DIM,
        build_orf_functional_judge,
    )
    from src.phage_discovery.benchmark.metrics import WindowPrediction

    rng = np.random.default_rng(77)
    bases = np.array(["A", "C", "G", "T"])
    dna = bases[rng.integers(0, 4, size=14000)].tolist()
    att_dr = "TAGCTAGCTAGCTAGGAC"  # 18 bp 高熵正向重复
    true_l, true_r = 1723, 12189
    dna[true_l : true_l + len(att_dr)] = list(att_dr)
    dna[true_r - len(att_dr) : true_r] = list(att_dr)
    # 保证直接重复两端相邻碱基严格错配，长度锁定在 18 bp
    dna[true_l - 1] = "A"
    dna[true_r - len(att_dr) - 1] = "C"
    dna[true_l + len(att_dr)] = "G"
    dna[true_r] = "T"
    seq = "".join(dna)

    class _MockBoundaryModel(UnifiedPhageModel):
        def _run_dna_backbone(
            self,
            contig_seqs: Dict[str, str],
            *,
            executor=None,
        ):
            del contig_seqs, executor
            wps = [
                WindowPrediction("ctg_b", 0, 5000, 0.90),
                WindowPrediction("ctg_b", 2500, 7500, 0.96),
                WindowPrediction("ctg_b", 5000, 10000, 0.95),
                WindowPrediction("ctg_b", 7500, 12500, 0.92),
            ]
            sub = np.full((4, 25), 0.92, dtype=np.float32)
            base_regs = [PredictedRegion("ctg_b", 1600, 12400, 0.96, 0.93, 4)]
            return wps, sub, None, base_regs, {"dna_infer_sec": 0.01}

    class _DummyScanner:
        workers = 1
        min_region_bp = 3000
        merge_gap_bp = 3000
        smooth_sub_profile = True

    stat_mean = np.zeros(ORF_JUDGE_STAT_DIM, dtype=np.float32)
    stat_std = np.ones(ORF_JUDGE_STAT_DIM, dtype=np.float32)
    m_stat = build_orf_functional_judge(stat_mean, stat_std, use_aa_seq=False, arch="r3")
    m_seq = build_orf_functional_judge(stat_mean, stat_std, use_aa_seq=False, arch="unified_v4_3")
    bundle = {
        "r3_stat": m_stat,
        "r3_seq": m_seq,
        "calibrator": None,
        "r2_seq": None,
        "unified_mode": True,
        "judge_arch": "unified_v4_3",
        "model_version": "Unified V4.3",
        "device": "cpu",
    }

    orfs: List[Tuple[int, int, int, str]] = [
        (300, 1200, 1, "M" * 60),     # 外部左宿主
        (2600, 4200, 1, "M" * 60),    # 内部区段
        (10600, 11800, 1, "M" * 60),  # 右侧 Integrase
    ]
    with np.errstate(all="ignore"):
        upm = _MockBoundaryModel(dna_scanner=_DummyScanner(), judge_bundle=bundle)  # type: ignore[arg-type]

    # 覆盖蛋白打分为确定性噬菌体核心/整合酶/外部宿主，触发保护逻辑与 att 对齐
    import src.phage_discovery.inference.unified_model as um_mod
    orig_score_fn = um_mod.score_contigs_with_judge_bundle

    def _mock_score(
        bundle: Dict[str, object],
        orfs_by_contig: Dict[str, List[Tuple[int, int, int, str]]],
        *,
        contig_ids=None,
        batch_size: int = 32,
        active_experts=None,
    ) -> Dict[str, Dict[str, np.ndarray]]:
        del bundle, orfs_by_contig, contig_ids, batch_size, active_experts
        ph = np.array([0.05, 0.95, 0.93], dtype=np.float32)
        f10 = np.zeros((3, 10), dtype=np.float32)
        f10[0, 9] = 0.85
        f10[1, 0] = 0.90
        f10[2, 4] = 0.92
        return {"ctg_b": {"phage_probs": ph, "func10_probs": f10, "r2_core_probs": f10[:, :5]}}

    um_mod.score_contigs_with_judge_bundle = _mock_score  # type: ignore[assignment]
    try:
        res = upm.scan_sequences({"ctg_b": seq}, precomputed_orfs={"ctg_b": orfs})
    finally:
        um_mod.score_contigs_with_judge_bundle = orig_score_fn

    assert len(res.regions) == 1
    assert res.regions[0].start_bp == true_l
    assert res.regions[0].end_bp == true_r
    assert res.routing_stats["rescue_stats"]["att_aligned"] == 1
    key = f"ctg_b:{true_l}-{true_r}"
    assert res.region_annotations[key]["att_site"]["att_dr_len_bp"] == len(att_dr)


def test_streaming_global_context_matches_full_sequence_features_and_streams_identical(tmp_path: Path):
    from src.phage_discovery.features.window_features import (
        compute_sequence_global_context,
        extract_contig_windows,
        get_feature_names,
    )

    # 1. 验证超长局部切片在注入整序列全局上下文后，背景偏离特征与单批全序列 提取严格一致
    rng = np.random.default_rng(77)
    at_half = "".join(np.array(["A", "T", "A", "G", "C"])[rng.integers(0, 5, size=12500)].tolist())
    gc_half = "".join(np.array(["G", "C", "G", "A", "T"])[rng.integers(0, 5, size=12500)].tolist())
    full_seq = at_half + gc_half

    full_feats = extract_contig_windows("ctg_full", full_seq, win_size=5000, step_size=2500, feature_profile="v4")
    # 对比全序列中心滑窗 (starts==12500) 与仅切取后半截 sub_seq = full_seq[7500:] 的中心滑窗 (starts==5000)
    idx_full = int(np.where(full_feats["starts"] == 12500)[0][0])
    sub_seq = full_seq[7500:]
    sub_local = extract_contig_windows("ctg_sub_local", sub_seq, win_size=5000, step_size=2500, feature_profile="v4")
    idx_sub = int(np.where(sub_local["starts"] == 5000)[0][0])

    names = get_feature_names("v4")
    gc_diff_i = names.index("ctx_gc_diff")
    kmer_cos_i = names.index("ctx_kmer_cosdist")
    # 不注全局背景时，切段会因 GC/4-mer 仅看局部发生明显漂移
    assert abs(float(full_feats["features"][idx_full, gc_diff_i]) - float(sub_local["features"][idx_sub, gc_diff_i])) > 0.02

    g_kmer, g_gc, g_self = compute_sequence_global_context(full_seq, context_win_size=5000)
    sub_global = extract_contig_windows(
        "ctg_sub_global",
        sub_seq,
        win_size=5000,
        step_size=2500,
        feature_profile="v4",
        global_ctx_kmer_unit=g_kmer,
        global_ctx_gc=g_gc,
        global_ctx_is_self=g_self,
    )
    assert np.max(np.abs(full_feats["features"][idx_full] - sub_global["features"][idx_sub])) < 1e-6
    assert abs(float(full_feats["features"][idx_full, kmer_cos_i]) - float(sub_global["features"][idx_sub, kmer_cos_i])) < 1e-6

    # 2. 验证 UnifiedPhageModel 流式扫描超长单条 Contig 时自动计算全局上下文并向每片 scan_sequences 注入
    upm = UnifiedPhageModel(dna_scanner=_FakeStreamingScanner(), judge_bundle=None, active_experts=("boundary",))  # type: ignore[arg-type]
    captured_ctx: List[Tuple[str, Tuple[np.ndarray, float, bool]]] = []
    orig_scan = upm.scan_sequences

    def _spy_scan(seqs, **kwargs):
        gmap = kwargs.get("global_ctx_by_contig") or {}
        for k, v in gmap.items():
            captured_ctx.append((k, v))
        return orig_scan(seqs, **kwargs)

    # 覆盖 _run_dna_backbone 避免真实模型权重依赖，只拦截传给 scan_sequences 的 global_ctx_by_contig
    def _dummy_backbone(c_seqs, executor=None):
        del executor
        return [], np.zeros((0, 25), dtype=np.float32), None, [], {"dna_feature_sec": 0.0, "dna_infer_decode_sec": 0.0}

    upm._run_dna_backbone = _dummy_backbone  # type: ignore[method-assign]
    upm.scan_sequences = _spy_scan  # type: ignore[method-assign]

    long_fa = _write_test_fasta(tmp_path / "long_single.fna", {"chr_long": full_seq})
    ckpt_dir = tmp_path / "ckpt"
    upm.scan_fasta_streaming(
        long_fa,
        ckpt_dir,
        chunk_max_bp=15000,
        long_contig_overlap_bp=5000,
    )
    assert len(captured_ctx) >= 2
    for seg_k, (ck, cgc, cself) in captured_ctx:
        assert seg_k.startswith("chr_long__seg_")
        assert np.allclose(ck, g_kmer, atol=1e-7)
        assert abs(cgc - g_gc) < 1e-9
        assert cself is False
