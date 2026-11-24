# -*- coding: utf-8 -*-
"""
SequenceProfiler - 数据集多维画像探测与智能赛道推荐
"""
import hashlib
import logging
import statistics
from pathlib import Path
from typing import List, Tuple

from ..models.errors import InvalidInputError
from ..models.schemas import SequenceProfile
from .id_codec import IdCodec

logger = logging.getLogger("phylo.profiler")

DNA_AMBIGUOUS_CHARS = set("ATGCNURYSWKMBDHV-.*?")


def extract_records_from_files(file_paths: List[Path]) -> List[Tuple[str, str]]:
    """
    统一从 FASTA / ZIP / GZ / ABI 文件中流式提取 (id, sequence) 记录。
    - 多序列单文件：保留纯净原始 record.id；
    - 单序列独立文件（例如多个组装基因组各自均命名为 >ngcs_scaffold_1）：
      若文件名 stem 包含 record.id 或该 record.id 在多文件间重名，自动使用样本文件名区分，避免伪重复与来源混淆。
    """
    from collections import Counter
    from Bio import SeqIO
    from src.utils.universal_parser import UniversalParser

    direct_fasta_exts = {".fasta", ".fas", ".fa", ".fna", ".faa"}
    per_file_entries: List[Tuple[str, List[Tuple[str, str]]]] = []

    for path in file_paths:
        if not path.exists() or not path.is_file():
            continue
        file_records: List[Tuple[str, str]] = []
        if path.suffix.lower() in direct_fasta_exts:
            try:
                with open(path, "r", encoding="utf-8", errors="replace") as fh:
                    for rec in SeqIO.parse(fh, "fasta"):
                        seq_id = str(rec.id or "").strip()
                        seq = "".join(str(rec.seq or "").split()).upper()
                        if seq_id and seq:
                            file_records.append((seq_id, seq))
            except Exception as exc:
                logger.warning(f"Direct FASTA parse failed for {path.name}: {exc}")

        if not file_records:
            for item in UniversalParser.parse_iter(str(path)):
                seq_id = str(item.get("id") or "").strip()
                seq = "".join(str(item.get("sequence") or "").split()).upper()
                if seq_id and seq:
                    file_records.append((seq_id, seq))

        if file_records:
            per_file_entries.append((path.stem, file_records))

    single_file_id_counts = Counter(
        recs[0][0] for _, recs in per_file_entries if len(recs) == 1
    )

    records: List[Tuple[str, str]] = []
    for stem, file_records in per_file_entries:
        if len(file_records) == 1:
            seq_id, seq = file_records[0]
            low_id = seq_id.lower()
            is_generic_contig = low_id.startswith(("node_", "contig", "scaffold"))
            if low_id in stem.lower() or is_generic_contig:
                records.append((stem, seq))
            elif len(per_file_entries) >= 2 and single_file_id_counts[seq_id] > 1:
                records.append((f"{stem}_{seq_id}", seq))
            else:
                records.append((seq_id, seq))
        else:
            records.extend(file_records)
    return records


def detect_molecule_type(sequences: List[str]) -> str:
    """检测序列集合是 DNA/RNA 还是蛋白质。"""
    sample_chars: set[str] = set()
    for seq in sequences[:30]:
        sample_chars.update(seq[:2000])
        if len(sample_chars) > 25:
            break
    for ch in sample_chars:
        if ch not in DNA_AMBIGUOUS_CHARS:
            return "protein"
    return "dna"


