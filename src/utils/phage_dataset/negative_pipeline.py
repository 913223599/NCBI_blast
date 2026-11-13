# -*- coding: utf-8 -*-
"""
配套负样本下载、反向核验与多维索引流水线 CLI 入口
"""
import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict, Optional

from .negative_downloader import NegativeDatasetDownloader
from .negative_indexer import build_negative_dataset_indexes
from .negative_validator import validate_negative_dataset_parallel


def run_negative_dataset_pipeline(
    data_dir: Path,
    *,
    target_count: int = 600,
    min_length_bp: int = 3000,
    build_blast_db: bool = True,
    skip_download: bool = False,
    skip_index: bool = False,
    api_key: Optional[str] = None,
) -> Dict[str, Any]:
    """执行负样本分层下载、多核反向噬菌体校验与索引构建全流程。"""
    root = Path(data_dir).resolve()
    downloader = NegativeDatasetDownloader(
        root,
        api_key=api_key,
        min_length_bp=min_length_bp,
    )

    download_summary: Dict[str, Any] = {}
    if not skip_download:
        download_summary = downloader.download_batch_dataset(target_count=target_count)

    ckpt_state = downloader.load_checkpoint()
    if skip_index:
        return {"download": download_summary, "manifest": {}}

    validations = validate_negative_dataset_parallel(root, min_length_bp=min_length_bp)
    manifest = build_negative_dataset_indexes(
        root,
        validations,
        checkpoint_saved_records=ckpt_state.get("saved_records", {}),
        build_blast_db=build_blast_db,
    )
    return {"download": download_summary, "manifest": manifest}


def main(argv: Optional[list] = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    parser = argparse.ArgumentParser(description="NCBI 配套负样本下载、校验与索引工具")
    parser.add_argument("--data-dir", required=True, help="负样本存放根目录")
    parser.add_argument("--count", type=int, default=600, help="目标负样本总数（默认 600）")
    parser.add_argument("--min-length", type=int, default=3000, help="最短序列阈值（默认 3000 bp）")
    parser.add_argument("--no-blastdb", action="store_true", help="跳过 makeblastdb 构建")
    parser.add_argument("--skip-download", action="store_true", help="跳过下载，直接校验与建索引")
    parser.add_argument("--only-download", action="store_true", help="仅执行下载与断点落盘")
    parser.add_argument("--api-key", default=None, help="可选 NCBI E-utilities API Key")

    args = parser.parse_args(argv)
    result = run_negative_dataset_pipeline(
        Path(args.data_dir),
        target_count=args.count,
        min_length_bp=args.min_length,
        build_blast_db=not args.no_blastdb,
        skip_download=args.skip_download,
        skip_index=args.only_download,
        api_key=args.api_key,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())

