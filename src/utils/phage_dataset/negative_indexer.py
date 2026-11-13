# -*- coding: utf-8 -*-
"""
配套负样本多维度索引构建器

生成产物（均原子写盘且强制 UTF-8）：
1. index/negative_index.sqlite：SQLite WAL 索引数据库（genomes + cds_features + 索引）；
2. index/negative_index.tsv：全量负样本元数据清单；
3. index/manifest.json：负样本总体统计、类别分布、校验汇总与产物路径；
4. blastdb/neg_refseq_nucl.* & blastdb/neg_refseq_prot.*：本地 NCBI BLAST+ 核酸与蛋白索引库。
"""
import csv
import json
import logging
import shutil
import sqlite3
from collections import Counter
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from ...workbench.models.tool_config import ToolConfig
from .indexer import _run_makeblastdb, compact_sqlite_db, remove_redundant_blast_fasta
from .negative_validator import NegativeRecordValidation

logger = logging.getLogger("utils.phage_dataset.negative_indexer")

NEG_TSV_HEADERS = [
    "accession",
    "status",
    "is_valid_negative",
    "negative_category",
    "organism",
    "host",
    "length_bp",
    "gc_percent",
    "n_percent",
    "topology",
    "cds_count",
    "translated_cds_count",
    "trna_count",
    "suspected_prophage_cds_count",
    "taxonomy",
    "fasta_sha256",
    "gbk_sha256",
    "fasta_relpath",
    "gbk_relpath",
    "warnings",
    "errors",
]