class SequenceProfiler:
    """序列集统计画像与分析赛道推荐器。"""

    GENOME_MAX_LEN_THRESHOLD = 10_000
    GENOME_TOTAL_BASES_THRESHOLD = 200_000

    @classmethod
    def profile_records(cls, records: List[Tuple[str, str]]) -> SequenceProfile:
        if not records:
            return SequenceProfile(warnings=["未检测到有效序列"])

        raw_ids = [r[0] for r in records]
        seqs = [r[1] for r in records]
        lengths = [len(s) for s in seqs]
        unique_count = len(set(raw_ids))
        dup_count = len(raw_ids) - unique_count

        mol_type = detect_molecule_type(seqs)
        min_len = min(lengths)
        max_len = max(lengths)
        median_len = int(statistics.median(lengths))
        total_bases = sum(lengths)
        mean_len = total_bases / max(1, len(lengths))
        stdev_len = statistics.pstdev(lengths) if len(lengths) > 1 else 0.0
        length_cv = round(stdev_len / mean_len, 4) if mean_len > 0 else 0.0

        is_aligned = len(records) >= 2 and min_len == max_len and max_len > 0
        has_gaps = any("-" in s for s in seqs[:50])

        # 计算稳定内容指纹：基于消歧并排序后的 (ID, 去空白序列) 摘要，与 write_sanitized_fasta 顺序完全一致
        dedup_for_hash = IdCodec.deduplicate_ids(raw_ids)
        hasher = hashlib.sha256()
        for rid, seq in sorted(zip(dedup_for_hash, seqs, strict=True), key=lambda x: (x[0], x[1])):
            hasher.update(rid.encode("utf-8", errors="replace"))
            hasher.update(b"\t")
            hasher.update(seq.encode("utf-8", errors="replace"))
            hasher.update(b"\n")
        content_hash = hasher.hexdigest()

        warnings: List[str] = []
        if len(records) < 3:
            warnings.append(f"当前仅包含 {len(records)} 条序列，构树建议至少 3 条序列。")
        if dup_count > 0:
            warnings.append(f"检测到 {dup_count} 个重复序列 ID，分析时将自动追加后缀消歧。")

        # 智能赛道与工具推荐
        if (
            mol_type == "dna"
            and not is_aligned
            and (max_len >= cls.GENOME_MAX_LEN_THRESHOLD or total_bases >= cls.GENOME_TOTAL_BASES_THRESHOLD)
        ):
            recommended_track = "genome"
            recommended_msa = "none"
            recommended_engine = "bionj"
            warnings.append(
                f"检测到长基因组序列（最长 {max_len:,} bp，总计 {total_bases:,} bp），"
                f"已自动推荐 [全基因组无对齐赛道 (Mash + BioNJ)]，避免 MAFFT 全局比对耗时卡死。"
            )
        elif is_aligned:
            recommended_track = "gene"
            recommended_msa = "none"
            recommended_engine = "fasttree" if len(records) > 120 else "iqtree"
        else:
            recommended_track = "gene"
            recommended_msa = "mafft"
            recommended_engine = "fasttree" if len(records) > 150 else "iqtree"

        return SequenceProfile(
            sequence_count=len(records),
            unique_id_count=unique_count,
            duplicate_id_count=dup_count,
            mol_type=mol_type,  # type: ignore[arg-type]
            min_length=min_len,
            median_length=median_len,
            max_length=max_len,
            total_bases=total_bases,
            length_cv=length_cv,
            is_aligned=is_aligned,
            has_gaps=has_gaps,
            content_hash=content_hash,
            recommended_track=recommended_track,  # type: ignore[arg-type]
            recommended_msa=recommended_msa,  # type: ignore[arg-type]
            recommended_engine=recommended_engine,  # type: ignore[arg-type]
            warnings=warnings,
            sample_ids=raw_ids[:20],
        )

    @classmethod
    def profile_files(cls, file_paths: List[Path]) -> Tuple[SequenceProfile, List[Tuple[str, str]]]:
        records = extract_records_from_files(file_paths)
        return cls.profile_records(records), records

    @classmethod
    def write_sanitized_fasta(
        cls,
        records: List[Tuple[str, str]],
        output_fasta: Path,
        id_map_path: Path,
    ) -> Tuple[Path, IdCodec]:
        """
        将原始序列集合写为安全短 ID FASTA，并落盘映射表。
        """
        if len(records) < 3:
            raise InvalidInputError(f"构树至少需要 3 条有效序列，当前仅解析到 {len(records)} 条。")

        dedup_ids = IdCodec.deduplicate_ids([r[0] for r in records])
        # 按确定性顺序排序后再编码，确保相同数据集无论输入顺序如何都生成一致的短 ID 映射，防止 StageCache 错位
        sorted_pairs = sorted(zip(dedup_ids, [r[1] for r in records], strict=True), key=lambda x: (x[0], x[1]))
        ordered_ids = [item[0] for item in sorted_pairs]

        codec = IdCodec()
        codec.build_mapping(ordered_ids)

        output_fasta.parent.mkdir(parents=True, exist_ok=True)
        with open(output_fasta, "w", encoding="utf-8", newline="\n") as fh:
            for idx, (_orig_id, seq) in enumerate(sorted_pairs, start=1):
                short_id = f"T{idx:06d}"
                # 仅清理极少数可能干扰 FASTA 引擎的字符（保留常规碱基/氨基酸及 '-'）
                clean_seq = seq.replace("*", "-")
                fh.write(f">{short_id}\n")
                for pos in range(0, len(clean_seq), 80):
                    fh.write(clean_seq[pos : pos + 80] + "\n")

        codec.save(id_map_path)
        return output_fasta, codec
