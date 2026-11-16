# -*- coding: utf-8 -*-
"""
UnifiedPhageModel 统一前噬菌体扫描生产 CLI 入口。

示例：
  python scripts/predict_unified.py --fasta sample.fasta --out-dir out_dir --chunk-mb 10
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Optional, Sequence, Tuple

import torch

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.phage_discovery.inference import (  # noqa: E402
    ALL_UNIFIED_EXPERTS,
    UnifiedPhageModel,
    export_unified_scan_outputs,
)


def _default_models_root() -> Path:
    return (REPO_ROOT.parent / "Phage data" / "models" / "full_v4").resolve()


def _parse_experts(raw: str) -> Tuple[str, ...]:
    parts = [p.strip() for p in str(raw or "").split(",") if p.strip()]
    return tuple(parts) if parts else ALL_UNIFIED_EXPERTS


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="UnifiedPhageModel 前噬菌体流式发现与注释工具")
    parser.add_argument("--fasta", type=Path, required=True, help="输入基因组或宏基因组 FASTA 路径")
    parser.add_argument("--out-dir", type=Path, required=True, help="标准化输出目录 (TSV/GFF3/FASTA/JSON)")
    parser.add_argument(
        "--models-root",
        type=Path,
        default=_default_models_root(),
        help="models/full_v4 根目录（相对推断自工作区父级 Phage data）",
    )
    parser.add_argument("--stage1-2-subdir", type=str, default="stage1_2", help="Stage 1.2 DNA 底座子目录名")
    parser.add_argument("--chunk-mb", type=float, default=10.0, help="流式分片上限 (Mb)；<=0 表示整库单批运行")
    parser.add_argument(
        "--experts",
        type=str,
        default=",".join(ALL_UNIFIED_EXPERTS),
        help="激活专家集合，逗号分隔（可选 boundary,gray_rescue,defense_func,intact）",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=max(1, min(12, (os.cpu_count() or 6) - 2)),
        help="特征提取并发进程数（自动保留主机余量核心）",
    )
    parser.add_argument("--device", type=str, default="auto", choices=["auto", "cuda", "cpu"], help="计算设备")
    parser.add_argument("--no-resume", action="store_true", help="禁用断点续跑，从头覆写分片记录")
    parser.add_argument("--fallback-r3-r2", action="store_true", help="强制回退至分离 R3+R2 模型包")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    fasta_path = Path(args.fasta).resolve()
    if not fasta_path.is_file():
        raise FileNotFoundError(f"输入 FASTA 不存在: {fasta_path}")

    device = ("cuda" if torch.cuda.is_available() else "cpu") if args.device == "auto" else str(args.device)
    experts = _parse_experts(args.experts)

    model = UnifiedPhageModel.from_models_root(
        Path(args.models_root).resolve(),
        stage1_2_subdir=str(args.stage1_2_subdir),
        workers=int(args.workers),
        device=device,
        active_experts=experts,
        prefer_unified_judge=not bool(args.fallback_r3_r2),
    )

    out_dir = Path(args.out_dir).resolve()
    if float(args.chunk_mb) > 0.0:
        res = model.scan_fasta_streaming(
            fasta_path,
            out_dir,
            chunk_max_bp=max(100_000, int(float(args.chunk_mb) * 1_000_000)),
            active_experts=experts,
            resume=not bool(args.no_resume),
            export_outputs=True,
        )
    else:
        res = model.scan_fasta(fasta_path, active_experts=experts)
        export_unified_scan_outputs(
            out_dir,
            regions=res.regions,
            region_annotations=res.region_annotations,
            routing_stats=res.routing_stats,
            timings_sec=res.timings_sec,
            total_bp=res.total_bp,
            total_windows=res.total_windows,
            source_fasta_path=fasta_path,
            suppressed_candidates=res.suppressed_candidates,
        )

    print(
        f"扫描完成: total_bp={res.total_bp:,} bp | contigs={len(res.contigs_bp)} "
        f"| regions={len(res.regions)} | skip_ratio={res.routing_stats.get('protein_skip_ratio')} "
        f"| out_dir={out_dir}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

