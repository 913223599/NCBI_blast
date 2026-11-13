# -*- coding: utf-8 -*-
"""
V3 蛋白验证门控与端到端双阶段扫描器单元测试
"""
from pathlib import Path
from typing import Dict, Sequence, Tuple

import numpy as np
import torch

from src.phage_discovery.benchmark.metrics import PredictedRegion
from src.phage_discovery.features.window_features import FEATURE_NAMES
from src.phage_discovery.inference.protein_gate import (
    ProteinGateConfig,
    evaluate_regions_with_protein_gate,
)
from src.phage_discovery.inference.scanner import GenomeScanner
from src.phage_discovery.student.distilled_student import build_distilled_student


def _synthetic_coding_dna(length_bp: int, gc_high: bool = False) -> str:
    """生成带有多个有效 ORF（含起始与终止密码子）的合成序列供 Pyrodigal 检出。"""
    if gc_high:
        # GCG GCC CGC GGC 等高频高GC三联体 + 终止 TGA
        orf = "ATG" + ("GCGGCCCGCGGCCTGGCC" * 20) + "TGA" + "CCCCCC"
    else:
        orf = "ATG" + ("GCTAAACTGATTGAAATG" * 20) + "TAA" + "AAAAAA"
    reps = max(1, (length_bp // len(orf)) + 1)
    return (orf * reps)[:length_bp]


def test_protein_gate_tiered_decisions():
    seqs = {
        "c_norm": (
            _synthetic_coding_dna(8000, gc_high=False)
            + _synthetic_coding_dna(6000, gc_high=False)
            + _synthetic_coding_dna(7000, gc_high=False)
        ),
        "c_high_gc": _synthetic_coding_dna(9000, gc_high=True),
    }

    regions = [
        # r0: 正常 GC 真噬菌体（含 Capsid + Terminase hallmark）
        PredictedRegion("c_norm", 0, 8000, peak_score=0.98, mean_score=0.94, window_count=3),
        # r1: 正常 GC 转座酶假阳性（仅有 transposase 命中）
        PredictedRegion("c_norm", 8000, 14000, peak_score=0.92, mean_score=0.88, window_count=2),
        # r2: 正常 GC 高置信暗物质候选（0 hits + 高均分 + 高编码密度）
        PredictedRegion("c_norm", 14000, 21000, peak_score=0.985, mean_score=0.95, window_count=3),
        # r3: 极端高 GC OOD 宿主区域（仅有 ABC transporter 通用酶命中，无病毒标志）
        PredictedRegion("c_high_gc", 0, 9000, peak_score=0.99, mean_score=0.96, window_count=4),
    ]

    def fake_hit_fetcher(orfs: Sequence[Tuple[str, str]]) -> Dict[str, Tuple[float, str]]:
        hits: Dict[str, Tuple[float, str]] = {}
        for qid, _ in orfs:
            if qid.startswith("r0__"):
                if qid.endswith("__g0"):
                    hits[qid] = (240.0, "major capsid protein [Escherichia phage T4]")
                elif qid.endswith("__g1"):
                    hits[qid] = (210.0, "terminase large subunit [Escherichia phage T4]")
            elif qid.startswith("r1__"):
                if qid.endswith("__g0"):
                    hits[qid] = (180.0, "IS6 family transposase [Staphylococcus phage]")
            elif qid.startswith("r3__"):
                if qid.endswith("__g0"):
                    hits[qid] = (160.0, "ABC transporter ATP-binding protein [Streptomyces phage]")
        return hits

    kept, details = evaluate_regions_with_protein_gate(
        seqs,
        regions,
        config=ProteinGateConfig(enabled=True),
        hit_fetcher=fake_hit_fetcher,
    )
    assert len(details) == 4
    assert details[0].decision == "keep" and details[0].tier == "hallmark_confirmed"
    assert details[1].decision == "reject" and details[1].tier == "rejected_transposase_dom"
    assert details[2].decision == "keep" and details[2].tier == "dark_matter_fallback"
    assert details[3].decision == "reject" and details[3].tier == "rejected_high_gc_no_evidence"
    assert len(kept) == 2


def test_genome_scanner_loads_checkpoint_and_scans(tmp_path: Path):
    feat_dim = len(FEATURE_NAMES)
    model = build_distilled_student(
        feat_dim,
        np.zeros(feat_dim, dtype=np.float32),
        np.ones(feat_dim, dtype=np.float32),
    )
    # 设偏置让输出分数确定落在一个可控区间
    with torch.no_grad():
        model.win_head[-1].bias.fill_(5.0)
        model.sub_head[-1].bias.fill_(4.0)
    pt_path = tmp_path / "student_distilled.pt"
    torch.save(model.state_dict(), pt_path)

    scanner = GenomeScanner(
        pt_path,
        seed_threshold=0.80,
        extend_threshold=0.50,
        sub_threshold=0.45,
        gate_config=ProteinGateConfig(enabled=True),
        workers=1,
        device="cpu",
    )

    seq = _synthetic_coding_dna(10000, gc_high=False)
    res = scanner.scan_sequences(
        {"contig_test": seq},
        hit_fetcher=lambda orfs: {orfs[0][0]: (300.0, "portal protein [Bacillus phage]")} if orfs else {},
    )
    assert res.total_bp == 10000
    assert res.total_windows >= 3
    assert len(res.raw_regions) >= 1
    assert len(res.verified_regions) == len(res.raw_regions)
    assert res.gate_details[0].tier == "hallmark_confirmed"

