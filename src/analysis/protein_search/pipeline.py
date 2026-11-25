# -*- coding: utf-8 -*-
"""
蛋白序列解析与多 FASTA 相似度检索顶层流水线编排模块。
"""

from __future__ import annotations

from .blast_runner import build_shard_specs, execute_sharded_blast
from .fasta_parser import parse_query_proteins, scan_target_directory, write_safe_query_fasta
from .marker import aggregate_and_export
from .models import PipelineResult, SearchConfig


def run_protein_fasta_search(config: SearchConfig) -> PipelineResult:
    """
    执行完整的蛋白解析 -> 目标扫描与类型识别 -> 分片建库与多核 BLAST（带 Checkpoint）
    -> 聚合标记与报告导出流程。
    """
    config.output_dir.mkdir(parents=True, exist_ok=True)
    work_dir = config.output_dir / "_work"
    work_dir.mkdir(parents=True, exist_ok=True)

    # 1. 解析查询蛋白并写出纯 ASCII 安全 ID 查询文件
    queries = parse_query_proteins(config.query_fasta)
    safe_query_fasta = write_safe_query_fasta(queries, work_dir / "queries.safe.fasta")

    # 2. 扫描目标目录并自动识别 DNA / Protein / 3Di
    target_records, empty_files = scan_target_directory(config.target_dir)

    # 3. 规划检索分片并执行带 Checkpoint 断点保护的多核 BLAST
    specs, shard_record_map, total_dna_bases, total_prot_residues = build_shard_specs(
        target_records=target_records,
        queries=queries,
        config=config,
        work_dir=work_dir,
    )

    checkpoint_path = work_dir / "checkpoint.json"
    shards_resumed, _shards_executed, _workers = execute_sharded_blast(
        specs=specs,
        shard_record_map=shard_record_map,
        query_fasta_abs=safe_query_fasta.resolve(),
        config=config,
        checkpoint_path=checkpoint_path,
        total_dna_bases=total_dna_bases,
        total_prot_residues=total_prot_residues,
    )

    # 4. 流式聚合分片结果、标记并导出所有产物
    file_summaries, seq_summaries, output_files, total_gt30_hsps, total_bl_hsps = (
        aggregate_and_export(
            queries=queries,
            target_records=target_records,
            empty_files=empty_files,
            specs=specs,
            config=config,
            shards_resumed=shards_resumed,
        )
    )

    dna_files = sum(1 for f in file_summaries if f.dominant_kind == "dna")
    prot_files = sum(1 for f in file_summaries if f.dominant_kind == "protein")
    skip_3di_files = sum(1 for f in file_summaries if f.dominant_kind == "3di")
    marked_hit_files = sum(1 for f in file_summaries if f.mark_label == "[HIT>30%]")
    marked_hit_seqs = sum(1 for s in seq_summaries if s.mark_label == "[HIT>30%]")
    bl_only_files = sum(1 for f in file_summaries if f.mark_label == "[BORDERLINE>30%]")

    return PipelineResult(
        output_dir=config.output_dir,
        query_count=len(queries),
        target_file_count=len(file_summaries),
        target_record_count=len(seq_summaries),
        dna_file_count=dna_files,
        protein_file_count=prot_files,
        skipped_3di_file_count=skip_3di_files,
        marked_hit_file_count=marked_hit_files,
        marked_hit_sequence_count=marked_hit_seqs,
        borderline_only_file_count=bl_only_files,
        total_gt30_hsps=total_gt30_hsps,
        total_borderline_hsps=total_bl_hsps,
        shards_total=len(specs),
        shards_resumed=shards_resumed,
        output_files=output_files,
    )
