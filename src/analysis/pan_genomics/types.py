# -*- coding: utf-8 -*-
"""
泛基因组与多样本比较分析数据模型与类型定义 (PanGenomics Types)
"""
from typing import Dict, List, Any, Optional
from pydantic import BaseModel, Field


class SampleInputItem(BaseModel):
    """待分析样本输入定义"""
    sample_id: str
    sample_name: str
    source_type: str = "task"  # 'task' | 'external_file'
    task_id: Optional[str] = None
    file_path: Optional[str] = None
    file_type: Optional[str] = None  # 'gbk' | 'faa' | 'fasta'


class PanGenomicsRunRequest(BaseModel):
    """泛基因组分析请求参数"""
    samples: List[SampleInputItem]
    identity_threshold: float = Field(0.5, description="正交聚类相似度阈值 (0.3 ~ 0.95)")
    coverage_threshold: float = Field(0.5, description="正交聚类覆盖度阈值 (0.3 ~ 0.9)")
    threads: Optional[int] = Field(None, description="并行计算线程数")


class OrthologGeneItem(BaseModel):
    """正交家族中的单基因信息"""
    sample_id: str
    sample_name: str
    gene_id: str
    locus_tag: str
    product: str
    category: str
    length_aa: int
    strand: str
    start: int
    end: int
    source_engine: Optional[str] = None


class OrthologGroup(BaseModel):
    """正交同源基因家族 (Orthologous Group)"""
    group_id: str
    representative_product: str
    category: str
    sample_count: int
    total_genes: int
    cluster_type: str  # 'Core' (全共有) | 'Accessory' (部分共有) | 'Unique' (单个特有)
    samples_present: List[str]
    genes: List[OrthologGeneItem]
    presence_map: Optional[Dict[str, Optional[Dict[str, Any]]]] = Field(default_factory=dict, description="按样本 ID 映射的具体基因或 null")


class LifestyleItem(BaseModel):
    """单个样本的生活史判定结果"""
    sample_id: str
    sample_name: str
    lifestyle: str  # 'Lytic' (烈性) | 'Temperate' (温和型) | 'Uncertain'
    confidence: float
    is_safe_for_therapy: bool
    integrase_count: int
    repressor_count: int
    markers: List[Dict[str, Any]]
    explanation: str


class TailProteinItem(BaseModel):
    """尾部受体识别蛋白"""
    sample_id: str
    sample_name: str
    gene_id: str
    locus_tag: str
    product: str
    tail_type: str  # 'Tail Fiber' | 'Tail Spike' | 'RBP' | 'Major Tail' | 'Tape Measure'
    length_aa: int
    sequence: str


class LysisProteinItem(BaseModel):
    """裂解系统蛋白 (含基因组物理坐标与链方向)"""
    sample_id: str
    sample_name: str
    gene_id: str
    locus_tag: str
    product: str
    lysis_role: str  # 'Endolysin' | 'Holin' | 'Spanin' | 'Antiholin'
    length_aa: int
    start: int = 0
    end: int = 0
    strand: str = "+"
    sequence: str


class PanGenomicsSummary(BaseModel):
    """泛基因组分析宏观统计与 Heaps Law 开闭判定"""
    total_samples: int
    total_genes: int
    total_clusters: int
    core_clusters_count: int
    accessory_clusters_count: int
    unique_clusters_count: int
    core_genes_count: int
    accessory_genes_count: int
    unique_genes_count: int
    heaps_law: Optional[Dict[str, Any]] = None  # { alpha, gamma, is_open, dilution_curve: [{n, pan_count, core_count}] }


class PanGenomicsResult(BaseModel):
    """泛基因组与多维交叉对比完整结果"""
    task_id: str
    created_at: str
    summary: PanGenomicsSummary
    sample_names: Dict[str, str]  # sample_id -> sample_name
    
    # 0. 全基因组 ANI 亲缘矩阵与层次聚类树
    ani_matrix: Dict[str, Dict[str, float]]
    ani_clustering: Optional[Dict[str, Any]] = None
    
    # 1. 泛基因组聚类与存在/缺失大表
    clusters: List[OrthologGroup]
    heaps_law: Optional[Dict[str, Any]] = None
    
    # 2. 宿主识别与尾部模块 (含层次聚类与鸡尾酒配方)
    tail_proteins: List[TailProteinItem]
    tail_identity_matrix: Dict[str, Dict[str, float]]
    tail_clustering: Optional[Dict[str, Any]] = None
    host_range_prediction: Dict[str, Any]
    
    # 3. 宿主攻防与生活史安全性
    lifestyles: List[LifestyleItem]
    arms_race_matrix: Dict[str, Dict[str, Any]]  # sample_id -> { acr_count, amr_count, vf_count, acr_list, amr_list, vf_list }
    
    # 4. 裂解系统 (含各样本真实物理构型与层次聚类)
    lysis_proteins: List[LysisProteinItem]
    lysis_identity_matrix: Dict[str, Dict[str, float]]
    lysis_clustering: Optional[Dict[str, Any]] = None
    
    # 5. 代谢重塑与 tRNA
    amg_genes: List[Dict[str, Any]]
    trna_profiles: Dict[str, List[Dict[str, Any]]]  # sample_id -> [tRNA items]
    amg_pathway_distributions: Optional[Dict[str, Dict[str, int]]] = None
    
    # 6. 功能大类全景热图与宏观分布
    category_distributions: Dict[str, Dict[str, int]]  # sample_id -> { category: count }

    # 7. AI/规则驱动的科研综合评估报告
    scientific_synthesis_report: Dict[str, Any]
