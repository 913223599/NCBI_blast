# -*- coding: utf-8 -*-
"""
噬菌体结构与尾部形态预测核心数据结构定义
"""
from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field


class StructureInspectRequest(BaseModel):
    """输入文件/文本或上游任务预检请求。"""

    source_mode: Literal["file", "paste", "annotation", "phage_discovery"] = "file"
    fasta_path: Optional[str] = None
    fasta_content: Optional[str] = None
    source_task_id: Optional[str] = None
    region_index: Optional[int] = Field(default=None, ge=1)


class StructureRunRequest(BaseModel):
    """提交噬菌体结构与尾部形态预测任务请求参数。"""

    task_name: str = Field(default="PhageStructure_Task", description="分析任务名称")
    source_mode: Literal["file", "paste", "annotation", "phage_discovery"] = "file"
    fasta_path: Optional[str] = Field(default=None, description="本地 FASTA / GBK / FAA 路径")
    fasta_content: Optional[str] = Field(default=None, description="直接粘贴的 FASTA 或 GenBank 文本")
    source_task_id: Optional[str] = Field(default=None, description="关联的历史注释或前噬菌体任务 ID")
    region_index: Optional[int] = Field(default=None, ge=1, description="若源自前噬菌体任务，可选特定区段索引")
    selected_contigs: Optional[List[str]] = Field(default=None, description="仅分析选中的 Contig ID")

    threads: Optional[int] = Field(default=None, ge=1, le=64, description="并行计算核心数")
    genetic_code: int = Field(default=11, description="遗传密码表 (默认 11，柔膜菌可选 4)")
    evalue_cutoff: float = Field(default=1e-4, gt=0.0, le=1.0, description="PyHMMER PHROG E-value 阈值")
    score_cutoff: float = Field(default=28.0, ge=10.0, le=500.0, description="PyHMMER 最低比特分阈值")
    force_hmm_rescan: bool = Field(default=False, description="即使输入含注释也强制重跑 PHROG HMM 结构扫描")
    enable_phold_enhance: bool = Field(default=False, description="是否对未知长 ORF 启动 Phold 3D 结构折叠补漏")
    enable_phagetailfinder: bool = Field(default=True, description="是否运行 PhageTailFinder 双状态 HMM 尾部基因簇预测")
    ptf_accurate_mode: bool = Field(default=False, description="PhageTailFinder 精确模式 (提高未命中 HMM 的保守惩罚)")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="附加上下文元数据")


class StructureBatchItemRequest(BaseModel):
    """批量结构预测中的单个待分析样本条目。"""

    task_name: Optional[str] = Field(default=None, description="可选样本任务名称")
    source_mode: Literal["file", "paste", "annotation", "phage_discovery"] = "file"
    fasta_path: Optional[str] = None
    fasta_content: Optional[str] = None
    source_task_id: Optional[str] = None
    region_index: Optional[int] = Field(default=None, ge=1)
    selected_contigs: Optional[List[str]] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class StructureBatchRunRequest(BaseModel):
    """批量提交多样本入队依次自动分析请求参数。"""

    items: List[StructureBatchItemRequest] = Field(..., min_length=1, description="批量样本条目列表")
    threads: Optional[int] = Field(default=None, ge=1, le=64)
    genetic_code: int = Field(default=11)
    evalue_cutoff: float = Field(default=1e-4, gt=0.0, le=1.0)
    score_cutoff: float = Field(default=28.0, ge=10.0, le=500.0)
    force_hmm_rescan: bool = Field(default=False)
    enable_phold_enhance: bool = Field(default=False)
    enable_phagetailfinder: bool = Field(default=True)
    ptf_accurate_mode: bool = Field(default=False)
    split_phage_regions: bool = Field(
        default=False,
        description="针对前噬菌体联动源，当未指定 region_index 时是否按检出区段拆分为独立排队任务",
    )
    split_fasta_records: bool = Field(
        default=False,
        description="针对文本粘贴的纯 FASTA 多条序列，是否按记录逐条拆分为独立排队任务",
    )


class PolyXRegion(BaseModel):
    """卷尺蛋白中的多聚/低复杂度富集微区 (polyX)。"""

    start_aa: int
    end_aa: int
    length_aa: int
    dominant_aa: str
    kind: Literal["homorun", "biased_window"] = "biased_window"
    snippet: str = ""


class TandemRepeatUnit(BaseModel):
    """卷尺蛋白中的串联重复序列阵列 (TRs)。"""

    start_aa: int
    end_aa: int
    period_aa: int
    copy_number: float
    length_aa: int
    identity: float
    similarity: float
    unit_sample: str = ""


class HydrophobicSegment(BaseModel):
    """TMP 疏水性高峰 / 潜在跨膜锚定片段。"""

    start_aa: int
    end_aa: int
    mean_kd: float


