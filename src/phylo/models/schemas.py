# -*- coding: utf-8 -*-
"""
PhyloCore 强类型 Pydantic 数据契约
"""
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field


TrackType = Literal["auto", "genome", "gene", "phage_taxonomy"]
MsaToolType = Literal["none", "mafft", "muscle", "clustalo"]
MsaStrategyType = Literal["auto", "fast", "accurate", "linsi", "einsi"]
TrimModeType = Literal["none", "gap", "kpic", "kpic_smart_gap", "smart_gap"]
AniEngineType = Literal["viridic_blastn", "fastani", "skani", "mash"]
MarkerModeType = Literal["terl", "proteome"]
SamplingModeType = Literal["focused", "macro_family_host"]
TreeEngineType = Literal["nj", "bionj", "fasttree", "iqtree", "mrbayes"]
JobStatusType = Literal["pending", "running", "completed", "failed", "cancelled"]
StageStatusType = Literal["pending", "running", "completed", "cached", "skipped", "failed", "cancelled"]
LabelFormatType = Literal["name_acc", "name", "accession"]


class DeliveryScopeConfig(BaseModel):
    """第 0 步：噬菌体分类鉴定与交付边界设置。"""

    target_rank: Literal["species", "genus", "family_order"] = "genus"
    sampling_mode: SamplingModeType = "focused"
    ani_species_threshold: float = Field(default=95.0, ge=85.0, le=99.9)
    ani_genus_threshold: float = Field(default=70.0, ge=50.0, le=90.0)
    ref_max_count: int = Field(default=80, ge=5, le=2500)
    ictv_reps_per_genus: int = Field(default=3, ge=1, le=10)
    max_target_genera: int = Field(default=4, ge=1, le=50)
    outgroup_count: int = Field(default=3, ge=0, le=10)
    derep_ani: float = Field(default=0.90, ge=0.70, le=0.995)
    derep_min_len: int = Field(default=20000, ge=1000, le=200000)
    treemmer_target: int = Field(default=80, ge=5, le=2500)
    treemmer_min_cluster: int = Field(default=25, ge=3, le=200)
    checkv_min_completeness: float = Field(default=95.0, ge=0.0, le=100.0)
    enable_checkv: bool = False
    local_ref_dir: Optional[str] = None
    outgroup_ids: List[str] = Field(default_factory=list)
    mash_top_k: int = Field(default=40, ge=5, le=200)


class AniHitRecord(BaseModel):
    """单条参考基因组与查询噬菌体的 ANI / wgANI 相似性详情。"""

    accession: str
    description: str = ""
    mash_distance: Optional[float] = None
    mash_ani: Optional[float] = None
    wg_ani: float = 0.0
    aligned_ani: float = 0.0
    af_query: float = 0.0
    af_ref: float = 0.0
    genome_length: int = 0
    gc_content: float = 0.0
    host: str = ""
    genus: str = ""
    subfamily: str = ""
    family: str = ""
    order: str = ""
    class_name: str = ""
    realm: str = ""
    classification_call: Literal[
        "same_species",
        "same_genus_new_species",
        "genus_boundary_ambiguous",
        "novel_genus_candidate",
    ] = "novel_genus_candidate"
    mosaic_warning: bool = False


class AniScreenResult(BaseModel):
    """第 1 步：全库 Mash 初筛与 VIRIDIC-wgANI 预判综合结果。"""

    query_ids: List[str] = Field(default_factory=list)
    engine_used: str = "viridic_blastn"
    engine_version: str = ""
    command_preview: str = ""
    top_hits: List[AniHitRecord] = Field(default_factory=list)
    matrix_labels: List[str] = Field(default_factory=list)
    wgani_matrix: List[List[float]] = Field(default_factory=list)
    af_matrix: List[List[float]] = Field(default_factory=list)
    candidate_genera: List[str] = Field(default_factory=list)
    candidate_families: List[str] = Field(default_factory=list)
    summary_call: str = ""
    ambiguous_zone: bool = False
    warnings: List[str] = Field(default_factory=list)
    recommended_outgroup_accessions: List[str] = Field(default_factory=list)


class ReferenceCandidate(BaseModel):
    """第 2 步：参考序列集候选株条目与角色标记。"""

    accession: str
    name: str = ""
    description: str = ""
    role: Literal["query", "ictv_rep", "neighbor", "outgroup"] = "neighbor"
    source: Literal["workspace", "inphared_cache", "ncbi_download", "local_dir"] = "inphared_cache"
    selected: bool = True
    genome_length: int = 0
    gc_content: float = 0.0
    host: str = ""
    genus: str = ""
    family: str = ""
    order: str = ""
    wg_ani: Optional[float] = None
    completeness: Optional[float] = None
    local_path: Optional[str] = None
    is_ictv_classified: bool = False


