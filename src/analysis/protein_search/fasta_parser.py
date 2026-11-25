# -*- coding: utf-8 -*-
"""
UTF-8 流式 FASTA 解析、序列分子类型自动识别（DNA / Protein / 3Di）及安全分片构建。
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Iterator

from .models import QueryProteinRecord, SequenceKind, TargetSequenceRecord

FASTA_EXTENSIONS = {".fasta", ".fa", ".fna", ".faa", ".fas", ".ffn", ".frn"}
_WHITESPACE_RE = re.compile(r"\s+")
_DNA_CORE_CHARS = frozenset("ACGTUN")
_DNA_IUPAC_CHARS = frozenset("ACGTUNRYKMSWBDHV-")
_HOMOPOLYMER_4_RE = re.compile(r"([DPVLQS])\1{3,}")
_THREE_DI_NAME_RE = re.compile(r"(?:^|[_\-\s.])3di(?:$|[_\-\s.])", re.IGNORECASE)


def iter_fasta_records(fasta_path: Path) -> Iterator[tuple[str, str]]:
    """
    以流式方式读取 UTF-8 FASTA 文件，逐条产出 (header, sequence)。
    禁用 GBK，统一采用 UTF-8（自动兼容 UTF-8 BOM）。
    """
    header: str | None = None
    seq_chunks: list[str] = []

    with fasta_path.open("r", encoding="utf-8-sig", errors="replace") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line:
                continue
            if line.startswith(">"):
                if header is not None:
                    yield header, "".join(seq_chunks)
                header = line[1:].strip()
                seq_chunks = []
            else:
                if header is None:
                    continue
                cleaned = _WHITESPACE_RE.sub("", line).upper()
                if cleaned:
                    seq_chunks.append(cleaned)

    if header is not None:
        yield header, "".join(seq_chunks)


def is_fasta_candidate_file(file_path: Path) -> bool:
    """判断文件是否为 FASTA 候选文件。"""
    if not file_path.is_file():
        return False
    if file_path.suffix.lower() in FASTA_EXTENSIONS:
        return True
    try:
        with file_path.open("r", encoding="utf-8-sig", errors="replace") as handle:
            for _ in range(5):
                line = handle.readline()
                if not line:
                    break
                stripped = line.strip()
                if stripped:
                    return stripped.startswith(">")
    except OSError:
        return False
    return False


def classify_file_sequences(
    records: list[tuple[str, str]],
    file_name: str = "",
) -> list[SequenceKind]:
    """
    综合文件名特征与序列字符统计，判定文件内每条序列的类型：
    - dna: 标准核酸序列（ACGTUN 占比 >= 90% 且 IUPAC 核酸字符占比 >= 98%）
    - 3di: Foldseek/Phold 3Di 结构状态字母表（防止误作蛋白比对）
    - protein: 标准蛋白质氨基酸序列
    - empty: 空序列
    """
    if not records:
        return []

    non_empty = [seq for _, seq in records if seq]
    if not non_empty:
        return ["empty" for _ in records]

    # 先判断文件级 3Di 特征
    file_stem = Path(file_name).stem if file_name else ""
    name_is_3di = bool(_THREE_DI_NAME_RE.search(file_stem))

    starts_with_m_ratio = sum(1 for s in non_empty if s.startswith("M")) / len(non_empty)
    joined = "".join(non_empty)
    total_chars = max(1, len(joined))
    acgtun_ratio_file = sum(1 for c in joined if c in _DNA_CORE_CHARS) / total_chars
    iupac_ratio_file = sum(1 for c in joined if c in _DNA_IUPAC_CHARS) / total_chars
    homopolymer_chars = sum(len(m.group(0)) for m in _HOMOPOLYMER_4_RE.finditer(joined))
    homopolymer_ratio = homopolymer_chars / total_chars

    file_is_dna = acgtun_ratio_file >= 0.90 and iupac_ratio_file >= 0.98
    file_is_3di = (not file_is_dna) and (
        name_is_3di
        or (len(non_empty) >= 5 and starts_with_m_ratio < 0.10 and homopolymer_ratio >= 0.08)
    )

    kinds: list[SequenceKind] = []
    for _, seq in records:
        if not seq:
            kinds.append("empty")
            continue
        seq_len = len(seq)
        acgtun_ratio = sum(1 for c in seq if c in _DNA_CORE_CHARS) / seq_len
        iupac_ratio = sum(1 for c in seq if c in _DNA_IUPAC_CHARS) / seq_len
        if acgtun_ratio >= 0.90 and iupac_ratio >= 0.98:
            kinds.append("dna")
        elif file_is_3di:
            kinds.append("3di")
        else:
            kinds.append("protein")
    return kinds


def parse_query_proteins(query_fasta: Path) -> list[QueryProteinRecord]:
    """解析查询蛋白 FASTA 文件中的全部条目。"""
    if not query_fasta.is_file():
        raise FileNotFoundError(f"查询蛋白文件不存在: {query_fasta}")

    raw_records = list(iter_fasta_records(query_fasta))
    if not raw_records:
        raise ValueError(f"查询蛋白文件为空或未包含有效 FASTA 条目: {query_fasta}")

    kinds = classify_file_sequences(raw_records, file_name=query_fasta.name)
    results: list[QueryProteinRecord] = []
    for idx, ((header, seq), kind) in enumerate(zip(raw_records, kinds), start=1):
        if not seq:
            continue
        query_id = header.split()[0] if header else f"query_{idx}"
        safe_id = f"Q_{idx:04d}"
        digest = hashlib.sha256(seq.encode("utf-8")).hexdigest()[:12]
        results.append(
            QueryProteinRecord(
                index=idx,
                safe_id=safe_id,
                query_id=query_id,
                header=header,
                length=len(seq),
                sequence=seq,
                sha256_prefix=digest,
                sequence_kind=kind,
            )
        )

    if not results:
        raise ValueError(f"查询蛋白文件中未解析到任何非空序列: {query_fasta}")
    return results


def write_safe_query_fasta(queries: list[QueryProteinRecord], dest_fasta: Path) -> Path:
    """将查询蛋白以纯 ASCII 安全 ID 写出为 UTF-8 FASTA，避免 BLAST 截断或编码异常。"""
    dest_fasta.parent.mkdir(parents=True, exist_ok=True)
    with dest_fasta.open("w", encoding="utf-8", newline="\n") as handle:
        for rec in queries:
            handle.write(f">{rec.safe_id}\n")
            seq = rec.sequence
            for pos in range(0, len(seq), 80):
                handle.write(seq[pos : pos + 80] + "\n")
    return dest_fasta


def scan_target_directory(
    target_dir: Path,
) -> tuple[list[TargetSequenceRecord], list[tuple[str, Path]]]:
    """
    递归扫描目标目录下的所有 FASTA 文件，构建序列元数据清单。
    为控制内存占用，此阶段仅保留元数据，不常驻目标序列本体。
    """
    if not target_dir.is_dir():
        raise NotADirectoryError(f"目标 FASTA 目录不存在: {target_dir}")

    all_files = sorted(
        (p for p in target_dir.rglob("*") if is_fasta_candidate_file(p)),
        key=lambda p: p.relative_to(target_dir).as_posix().lower(),
    )

    records: list[TargetSequenceRecord] = []
    empty_files: list[tuple[str, Path]] = []
    global_idx = 0

    for file_path in all_files:
        rel_path = file_path.relative_to(target_dir).as_posix()
        raw_recs = list(iter_fasta_records(file_path))
        if not raw_recs:
            empty_files.append((rel_path, file_path))
            continue

        kinds = classify_file_sequences(raw_recs, file_name=file_path.name)
        for rec_idx, ((header, seq), kind) in enumerate(zip(raw_recs, kinds), start=1):
            global_idx += 1
            safe_id = f"T_{global_idx:06d}"
            seq_id = header.split()[0] if header else f"seq_{rec_idx}"
            records.append(
                TargetSequenceRecord(
                    safe_id=safe_id,
                    file_name=file_path.name,
                    rel_path=rel_path,
                    abs_path=file_path,
                    record_index=rec_idx,
                    seq_id=seq_id,
                    header=header,
                    kind=kind,
                    length=len(seq),
                )
            )
        # 主动释放单文件序列列表
        raw_recs.clear()

    return records, empty_files


def write_shard_fasta(
    shard_records: list[TargetSequenceRecord],
    dest_fasta: Path,
) -> Path:
    """
    按文件流式读取源 FASTA，将指定分片中的序列按 safe_id 写入纯 ASCII 标题的 UTF-8 FASTA。
    """
    dest_fasta.parent.mkdir(parents=True, exist_ok=True)

    # 按源文件分组，避免重复打开同一文件
    by_file: dict[Path, dict[int, TargetSequenceRecord]] = {}
    file_order: list[Path] = []
    for rec in shard_records:
        if rec.abs_path not in by_file:
            by_file[rec.abs_path] = {}
            file_order.append(rec.abs_path)
        by_file[rec.abs_path][rec.record_index] = rec

    with dest_fasta.open("w", encoding="utf-8", newline="\n") as out:
        for file_path in file_order:
            wanted = by_file[file_path]
            for rec_idx, (_, seq) in enumerate(iter_fasta_records(file_path), start=1):
                meta = wanted.get(rec_idx)
                if meta is None or not seq:
                    continue
                out.write(f">{meta.safe_id}\n")
                for pos in range(0, len(seq), 80):
                    out.write(seq[pos : pos + 80] + "\n")

    return dest_fasta
