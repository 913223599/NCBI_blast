# -*- coding: utf-8 -*-
"""统一原始 DNA 窗口特征提取（训练与推理同源，避免注释来源泄露）。"""
from .window_features import (
    FEATURE_NAMES,
    compute_window_features,
    extract_contig_windows,
    predict_genes,
)

__all__ = [
    "FEATURE_NAMES",
    "compute_window_features",
    "extract_contig_windows",
    "predict_genes",
]