class MarkerHitItem(BaseModel):
    """第 3 步：单株噬菌体标志基因（TerL）提取明细。"""

    sample_id: str
    protein_id: str = ""
    phrog_id: str = ""
    evalue: Optional[float] = None
    bitscore: Optional[float] = None
    aa_length: int = 0
    status: Literal["extracted", "missing", "multi_copy"] = "extracted"
    notes: str = ""


class MarkerExtractionReport(BaseModel):
    """第 3 步：标志基因提取或蛋白质组建树汇总报告。"""

    mode: MarkerModeType = "terl"
    total_genomes: int = 0
    extracted_count: int = 0
    missing_ids: List[str] = Field(default_factory=list)
    tool_used: str = ""
    tool_version: str = ""
    hits: List[MarkerHitItem] = Field(default_factory=list)


class QcCheckItem(BaseModel):
    """第 8 步：单条交付前质检清单结论。"""

    key: str
    title: str
    criterion: str
    status: Literal["pass", "warn", "fail"] = "pass"
    observed: str = ""
    explanation: str = ""


class DeliveryQcReport(BaseModel):
    """第 6 & 8 步：ANI-树一致性审计与完整交付质检报告。"""

    checks: List[QcCheckItem] = Field(default_factory=list)
    overall_status: Literal["pass", "warn", "fail"] = "pass"
    ani_tree_consistent: bool = True
    consistency_note: str = ""
    best_model: Optional[str] = None
    best_model_bic: Optional[float] = None
    iqtree_command: Optional[str] = None
    conclusion_zh: str = ""
    conclusion_en: str = ""
    itol_files: List[str] = Field(default_factory=list)


class SequenceProfile(BaseModel):
    """输入序列数据集的多维画像。"""

    sequence_count: int = 0
    unique_id_count: int = 0
    duplicate_id_count: int = 0
    mol_type: Literal["dna", "protein"] = "dna"
    min_length: int = 0
    median_length: int = 0
    max_length: int = 0
    total_bases: int = 0
    length_cv: float = 0.0
    is_aligned: bool = False
    has_gaps: bool = False
    content_hash: str = ""
    recommended_track: Literal["genome", "gene"] = "gene"
    recommended_msa: MsaToolType = "mafft"
    recommended_engine: TreeEngineType = "fasttree"
    warnings: List[str] = Field(default_factory=list)
    sample_ids: List[str] = Field(default_factory=list)


class ToolDescriptor(BaseModel):
    """外部生物信息工具探测描述。"""

    name: str
    available: bool = False
    runtime: Literal["native", "wsl", "python", "none"] = "none"
    path: str = ""
    version: str = ""
    notes: str = ""


class EngineCapabilities(BaseModel):
    """单个建树引擎支持的合法参数空间。"""

    engine: TreeEngineType
    label: str
    available: bool
    supports_dna: bool = True
    supports_protein: bool = True
    supports_bootstrap: bool = True
    min_bootstrap: int = 0
    max_bootstrap: int = 1000
    bootstrap_step: int = 100
    models_dna: List[str] = Field(default_factory=list)
    models_protein: List[str] = Field(default_factory=list)
    notes: str = ""


class CapabilitiesResponse(BaseModel):
    """系统计算能力与引擎契约总览。"""

    cpu_logical_cores: int
    cpu_safe_max: int
    cpu_default: int
    gpu_available: bool
    gpu_name: str = ""
    gpu_total_vram_mb: int = 0
    gpu_free_vram_mb: int = 0
    wsl_available: bool = False
    wsl_distro: str = ""
    tools: Dict[str, ToolDescriptor] = Field(default_factory=dict)
    engines: Dict[str, EngineCapabilities] = Field(default_factory=dict)


class PhyloJobConfig(BaseModel):
    """前端提交的系统发育分析任务配置。"""

    title: Optional[str] = None
    files: Optional[List[str]] = None
    track: TrackType = "auto"
    msa: MsaToolType = "mafft"
    msa_strategy: MsaStrategyType = "auto"
    trim_mode: TrimModeType = "none"
    trim_gap_threshold: Optional[float] = Field(default=None, ge=0.05, le=1.0)
    engine: TreeEngineType = "nj"
    model: str = "jc69"
    bootstrap: int = Field(default=100, ge=0, le=5000)
    iqtree_bnni: bool = True
    iqtree_alrt: int = Field(default=1000, ge=0, le=10000)
    iqtree_seed: int = Field(default=42, ge=0, le=2147483647)
    outgroup_ids: List[str] = Field(default_factory=list)
    threads: int = Field(default=0, ge=0, le=256)
    use_gpu: bool = True
    mash_kmer: int = Field(default=21, ge=11, le=31)
    mash_sketch: int = Field(default=1000, ge=100, le=50000)
    mrbayes_ngen: int = Field(default=10000, ge=1000, le=1000000)
    midpoint_root: bool = True
    use_cache: bool = True
    phage_scope: Optional[DeliveryScopeConfig] = None
    marker_mode: MarkerModeType = "terl"
    ani_engine: AniEngineType = "viridic_blastn"
    selected_references: List[ReferenceCandidate] = Field(default_factory=list)
    precomputed_ani_result: Optional[AniScreenResult] = None


