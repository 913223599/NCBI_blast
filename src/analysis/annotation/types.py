# -*- coding: utf-8 -*-
"""
功能注释数据模型定义
"""
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field


class ContigMetaItem(BaseModel):
    """单条 Contig/Scaffold 序列元数据"""
    id: str
    description: str = ""
    length_bp: int
    gc_content: float
    selected: bool = True


class FastaInspectRequest(BaseModel):
    """FASTA 快速预检查请求"""
    fasta_path: Optional[str] = None
    fasta_content: Optional[str] = None


class FastaInspectResponse(BaseModel):
    """FASTA 快速预检查响应"""
    success: bool = True
    num_contigs: int = 0
    total_length: int = 0
    gc_content: float = 0.0
    contigs: List[ContigMetaItem] = []


class AnnotationRunRequest(BaseModel):
    """注释任务运行请求参数"""
    task_name: Optional[str] = Field(default="Annotation_Task", description="任务名称")
    sample_type: str = Field(default="BACTERIA", description="样本类型: BACTERIA, PHAGE, VIRUS, GENERAL")
    engine: str = Field(default="auto", description="注释引擎: auto, prokka, pharokka, prodigal, builtin")
    fasta_path: Optional[str] = Field(default=None, description="服务器本地 FASTA 文件路径")
    fasta_content: Optional[str] = Field(default=None, description="直接提交的 FASTA 序列文本")
    prefix: Optional[str] = Field(default="ANNO", description="基因位点前缀 (Locus Tag Prefix)")
    genetic_code: int = Field(default=11, description="翻译遗传密码子代号 (标准=1, 细菌/古菌/质粒=11, 支原体=4)")
    min_contig_len: int = Field(default=200, description="过滤序列的最小长度阈值 (bp)")
    threads: Optional[int] = Field(default=None, description="并行线程数 (默认自适应保留核心)")
    selected_contigs: Optional[List[str]] = Field(default=None, description="选定需要分析的 Contig ID 列表，留空表示全部分析")


class FeatureItem(BaseModel):
    """单个基因组特征条目"""
    id: str
    locus_tag: str
    feature_type: str  # CDS, tRNA, rRNA, tmRNA, CRISPR, misc_feature
    start: int
    end: int
    strand: str  # "+" or "-"
    length_bp: int
    gene_name: Optional[str] = None
    product: str = "hypothetical protein"
    protein_id: Optional[str] = None
    protein_length_aa: Optional[int] = None
    molecular_weight_kda: Optional[float] = None
    translation: Optional[str] = None
    nucleotide_seq: Optional[str] = None
    ec_number: Optional[str] = None
    cog: Optional[str] = None
    notes: Optional[str] = None


class AnnotationSummary(BaseModel):
    """注释结果统计摘要"""
    total_length: int = 0
    num_contigs: int = 0
    gc_content: float = 0.0
    cds_count: int = 0
    trna_count: int = 0
    rrna_count: int = 0
    tmrna_count: int = 0
    crispr_count: int = 0
    other_count: int = 0
    total_features: int = 0
    coding_density_pct: float = 0.0
    avg_gene_length: float = 0.0


class AnnotationTaskRecord(BaseModel):
    """注释任务持久化记录"""
    task_id: str
    task_name: str
    sample_type: str
    engine: str
    status: str  # pending, running, completed, failed, cancelled
    progress: int = 0
    current_step: str = ""
    error_msg: Optional[str] = None
    created_at: str
    updated_at: str
    summary: Optional[AnnotationSummary] = None
    files: Dict[str, str] = Field(default_factory=dict)
