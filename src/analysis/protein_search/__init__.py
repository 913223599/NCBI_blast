# -*- coding: utf-8 -*-
"""
蛋白序列解析与多 FASTA 相似度检索包。

模块划分（单一职责原则）：
- models: 核心数据结构与配置模型
- fasta_parser: UTF-8 流式 FASTA 解析、分子类型识别与安全分片准备
- blast_runner: 多核资源规划、分片建库、并发 tblastn/blastp 与 Checkpoint 断点保护
- marker: 分片命中流式聚合、阈值标记、带标记 FASTA 导出与中文报告生成
- pipeline: 端到端检索流水线编排
"""

from .models import (
    BlastHitRecord,
    FileMarkSummary,
    PipelineResult,
    QueryProteinRecord,
    SearchConfig,
    SequenceMarkSummary,
    ShardSpec,
    TargetSequenceRecord,
)
from .pipeline import run_protein_fasta_search

__all__ = [
    "BlastHitRecord",
    "FileMarkSummary",
    "PipelineResult",
    "QueryProteinRecord",
    "SearchConfig",
    "SequenceMarkSummary",
    "ShardSpec",
    "TargetSequenceRecord",
    "run_protein_fasta_search",
]