class StageState(BaseModel):
    """流水线单阶段断点状态。"""

    name: str
    label: str
    status: StageStatusType = "pending"
    progress: int = 0
    cached: bool = False
    elapsed_sec: float = 0.0
    message: str = ""
    artifact_path: Optional[str] = None


class TreeMetrics(BaseModel):
    """生成进化树的拓扑与质量统计指标。"""

    leaf_count: int = 0
    internal_count: int = 0
    total_branch_length: float = 0.0
    diameter: float = 0.0
    mean_support: Optional[float] = None
    min_support: Optional[float] = None
    max_support: Optional[float] = None
    mean_alrt: Optional[float] = None
    strong_ufboot_ratio: Optional[float] = None
    has_dual_support: bool = False
    best_model: Optional[str] = None
    best_model_bic: Optional[float] = None
    is_rooted: bool = False


class WorkspaceFileItem(BaseModel):
    """工作区单个文件条目。"""

    name: str
    size: int
    modified_at: float
    ext: str


class WorkspaceInfo(BaseModel):
    """工作区文件清单与实时画像。"""

    files: List[WorkspaceFileItem] = Field(default_factory=list)
    profile: Optional[SequenceProfile] = None


class PhyloJobRecord(BaseModel):
    """持久化及前端展示用的完整任务记录。"""

    job_id: str
    title: str
    status: JobStatusType = "pending"
    resolved_track: Literal["genome", "gene", "phage_taxonomy"] = "gene"
    config: PhyloJobConfig
    profile: Optional[SequenceProfile] = None
    stages: List[StageState] = Field(default_factory=list)
    progress: int = 0
    current_stage: str = "pending"
    message: str = ""
    error: Optional[str] = None
    created_at: float
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    elapsed_sec: float = 0.0
    newick: Optional[str] = None
    metrics: Optional[TreeMetrics] = None
    job_dir: str = ""
    artifacts: Dict[str, Any] = Field(default_factory=dict)
    ani_result: Optional[AniScreenResult] = None
    marker_report: Optional[MarkerExtractionReport] = None
    qc_report: Optional[DeliveryQcReport] = None
    node_metadata: Dict[str, Dict[str, Any]] = Field(default_factory=dict)


PublicationLayoutType = Literal["circular", "rectangular"]
PublicationFormatType = Literal["pdf", "svg", "png"]
PublicationSupportStyle = Literal["dots", "text", "both", "none"]
ItolExportFormatType = Literal["pdf", "svg", "png", "eps"]
ItolDisplayModeType = Literal["rectangular", "circular", "unrooted"]


class PublicationFigureRequest(BaseModel):
    """方案 C：离线本地出版级进化树渲染请求参数。"""

    layout: PublicationLayoutType = "circular"
    formats: List[PublicationFormatType] = Field(default_factory=lambda: ["pdf", "svg", "png"])
    dpi: int = Field(default=300, ge=150, le=600)
    use_branch_lengths: bool = True
    support_style: PublicationSupportStyle = "dots"
    show_genus_strip: bool = True
    show_genome_length: bool = True
    show_gc_bar: bool = True
    ladderize: bool = True
    label_format: LabelFormatType = "name_acc"
    title: Optional[str] = None


class PublicationFigureItem(BaseModel):
    """单个已生成的出版级图件元信息。"""

    filename: str
    format: str
    layout: str
    size_bytes: int
    download_url: str


class PublicationRenderResponse(BaseModel):
    """离线出版级渲染结果返回。"""

    job_id: str
    layout: str
    figures: List[PublicationFigureItem] = Field(default_factory=list)


class ItolPullRequest(BaseModel):
    """方案 B：从免费官方 iTOL batch_downloader.cgi 拉取出图参数。"""

    tree_id_or_url: str
    format: ItolExportFormatType = "pdf"
    display_mode: ItolDisplayModeType = "circular"
    bootstrap_display: bool = True
    ignore_branch_length: bool = False
    datasets_visible: str = ""
    dpi: int = Field(default=300, ge=150, le=600)


class ItolPullResponse(BaseModel):
    """iTOL 导出拉取完成响应。"""

    job_id: str
    tree_id: str
    filename: str
    format: str
    size_bytes: int
    download_url: str
    itol_tree_url: str
