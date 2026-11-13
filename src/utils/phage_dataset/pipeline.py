# -*- coding: utf-8 -*-
"""
噬菌体数据集下载、多核验证与索引构建统一流水线入口
支持以函数调用或命令行方式向任意指定目录同步并建库。
"""
import argparse
import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional

from .indexer import build_phage_dataset_indexes
from .ncbi_downloader import PhageDatasetDownloader
from .validator import validate_dataset_parallel

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent


def run_phage_dataset_pipeline(
    data_dir: Path,
    *,
    target_count: int = 500,
    batch_size: int = 20,
    min_length_bp: int = 3000,
    build_blast_db: bool = True,
    skip_download: bool = False,
    api_key: Optional[str] = None,
) -> Dict[str, Any]:
    """执行端到端噬菌体数据集下载、多核验证与索引构建。"""
    target_dir = Path(data_dir).resolve()
    downloader = PhageDatasetDownloader(
        target_dir,
        batch_size=batch_size,
        min_length_bp=min_length_bp,
        api_key=api_key,
    )

    download_summary: Dict[str, Any] = {}
    if not skip_download:
        download_summary = downloader.download_batch_dataset(target_count=target_count)

    state = downloader.load_checkpoint()
    validations = validate_dataset_parallel(target_dir, min_length_bp=min_length_bp)
    manifest = build_phage_dataset_indexes(
        target_dir,
        validations,
        checkpoint_saved_records=state.get("saved_records", {}),
        build_blast_db=build_blast_db,
    )
    return {
        "download": download_summary,
        "manifest": manifest,
    }


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    parser = argparse.ArgumentParser(description="NCBI RefSeq 噬菌体数据集批量下载、多核验证与本地建库工具")
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=PROJECT_ROOT / "data" / "phage_data",
        help="目标数据根目录（其下自动维护 fasta/、gbk/、index/、blastdb/）",
    )
    parser.add_argument("--count", type=int, default=500, help="目标收集的完整噬菌体数量")
    parser.add_argument("--batch-size", type=int, default=20, help="NCBI 每次批量请求记录数")
    parser.add_argument("--min-length", type=int, default=3000, help="最小基因组长度阈值 (bp)")
    parser.add_argument("--no-blastdb", action="store_true", help="仅生成 SQLite/TSV/JSON 索引，不执行 makeblastdb")
    parser.add_argument("--skip-download", action="store_true", help="跳过下载，仅对已有文件执行全量校验与重建索引")
    parser.add_argument("--api-key", type=str, default=None, help="可选 NCBI E-utilities API Key")

    args = parser.parse_args()
    result = run_phage_dataset_pipeline(
        args.data_dir,
        target_count=args.count,
        batch_size=args.batch_size,
        min_length_bp=args.min_length,
        build_blast_db=not args.no_blastdb,
        skip_download=args.skip_download,
        api_key=args.api_key,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

