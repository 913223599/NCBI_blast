# -*- coding: utf-8 -*-
"""
噬菌体数据集多维度索引构建器

生成产物（均原子写盘且强制 UTF-8）：
1. index/phage_index.sqlite：SQLite WAL 索引数据库（genomes 元数据表 + cds_features 特征表 + 检索索引）；
2. index/phage_index.tsv：全量元数据清单（可用 Excel/Pandas 直接分析）；
3. index/manifest.json：数据集总体统计、宿主分布、校验汇总与各产物路径/指纹；
4. blastdb/phage_refseq_nucl.* & blastdb/phage_refseq_prot.*：本地 NCBI BLAST+ 核酸与蛋白检索索引。
"""
import csv
import json
import logging
import os
import shutil
import subprocess
import tempfile
from collections import Counter
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
import sqlite3

from ...workbench.models.tool_config import ToolConfig
from .validator import PhageRecordValidation

logger = logging.getLogger("utils.phage_dataset.indexer")

TSV_HEADERS = [
    "accession",
    "status",
    "is_phage",
    "phage_confidence",
    "phage_tax_group",
    "phage_evidence",
    "organism",
    "host",
    "length_bp",
    "gc_percent",
    "n_percent",
    "topology",
    "cds_count",
    "translated_cds_count",
    "trna_count",
    "has_integrase",
    "has_terminase",
    "has_lysin",
    "has_capsid",
    "has_tail",
    "taxonomy",
    "fasta_sha256",
    "gbk_sha256",
    "fasta_relpath",
    "gbk_relpath",
    "warnings",
    "errors",
]


def _to_windows_short_path(path: Path) -> Path:
    """在 Windows 下将含空格目录转为 8.3 短路径（若系统支持），否则原样返回。"""
    if os.name != "nt":
        return path
    try:
        import ctypes

        buf = ctypes.create_unicode_buffer(1024)
        n = ctypes.windll.kernel32.GetShortPathNameW(str(path), buf, len(buf))
        if 0 < n < len(buf) and " " not in buf.value:
            return Path(buf.value)
    except Exception:
        pass
    return path


def _link_or_copy_fasta(src: Path, dst: Path) -> None:
    """优先使用零拷贝硬链接复用 FASTA，跨盘时回退文件复制。"""
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)


def _run_makeblastdb(
    makeblastdb_bin: Any,
    input_fasta: Path,
    db_prefix: Path,
    dbtype: str,
    title: str,
    parse_seqids: bool = False,
) -> bool:
    """调用本地 makeblastdb 构建 BLAST 索引库（自动通过无空格暂存区规避 Windows LMDB mmap 路径空格异常）。"""
    if not input_fasta.exists() or input_fasta.stat().st_size == 0:
        return False

    work_dir = db_prefix.parent.resolve()
    out_arg = db_prefix.name
    needs_staging = " " in str(work_dir)

    if not needs_staging:
        in_arg = input_fasta.name if input_fasta.parent.resolve() == work_dir else str(input_fasta.resolve())
        return _exec_makeblastdb_in_dir(
            makeblastdb_bin=makeblastdb_bin,
            in_arg=in_arg,
            out_arg=out_arg,
            dbtype=dbtype,
            title=title,
            parse_seqids=parse_seqids,
            exec_dir=work_dir,
        )

    # 目标目录含空格时：在无空格临时目录内生成全部库文件，随后原子搬运回目标目录
    anchor_tmp = Path(tempfile.gettempdir())
    stage_parent = anchor_tmp if " " not in str(anchor_tmp) else _to_windows_short_path(anchor_tmp)
    if " " in str(stage_parent) and work_dir.anchor:
        stage_parent = Path(work_dir.anchor)

    with tempfile.TemporaryDirectory(prefix="phage_blast_", dir=str(stage_parent)) as tmp_root:
        resolved_root = _to_windows_short_path(Path(tmp_root).resolve())
        stage_dir = resolved_root / work_dir.name
        stage_dir.mkdir(parents=True, exist_ok=True)
        staged_fasta = stage_dir / input_fasta.name
        _link_or_copy_fasta(input_fasta.resolve(), staged_fasta)

        ok = _exec_makeblastdb_in_dir(
            makeblastdb_bin=makeblastdb_bin,
            in_arg=staged_fasta.name,
            out_arg=out_arg,
            dbtype=dbtype,
            title=title,
            parse_seqids=parse_seqids,
            exec_dir=stage_dir,
        )
        if not ok:
            return False

        # 先清除目标目录中可能残存的旧版库碎片，再搬运新生成的全套索引文件
        for old_item in work_dir.glob(f"{out_arg}.*"):
            if old_item.name != input_fasta.name and old_item.is_file():
                old_item.unlink(missing_ok=True)
        for gen_item in stage_dir.glob(f"{out_arg}.*"):
            if gen_item.name != staged_fasta.name and gen_item.is_file():
                shutil.move(str(gen_item), str(work_dir / gen_item.name))
        return True


