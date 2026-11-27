# -*- coding: utf-8 -*-
"""向后兼容门面：多线程 Range 分片下载实现已下沉至 src/core/download/parallel_downloader.py。"""
from ....core.download.parallel_downloader import (
    ParallelProgressTracker,
    ParallelRunContext,
    RemoteFileMeta,
    SegmentSpec,
    cleanup_parallel_segments,
    parallel_range_download,
    probe_parallel_support,
)

__all__ = [
    "ParallelProgressTracker",
    "ParallelRunContext",
    "RemoteFileMeta",
    "SegmentSpec",
    "cleanup_parallel_segments",
    "parallel_range_download",
    "probe_parallel_support",
]
