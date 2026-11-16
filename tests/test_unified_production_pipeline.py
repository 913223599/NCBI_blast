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
from src.phage_discovery.inference.unified_model import UnifiedPhageModel


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
        n = len(contig_ids)
        self.seen_contig_batches.append(sorted(set(str(x) for x in contig_ids)))
        win_scores = np.zeros(n, dtype=np.float32)
        sub_probs = np.zeros((n, 25), dtype=np.float32)
        for idx, cid in enumerate(contig_ids):
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
    seqs = {
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

    seqs = {
        "host_1": "ACGT" * 2000,
        "phage_1": "ATGC" * 2000,
        "host_2": "CGTA" * 2000,
        "phage_2": "GCTA" * 2000,
    }
    fa = _write_test_fasta(tmp_path / "sample.fna", seqs)

    scanner = _FakeStreamingScanner()
    upm = UnifiedPhageModel(dna_scanner=scanner, judge_bundle=None, active_experts=("boundary",))

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
