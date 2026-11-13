# -*- coding: utf-8 -*-
"""
前噬菌体发现工作台请求与数据结构定义
"""
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class PhageScanInspectRequest(BaseModel):
    """FASTA / GenBank 输入预检请求。"""

    fasta_path: Optional[str] = None
    fasta_content: Optional[str] = None


class PhageScanRunRequest(BaseModel):
    """提交前噬菌体发现扫描任务请求参数。"""

    task_name: str = Field(default="PhageDiscovery_Task", description="扫描任务名称")
    fasta_path: Optional[str] = Field(default=None, description="待扫描的本地基因组 FASTA/GBK 路径")
    fasta_content: Optional[str] = Field(default=None, description="直接粘贴的 FASTA 文本内容")
    selected_contigs: Optional[List[str]] = Field(default=None, description="勾选参与扫描的 Contig ID 列表")

    model_id: Optional[str] = Field(default=None, description="选用的模型标识 (如 student_v4_2)")
    custom_model_dir: Optional[str] = Field(default=None, description="自定义覆盖模型目录路径")
    device: str = Field(default="auto", description="计算设备: auto / cuda / cpu")
    workers: Optional[int] = Field(default=None, description="多核特征提取线程数")

    apply_protein_gate: bool = Field(default=False, description="是否启用第二阶段 BLASTp 病毒标志蛋白门控")
    blast_db: Optional[str] = Field(default=None, description="可选自定义蛋白 BLAST 库前缀")

    seed_threshold: Optional[float] = Field(default=None, ge=0.05, le=0.999, description="种子激活阈值")
    extend_threshold: Optional[float] = Field(default=None, ge=0.05, le=0.999, description="滞回扩展阈值")
    sub_threshold: Optional[float] = Field(default=None, ge=0.05, le=0.999, description="200bp 精细边界阈值")
    merge_gap_bp: int = Field(default=3000, ge=0, le=50000, description="邻近前噬菌体片段合并最大间隔 (bp)")
    min_region_bp: int = Field(default=3000, ge=400, le=50000, description="最短保留区段长度 (bp)")

    metadata: Dict[str, Any] = Field(default_factory=dict, description="附加上下文元数据")


class PhageConfigPathRequest(BaseModel):
    """保存自定义模型目录或蛋白门控库配置请求。"""

    models_root: Optional[str] = None
    default_model_dir: Optional[str] = None
    blast_db: Optional[str] = None