def _exec_makeblastdb_in_dir(
    makeblastdb_bin: Any,
    in_arg: str,
    out_arg: str,
    dbtype: str,
    title: str,
    parse_seqids: bool,
    exec_dir: Path,
) -> bool:
    """在指定无空格工作目录内执行 makeblastdb 进程。"""
    cmd = [
        str(makeblastdb_bin),
        "-in",
        in_arg,
        "-dbtype",
        dbtype,
        "-title",
        title,
        "-out",
        out_arg,
    ]
    if parse_seqids:
        cmd.append("-parse_seqids")

    try:
        res = subprocess.run(
            cmd,
            cwd=str(exec_dir),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=600,
        )
        if res.returncode == 0:
            return True
        logger.warning(f"makeblastdb ({dbtype}) 返回异常 {res.returncode}: {res.stderr.strip()}")
    except Exception as exc:
        logger.warning(f"makeblastdb ({dbtype}) 执行失败: {exc}")
    return False


def compact_sqlite_db(db_path: Path) -> None:
    """对 SQLite WAL 数据库执行 checkpoint、VACUUM 压缩与查询优化。"""
    if not db_path.exists():
        return
    with closing(sqlite3.connect(db_path, isolation_level=None)) as conn:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
        conn.execute("VACUUM;")
        conn.execute("PRAGMA optimize;")
    for suffix in ("-wal", "-shm"):
        aux = Path(f"{db_path}{suffix}")
        if aux.exists():
            try:
                aux.unlink()
            except OSError:
                pass


def remove_redundant_blast_fasta(
    fasta_path: Path,
    db_prefix: Path,
    dbtype: str,
) -> int:
    """
    仅当对应的真实 BLAST+ 索引数据文件（.nsq/.psq，含分卷如 .00.nsq）存在时，
    安全移除中间合并 FASTA/FAA 文件并返回释放字节数。
    """
    if not fasta_path.exists():
        return 0
    ext = "nsq" if dbtype == "nucl" else "psq"
    has_real_db = any(
        p.is_file() and p.stat().st_size > 0
        for p in db_prefix.parent.glob(f"{db_prefix.name}*.{ext}")
    )
    if not has_real_db:
        return 0
    reclaimed = fasta_path.stat().st_size
    fasta_path.unlink()
    return reclaimed


