# -*- coding: utf-8 -*-
"""
蛋白序列检索模块的数据模型与配置定义。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

SequenceKind = Literal["dna", "protein", "3di", "empty"]
HitMarkStatus = Literal["HIT_GT_30", "BORDERLINE_GT_30", "BELOW_THRESHOLD"]
EntityMarkLabel = Literal[
    "[HIT>30%]",
    "[BORDERLINE>30%]",
    "[NO_HIT]",
    "[SKIPPED_3DI]",
    "[EMPTY]",
]


@dataclass(frozen=True)
class QueryProteinRecord:
    """解析后的单条查询蛋白条目。"""

    index: int
    safe_id: str
    query_id: str
    header: str
    length: int
    sequence: str
    sha256_prefix: str
    sequence_kind: SequenceKind


@dataclass(frozen=True)
class TargetSequenceRecord:
    """扫描到的目标 FASTA 单条序列元信息（不常驻序列本体以控制内存）。"""

    safe_id: str
    file_name: str
    rel_path: str
    abs_path: Path
    record_index: int
    seq_id: str
    header: str
    kind: SequenceKind
    length: int


@dataclass(frozen=True)
class ShardSpec:
    """单个 BLAST 检索分片定义。"""

    shard_id: str
    db_type: Literal["nucl", "prot"]
    program: Literal["tblastn", "blastp"]
    rel_paths: tuple[str, ...]
    record_count: int
    total_residues: int
    fingerprint: str
    fasta_path: Path
    hit_tsv_path: Path


@dataclass(frozen=True)
class BlastHitRecord:
    """单条 BLAST HSP 比对结果及其阈值标记状态。"""

    query_safe_id: str
    query_id: str
    query_header: str
    query_len: int
    target_safe_id: str
    target_file: str
    target_rel_path: str
    target_record_index: int
    target_seq_id: str
    target_header: str
    target_kind: str
    target_len: int
    program: str
    pident: float
    ppos: float
    align_len: int
    nident: int
    positive: int
    mismatch: int
    gapopen: int
    qstart: int
    qend: int
    qcov_hsp: float
    sstart: int
    send: int
    sframe: int
    evalue: float
    bitscore: float
    mark_status: HitMarkStatus


@dataclass
class SequenceMarkSummary:
    """序列条目级检索与标记汇总。"""

    safe_id: str
    file_name: str
    rel_path: str
    record_index: int
    seq_id: str
    header: str
    kind: SequenceKind
    length: int
    mark_label: EntityMarkLabel
    hit_gt30_count: int = 0
    borderline_gt30_count: int = 0
    matched_query_ids: list[str] = field(default_factory=list)
    borderline_query_ids: list[str] = field(default_factory=list)
    best_query_id: str = ""
    max_pident: float = 0.0
    max_ppos: float = 0.0
    min_evalue: float | None = None
    max_bitscore: float = 0.0
    best_align_len: int = 0
    best_qcov_hsp: float = 0.0
    best_program: str = ""
    best_sstart: int = 0
    best_send: int = 0
    best_sframe: int = 0


@dataclass
class FileMarkSummary:
    """目标文件级检索与标记汇总。"""

    file_name: str
    rel_path: str
    dominant_kind: SequenceKind
    total_records: int
    total_length: int
    mark_label: EntityMarkLabel
    hit_record_count: int = 0
    borderline_record_count: int = 0
    hit_gt30_hsp_count: int = 0
    matched_query_ids: list[str] = field(default_factory=list)
    borderline_query_ids: list[str] = field(default_factory=list)
    best_query_id: str = ""
    best_target_seq_id: str = ""
    max_pident: float = 0.0
    max_ppos: float = 0.0
    min_evalue: float | None = None
    max_bitscore: float = 0.0
    best_align_len: int = 0
    best_qcov_hsp: float = 0.0
    best_program: str = ""
    note: str = ""


@dataclass(frozen=True)
class SearchConfig:
    """检索流水线配置（全部路径由调用方传入，严禁硬编码）。"""

    query_fasta: Path
    target_dir: Path
    output_dir: Path
    min_pident: float = 30.0
    max_evalue: float = 1e-5
    blast_evalue: float = 1e-3
    min_align_len: int = 30
    shard_max_files: int = 10
    shard_max_residues: int = 1_000_000
    max_target_seqs: int = 2000
    db_gencode: int = 11
    threads: int | None = None
    resume: bool = True
    blast_bin_dir: Path | None = None
    clean_temp_db: bool = True


@dataclass(frozen=True)
class PipelineResult:
    """流水线执行完成后的交付路径与核心统计。"""

    output_dir: Path
    query_count: int
    target_file_count: int
    target_record_count: int
    dna_file_count: int
    protein_file_count: int
    skipped_3di_file_count: int
    marked_hit_file_count: int
    marked_hit_sequence_count: int
    borderline_only_file_count: int
    total_gt30_hsps: int
    total_borderline_hsps: int
    shards_total: int
    shards_resumed: int
    output_files: dict[str, Path]
