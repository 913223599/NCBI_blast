# -*- coding: utf-8 -*-
"""
Figure Studio 强类型 Pydantic 请求与响应模型定义。
"""
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field

StudioFormatType = Literal["pdf", "svg", "png"]
StudioPaletteType = Literal["nature", "lancet", "okabe_ito", "monochrome"]


class StudioFigureFile(BaseModel):
    filename: str
    format: str
    size_bytes: int
    download_url: str


class StudioRenderResponse(BaseModel):
    render_id: str
    tool_id: str
    title: str
    created_at: float
    figures: List[StudioFigureFile] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class StudioHistoryItem(BaseModel):
    render_id: str
    tool_id: str
    title: str
    created_at: float
    figures: List[StudioFigureFile] = Field(default_factory=list)


class GenomeFeatureItem(BaseModel):
    locus_tag: str = ""
    start: int
    end: int
    strand: str = "+"
    feature_type: str = "CDS"
    product: str = "hypothetical protein"
    category: str = ""
    function: str = ""
    phrog: Optional[str] = None
    translation: str = ""
    nucleotide_seq: str = ""


class ParsedGenomeInput(BaseModel):
    name: str
    sequence: str = ""
    length: int = 0
    features: List[GenomeFeatureItem] = Field(default_factory=list)


class ViridicRenderRequest(BaseModel):
    mode: Literal["viridic_dual", "tree_triangle"] = "viridic_dual"
    phylo_job_id: Optional[str] = None
    use_demo: bool = False
    labels: List[str] = Field(default_factory=list)
    wgani_matrix: List[List[float]] = Field(default_factory=list)
    af_matrix: List[List[float]] = Field(default_factory=list)
    genome_lengths: List[int] = Field(default_factory=list)
    newick: Optional[str] = None
    cluster_reorder: bool = True
    show_values: bool = True
    palette: StudioPaletteType = "nature"
    title: str = "VIRIDIC Intergenomic Similarity & Alignment Matrix"
    formats: List[StudioFormatType] = Field(default_factory=lambda: ["pdf", "svg", "png"])
    dpi: int = Field(default=300, ge=100, le=600)


class GenomeMapRenderRequest(BaseModel):
    mode: Literal["circular", "linear_multitrack"] = "circular"
    annotation_task_id: Optional[str] = None
    gbk_path: Optional[str] = None
    gbk_content: Optional[str] = None
    use_demo: bool = False
    gc_window: int = Field(default=0, ge=0, le=5000)
    show_labels: bool = True
    max_labels: int = Field(default=28, ge=6, le=60)
    show_gc_content: bool = True
    show_gc_skew: bool = True
    palette: StudioPaletteType = "nature"
    title: Optional[str] = None
    formats: List[StudioFormatType] = Field(default_factory=lambda: ["pdf", "svg", "png"])
    dpi: int = Field(default=300, ge=100, le=600)


class SyntenyRenderRequest(BaseModel):
    mode: Literal["lovis4u", "clinker"] = "lovis4u"
    annotation_task_ids: List[str] = Field(default_factory=list)
    gbk_paths: List[str] = Field(default_factory=list)
    use_demo: bool = False
    min_identity: float = Field(default=35.0, ge=15.0, le=99.0)
    show_identity_labels: bool = False
    show_labels: bool = True
    palette: StudioPaletteType = "nature"
    title: str = "Comparative Phage Genome Synteny"
    formats: List[StudioFormatType] = Field(default_factory=lambda: ["pdf", "svg", "png"])
    dpi: int = Field(default=300, ge=100, le=600)


class DiversityRenderRequest(BaseModel):
    ref_annotation_task_id: Optional[str] = None
    compare_annotation_task_ids: List[str] = Field(default_factory=list)
    phylo_job_id: Optional[str] = None
    fasta_content: Optional[str] = None
    use_demo: bool = False
    window_size: int = Field(default=250, ge=50, le=5000)
    step_size: int = Field(default=50, ge=10, le=1000)
    show_gene_table: bool = True
    palette: StudioPaletteType = "nature"
    title: str = "Genome-Wide Nucleotide Diversity (Pi) & Polymorphism Map"
    formats: List[StudioFormatType] = Field(default_factory=lambda: ["pdf", "svg", "png"])
    dpi: int = Field(default=300, ge=100, le=600)


class NetworkRenderRequest(BaseModel):
    phylo_job_id: Optional[str] = None
    annotation_task_ids: List[str] = Field(default_factory=list)
    edges_csv: Optional[str] = None
    use_demo: bool = False
    min_weight: float = Field(default=0.20, ge=0.0, le=1.0)
    color_by: Literal["family", "host"] = "family"
    show_waffle: bool = True
    show_labels: bool = True
    palette: StudioPaletteType = "nature"
    title: str = "Gene-Sharing Viral Protein Cluster Network"
    formats: List[StudioFormatType] = Field(default_factory=lambda: ["pdf", "svg", "png"])
    dpi: int = Field(default=300, ge=100, le=600)


class HostMatrixRenderRequest(BaseModel):
    mode: Literal["dual_tree_heatmap", "sparse_specificity"] = "dual_tree_heatmap"
    use_demo: bool = False
    matrix_csv: Optional[str] = None
    row_labels: List[str] = Field(default_factory=list)
    col_labels: List[str] = Field(default_factory=list)
    values: List[List[float]] = Field(default_factory=list)
    row_groups: List[str] = Field(default_factory=list)
    col_groups: List[str] = Field(default_factory=list)
    phylo_job_id: Optional[str] = None
    row_newick: Optional[str] = None
    col_newick: Optional[str] = None
    cluster_rows: bool = True
    cluster_cols: bool = True
    show_values: bool = False
    palette: StudioPaletteType = "nature"
    title: str = "Phage-Host Interaction & Receptor Specificity Matrix"
    formats: List[StudioFormatType] = Field(default_factory=lambda: ["pdf", "svg", "png"])
    dpi: int = Field(default=300, ge=100, le=600)