def _build_sqlite_index(
    db_path: Path,
    records: List[PhageRecordValidation],
    data_dir: Path,
    checkpoint_map: Dict[str, Any],
    min_prot_aa: int = 25,
) -> None:
    """原子构建 SQLite WAL 关系型索引（genomes + cds_features 分批事务落盘）。"""
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
                is_phage INTEGER NOT NULL,
                phage_confidence TEXT,
                phage_tax_group TEXT,
                phage_evidence TEXT,
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
                has_integrase INTEGER,
                has_terminase INTEGER,
                has_lysin INTEGER,
                has_capsid INTEGER,
                has_tail INTEGER,
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
            fa_rel = f"fasta/{Path(r.fasta_path).name}"
            gb_rel = f"gbk/{Path(r.gbk_path).name}"
            src_grp = str((checkpoint_map.get(r.accession) or {}).get("source_group", ""))
            genome_rows.append((
                r.accession,
                r.status,
                int(r.is_phage),
                r.phage_confidence,
                r.phage_tax_group,
                "; ".join(r.phage_evidence),
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
                int(r.has_integrase),
                int(r.has_terminase),
                int(r.has_lysin),
                int(r.has_capsid),
                int(r.has_tail),
                r.fasta_sha256,
                r.gbk_sha256,
                fa_rel,
                gb_rel,
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
                accession, status, is_phage, phage_confidence, phage_tax_group, phage_evidence,
                source_group, organism, host, taxonomy, description,
                length_bp, gc_percent, n_percent, topology, molecule_type,
                cds_count, translated_cds_count, trna_count,
                has_integrase, has_terminase, has_lysin, has_capsid, has_tail,
                fasta_sha256, gbk_sha256, fasta_relpath, gbk_relpath, warnings, errors
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            genome_rows,
        )
        if cds_batch:
            conn.executemany(
                "INSERT INTO cds_features (accession, locus_tag, protein_id, start_pos, end_pos, strand, length_aa, product) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                cds_batch,
            )

        conn.execute("CREATE INDEX idx_genomes_host ON genomes(host)")
        conn.execute("CREATE INDEX idx_genomes_status ON genomes(status)")
        conn.execute("CREATE INDEX idx_genomes_is_phage ON genomes(is_phage)")
        conn.execute("CREATE INDEX idx_genomes_tax_group ON genomes(phage_tax_group)")
        conn.execute("CREATE INDEX idx_genomes_length ON genomes(length_bp)")
        conn.execute("CREATE INDEX idx_genomes_integrase ON genomes(has_integrase)")
        conn.execute("CREATE INDEX idx_cds_accession ON cds_features(accession)")
        conn.execute("CREATE INDEX idx_cds_product ON cds_features(product)")

    compact_sqlite_db(tmp_db)

    # 清理目标路径残留 WAL 辅助文件并切换至正式索引路径
    for suffix in ("-wal", "-shm"):
        aux = Path(f"{db_path}{suffix}")
        if aux.exists():
            aux.unlink()
    tmp_db.replace(db_path)


def build_phage_dataset_indexes(
    data_dir: Path,
    validations: List[PhageRecordValidation],
    checkpoint_saved_records: Optional[Dict[str, Any]] = None,
    build_blast_db: bool = True,
    min_prot_aa: int = 25,
    keep_merged_fasta: bool = False,
) -> Dict[str, Any]:
    """
    依据校验结果构建多层次本地索引：
    - SQLite 关系型索引 (index/phage_index.sqlite)
    - TSV 总表 (index/phage_index.tsv)
    - JSON 清单报告 (index/manifest.json)
    - 本地核酸与蛋白 BLAST 库 (blastdb/)
    """
    root = Path(data_dir).resolve()
    index_dir = root / "index"
    blast_dir = root / "blastdb"
    index_dir.mkdir(parents=True, exist_ok=True)
    blast_dir.mkdir(parents=True, exist_ok=True)

    checkpoint_map = checkpoint_saved_records or {}

    # 1. SQLite WAL 索引
    sqlite_path = index_dir / "phage_index.sqlite"
    _build_sqlite_index(sqlite_path, validations, root, checkpoint_map, min_prot_aa=min_prot_aa)

    # 2. TSV 元数据表（原子写入）
    tsv_path = index_dir / "phage_index.tsv"
    tmp_tsv = tsv_path.with_name(f".{tsv_path.name}.tmp")
    with open(tmp_tsv, "w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh, delimiter="\t")
        writer.writerow(TSV_HEADERS)
        for r in validations:
            writer.writerow([
                r.accession,
                r.status,
                int(r.is_phage),
                r.phage_confidence,
                r.phage_tax_group,
                "; ".join(r.phage_evidence),
                r.organism,
                r.host,
                r.length_bp,
                r.gc_percent,
                r.n_percent,
                r.topology,
                r.cds_count,
                r.translated_cds_count,
                r.trna_count,
                int(r.has_integrase),
                int(r.has_terminase),
                int(r.has_lysin),
                int(r.has_capsid),
                int(r.has_tail),
                r.taxonomy,
                r.fasta_sha256,
                r.gbk_sha256,
                f"fasta/{Path(r.fasta_path).name}",
                f"gbk/{Path(r.gbk_path).name}",
                "; ".join(r.warnings),
                "; ".join(r.errors),
            ])
    tmp_tsv.replace(tsv_path)

    # 3. 汇总经完整度与噬菌体真实性双验证通过的序列至流式合并 FASTA / FAA，并构建本地 BLAST+ 索引
    valid_records = [r for r in validations if r.status in ("passed", "warning") and r.is_phage]
    nucl_fasta = blast_dir / "phage_refseq_nucl.fna"
    prot_fasta = blast_dir / "phage_refseq_prot.faa"

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
                header = f">{r.accession}|{cds.protein_id}|{cds.locus_tag} {cds.product}"
                pf.write(f"{header}\n{cds.translation}\n")

    tmp_nucl.replace(nucl_fasta)
    tmp_prot.replace(prot_fasta)

    nucl_db_ready = False
    prot_db_ready = False
    nucl_prefix = blast_dir / "phage_refseq_nucl"
    prot_prefix = blast_dir / "phage_refseq_prot"
    makeblastdb_bin = ToolConfig.resolve_bio_tool("makeblastdb") if build_blast_db else None
    if makeblastdb_bin and valid_records:
        nucl_db_ready = _run_makeblastdb(
            makeblastdb_bin,
            nucl_fasta,
            nucl_prefix,
            dbtype="nucl",
            title="Local Phage RefSeq Nucleotide Index",
            parse_seqids=True,
        )
        if total_prot_seqs > 0:
            prot_db_ready = _run_makeblastdb(
                makeblastdb_bin,
                prot_fasta,
                prot_prefix,
                dbtype="prot",
                title="Local Phage RefSeq Protein Index",
                parse_seqids=False,
            )

    cleaned_fastas = False
    if build_blast_db and not keep_merged_fasta:
        if nucl_db_ready:
            cleaned_fastas = remove_redundant_blast_fasta(nucl_fasta, nucl_prefix, "nucl") > 0 or cleaned_fastas
        if prot_db_ready:
            cleaned_fastas = remove_redundant_blast_fasta(prot_fasta, prot_prefix, "prot") > 0 or cleaned_fastas

    # 4. 生成总体统计清单 manifest.json
    host_counter = Counter(r.host or "Unspecified" for r in valid_records)
    topo_counter = Counter(r.topology for r in valid_records)
    status_counter = Counter(r.status for r in validations)
    confidence_counter = Counter(r.phage_confidence for r in validations)
    tax_group_counter = Counter(r.phage_tax_group or "Unspecified" for r in valid_records)

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
            "verified_phage_count": sum(1 for r in validations if r.is_phage),
            "rejected_non_phage_count": sum(1 for r in validations if not r.is_phage and any("not_verified_as_phage" in e for e in r.errors)),
            "valid_genomes_count": len(valid_records),
            "total_bp": total_bp,
            "avg_length_bp": round(total_bp / len(valid_records), 1) if valid_records else 0,
            "total_cds": total_cds,
            "total_translated_proteins": total_prot_seqs,
            "genomes_with_integrase": sum(1 for r in valid_records if r.has_integrase),
            "genomes_with_terminase": sum(1 for r in valid_records if r.has_terminase),
            "genomes_with_lysin": sum(1 for r in valid_records if r.has_lysin),
        },
        "phage_confidence_distribution": dict(confidence_counter),
        "phage_tax_group_distribution": dict(tax_group_counter),
        "topology_distribution": dict(topo_counter),
        "host_distribution_top20": dict(host_counter.most_common(20)),
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

