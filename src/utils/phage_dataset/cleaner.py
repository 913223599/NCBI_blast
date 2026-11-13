# -*- coding: utf-8 -*-
"""
噬菌体正负样本数据库清理与质量加固工具

功能职责（单向、可重入、原子写盘、强制 UTF-8）：
1. 清理 BLASTDB 构建后冗余的中间合并 FASTA/FAA 文件及残留 .tmp 临时文件；
2. 过滤 SQLite cds_features 表中的无意义短肽噪声（< min_prot_aa aa）及假基因噪声，并执行 WAL checkpoint + VACUUM 压缩；
3. 对负样本库（bacterial_chromosome / plasmid）运行本地 BLASTn + 前噬菌体特征基因聚簇检测，
   生成前噬菌体掩蔽区间表 `prophage_masks`（落盘至 negative_index.sqlite 与 prophage_masks.tsv）；
4. 从预处理训练集划分 splits/{train,val,test}.tsv 中剔除高 N 比例（n_percent > max_n_percent）的残缺基因组并刷新清单。
"""
import argparse
import csv
import json
import logging
import os
import re
import sqlite3
import subprocess
import tempfile
from collections import defaultdict
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from ...workbench.models.tool_config import ToolConfig
from .indexer import compact_sqlite_db, remove_redundant_blast_fasta

logger = logging.getLogger("utils.phage_dataset.cleaner")

PROPHAGE_CLUSTER_PATTERN = re.compile(
    r"(?:prophage|bacteriophage|terminase|capsid|portal|tail\s*(?:fiber|sheath|tube|protein)|baseplate|holin|endolysin|lysin)",
    re.IGNORECASE,
)


def merge_intervals(
    intervals: Iterable[Tuple[int, int]],
    max_length: Optional[int] = None,
    flank_bp: int = 0,
) -> List[Tuple[int, int]]:
    """
    扩展并合并重叠或相邻的 0-based 半开区间 [start, end)。

    参数:
        intervals: 原始区间列表 (start, end)。
        max_length: 若提供则将区间终点限制在 [0, max_length]。
        flank_bp: 向两端扩展的缓冲长度（bp）。
    """
    normalized: List[Tuple[int, int]] = []
    for raw_start, raw_end in intervals:
        s = min(int(raw_start), int(raw_end)) - max(0, int(flank_bp))
        e = max(int(raw_start), int(raw_end)) + max(0, int(flank_bp))
        if s < 0:
            s = 0
        if max_length is not None and max_length > 0 and e > max_length:
            e = max_length
        if e > s:
            normalized.append((s, e))

    if not normalized:
        return []

    normalized.sort(key=lambda item: (item[0], item[1]))
    merged: List[Tuple[int, int]] = [normalized[0]]
    for s, e in normalized[1:]:
        prev_s, prev_e = merged[-1]
        if s <= prev_e:
            merged[-1] = (prev_s, max(prev_e, e))
        else:
            merged.append((s, e))
    return merged


