# -*- coding: utf-8 -*-
"""
分片命中流式聚合、阈值标记、带标记 FASTA 导出与简体中文汇总报告生成模块。
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Iterator

from .fasta_parser import iter_fasta_records
from .models import (
    BlastHitRecord,
    EntityMarkLabel,
    FileMarkSummary,
    HitMarkStatus,
    QueryProteinRecord,
    SearchConfig,
    SequenceKind,
    SequenceMarkSummary,
    ShardSpec,
    TargetSequenceRecord,
)

HIT_TSV_HEADERS = [
    "mark_status",
    "query_id",
    "query_len",
    "target_file",
    "target_rel_path",
    "target_record_index",
    "target_seq_id",
    "target_kind",
    "target_len",
    "program",
    "pident",
    "ppos",
    "align_len",
    "nident",
    "positive",
    "mismatch",
    "gapopen",
    "qstart",
    "qend",
    "qcov_hsp",
    "sstart",
    "send",
    "sframe",
    "evalue",
    "bitscore",
    "target_header",
]


def classify_hit_status(
    pident: float,
    evalue: float,
    align_len: int,
    config: SearchConfig,
) -> HitMarkStatus:
    """判定单条 HSP 命中的标记级别。"""
    if pident > config.min_pident:
        if evalue <= config.max_evalue and align_len >= config.min_align_len:
            return "HIT_GT_30"
        return "BORDERLINE_GT_30"
    return "BELOW_THRESHOLD"


def iter_shard_hits(
    specs: list[ShardSpec],
    query_by_safe_id: dict[str, QueryProteinRecord],
    target_by_safe_id: dict[str, TargetSequenceRecord],
    config: SearchConfig,
) -> Iterator[BlastHitRecord]:
    """流式逐行读取所有分片落盘命中文件并还原原始 ID 与元信息。"""
    for spec in specs:
        if not spec.hit_tsv_path.is_file():
            continue
        with spec.hit_tsv_path.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                stripped = line.strip()
                if not stripped:
                    continue
                parts = stripped.split("\t")
                if len(parts) < 19:
                    continue
                program = parts[0]
                q_safe = parts[1]
                s_safe = parts[2]
                q_rec = query_by_safe_id.get(q_safe)
                t_rec = target_by_safe_id.get(s_safe)
                if q_rec is None or t_rec is None:
                    continue

                pident = float(parts[3])
                ppos = float(parts[4])
                align_len = int(parts[5])
                nident = int(parts[6])
                positive = int(parts[7])
                mismatch = int(parts[8])
                gapopen = int(parts[9])
                qstart = int(parts[10])
                qend = int(parts[11])
                qlen = int(parts[12])
                sstart = int(parts[13])
                send = int(parts[14])
                sframe = int(parts[16])
                evalue = float(parts[17])
                bitscore = float(parts[18])
                qcov_hsp = round((abs(qend - qstart) + 1) / max(1, qlen) * 100.0, 2)
                mark_status = classify_hit_status(pident, evalue, align_len, config)

                yield BlastHitRecord(
                    query_safe_id=q_safe,
                    query_id=q_rec.query_id,
                    query_header=q_rec.header,
                    query_len=q_rec.length,
                    target_safe_id=s_safe,
                    target_file=t_rec.file_name,
                    target_rel_path=t_rec.rel_path,
                    target_record_index=t_rec.record_index,
                    target_seq_id=t_rec.seq_id,
                    target_header=t_rec.header,
                    target_kind=t_rec.kind,
                    target_len=t_rec.length,
                    program=program,
                    pident=pident,
                    ppos=ppos,
                    align_len=align_len,
                    nident=nident,
                    positive=positive,
                    mismatch=mismatch,
                    gapopen=gapopen,
                    qstart=qstart,
                    qend=qend,
                    qcov_hsp=qcov_hsp,
                    sstart=sstart,
                    send=send,
                    sframe=sframe,
                    evalue=evalue,
                    bitscore=bitscore,
                    mark_status=mark_status,
                )


def _hit_to_row(hit: BlastHitRecord) -> list[object]:
    return [
        hit.mark_status,
        hit.query_id,
        hit.query_len,
        hit.target_file,
        hit.target_rel_path,
        hit.target_record_index,
        hit.target_seq_id,
        hit.target_kind,
        hit.target_len,
        hit.program,
        f"{hit.pident:.2f}",
        f"{hit.ppos:.2f}",
        hit.align_len,
        hit.nident,
        hit.positive,
        hit.mismatch,
        hit.gapopen,
        hit.qstart,
        hit.qend,
        f"{hit.qcov_hsp:.2f}",
        hit.sstart,
        hit.send,
        hit.sframe,
        f"{hit.evalue:.3e}",
        f"{hit.bitscore:.1f}",
        hit.target_header,
    ]


def _is_better_hit(candidate: BlastHitRecord, cur_pident: float, cur_bitscore: float) -> bool:
    if candidate.pident != cur_pident:
        return candidate.pident > cur_pident
    return candidate.bitscore > cur_bitscore


def aggregate_and_export(
    queries: list[QueryProteinRecord],
    target_records: list[TargetSequenceRecord],
    empty_files: list[tuple[str, Path]],
    specs: list[ShardSpec],
    config: SearchConfig,
    shards_resumed: int,
) -> tuple[
    list[FileMarkSummary],
    list[SequenceMarkSummary],
    dict[str, Path],
    int,
    int,
]:
    """
    流式聚合全部分片结果，写出所有结构化标记表格、带标记 FASTA 及简体中文分析报告。
    """
    out_dir = config.output_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    query_by_safe = {q.safe_id: q for q in queries}
    target_by_safe = {t.safe_id: t for t in target_records}

    # 初始化序列级汇总
    seq_summaries: dict[str, SequenceMarkSummary] = {}
    for t in target_records:
        init_label: EntityMarkLabel
        if t.kind == "3di":
            init_label = "[SKIPPED_3DI]"
        elif t.kind == "empty":
            init_label = "[EMPTY]"
        else:
            init_label = "[NO_HIT]"
        seq_summaries[t.safe_id] = SequenceMarkSummary(
            safe_id=t.safe_id,
            file_name=t.file_name,
            rel_path=t.rel_path,
            record_index=t.record_index,
            seq_id=t.seq_id,
            header=t.header,
            kind=t.kind,
            length=t.length,
            mark_label=init_label,
        )

    # 查询蛋白命中统计
    query_hit_files: dict[str, set[str]] = {q.query_id: set() for q in queries}
    query_hit_seqs: dict[str, set[str]] = {q.query_id: set() for q in queries}
    query_best_pident: dict[str, float] = {q.query_id: 0.0 for q in queries}
    query_best_target: dict[str, str] = {q.query_id: "" for q in queries}

    all_hits_path = out_dir / "blast_hits_all.tsv"
    gt30_hits_path = out_dir / "blast_hits_gt30.tsv"
    borderline_hits_path = out_dir / "blast_hits_borderline_gt30.tsv"

    gt30_hits: list[BlastHitRecord] = []
    borderline_hits: list[BlastHitRecord] = []
    ppos_only_gt30_files: set[str] = set()

    with all_hits_path.open("w", encoding="utf-8", newline="") as all_f:
        all_writer = csv.writer(all_f, delimiter="\t", lineterminator="\n")
        all_writer.writerow(HIT_TSV_HEADERS)

        for hit in iter_shard_hits(specs, query_by_safe, target_by_safe, config):
            all_writer.writerow(_hit_to_row(hit))
            sm = seq_summaries[hit.target_safe_id]

            if hit.ppos > config.min_pident and hit.pident <= config.min_pident:
                if hit.evalue <= config.max_evalue and hit.align_len >= config.min_align_len:
                    ppos_only_gt30_files.add(hit.target_rel_path)

            if hit.mark_status == "HIT_GT_30":
                gt30_hits.append(hit)
                sm.hit_gt30_count += 1
                sm.mark_label = "[HIT>30%]"
                if hit.query_id not in sm.matched_query_ids:
                    sm.matched_query_ids.append(hit.query_id)
                if _is_better_hit(hit, sm.max_pident, sm.max_bitscore):
                    sm.best_query_id = hit.query_id
                    sm.max_pident = hit.pident
                    sm.max_ppos = hit.ppos
                    sm.min_evalue = hit.evalue
                    sm.max_bitscore = hit.bitscore
                    sm.best_align_len = hit.align_len
                    sm.best_qcov_hsp = hit.qcov_hsp
                    sm.best_program = hit.program
                    sm.best_sstart = hit.sstart
                    sm.best_send = hit.send
                    sm.best_sframe = hit.sframe

                query_hit_files[hit.query_id].add(hit.target_rel_path)
                query_hit_seqs[hit.query_id].add(hit.target_safe_id)
                if hit.pident > query_best_pident[hit.query_id]:
                    query_best_pident[hit.query_id] = hit.pident
                    query_best_target[hit.query_id] = f"{hit.target_file}:{hit.target_seq_id}"

            elif hit.mark_status == "BORDERLINE_GT_30":
                borderline_hits.append(hit)
                sm.borderline_gt30_count += 1
                if hit.query_id not in sm.borderline_query_ids:
                    sm.borderline_query_ids.append(hit.query_id)
                if sm.mark_label != "[HIT>30%]":
                    sm.mark_label = "[BORDERLINE>30%]"
                    if _is_better_hit(hit, sm.max_pident, sm.max_bitscore):
                        sm.best_query_id = hit.query_id
                        sm.max_pident = hit.pident
                        sm.max_ppos = hit.ppos
                        sm.min_evalue = hit.evalue
                        sm.max_bitscore = hit.bitscore
                        sm.best_align_len = hit.align_len
                        sm.best_qcov_hsp = hit.qcov_hsp
                        sm.best_program = hit.program
                        sm.best_sstart = hit.sstart
                        sm.best_send = hit.send
                        sm.best_sframe = hit.sframe

    # 按相似度与 bitscore 降序写出 >30% 明细表与边缘候选表
    gt30_hits.sort(key=lambda h: (-h.pident, -h.bitscore, h.evalue, h.target_rel_path))
    borderline_hits.sort(key=lambda h: (-h.pident, -h.bitscore, h.evalue, h.target_rel_path))

    with gt30_hits_path.open("w", encoding="utf-8", newline="") as f_gt30:
        w = csv.writer(f_gt30, delimiter="\t", lineterminator="\n")
        w.writerow(HIT_TSV_HEADERS)
        for hit in gt30_hits:
            w.writerow(_hit_to_row(hit))

    with borderline_hits_path.open("w", encoding="utf-8", newline="") as f_bl:
        w = csv.writer(f_bl, delimiter="\t", lineterminator="\n")
        w.writerow(HIT_TSV_HEADERS)
        for hit in borderline_hits:
            w.writerow(_hit_to_row(hit))

    # 聚合文件级汇总
    file_groups: dict[str, list[SequenceMarkSummary]] = {}
    for sm in seq_summaries.values():
        file_groups.setdefault(sm.rel_path, []).append(sm)

    file_summaries: list[FileMarkSummary] = []
    for rel_path in sorted(file_groups.keys(), key=str.lower):
        sms = file_groups[rel_path]
        kinds = [s.kind for s in sms]
        if "dna" in kinds:
            dom_kind: SequenceKind = "dna"
        elif "protein" in kinds:
            dom_kind = "protein"
        elif "3di" in kinds:
            dom_kind = "3di"
        else:
            dom_kind = "empty"

        hit_sms = [s for s in sms if s.mark_label == "[HIT>30%]"]
        bl_sms = [s for s in sms if s.mark_label == "[BORDERLINE>30%]"]

        if dom_kind == "3di":
            f_label: EntityMarkLabel = "[SKIPPED_3DI]"
            note = "Foldseek/Phold 3Di 结构状态字母表序列，非核酸/蛋白序列，已自动跳过"
        elif dom_kind == "empty":
            f_label = "[EMPTY]"
            note = "空序列文件"
        elif hit_sms:
            f_label = "[HIT>30%]"
            note = f"含 {len(hit_sms)}/{len(sms)} 条序列匹配相似度 > {config.min_pident:.0f}%"
        elif bl_sms:
            f_label = "[BORDERLINE>30%]"
            note = (
                f"仅含边缘匹配（pident > {config.min_pident:.0f}% 但 evalue > {config.max_evalue:.0e} "
                f"或 align_len < {config.min_align_len} aa）"
            )
        else:
            f_label = "[NO_HIT]"
            note = "未检出相似度 > 30% 的同源区域"

        matched_q: list[str] = []
        borderline_q: list[str] = []
        for s in hit_sms:
            for qid in s.matched_query_ids:
                if qid not in matched_q:
                    matched_q.append(qid)
        for s in sms:
            for qid in s.borderline_query_ids:
                if qid not in borderline_q:
                    borderline_q.append(qid)

        best_pool = hit_sms if hit_sms else bl_sms
        best_sm = (
            max(best_pool, key=lambda s: (s.max_pident, s.max_bitscore))
            if best_pool
            else None
        )

        file_summaries.append(
            FileMarkSummary(
                file_name=sms[0].file_name,
                rel_path=rel_path,
                dominant_kind=dom_kind,
                total_records=len(sms),
                total_length=sum(s.length for s in sms),
                mark_label=f_label,
                hit_record_count=len(hit_sms),
                borderline_record_count=len(bl_sms),
                hit_gt30_hsp_count=sum(s.hit_gt30_count for s in sms),
                matched_query_ids=matched_q,
                borderline_query_ids=borderline_q,
                best_query_id=best_sm.best_query_id if best_sm else "",
                best_target_seq_id=best_sm.seq_id if best_sm else "",
                max_pident=best_sm.max_pident if best_sm else 0.0,
                max_ppos=best_sm.max_ppos if best_sm else 0.0,
                min_evalue=best_sm.min_evalue if best_sm else None,
                max_bitscore=best_sm.max_bitscore if best_sm else 0.0,
                best_align_len=best_sm.best_align_len if best_sm else 0,
                best_qcov_hsp=best_sm.best_qcov_hsp if best_sm else 0.0,
                best_program=best_sm.best_program if best_sm else "",
                note=note,
            )
        )

    for rel_path, f_path in empty_files:
        file_summaries.append(
            FileMarkSummary(
                file_name=f_path.name,
                rel_path=rel_path,
                dominant_kind="empty",
                total_records=0,
                total_length=0,
                mark_label="[EMPTY]",
                note="文件不含 FASTA 序列记录",
            )
        )

    # 排序：先 [HIT>30%] 按最高相似度降序，再边缘，再未命中，再跳过
    label_rank = {
        "[HIT>30%]": 0,
        "[BORDERLINE>30%]": 1,
        "[NO_HIT]": 2,
        "[SKIPPED_3DI]": 3,
        "[EMPTY]": 4,
    }
    file_summaries.sort(
        key=lambda f: (label_rank[f.mark_label], -f.max_pident, -f.max_bitscore, f.rel_path.lower())
    )

    ordered_seq_summaries = sorted(
        seq_summaries.values(),
        key=lambda s: (
            label_rank[s.mark_label],
            -s.max_pident,
            -s.max_bitscore,
            s.rel_path.lower(),
            s.record_index,
        ),
    )

    # 1. 导出查询蛋白解析清单
    query_tsv_path = out_dir / "query_proteins.tsv"
    with query_tsv_path.open("w", encoding="utf-8", newline="") as qf:
        w = csv.writer(qf, delimiter="\t", lineterminator="\n")
        w.writerow(
            [
                "index",
                "safe_id",
                "query_id",
                "length_aa",
                "sha256_prefix",
                "hit_target_files_gt30",
                "hit_target_seqs_gt30",
                "best_pident",
                "best_target",
                "header",
            ]
        )
        for q in queries:
            w.writerow(
                [
                    q.index,
                    q.safe_id,
                    q.query_id,
                    q.length,
                    q.sha256_prefix,
                    len(query_hit_files[q.query_id]),
                    len(query_hit_seqs[q.query_id]),
                    f"{query_best_pident[q.query_id]:.2f}",
                    query_best_target[q.query_id],
                    q.header,
                ]
            )

    # 2. 导出文件级标记汇总表
    files_tsv_path = out_dir / "marked_files_summary.tsv"
    with files_tsv_path.open("w", encoding="utf-8", newline="") as ff:
        w = csv.writer(ff, delimiter="\t", lineterminator="\n")
        w.writerow(
            [
                "mark_label",
                "file_name",
                "rel_path",
                "sequence_kind",
                "total_records",
                "hit_records_gt30",
                "total_length",
                "matched_query_count",
                "matched_query_ids",
                "best_query_id",
                "best_target_seq_id",
                "max_pident",
                "max_ppos",
                "min_evalue",
                "max_bitscore",
                "best_align_len",
                "best_qcov_hsp",
                "program",
                "note",
            ]
        )
        for fs in file_summaries:
            w.writerow(
                [
                    fs.mark_label,
                    fs.file_name,
                    fs.rel_path,
                    fs.dominant_kind,
                    fs.total_records,
                    fs.hit_record_count,
                    fs.total_length,
                    len(fs.matched_query_ids),
                    ";".join(fs.matched_query_ids),
                    fs.best_query_id,
                    fs.best_target_seq_id,
                    f"{fs.max_pident:.2f}" if fs.max_pident > 0 else "",
                    f"{fs.max_ppos:.2f}" if fs.max_ppos > 0 else "",
                    f"{fs.min_evalue:.3e}" if fs.min_evalue is not None else "",
                    f"{fs.max_bitscore:.1f}" if fs.max_bitscore > 0 else "",
                    fs.best_align_len if fs.best_align_len > 0 else "",
                    f"{fs.best_qcov_hsp:.2f}" if fs.best_qcov_hsp > 0 else "",
                    fs.best_program,
                    fs.note,
                ]
            )

    # 3. 导出序列条目级标记汇总表
    seqs_tsv_path = out_dir / "marked_sequences_summary.tsv"
    with seqs_tsv_path.open("w", encoding="utf-8", newline="") as sf:
        w = csv.writer(sf, delimiter="\t", lineterminator="\n")
        w.writerow(
            [
                "mark_label",
                "safe_id",
                "file_name",
                "rel_path",
                "record_index",
                "seq_id",
                "sequence_kind",
                "length",
                "hit_gt30_hsps",
                "matched_query_count",
                "matched_query_ids",
                "best_query_id",
                "max_pident",
                "max_ppos",
                "min_evalue",
                "max_bitscore",
                "best_align_len",
                "best_qcov_hsp",
                "best_sstart",
                "best_send",
                "best_sframe",
                "program",
                "header",
            ]
        )
        for sm in ordered_seq_summaries:
            w.writerow(
                [
                    sm.mark_label,
                    sm.safe_id,
                    sm.file_name,
                    sm.rel_path,
                    sm.record_index,
                    sm.seq_id,
                    sm.kind,
                    sm.length,
                    sm.hit_gt30_count,
                    len(sm.matched_query_ids),
                    ";".join(sm.matched_query_ids),
                    sm.best_query_id,
                    f"{sm.max_pident:.2f}" if sm.max_pident > 0 else "",
                    f"{sm.max_ppos:.2f}" if sm.max_ppos > 0 else "",
                    f"{sm.min_evalue:.3e}" if sm.min_evalue is not None else "",
                    f"{sm.max_bitscore:.1f}" if sm.max_bitscore > 0 else "",
                    sm.best_align_len if sm.best_align_len > 0 else "",
                    f"{sm.best_qcov_hsp:.2f}" if sm.best_qcov_hsp > 0 else "",
                    sm.best_sstart if sm.best_sstart > 0 else "",
                    sm.best_send if sm.best_send > 0 else "",
                    sm.best_sframe if sm.best_program == "tblastn" else "",
                    sm.best_program,
                    sm.header,
                ]
            )

    # 4. 流式导出带标记头的阳性命中 FASTA 序列集合
    marked_fasta_path = out_dir / "marked_hit_sequences.fasta"
    _export_marked_hit_fasta(
        ordered_seq_summaries=ordered_seq_summaries,
        target_by_safe=target_by_safe,
        dest_fasta=marked_fasta_path,
    )

    # 5. 生成简体中文 Markdown 汇总分析报告
    report_md_path = out_dir / "search_report.md"
    _write_markdown_report(
        report_path=report_md_path,
        queries=queries,
        file_summaries=file_summaries,
        seq_summaries=ordered_seq_summaries,
        query_hit_files=query_hit_files,
        query_hit_seqs=query_hit_seqs,
        query_best_pident=query_best_pident,
        query_best_target=query_best_target,
        gt30_hits=gt30_hits,
        borderline_hits=borderline_hits,
        ppos_only_gt30_files=sorted(ppos_only_gt30_files),
        config=config,
        shards_total=len(specs),
        shards_resumed=shards_resumed,
    )

    output_files = {
        "query_proteins_tsv": query_tsv_path,
        "marked_files_summary_tsv": files_tsv_path,
        "marked_sequences_summary_tsv": seqs_tsv_path,
        "blast_hits_gt30_tsv": gt30_hits_path,
        "blast_hits_borderline_gt30_tsv": borderline_hits_path,
        "blast_hits_all_tsv": all_hits_path,
        "marked_hit_sequences_fasta": marked_fasta_path,
        "search_report_md": report_md_path,
    }
    return (
        file_summaries,
        ordered_seq_summaries,
        output_files,
        len(gt30_hits),
        len(borderline_hits),
    )


def _export_marked_hit_fasta(
    ordered_seq_summaries: list[SequenceMarkSummary],
    target_by_safe: dict[str, TargetSequenceRecord],
    dest_fasta: Path,
) -> None:
    """流式从源 FASTA 文件读取命中序列，写入带 [HIT>30%] 标记头的新 FASTA（不改写原文件）。"""
    hit_sms = [s for s in ordered_seq_summaries if s.mark_label == "[HIT>30%]"]
    by_file: dict[Path, dict[int, SequenceMarkSummary]] = {}
    file_order: list[Path] = []
    for sm in hit_sms:
        t_rec = target_by_safe[sm.safe_id]
        if t_rec.abs_path not in by_file:
            by_file[t_rec.abs_path] = {}
            file_order.append(t_rec.abs_path)
        by_file[t_rec.abs_path][t_rec.record_index] = sm

    with dest_fasta.open("w", encoding="utf-8", newline="\n") as out:
        for file_path in file_order:
            wanted = by_file[file_path]
            for rec_idx, (orig_header, seq) in enumerate(iter_fasta_records(file_path), start=1):
                sm = wanted.get(rec_idx)
                if sm is None or not seq:
                    continue
                evalue_str = f"{sm.min_evalue:.2e}" if sm.min_evalue is not None else "NA"
                tag = (
                    f"[HIT>30%|file={sm.file_name}|best_query={sm.best_query_id}"
                    f"|max_pident={sm.max_pident:.2f}%|min_evalue={evalue_str}"
                    f"|align_len={sm.best_align_len}aa|hit_queries={len(sm.matched_query_ids)}]"
                )
                out.write(f">{tag} {orig_header}\n")
                for pos in range(0, len(seq), 80):
                    out.write(seq[pos : pos + 80] + "\n")


def _write_markdown_report(
    report_path: Path,
    queries: list[QueryProteinRecord],
    file_summaries: list[FileMarkSummary],
    seq_summaries: list[SequenceMarkSummary],
    query_hit_files: dict[str, set[str]],
    query_hit_seqs: dict[str, set[str]],
    query_best_pident: dict[str, float],
    query_best_target: dict[str, str],
    gt30_hits: list[BlastHitRecord],
    borderline_hits: list[BlastHitRecord],
    ppos_only_gt30_files: list[str],
    config: SearchConfig,
    shards_total: int,
    shards_resumed: int,
) -> None:
    """生成简体中文 Markdown 汇总报告（严禁使用 Emoji）。"""
    hit_files = [f for f in file_summaries if f.mark_label == "[HIT>30%]"]
    bl_files = [f for f in file_summaries if f.mark_label == "[BORDERLINE>30%]"]
    no_hit_files = [f for f in file_summaries if f.mark_label == "[NO_HIT]"]
    skip_3di_files = [f for f in file_summaries if f.mark_label == "[SKIPPED_3DI]"]
    dna_files = [f for f in file_summaries if f.dominant_kind == "dna"]
    prot_files = [f for f in file_summaries if f.dominant_kind == "protein"]
    hit_seqs = [s for s in seq_summaries if s.mark_label == "[HIT>30%]"]

    lines: list[str] = [
        "# 蛋白序列解析与 FASTA 相似度检索标记报告",
        "",
        "## 1. 检索配置与总体概览",
        "",
        f"- **查询蛋白文件**：`{config.query_fasta.name}`（共解析 **{len(queries)}** 条蛋白序列）",
        f"- **目标 FASTA 目录**：`{config.target_dir.name}`（共扫描 **{len(file_summaries)}** 个文件，**{len(seq_summaries)}** 条序列）",
        f"  - DNA 核酸序列文件：**{len(dna_files)}** 个（使用 `tblastn -db_gencode {config.db_gencode}`）",
        f"  - Protein 蛋白序列文件：**{len(prot_files)}** 个（使用 `blastp`）",
        f"  - 3Di 结构编码文件：**{len(skip_3di_files)}** 个（自动识别并安全跳过，防止假阳性）",
        f"- **标记判定阈值**：序列一致性 `pident > {config.min_pident:.1f}%` 且 `evalue <= {config.max_evalue:.0e}` 且 `align_len >= {config.min_align_len} aa`（BLAST 召回阈值 `evalue <= {config.blast_evalue:.0e}`）",
        f"- **分片执行概况**：共 {shards_total} 个分片（本次断点复用 {shards_resumed} 个分片）",
        "",
        "### 核心标记结论",
        "",
        f"- **标记为 `[HIT>30%]` 的目标文件**：**{len(hit_files)}** / {len(file_summaries)} 个（共 **{len(hit_seqs)}** 条具体序列，**{len(gt30_hits)}** 条可信 HSP 比对）",
        f"- **仅含边缘匹配 `[BORDERLINE>30%]` 的目标文件**：**{len(bl_files)}** 个（总计 {len(borderline_hits)} 条边缘 HSP）",
        f"- **未命中 `[NO_HIT]` 的目标文件**：**{len(no_hit_files)}** 个",
        f"- **跳过 `[SKIPPED_3DI]` 的目标文件**：**{len(skip_3di_files)}** 个",
        "",
        "## 2. 标记为 `[HIT>30%]` 的目标文件清单",
        "",
    ]

    if hit_files:
        lines.extend(
            [
                "| 序号 | 标记 | 目标文件名 | 类型 | 命中序列数/总序列数 | 最高一致性 pident(%) | 正相似性 ppos(%) | 最小 E-value | 比对长度(aa) | 查询覆盖(%) | 最佳匹配查询蛋白 | 命中的全部查询蛋白 |",
                "|---:|---|---|---|---:|---:|---:|---:|---:|---:|---|---|",
            ]
        )
        for idx, fs in enumerate(hit_files, start=1):
            ev_str = f"{fs.min_evalue:.2e}" if fs.min_evalue is not None else "-"
            q_list = ", ".join(fs.matched_query_ids)
            lines.append(
                f"| {idx} | `{fs.mark_label}` | `{fs.file_name}` | {fs.dominant_kind} | "
                f"{fs.hit_record_count}/{fs.total_records} | {fs.max_pident:.2f} | "
                f"{fs.max_ppos:.2f} | {ev_str} | {fs.best_align_len} | "
                f"{fs.best_qcov_hsp:.2f} | `{fs.best_query_id}` | {q_list} |"
            )
    else:
        lines.append("未检索到满足严格阈值的 `[HIT>30%]` 目标文件。")

    lines.extend(["", "## 3. 标记为 `[HIT>30%]` 的具体序列条目明细", ""])
    if hit_seqs:
        lines.extend(
            [
                "| 序号 | 标记 | 所属文件 | 记录序号 | 序列ID | 类型 | 最高pident(%) | ppos(%) | E-value | 比对长度(aa) | 目标区间(sstart..send) | 最佳查询蛋白 |",
                "|---:|---|---|---:|---|---|---:|---:|---:|---:|---|---|",
            ]
        )
        for idx, sm in enumerate(hit_seqs, start=1):
            ev_str = f"{sm.min_evalue:.2e}" if sm.min_evalue is not None else "-"
            frame_info = f" (frame {sm.best_sframe:+d})" if sm.best_program == "tblastn" else ""
            lines.append(
                f"| {idx} | `{sm.mark_label}` | `{sm.file_name}` | {sm.record_index} | "
                f"`{sm.seq_id}` | {sm.kind} | {sm.max_pident:.2f} | {sm.max_ppos:.2f} | "
                f"{ev_str} | {sm.best_align_len} | {sm.best_sstart}..{sm.best_send}{frame_info} | "
                f"`{sm.best_query_id}` |"
            )
    else:
        lines.append("无满足阈值的序列条目。")

    lines.extend(["", "## 4. 查询蛋白条目解析与命中分布", ""])
    lines.extend(
        [
            "| 序号 | 蛋白条目 ID | 长度(aa) | 序列指纹(SHA256前缀) | 命中文件数(>30%) | 命中序列数(>30%) | 最高pident(%) | 最佳目标序列 |",
            "|---:|---|---:|---|---:|---:|---:|---|",
        ]
    )
    for q in queries:
        bp = f"{query_best_pident[q.query_id]:.2f}" if query_best_pident[q.query_id] > 0 else "-"
        bt = f"`{query_best_target[q.query_id]}`" if query_best_target[q.query_id] else "-"
        lines.append(
            f"| {q.index} | `{q.query_id}` | {q.length} | `{q.sha256_prefix}` | "
            f"{len(query_hit_files[q.query_id])} | {len(query_hit_seqs[q.query_id])} | {bp} | {bt} |"
        )

    lines.extend(["", "## 5. 边缘候选与补充核查信息", ""])
    if bl_files:
        lines.append(
            f"发现 **{len(bl_files)}** 个文件仅包含边缘 `pident > {config.min_pident:.0f}%` 匹配"
            f"（未达到 `evalue <= {config.max_evalue:.0e}` 或 `align_len >= {config.min_align_len} aa`），详见 `blast_hits_borderline_gt30.tsv`："
        )
        for fs in bl_files:
            ev_str = f"{fs.min_evalue:.2e}" if fs.min_evalue is not None else "-"
            lines.append(
                f"- `{fs.file_name}`: max_pident={fs.max_pident:.2f}%, evalue={ev_str}, "
                f"align_len={fs.best_align_len} aa, best_query=`{fs.best_query_id}`"
            )
    else:
        lines.append("无仅含边缘匹配的目标文件。")

    if ppos_only_gt30_files:
        hit_rel_set = {f.rel_path for f in hit_files}
        extra_ppos_files = [rp for rp in ppos_only_gt30_files if rp not in hit_rel_set]
        if extra_ppos_files:
            lines.append("")
            lines.append(
                f"补充说明：另有 **{len(extra_ppos_files)}** 个文件虽最高一致性 `pident <= {config.min_pident:.0f}%`，"
                f"但存在保守相似残基比例 `ppos > {config.min_pident:.0f}%`（且 `evalue <= {config.max_evalue:.0e}`、"
                f"`align_len >= {config.min_align_len} aa`）的远源相似区域，详情见 `blast_hits_all.tsv`："
            )
            for rp in extra_ppos_files:
                lines.append(f"- `{rp}`")

    lines.extend(["", "## 6. 跳过及未命中目标文件说明", ""])
    if skip_3di_files:
        lines.append("### 6.1 自动跳过的非蛋白/非核酸结构编码文件 (`[SKIPPED_3DI]`)")
        for fs in skip_3di_files:
            lines.append(f"- `{fs.file_name}`（{fs.total_records} 条记录，{fs.note}）")
        lines.append("")

    lines.append(f"### 6.2 未检出 >30% 相似度的目标文件 (`[NO_HIT]`, 共 {len(no_hit_files)} 个)")
    if no_hit_files:
        lines.append(", ".join(f"`{fs.file_name}`" for fs in no_hit_files))
    else:
        lines.append("无。")

    lines.extend(
        [
            "",
            "## 7. 输出交付文件说明",
            "",
            "- `query_proteins.tsv`：解析出的查询蛋白条目清单及命中汇总。",
            "- `marked_files_summary.tsv`：全部目标文件的标记总表（含 `[HIT>30%]` / `[BORDERLINE>30%]` / `[NO_HIT]` / `[SKIPPED_3DI]`）。",
            "- `marked_sequences_summary.tsv`：精确到每条 FASTA 记录（含 multi-FASTA）的标记明细表。",
            "- `blast_hits_gt30.tsv`：所有可信 `pident > 30%` HSP 比对明细。",
            "- `blast_hits_borderline_gt30.tsv`：所有边缘 `pident > 30%` 候选比对明细。",
            "- `blast_hits_all.tsv`：全量 BLAST 召回记录（含 `pident <= 30%` 与 `ppos`）。",
            "- `marked_hit_sequences.fasta`：汇总导出的阳性命中序列（FASTA 标题已添加 `[HIT>30%|...]` 标记头，未改写任何原始文件）。",
            "- `search_report.md`：本汇总分析报告。",
            "",
        ]
    )

    report_path.write_text("\n".join(lines), encoding="utf-8")
