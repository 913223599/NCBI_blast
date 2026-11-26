# -*- coding: utf-8 -*-
"""向后兼容门面：实际实现已下沉至 src/core/blast_utils.py，消除跨层循环依赖。"""
from ...core.blast_utils import (
    _result_cache,
    parse_blast_csv,
    canonicalize_species_name,
    is_unclassified_or_genus_only,
    select_consensus_hit,
)

__all__ = [
    "_result_cache",
    "parse_blast_csv",
    "canonicalize_species_name",
    "is_unclassified_or_genus_only",
    "select_consensus_hit",
]