def _atomic_write_json(path: Path, payload: Dict[str, Any]) -> None:
    """原子写盘 UTF-8 JSON 文件。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_path.replace(path)


def _prune_tmp_files(base_dir: Path) -> Dict[str, Any]:
    """清理数据集子目录下遗留的 .tmp 临时文件。"""
    removed_files: List[str] = []
    reclaimed_bytes = 0
    for sub in ("index", "blastdb", "meta", "preprocessed"):
        sub_dir = base_dir / sub
        if not sub_dir.exists():
            continue
        for item in sub_dir.rglob("*.tmp"):
            if item.is_file():
                try:
                    size = item.stat().st_size
                    item.unlink()
                    removed_files.append(str(item))
                    reclaimed_bytes += size
                except OSError as exc:
                    logger.warning(f"删除临时文件失败 {item}: {exc}")
    return {
        "removed_tmp_count": len(removed_files),
        "reclaimed_bytes": reclaimed_bytes,
    }


def _update_manifest_after_fasta_cleanup(manifest_path: Path, nucl_removed: bool, prot_removed: bool) -> None:
    """同步更新 index/manifest.json 中的产物状态。"""
    if not manifest_path.exists():
        return
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        artifacts = data.get("artifacts")
        if isinstance(artifacts, dict):
            if nucl_removed:
                artifacts["nucl_fasta"] = ""
            if prot_removed:
                artifacts["prot_fasta"] = ""
            if nucl_removed or prot_removed:
                artifacts["cleaned_intermediate_fastas"] = True
        _atomic_write_json(manifest_path, data)
    except Exception as exc:
        logger.warning(f"更新 manifest 失败 {manifest_path}: {exc}")


def prune_redundant_artifacts(
    data_dir: Path,
    nucl_fasta_name: str,
    nucl_db_prefix_name: str,
    prot_fasta_name: str,
    prot_db_prefix_name: str,
) -> Dict[str, Any]:
    """安全删除已有真实 .nsq/.psq BLAST 索引支撑的中间合并 FASTA/FAA，并清理残留临时文件。"""
    root = Path(data_dir).resolve()
    blast_dir = root / "blastdb"

    tmp_report = _prune_tmp_files(root)
    nucl_fasta = blast_dir / nucl_fasta_name
    prot_fasta = blast_dir / prot_fasta_name

    nucl_reclaimed = remove_redundant_blast_fasta(
        nucl_fasta, blast_dir / nucl_db_prefix_name, "nucl"
    )
    prot_reclaimed = remove_redundant_blast_fasta(
        prot_fasta, blast_dir / prot_db_prefix_name, "prot"
    )

    _update_manifest_after_fasta_cleanup(
        root / "index" / "manifest.json",
        nucl_removed=nucl_reclaimed > 0,
        prot_removed=prot_reclaimed > 0,
    )

    total_bytes = tmp_report["reclaimed_bytes"] + nucl_reclaimed + prot_reclaimed
    return {
        "data_dir": str(root),
        "removed_tmp_count": tmp_report["removed_tmp_count"],
        "nucl_fasta_reclaimed_mb": round(nucl_reclaimed / (1024 * 1024), 2),
        "prot_fasta_reclaimed_mb": round(prot_reclaimed / (1024 * 1024), 2),
        "total_reclaimed_mb": round(total_bytes / (1024 * 1024), 2),
        "total_reclaimed_bytes": total_bytes,
    }


def clean_sqlite_cds_noise(db_path: Path, min_prot_aa: int = 25) -> Dict[str, Any]:
    """
    清理 SQLite cds_features 表中的短肽碎片（< min_prot_aa）及假基因噪声，
    随后执行 WAL checkpoint(TRUNCATE) + VACUUM + PRAGMA optimize。
    """
    target = Path(db_path).resolve()
    if not target.exists():
        return {"db_path": str(target), "exists": False}

    size_before = target.stat().st_size
    deleted_short = 0
    deleted_pseudo = 0

    with closing(sqlite3.connect(target)) as conn:
        total_before = conn.execute("SELECT COUNT(*) FROM cds_features").fetchone()[0]
        short_row = conn.execute(
            "SELECT COUNT(*) FROM cds_features WHERE length_aa IS NULL OR length_aa < ?",
            (min_prot_aa,),
        ).fetchone()
        deleted_short = int(short_row[0]) if short_row else 0

        pseudo_row = conn.execute(
            "SELECT COUNT(*) FROM cds_features WHERE length_aa >= ? AND LOWER(COALESCE(product, '')) LIKE '%pseudo%'",
            (min_prot_aa,),
        ).fetchone()
        deleted_pseudo = int(pseudo_row[0]) if pseudo_row else 0

        conn.execute(
            """
            DELETE FROM cds_features
            WHERE length_aa IS NULL
               OR length_aa < ?
               OR LOWER(COALESCE(product, '')) LIKE '%pseudo%'
            """,
            (min_prot_aa,),
        )
        conn.commit()
        total_after = conn.execute("SELECT COUNT(*) FROM cds_features").fetchone()[0]

    compact_sqlite_db(target)
    size_after = target.stat().st_size

    return {
        "db_path": str(target),
        "exists": True,
        "cds_before": int(total_before),
        "cds_after": int(total_after),
        "deleted_short_lt_min_aa": deleted_short,
        "deleted_pseudo": deleted_pseudo,
        "size_before_mb": round(size_before / (1024 * 1024), 2),
        "size_after_mb": round(size_after / (1024 * 1024), 2),
        "reclaimed_mb": round(max(0, size_before - size_after) / (1024 * 1024), 2),
        "reclaimed_bytes": max(0, size_before - size_after),
    }


def _collect_negative_targets_and_cds_clusters(
    neg_sqlite: Path,
    neg_root: Path,
    categories: Tuple[str, ...],
) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, List[Tuple[int, int, str]]]]:
    """读取待扫描负样本信息，并识别特征基因局部聚簇作为补充掩蔽候选。"""
    targets: Dict[str, Dict[str, Any]] = {}
    cds_hits: Dict[str, List[Tuple[int, int, str]]] = defaultdict(list)

    if not neg_sqlite.exists():
        return targets, cds_hits

    placeholders = ",".join("?" for _ in categories)
    with closing(sqlite3.connect(neg_sqlite)) as conn:
        rows = conn.execute(
            f"""
            SELECT accession, negative_category, length_bp, fasta_relpath
            FROM genomes
            WHERE is_valid_negative = 1
              AND negative_category IN ({placeholders})
            """,
            categories,
        ).fetchall()

        for acc, cat, length_bp, fasta_rel in rows:
            fa_path = neg_root / fasta_rel if fasta_rel else neg_root / "fasta" / f"{acc}.fasta"
            targets[acc] = {
                "category": cat,
                "length_bp": int(length_bp or 0),
                "fasta_path": fa_path,
            }

        if targets:
            acc_list = list(targets.keys())
            for offset in range(0, len(acc_list), 500):
                chunk = acc_list[offset:offset + 500]
                ph = ",".join("?" for _ in chunk)
                cds_rows = conn.execute(
                    f"""
                    SELECT accession, start_pos, end_pos, product
                    FROM cds_features
                    WHERE accession IN ({ph})
                    ORDER BY accession, start_pos
                    """,
                    chunk,
                ).fetchall()
                by_acc: Dict[str, List[Tuple[int, int, str]]] = defaultdict(list)
                for acc, s_pos, e_pos, product in cds_rows:
                    if product and PROPHAGE_CLUSTER_PATTERN.search(product):
                        by_acc[acc].append((int(s_pos or 0), int(e_pos or 0), product))

                # 同一条序列内至少 2 个噬菌体核心功能基因距离 <= 10,000 bp 时才认定为潜在前噬菌体基因簇
                for acc, items in by_acc.items():
                    if len(items) < 2:
                        continue
                    cluster: List[Tuple[int, int, str]] = [items[0]]
                    for s_pos, e_pos, prod in items[1:]:
                        if s_pos - cluster[-1][1] <= 10000:
                            cluster.append((s_pos, e_pos, prod))
                        else:
                            if len(cluster) >= 2:
                                cds_hits[acc].append((cluster[0][0], cluster[-1][1], "cds_cluster"))
                            cluster = [(s_pos, e_pos, prod)]
                    if len(cluster) >= 2:
                        cds_hits[acc].append((cluster[0][0], cluster[-1][1], "cds_cluster"))

    return targets, cds_hits


def _run_blastn_prophage_scan(
    blastn_bin: Path,
    phage_blast_dir: Path,
    db_name: str,
    query_fasta: Path,
    perc_identity: float,
    evalue: str,
    min_hit_len: int,
    threads: int,
) -> Dict[str, List[Tuple[int, int, str]]]:
    """调用本地 BLASTn 将负样本序列比对到纯净噬菌体库，定位残留前噬菌体区域。"""
    hits_by_acc: Dict[str, List[Tuple[int, int, str]]] = defaultdict(list)
    out_tsv = query_fasta.with_suffix(".blastn.tsv")

    cmd = [
        str(blastn_bin),
        "-query", str(query_fasta),
        "-db", db_name,
        "-out", str(out_tsv),
        "-outfmt", "6 qseqid sseqid pident length qstart qend sstart send evalue bitscore",
        "-perc_identity", str(perc_identity),
        "-evalue", str(evalue),
        "-num_threads", str(max(1, threads)),
    ]
    res = subprocess.run(
        cmd,
        cwd=str(phage_blast_dir),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=1800,
    )
    if res.returncode != 0:
        raise RuntimeError(f"blastn 前噬菌体扫描失败 ({res.returncode}): {res.stderr.strip()}")

    if out_tsv.exists():
        with open(out_tsv, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                parts = line.rstrip("\r\n").split("\t")
                if len(parts) < 10:
                    continue
                qseqid = parts[0].split()[0]
                sseqid = parts[1].split()[0]
                aln_len = int(parts[3])
                if aln_len < min_hit_len:
                    continue
                qstart = int(parts[4])
                qend = int(parts[5])
                s0 = max(0, min(qstart, qend) - 1)
                e0 = max(qstart, qend)
                hits_by_acc[qseqid].append((s0, e0, f"blastn:{sseqid}"))
    return hits_by_acc


def scan_and_mask_negative_prophages(
    positive_dir: Path,
    negative_dir: Path,
    perc_identity: float = 80.0,
    min_hit_len: int = 500,
    evalue: str = "1e-20",
    flank_bp: int = 1000,
    categories: Tuple[str, ...] = ("bacterial_chromosome", "plasmid"),
    threads: Optional[int] = None,
) -> Dict[str, Any]:
    """
    检测负样本细菌染色体和质粒中潜伏的前噬菌体同源区间与核心基因簇，
    并将掩蔽坐标表写入 negative_index.sqlite (`prophage_masks`) 与 prophage_masks.tsv。
    """
    pos_root = Path(positive_dir).resolve()
    neg_root = Path(negative_dir).resolve()
    neg_sqlite = neg_root / "index" / "negative_index.sqlite"
    phage_blast_dir = pos_root / "blastdb"

    if not neg_sqlite.exists():
        return {"skipped": True, "reason": f"未找到负样本索引 {neg_sqlite}"}

    cpu_cnt = os.cpu_count() or 4
    worker_threads = threads if threads is not None else max(1, cpu_cnt - 2)

    targets, cds_clusters = _collect_negative_targets_and_cds_clusters(
        neg_sqlite, neg_root, categories
    )
    if not targets:
        return {"skipped": True, "reason": "无可扫描负样本目标"}

    blastn_bin = ToolConfig.resolve_bio_tool("blastn")
    has_phage_db = any(
        p.is_file() and p.stat().st_size > 0
        for p in phage_blast_dir.glob("phage_refseq_nucl*.nsq")
    )

    blast_hits: Dict[str, List[Tuple[int, int, str]]] = {}
    blastn_executed = False
    if blastn_bin and has_phage_db:
        # 使用不含空格的临时目录存放查询文件，规避 Windows BLAST+ 路径空格兼容问题
        with tempfile.TemporaryDirectory(prefix="phage_neg_mask_") as tmp_dir:
            query_fasta = Path(tmp_dir) / "neg_targets.fna"
            seq_written = 0
            with open(query_fasta, "w", encoding="utf-8") as out_fh:
                for acc, meta in targets.items():
                    fa_path = Path(meta["fasta_path"])
                    if fa_path.exists():
                        with open(fa_path, "r", encoding="utf-8", errors="replace") as in_fh:
                            for line in in_fh:
                                if line.startswith(">"):
                                    out_fh.write(f">{acc}\n")
                                else:
                                    out_fh.write(line)
                            out_fh.write("\n")
                        seq_written += 1

            if seq_written > 0:
                blast_hits = _run_blastn_prophage_scan(
                    blastn_bin=blastn_bin,
                    phage_blast_dir=phage_blast_dir,
                    db_name="phage_refseq_nucl",
                    query_fasta=query_fasta,
                    perc_identity=perc_identity,
                    evalue=evalue,
                    min_hit_len=min_hit_len,
                    threads=worker_threads,
                )
                blastn_executed = True

    mask_rows: List[Tuple[str, str, int, int, int, str]] = []
    masked_by_cat: Dict[str, int] = defaultdict(int)
    total_masked_bp = 0
    total_raw_blastn_hits = sum(len(v) for v in blast_hits.values())
    total_cds_clusters = sum(len(v) for v in cds_clusters.values())

    for acc, meta in sorted(targets.items()):
        raw_regions: List[Tuple[int, int]] = []
        sources: Set[str] = set()
        for s_pos, e_pos, src in blast_hits.get(acc, []):
            raw_regions.append((s_pos, e_pos))
            sources.add("blastn")
        for s_pos, e_pos, src in cds_clusters.get(acc, []):
            raw_regions.append((s_pos, e_pos))
            sources.add(src)

        if not raw_regions:
            continue

        merged = merge_intervals(raw_regions, max_length=meta["length_bp"], flank_bp=flank_bp)
        source_label = "+".join(sorted(sources))
        if merged:
            masked_by_cat[meta["category"]] += 1
        for s_pos, e_pos in merged:
            span = e_pos - s_pos
            total_masked_bp += span
            mask_rows.append((acc, meta["category"], s_pos, e_pos, span, source_label))

    with closing(sqlite3.connect(neg_sqlite)) as conn:
        conn.execute("DROP TABLE IF EXISTS prophage_masks;")
        conn.execute("""
            CREATE TABLE prophage_masks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                accession TEXT NOT NULL,
                negative_category TEXT,
                start_pos INTEGER NOT NULL,
                end_pos INTEGER NOT NULL,
                mask_length_bp INTEGER NOT NULL,
                evidence_source TEXT,
                FOREIGN KEY(accession) REFERENCES genomes(accession)
            )
        """)
        if mask_rows:
            conn.executemany(
                """
                INSERT INTO prophage_masks (
                    accession, negative_category, start_pos, end_pos, mask_length_bp, evidence_source
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                mask_rows,
            )
        conn.execute("CREATE INDEX idx_prophage_masks_acc ON prophage_masks(accession);")
        conn.commit()

    compact_sqlite_db(neg_sqlite)

    masks_tsv = neg_root / "index" / "prophage_masks.tsv"
    tmp_tsv = masks_tsv.with_name(f".{masks_tsv.name}.tmp")
    with open(tmp_tsv, "w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh, delimiter="\t")
        writer.writerow(["accession", "negative_category", "start_pos", "end_pos", "mask_length_bp", "evidence_source"])
        writer.writerows(mask_rows)
    tmp_tsv.replace(masks_tsv)

    masked_accessions = len({row[0] for row in mask_rows})
    return {
        "skipped": False,
        "blastn_executed": blastn_executed,
        "scanned_targets": len(targets),
        "raw_blastn_hits": total_raw_blastn_hits,
        "raw_cds_cluster_hits": total_cds_clusters,
        "masked_accessions_count": masked_accessions,
        "masked_accessions_by_category": dict(masked_by_cat),
        "merged_mask_intervals_count": len(mask_rows),
        "total_masked_bp": total_masked_bp,
        "total_masked_mb": round(total_masked_bp / (1024 * 1024), 3),
        "masks_tsv": str(masks_tsv),
    }


def filter_high_n_preprocessed_splits(
    positive_dir: Path,
    max_n_percent: float = 2.0,
) -> Dict[str, Any]:
    """
    从预处理划分 splits/{train,val,test}.tsv 中剔除高 N 比例残缺基因组，
    并同步更新 preprocess_manifest.json。保留原始 FASTA/GBK 与全量索引供可追溯审计。
    """
    pos_root = Path(positive_dir).resolve()
    pos_sqlite = pos_root / "index" / "phage_index.sqlite"
    splits_dir = pos_root / "preprocessed" / "splits"
    manifest_path = pos_root / "preprocessed" / "preprocess_manifest.json"

    if not pos_sqlite.exists():
        return {"skipped": True, "reason": f"未找到正样本索引 {pos_sqlite}"}

    high_n_accessions: Dict[str, float] = {}
    with closing(sqlite3.connect(pos_sqlite)) as conn:
        rows = conn.execute(
            "SELECT accession, n_percent FROM genomes WHERE n_percent > ?",
            (max_n_percent,),
        ).fetchall()
        for acc, n_pct in rows:
            high_n_accessions[str(acc)] = float(n_pct)

    split_counts_before: Dict[str, int] = {}
    split_counts_after: Dict[str, int] = {}
    removed_from_splits: Dict[str, List[str]] = {}

    if splits_dir.exists():
        for split_name in ("train", "val", "test"):
            split_file = splits_dir / f"{split_name}.tsv"
            if not split_file.exists():
                continue
            with open(split_file, "r", encoding="utf-8", newline="") as in_fh:
                reader = csv.reader(in_fh, delimiter="\t")
                rows = list(reader)
            if not rows:
                split_counts_before[split_name] = 0
                split_counts_after[split_name] = 0
                removed_from_splits[split_name] = []
                continue

            header = rows[0]
            body = rows[1:]
            split_counts_before[split_name] = len(body)

            acc_idx = header.index("accession") if "accession" in header else 0
            kept_body: List[List[str]] = []
            removed: List[str] = []
            for row in body:
                acc = row[acc_idx] if len(row) > acc_idx else ""
                if acc in high_n_accessions:
                    removed.append(acc)
                else:
                    kept_body.append(row)

            tmp_split = split_file.with_name(f".{split_file.name}.tmp")
            with open(tmp_split, "w", encoding="utf-8", newline="") as out_fh:
                writer = csv.writer(out_fh, delimiter="\t")
                writer.writerow(header)
                writer.writerows(kept_body)
            tmp_split.replace(split_file)

            split_counts_after[split_name] = len(kept_body)
            removed_from_splits[split_name] = removed

    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if "splits" in manifest and isinstance(manifest["splits"], dict):
                for split_name, count in split_counts_after.items():
                    manifest["splits"][split_name] = count
            manifest["high_n_filtering"] = {
                "max_n_percent_threshold": max_n_percent,
                "filtered_accessions": high_n_accessions,
                "removed_from_splits": removed_from_splits,
                "applied_at": datetime.now().isoformat(timespec="seconds"),
            }
            _atomic_write_json(manifest_path, manifest)
        except Exception as exc:
            logger.warning(f"更新 preprocess_manifest.json 失败: {exc}")

    return {
        "skipped": False,
        "max_n_percent": max_n_percent,
        "high_n_accessions": high_n_accessions,
        "split_counts_before": split_counts_before,
        "split_counts_after": split_counts_after,
        "removed_from_splits": removed_from_splits,
    }


def clean_phage_databases(
    positive_dir: Path,
    negative_dir: Optional[Path] = None,
    min_prot_aa: int = 25,
    max_n_percent: float = 2.0,
    prophage_perc_identity: float = 80.0,
    prophage_min_hit_len: int = 500,
    prophage_flank_bp: int = 1000,
    threads: Optional[int] = None,
) -> Dict[str, Any]:
    """执行正负样本数据库端到端清理，并输出 meta/cleanup_report.json。"""
    pos_root = Path(positive_dir).resolve()
    neg_root = Path(negative_dir).resolve() if negative_dir else pos_root / "negative"

    pos_artifact_cleanup = prune_redundant_artifacts(
        pos_root,
        nucl_fasta_name="phage_refseq_nucl.fna",
        nucl_db_prefix_name="phage_refseq_nucl",
        prot_fasta_name="phage_refseq_prot.faa",
        prot_db_prefix_name="phage_refseq_prot",
    )
    neg_artifact_cleanup = (
        prune_redundant_artifacts(
            neg_root,
            nucl_fasta_name="neg_refseq_nucl.fna",
            nucl_db_prefix_name="neg_refseq_nucl",
            prot_fasta_name="neg_refseq_prot.faa",
            prot_db_prefix_name="neg_refseq_prot",
        )
        if neg_root.exists()
        else {"skipped": True}
    )

    pos_sqlite_cleanup = clean_sqlite_cds_noise(
        pos_root / "index" / "phage_index.sqlite", min_prot_aa=min_prot_aa
    )
    neg_sqlite_cleanup = (
        clean_sqlite_cds_noise(
            neg_root / "index" / "negative_index.sqlite", min_prot_aa=min_prot_aa
        )
        if neg_root.exists()
        else {"skipped": True}
    )

    prophage_mask_report = (
        scan_and_mask_negative_prophages(
            positive_dir=pos_root,
            negative_dir=neg_root,
            perc_identity=prophage_perc_identity,
            min_hit_len=prophage_min_hit_len,
            flank_bp=prophage_flank_bp,
            threads=threads,
        )
        if neg_root.exists()
        else {"skipped": True}
    )

    high_n_report = filter_high_n_preprocessed_splits(
        positive_dir=pos_root, max_n_percent=max_n_percent
    )

    total_reclaimed_bytes = (
        pos_artifact_cleanup.get("total_reclaimed_bytes", 0)
        + neg_artifact_cleanup.get("total_reclaimed_bytes", 0)
        + pos_sqlite_cleanup.get("reclaimed_bytes", 0)
        + neg_sqlite_cleanup.get("reclaimed_bytes", 0)
    )

    report: Dict[str, Any] = {
        "cleaned_at": datetime.now().isoformat(timespec="seconds"),
        "positive_dir": str(pos_root),
        "negative_dir": str(neg_root),
        "parameters": {
            "min_prot_aa": min_prot_aa,
            "max_n_percent": max_n_percent,
            "prophage_perc_identity": prophage_perc_identity,
            "prophage_min_hit_len": prophage_min_hit_len,
            "prophage_flank_bp": prophage_flank_bp,
        },
        "summary": {
            "total_disk_reclaimed_mb": round(total_reclaimed_bytes / (1024 * 1024), 2),
            "positive_cds_removed": pos_sqlite_cleanup.get("deleted_short_lt_min_aa", 0)
            + pos_sqlite_cleanup.get("deleted_pseudo", 0),
            "negative_cds_removed": neg_sqlite_cleanup.get("deleted_short_lt_min_aa", 0)
            + neg_sqlite_cleanup.get("deleted_pseudo", 0),
            "negative_prophage_masked_accessions": prophage_mask_report.get("masked_accessions_count", 0),
            "negative_prophage_mask_intervals": prophage_mask_report.get("merged_mask_intervals_count", 0),
            "high_n_positive_filtered_count": len(high_n_report.get("high_n_accessions", {})),
        },
        "positive_artifact_cleanup": pos_artifact_cleanup,
        "negative_artifact_cleanup": neg_artifact_cleanup,
        "positive_sqlite_cleanup": pos_sqlite_cleanup,
        "negative_sqlite_cleanup": neg_sqlite_cleanup,
        "negative_prophage_masking": prophage_mask_report,
        "high_n_split_filtering": high_n_report,
    }

    report_path = pos_root / "meta" / "cleanup_report.json"
    _atomic_write_json(report_path, report)
    report["report_path"] = str(report_path)
    return report


def main() -> int:
    """CLI 入口。"""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    parser = argparse.ArgumentParser(description="清理并加固噬菌体正负样本本地数据库")
    parser.add_argument("--positive-dir", required=True, help="正样本数据集根目录")
    parser.add_argument("--negative-dir", default="", help="负样本数据集根目录（默认为 <positive-dir>/negative）")
    parser.add_argument("--min-prot-aa", type=int, default=25, help="最小保留蛋白长度（aa），默认 25")
    parser.add_argument("--max-n-percent", type=float, default=2.0, help="splits 中允许的最大 N 百分比阈值，默认 2.0")
    parser.add_argument("--prophage-perc-identity", type=float, default=80.0, help="负样本前噬菌体扫描 BLASTn 相似度阈值")
    parser.add_argument("--prophage-min-hit-len", type=int, default=500, help="负样本前噬菌体扫描最小比对长度（bp）")
    parser.add_argument("--prophage-flank-bp", type=int, default=1000, help="掩蔽区间上下游延伸缓冲（bp）")
    parser.add_argument("--threads", type=int, default=0, help="BLASTn 线程数（0 表示自动保留 2 核）")

    args = parser.parse_args()
    report = clean_phage_databases(
        positive_dir=Path(args.positive_dir),
        negative_dir=Path(args.negative_dir) if args.negative_dir else None,
        min_prot_aa=args.min_prot_aa,
        max_n_percent=args.max_n_percent,
        prophage_perc_identity=args.prophage_perc_identity,
        prophage_min_hit_len=args.prophage_min_hit_len,
        prophage_flank_bp=args.prophage_flank_bp,
        threads=args.threads if args.threads > 0 else None,
    )
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
