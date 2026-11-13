# -*- coding: utf-8 -*-
"""双阶段高精度噬菌体基因组扫描与蛋白门控验证包。"""
from .protein_gate import (
    ProteinGateConfig,
    RegionGateResult,
    evaluate_regions_with_protein_gate,
)
from .scanner import GenomeScanner, ScanResult

__all__ = [
    "ProteinGateConfig",
    "RegionGateResult",
    "evaluate_regions_with_protein_gate",
    "GenomeScanner",
    "ScanResult",
]

