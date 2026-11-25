# -*- coding: utf-8 -*-
"""
命令行入口：解析查询蛋白 FASTA 并在目标 FASTA 目录中执行多核分片相似度检索与标记。

使用示例：
    python scripts/run_protein_fasta_search.py \
        --query <查询蛋白.fasta> \
        --target-dir <目标FASTA目录> \
        --output-dir results/protein_fasta_search \
        --min-pident 30.0
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# 通过相对路径定位项目根目录（严禁硬编码绝对路径）
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.analysis.protein_search import SearchConfig, run_protein_fasta_search  # noqa: E402


def build_arg_parser() -> argparse.ArgumentParser:
    default_out = PROJECT_ROOT / "results" / "protein_fasta_search"
    parser = argparse.ArgumentParser(
        description="解析蛋白序列 FASTA 并在目标 FASTA 目录中检索并标记相似度超过阈值的序列。",
    )
    parser.add_argument(
        "--query",
        type=Path,
        required=True,
        help="查询蛋白序列 FASTA 文件路径。",
    )
    parser.add_argument(
        "--target-dir",
        type=Path,
        required=True,
        help="待检索的目标 FASTA 序列目录路径。",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=default_out,
        help="输出结果目录（默认位于项目相对路径 results/protein_fasta_search）。",
    )
    parser.add_argument(
        "--min-pident",
        type=float,
        default=30.0,
        help="阳性标记最小一致性百分比阈值（严格大于该值，默认 30.0）。",
    )
    parser.add_argument(
        "--max-evalue",
        type=float,
        default=1e-5,
        help="阳性标记最大 E-value 阈值（默认 1e-5）。",
    )
    parser.add_argument(
        "--blast-evalue",
        type=float,
        default=1e-3,
        help="BLAST 检索召回 E-value 阈值（默认 1e-3）。",
    )
    parser.add_argument(
        "--min-align-len",
        type=int,
        default=30,
        help="阳性标记最小比对长度（氨基酸残基数，默认 30）。",
    )
    parser.add_argument(
        "--shard-max-files",
        type=int,
        default=10,
        help="单个检索分片包含的最大文件数（默认 10）。",
    )
    parser.add_argument(
        "--shard-max-residues",
        type=int,
        default=1_000_000,
        help="单个检索分片包含的最大碱基/残基数（默认 1000000）。",
    )
    parser.add_argument(
        "--db-gencode",
        type=int,
        default=11,
        help="tblastn 使用的遗传密码子表编号（细菌/噬菌体默认 11）。",
    )
    parser.add_argument(
        "--threads",
        type=int,
        default=None,
        help="总并行线程预算上限（默认自动按主机核心数预留核心后分配）。",
    )
    parser.add_argument(
        "--no-resume",
        action="store_true",
        help="禁用断点续跑，强制重新执行所有分片。",
    )
    parser.add_argument(
        "--blast-bin-dir",
        type=Path,
        default=None,
        help="可选：手动指定 NCBI BLAST+ 可执行文件所在目录。",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    # 强制标准输出采用 UTF-8
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    args = build_arg_parser().parse_args(argv)
    config = SearchConfig(
        query_fasta=args.query.resolve(),
        target_dir=args.target_dir.resolve(),
        output_dir=args.output_dir.resolve(),
        min_pident=args.min_pident,
        max_evalue=args.max_evalue,
        blast_evalue=args.blast_evalue,
        min_align_len=args.min_align_len,
        shard_max_files=args.shard_max_files,
        shard_max_residues=args.shard_max_residues,
        db_gencode=args.db_gencode,
        threads=args.threads,
        resume=not args.no_resume,
        blast_bin_dir=args.blast_bin_dir.resolve() if args.blast_bin_dir else None,
    )

    result = run_protein_fasta_search(config)
    print("=== 蛋白 FASTA 相似度检索完成 ===")
    print(f"查询蛋白条目数: {result.query_count}")
    print(
        f"扫描目标文件数: {result.target_file_count} "
        f"(DNA={result.dna_file_count}, Protein={result.protein_file_count}, "
        f"Skipped_3Di={result.skipped_3di_file_count})"
    )
    print(f"扫描目标序列总条数: {result.target_record_count}")
    print(
        f"标记 [HIT>30%] 结果: {result.marked_hit_file_count} 个文件 / "
        f"{result.marked_hit_sequence_count} 条序列 ({result.total_gt30_hsps} 条 HSP)"
    )
    print(
        f"边缘 [BORDERLINE>30%] 文件数: {result.borderline_only_file_count} "
        f"({result.total_borderline_hsps} 条 HSP)"
    )
    print(f"分片数: {result.shards_total} (断点复用: {result.shards_resumed})")
    print(f"汇总报告: {result.output_files['search_report_md']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
