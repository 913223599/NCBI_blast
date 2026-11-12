# -*- coding: utf-8 -*-
"""
核心功能蛋白跨样本比对数据模型 (Data Models)
"""
from typing import Dict, List, Optional
from pydantic import BaseModel


class ProteinItem(BaseModel):
    """单个蛋白质条目"""
    id: str
    locus_tag: str
    product: str
    translation: str
    length_aa: int
    start: int
    end: int
    strand: str
    category: str = "other"


class MutationSite(BaseModel):
    """单处点突变或变异位点"""
    pos: int
    ref_aa: str
    alt_aa: str
    impact_type: str = "conservative"
    impact_label: str = "同类保守替换"
    description: str


class RegionDomainItem(BaseModel):
    """蛋白质特定区段（N端、中段、C端）保守性与变异分布"""
    name: str
    start: int
    end: int
    length: int
    identity_pct: float
    mutation_count: int
    conservative_count: int
    radical_count: int
    status: str


class ProteinComparisonRow(BaseModel):
    """单对蛋白质比对明细记录"""
    category: str
    category_label: str

    sample_a_id: str
    sample_a_tag: str
    sample_a_product: str
    sample_a_len: int
    sample_a_range: str
    sample_a_strand: str
    sample_a_seq: str

    sample_b_id: Optional[str] = None
    sample_b_tag: Optional[str] = None
    sample_b_product: Optional[str] = None
    sample_b_len: Optional[int] = 0
    sample_b_range: Optional[str] = None
    sample_b_strand: Optional[str] = None
    sample_b_seq: Optional[str] = None

    match_status: str
    identity_pct: float = 0.0
    diff_count: int = 0
    mutations: List[MutationSite] = []
    length_diff: int = 0
    notes: Optional[str] = None

    aligned_seq_a: str = ""
    aligned_markup: str = ""
    aligned_seq_b: str = ""
    conservative_mutation_cnt: int = 0
    radical_mutation_cnt: int = 0
    indel_cnt: int = 0
    hotspot_conclusion: str = ""
    region_domains: List[RegionDomainItem] = []


class ProteinComparisonResult(BaseModel):
    """跨样本比对汇总报告"""
    sample_a_name: str
    sample_b_name: str
    sample_a_total_cds: int
    sample_b_total_cds: int

    total_compared_pairs: int = 0
    identical_count: int = 0
    conserved_count: int = 0
    divergent_count: int = 0
    unique_a_count: int = 0
    unique_b_count: int = 0
    average_identity_pct: float = 0.0

    category_summary: Dict[str, Dict[str, int]] = {}
    rows: List[ProteinComparisonRow] = []