class TmpAnalysisItem(BaseModel):
    """单个卷尺蛋白 (TMP) 或候选标尺蛋白的定量分析结果。"""

    locus_tag: str
    contig_id: str
    product: str
    phrog_id: str = ""
    evidence_kind: Literal["confirmed_tmp", "gp29_tail_length", "putative_syntenic_tmp"] = "confirmed_tmp"
    confidence: float = 0.0
    start_bp: int = 0
    end_bp: int = 0
    strand: str = "+"
    length_aa: int
    est_tail_length_nm: float
    est_tail_range_nm: List[float] = Field(default_factory=list)
    polyx_count: int = 0
    polyx_total_aa: int = 0
    polyx_fraction_pct: float = 0.0
    polyx_aa_summary: Dict[str, int] = Field(default_factory=dict)
    tr_count: int = 0
    tr_total_aa: int = 0
    tr_fraction_pct: float = 0.0
    max_tr_period_aa: int = 0
    polyx_regions: List[PolyXRegion] = Field(default_factory=list)
    tandem_repeats: List[TandemRepeatUnit] = Field(default_factory=list)
    hydrophobic_segments: List[HydrophobicSegment] = Field(default_factory=list)
    hydropathy_profile: List[float] = Field(default_factory=list)
    interpretation: str = ""


class StructureProteinItem(BaseModel):
    """经识别的噬菌体结构、连接器或辅助功能蛋白明细。"""

    locus_tag: str
    contig_id: str
    start: int
    end: int
    strand: str
    length_aa: int
    product: str
    raw_product: str = ""
    phrog_id: str = ""
    phrog_category: str = ""
    structural_role: str = "OTHER"
    role_label_cn: str = ""
    hmm_score: float = 0.0
    hmm_evalue: float = 1.0
    evidence_source: str = "annotation"
    ptf_is_tail: bool = False
    ptf_tail_prob: float = 0.0
    ptf_pfam: str = ""
    ptf_pfam_desc: str = ""
    ptf_all_pfams: List[str] = Field(default_factory=list)
    translation: str = ""


class TailFinderCluster(BaseModel):
    """PhageTailFinder 双状态 HMM 识别的共线性尾部基因簇。"""

    cluster_id: str
    start_bp: int
    end_bp: int
    orf_count: int
    novel_orf_count: int = 0
    mean_tail_prob: float = 0.0
    loci: List[str] = Field(default_factory=list)
    pfam_hits: List[str] = Field(default_factory=list)


class ConnectorProfile(BaseModel):
    """Virfam 头-颈-尾连接器模块构型分析。"""

    type_hint: Literal[
        "Type_1_Sipho_Myo",
        "Type_2_Sipho_Podo",
        "Type_3_Podoviridae",
        "Mixed_or_Uncertain",
        "Absent",
    ] = "Absent"
    type_label_cn: str = "未检出典型连接器"
    portal_count: int = 0
    ad1_count: int = 0
    ad2_count: int = 0
    ad3_count: int = 0
    hc1_count: int = 0
    hc2_count: int = 0
    hc3_count: int = 0
    neck1_count: int = 0
    tail_terminator_count: int = 0
    collar_podo_count: int = 0
    general_connector_count: int = 0


class StructuralModuleMatrix(BaseModel):
    """噬菌体 6 大核心结构/功能组件检出统计。"""

    head_packaging_count: int = 0
    connector_count: int = 0
    tail_sheath_count: int = 0
    tail_tube_count: int = 0
    major_tail_count: int = 0
    tail_assembly_chaperone_count: int = 0
    tape_measure_count: int = 0
    tail_tubular_ab_count: int = 0
    internal_virion_count: int = 0
    tail_needle_count: int = 0
    baseplate_count: int = 0
    tail_fiber_rbp_count: int = 0
    lysis_count: int = 0
    integrase_count: int = 0
    non_tailed_marker_count: int = 0
    t6ss_confounder_count: int = 0


class EvidenceItem(BaseModel):
    """形态分类判定中的单条可解释依据。"""

    rule: str
    target_morphotype: str
    weight: float
    detail: str
    loci: List[str] = Field(default_factory=list)


class MorphotypePrediction(BaseModel):
    """最终形态与尾部结构预测结论。"""

    morphotype_code: Literal[
        "Myoviridae-like",
        "Siphoviridae-like",
        "Podoviridae-like",
        "Non-tailed",
        "Incomplete",
    ]
    morphotype_label_cn: str
    tail_feature_tag: str
    confidence: float
    class_scores: Dict[str, float] = Field(default_factory=dict)
    decision_basis: str
    lifestyle_hint: Literal["Temperate", "Lytic", "Unknown"] = "Unknown"
    estimated_tail_length_nm: Optional[float] = None
    estimated_tail_range_nm: List[float] = Field(default_factory=list)
    evidence_chain: List[EvidenceItem] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)


class ContigStructureResult(BaseModel):
    """单条 Contig / 前噬菌体区段的结构预测完整剖析结果。"""

    contig_id: str
    length_bp: int
    gc_percent: float
    total_orfs: int
    hmm_matched_orfs: int
    prediction: MorphotypePrediction
    connector_profile: ConnectorProfile
    module_matrix: StructuralModuleMatrix
    ptf_tail_protein_count: int = 0
    ptf_tail_clusters: List[TailFinderCluster] = Field(default_factory=list)
    tmp_analyses: List[TmpAnalysisItem] = Field(default_factory=list)
    structural_proteins: List[StructureProteinItem] = Field(default_factory=list)


class PhageStructureResult(BaseModel):
    """任务级全套噬菌体结构与尾部形态预测结果。"""

    task_id: str
    task_name: str
    created_at: str
    source_mode: str
    elapsed_sec: float = 0.0
    total_bp: int = 0
    contig_count: int = 0
    primary_prediction: MorphotypePrediction
    contigs: List[ContigStructureResult] = Field(default_factory=list)
    summary: Dict[str, Any] = Field(default_factory=dict)
    files: Dict[str, str] = Field(default_factory=dict)