def _build_negative_sqlite(
    db_path: Path,
    records: List[NegativeRecordValidation],
    checkpoint_map: Dict[str, Any],
    min_prot_aa: int = 25,
) -> None:
    """原子构建负样本 SQLite WAL 关系型索引。"""
    tmp_db = db_path.with_name(f".{db_path.name}.tmp")
    if tmp_db.exists():
        tmp_db.unlink()

    with closing(sqlite3.connect(tmp_db)) as conn, conn:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute("""
            CREATE TABLE genomes (
                accession TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                is_valid_negative INTEGER NOT NULL,
                negative_category TEXT,
                source_group TEXT,
                organism TEXT,
                host TEXT,
                taxonomy TEXT,
                description TEXT,
                length_bp INTEGER,
                gc_percent REAL,
                n_percent REAL,
                topology TEXT,
                molecule_type TEXT,
                cds_count INTEGER,
                translated_cds_count INTEGER,
                trna_count INTEGER,
                suspected_prophage_cds_count INTEGER,
                fasta_sha256 TEXT,
                gbk_sha256 TEXT,
                fasta_relpath TEXT,
                gbk_relpath TEXT,
                warnings TEXT,
                errors TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE cds_features (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                accession TEXT NOT NULL,
                locus_tag TEXT,
                protein_id TEXT,
                start_pos INTEGER,
                end_pos INTEGER,
                strand INTEGER,
                length_aa INTEGER,
                product TEXT,
                FOREIGN KEY(accession) REFERENCES genomes(accession)
            )
        """)

        genome_rows = []
        cds_batch: List[tuple] = []
        for r in records:
            src_grp = str((checkpoint_map.get(r.accession) or {}).get("source_group", ""))
            genome_rows.append((
                r.accession,
                r.status,
                int(r.is_valid_negative),
                r.negative_category,
                src_grp,
                r.organism,
                r.host,
                r.taxonomy,
                r.description,
                r.length_bp,
                r.gc_percent,
                r.n_percent,
                r.topology,
                r.molecule_type,
                r.cds_count,
                r.translated_cds_count,
                r.trna_count,
                r.suspected_prophage_cds_count,
                r.fasta_sha256,
                r.gbk_sha256,
                f"fasta/{Path(r.fasta_path).name}",
                f"gbk/{Path(r.gbk_path).name}",
                "; ".join(r.warnings),
                "; ".join(r.errors),
            ))
            for cds in r.cds_items:
                if cds.length_aa < min_prot_aa:
                    continue
                cds_batch.append((
                    cds.accession,
                    cds.locus_tag,
                    cds.protein_id,
                    cds.start,
                    cds.end,
                    cds.strand,
                    cds.length_aa,
                    cds.product,
                ))
                if len(cds_batch) >= 2000:
                    conn.executemany(
                        "INSERT INTO cds_features (accession, locus_tag, protein_id, start_pos, end_pos, strand, length_aa, product) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        cds_batch,
                    )
                    cds_batch.clear()

        conn.executemany(
            """
            INSERT INTO genomes (
                accession, status, is_valid_negative, negative_category, source_group,
                organism, host, taxonomy, description, length_bp, gc_percent, n_percent,
                topology, molecule_type, cds_count, translated_cds_count, trna_count,
                suspected_prophage_cds_count, fasta_sha256, gbk_sha256,
                fasta_relpath, gbk_relpath, warnings, errors
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            genome_rows,
        )
        if cds_batch:
            conn.executemany(
                "INSERT INTO cds_features (accession, locus_tag, protein_id, start_pos, end_pos, strand, length_aa, product) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                cds_batch,
            )

        conn.execute("CREATE INDEX idx_neg_category ON genomes(negative_category)")
        conn.execute("CREATE INDEX idx_neg_status ON genomes(status)")
        conn.execute("CREATE INDEX idx_neg_length ON genomes(length_bp)")
        conn.execute("CREATE INDEX idx_neg_cds_acc ON cds_features(accession)")
        conn.execute("CREATE INDEX idx_neg_cds_prod ON cds_features(product)")

    compact_sqlite_db(tmp_db)

    for suffix in ("-wal", "-shm"):
        aux = Path(f"{db_path}{suffix}")
        if aux.exists():
            aux.unlink()
    tmp_db.replace(db_path)


def build_negative_dataset_indexes(
    data_dir: Path,
    validations: List[NegativeRecordValidation],
    checkpoint_saved_records: Optional[Dict[str, Any]] = None,
    build_blast_db: bool = True,
    min_prot_aa: int = 25,
    keep_merged_fasta: bool = False,
) -> Dict[str, Any]:
    """根据负样本校验结果构建 SQLite WAL、TSV、JSON 与本地核酸/蛋白 BLAST 库。"""
    root = Path(data_dir).resolve()
    index_dir = root / "index"
    blast_dir = root / "blastdb"
    index_dir.mkdir(parents=True, exist_ok=True)
    blast_dir.mkdir(parents=True, exist_ok=True)

    checkpoint_map = checkpoint_saved_records or {}

    sqlite_path = index_dir / "negative_index.sqlite"
    _build_negative_sqlite(sqlite_path, validations, checkpoint_map, min_prot_aa=min_prot_aa)

    tsv_path = index_dir / "negative_index.tsv"
    tmp_tsv = tsv_path.with_name(f".{tsv_path.name}.tmp")
    with open(tmp_tsv, "w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh, delimiter="\t")
        writer.writerow(NEG_TSV_HEADERS)
        for r in validations:
            writer.writerow([
                r.accession,
                r.status,
                int(r.is_valid_negative),
                r.negative_category,
                r.organism,
                r.host,
                r.length_bp,
                r.gc_percent,
                r.n_percent,
                r.topology,
                r.cds_count,
                r.translated_cds_count,
                r.trna_count,
                r.suspected_prophage_cds_count,
                r.taxonomy,
                r.fasta_sha256,
                r.gbk_sha256,
                f"fasta/{Path(r.fasta_path).name}",
                f"gbk/{Path(r.gbk_path).name}",
                "; ".join(r.warnings),
                "; ".join(r.errors),
            ])
    tmp_tsv.replace(tsv_path)

    valid_records = [r for r in validations if r.status in ("passed", "warning") and r.is_valid_negative]
    nucl_fasta = blast_dir / "neg_refseq_nucl.fna"
    prot_fasta = blast_dir / "neg_refseq_prot.faa"

    tmp_nucl = nucl_fasta.with_name(f".{nucl_fasta.name}.tmp")
    tmp_prot = prot_fasta.with_name(f".{prot_fasta.name}.tmp")
    total_prot_seqs = 0

    with open(tmp_nucl, "w", encoding="utf-8") as nf, open(tmp_prot, "w", encoding="utf-8") as pf:
        for r in valid_records:
            fa_file = Path(r.fasta_path)
            if fa_file.exists():
                with open(fa_file, "r", encoding="utf-8") as src_f:
                    shutil.copyfileobj(src_f, nf)
                    nf.write("\n")
            for cds in r.cds_items:
                if not cds.translation or cds.length_aa < min_prot_aa:
                    continue
                total_prot_seqs += 1
                pf.write(f">{r.accession}|{cds.protein_id}|{cds.locus_tag} {cds.product}\n{cds.translation}\n")

    tmp_nucl.replace(nucl_fasta)
    tmp_prot.replace(prot_fasta)

    nucl_db_ready = False
    prot_db_ready = False
    nucl_prefix = blast_dir / "neg_refseq_nucl"
    prot_prefix = blast_dir / "neg_refseq_prot"
    makeblastdb_bin = ToolConfig.resolve_bio_tool("makeblastdb") if build_blast_db else None
    if makeblastdb_bin and valid_records:
        nucl_db_ready = _run_makeblastdb(
            makeblastdb_bin,
            nucl_fasta,
            nucl_prefix,
            dbtype="nucl",
            title="Local Negative Reference Nucleotide Index",
            parse_seqids=True,
        )
        if total_prot_seqs > 0:
            prot_db_ready = _run_makeblastdb(
                makeblastdb_bin,
                prot_fasta,
                prot_prefix,
                dbtype="prot",
                title="Local Negative Reference Protein Index",
                parse_seqids=False,
            )

    cleaned_fastas = False
    if build_blast_db and not keep_merged_fasta:
        if nucl_db_ready:
            cleaned_fastas = remove_redundant_blast_fasta(nucl_fasta, nucl_prefix, "nucl") > 0 or cleaned_fastas
        if prot_db_ready:
            cleaned_fastas = remove_redundant_blast_fasta(prot_fasta, prot_prefix, "prot") > 0 or cleaned_fastas

    cat_counter = Counter(r.negative_category or "unknown" for r in valid_records)
    topo_counter = Counter(r.topology for r in valid_records)
    status_counter = Counter(r.status for r in validations)

    total_bp = sum(r.length_bp for r in valid_records)
    total_cds = sum(r.cds_count for r in valid_records)
    manifest: Dict[str, Any] = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "data_dir": str(root),
        "summary": {
            "total_records": len(validations),
            "passed_count": status_counter.get("passed", 0),
            "warning_count": status_counter.get("warning", 0),
            "failed_count": status_counter.get("failed", 0),
            "valid_negative_count": len(valid_records),
            "rejected_phage_contaminated": sum(1 for r in validations if not r.is_valid_negative),
            "total_bp": total_bp,
            "avg_length_bp": round(total_bp / len(valid_records), 1) if valid_records else 0,
            "total_cds": total_cds,
            "total_translated_proteins": total_prot_seqs,
            "genomes_with_suspected_prophage_markers": sum(1 for r in valid_records if r.suspected_prophage_cds_count > 0),
        },
        "negative_category_distribution": dict(cat_counter),
        "topology_distribution": dict(topo_counter),
        "artifacts": {
            "sqlite_index": str(sqlite_path),
            "tsv_index": str(tsv_path),
            "nucl_fasta": str(nucl_fasta) if nucl_fasta.exists() else "",
            "prot_fasta": str(prot_fasta) if prot_fasta.exists() else "",
            "blast_nucl_db_prefix": str(nucl_prefix),
            "blast_prot_db_prefix": str(prot_prefix),
            "blast_nucl_db_ready": nucl_db_ready,
            "blast_prot_db_ready": prot_db_ready,
            "cleaned_intermediate_fastas": cleaned_fastas,
            "makeblastdb_bin": str(makeblastdb_bin) if makeblastdb_bin else "",
        },
    }

    manifest_path = index_dir / "manifest.json"
    tmp_manifest = manifest_path.with_name(f".{manifest_path.name}.tmp")
    tmp_manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_manifest.replace(manifest_path)

    return manifest

