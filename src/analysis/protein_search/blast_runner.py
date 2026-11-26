# -*- coding: utf-8 -*-
"""
多核并发 BLAST+（makeblastdb / tblastn / blastp）执行器与分片 Checkpoint 断点保护模块。
"""

from __future__ import annotations

import concurrent.futures
import ctypes
import hashlib
import json
import os
from ...utils.resource_guard import get_total_logical_cores
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

from .fasta_parser import write_shard_fasta
from .models import QueryProteinRecord, SearchConfig, ShardSpec, TargetSequenceRecord
import logging
logger = logging.getLogger(__name__)

BLAST_OUTFMT_FIELDS = (
    "qseqid",
    "sseqid",
    "pident",
    "ppos",
    "length",
    "nident",
    "positive",
    "mismatch",
    "gapopen",
    "qstart",
    "qend",
    "qlen",
    "sstart",
    "send",
    "slen",
    "sframe",
    "evalue",
    "bitscore",
)
BLAST_OUTFMT_SPEC = "6 " + " ".join(BLAST_OUTFMT_FIELDS)


def get_windows_short_path(path: Path) -> str:
    """在 Windows 下将含空格/非 ASCII 字符的路径转换为 8.3 短路径（不可用时回退绝对路径）。"""
    abs_str = str(path.resolve())
    if os.name != "nt":
        return abs_str
    try:
        buf = ctypes.create_unicode_buffer(4096)
        ret = ctypes.windll.kernel32.GetShortPathNameW(abs_str, buf, len(buf))
        if ret > 0:
            return buf.value
    except Exception as exc:
        logger.debug("Windows 短路径转换失败，回退原路径 (%s): %s", abs_str, exc)
    return abs_str


def compute_parallel_plan(
    num_shards: int,
    cpu_count: int | None = None,
    requested_threads: int | None = None,
) -> tuple[int, int]:
    """
    计算 (并发分片进程数, 每进程 BLAST 线程数)。
    严格遵守核心保留原则：主机逻辑核 >= 12 时保留 4 核，>= 4 时保留 2 核，防止主机卡死；
    同时充分利用多核并行加速。
    """
    total_cpus = max(1, cpu_count if cpu_count is not None else get_total_logical_cores())
    if total_cpus >= 12:
        reserved = 4
    elif total_cpus >= 4:
        reserved = 2
    else:
        reserved = max(0, total_cpus - 1)

    max_budget = max(1, total_cpus - reserved)
    if requested_threads is not None and requested_threads > 0:
        budget = max(1, min(requested_threads, max_budget))
    else:
        budget = max_budget

    active_shards = max(1, num_shards)
    if active_shards == 1:
        return 1, min(16, budget)

    max_workers = min(active_shards, budget, 8)
    threads_per_worker = max(1, min(8, budget // max_workers))
    return max_workers, threads_per_worker


def resolve_blast_executable(tool_name: str, blast_bin_dir: Path | None = None) -> str:
    """
    动态解析 BLAST+ 可执行文件路径（严禁硬编码固定盘符）。
    查找顺序：
    1. 显式传入的 blast_bin_dir
    2. 项目内置 ToolConfig（若可用）
    3. 系统 PATH (shutil.which)
    """
    exe_suffix = ".exe" if os.name == "nt" else ""
    candidate_names = [f"{tool_name}{exe_suffix}", tool_name]

    if blast_bin_dir is not None:
        for name in candidate_names:
            candidate = blast_bin_dir / name
            if candidate.is_file():
                return str(candidate.resolve())

    # 尝试复用项目内的 ToolConfig（相对包导入）
    try:
        from ...workbench.models.tool_config import ToolConfig  # type: ignore

        resolved = ToolConfig.resolve_bio_tool(tool_name)
        if resolved and Path(resolved).is_file():
            return str(Path(resolved).resolve())
    except Exception as exc:
        logger.debug("通过 ToolConfig 解析可执行文件失败 (%s): %s", tool_name, exc)

    found = shutil.which(tool_name)
    if found:
        return str(Path(found).resolve())

    raise FileNotFoundError(
        f"未找到 BLAST+ 可执行文件 '{tool_name}'，请确认 NCBI BLAST+ 已安装并加入 PATH，或通过 --blast-bin-dir 指定目录。"
    )


def build_shard_specs(
    target_records: list[TargetSequenceRecord],
    queries: list[QueryProteinRecord],
    config: SearchConfig,
    work_dir: Path,
) -> tuple[list[ShardSpec], dict[str, list[TargetSequenceRecord]], int, int]:
    """
    按分子类型（DNA / Protein）将目标序列切分为多个检索分片，
    同时计算全库有效残基规模（用于统一 -dbsize，保证分片 E-value 与全库一致）。
    """
    query_sig_src = "|".join(f"{q.safe_id}:{q.sha256_prefix}" for q in queries)
    base_param_sig = (
        f"q={hashlib.sha256(query_sig_src.encode('utf-8')).hexdigest()[:16]}"
        f"|be={config.blast_evalue}|mts={config.max_target_seqs}|gc={config.db_gencode}"
    )

    dna_by_file: dict[str, list[TargetSequenceRecord]] = {}
    prot_by_file: dict[str, list[TargetSequenceRecord]] = {}
    total_dna_bases = 0
    total_prot_residues = 0

    for rec in target_records:
        if rec.kind == "dna":
            dna_by_file.setdefault(rec.rel_path, []).append(rec)
            total_dna_bases += rec.length
        elif rec.kind == "protein":
            prot_by_file.setdefault(rec.rel_path, []).append(rec)
            total_prot_residues += rec.length

    shards_dir = work_dir / "shards"
    shards_dir.mkdir(parents=True, exist_ok=True)

    specs: list[ShardSpec] = []
    shard_record_map: dict[str, list[TargetSequenceRecord]] = {}

    def _pack_groups(
        grouped: dict[str, list[TargetSequenceRecord]],
        db_type: str,
        program: str,
        prefix: str,
    ) -> None:
        sorted_paths = sorted(grouped.keys(), key=str.lower)
        cur_paths: list[str] = []
        cur_recs: list[TargetSequenceRecord] = []
        cur_res = 0
        shard_idx = 0

        def _flush() -> None:
            nonlocal shard_idx, cur_paths, cur_recs, cur_res
            if not cur_recs:
                return
            shard_idx += 1
            shard_id = f"{prefix}_{shard_idx:03d}"
            file_sigs = []
            for rp in cur_paths:
                f_path = grouped[rp][0].abs_path
                st = f_path.stat()
                file_sigs.append(f"{rp}:{st.st_size}:{st.st_mtime_ns}")
            fp_input = (
                f"{base_param_sig}|prog={program}|dna_tot={total_dna_bases}"
                f"|prot_tot={total_prot_residues}|files={'|'.join(file_sigs)}"
            )
            fingerprint = hashlib.sha256(fp_input.encode("utf-8")).hexdigest()[:20]
            fasta_path = shards_dir / f"{shard_id}.fasta"
            hit_tsv_path = shards_dir / f"{shard_id}.hits.tsv"
            spec = ShardSpec(
                shard_id=shard_id,
                db_type=db_type,  # type: ignore[arg-type]
                program=program,  # type: ignore[arg-type]
                rel_paths=tuple(cur_paths),
                record_count=len(cur_recs),
                total_residues=cur_res,
                fingerprint=fingerprint,
                fasta_path=fasta_path,
                hit_tsv_path=hit_tsv_path,
            )
            specs.append(spec)
            shard_record_map[shard_id] = list(cur_recs)
            cur_paths = []
            cur_recs = []
            cur_res = 0

        for rp in sorted_paths:
            recs = grouped[rp]
            file_res = sum(r.length for r in recs)
            exceed_files = len(cur_paths) >= config.shard_max_files
            exceed_res = cur_res > 0 and (cur_res + file_res > config.shard_max_residues)
            if cur_paths and (exceed_files or exceed_res):
                _flush()
            cur_paths.append(rp)
            cur_recs.extend(recs)
            cur_res += file_res

        _flush()

    _pack_groups(dna_by_file, "nucl", "tblastn", "dna_shard")
    _pack_groups(prot_by_file, "prot", "blastp", "prot_shard")

    return specs, shard_record_map, total_dna_bases, total_prot_residues


class CheckpointStore:
    """线程安全的原子落盘 Checkpoint 管理器（UTF-8 JSON）。"""

    def __init__(self, checkpoint_path: Path) -> None:
        self.checkpoint_path = checkpoint_path
        self._lock = threading.Lock()
        self._data: dict[str, Any] = {"version": 1, "shards": {}}
        if checkpoint_path.is_file():
            try:
                loaded = json.loads(checkpoint_path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict) and isinstance(loaded.get("shards"), dict):
                    self._data = loaded
            except Exception:
                self._data = {"version": 1, "shards": {}}

    def is_completed(self, spec: ShardSpec) -> bool:
        with self._lock:
            entry = self._data["shards"].get(spec.shard_id)
            if not entry:
                return False
            return (
                entry.get("status") == "completed"
                and entry.get("fingerprint") == spec.fingerprint
                and spec.hit_tsv_path.is_file()
            )

    def mark_completed(self, spec: ShardSpec, hit_count: int, elapsed_sec: float) -> None:
        with self._lock:
            self._data["shards"][spec.shard_id] = {
                "status": "completed",
                "fingerprint": spec.fingerprint,
                "program": spec.program,
                "record_count": spec.record_count,
                "hit_count": hit_count,
                "hit_tsv": spec.hit_tsv_path.name,
                "elapsed_sec": round(elapsed_sec, 4),
            }
            self._atomic_save()

    def mark_failed(self, spec: ShardSpec, error_msg: str) -> None:
        with self._lock:
            self._data["shards"][spec.shard_id] = {
                "status": "failed",
                "fingerprint": spec.fingerprint,
                "program": spec.program,
                "error": error_msg,
            }
            self._atomic_save()

    def _atomic_save(self) -> None:
        self.checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.checkpoint_path.with_suffix(".json.tmp")
        tmp_path.write_text(
            json.dumps(self._data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(tmp_path, self.checkpoint_path)


def _cleanup_shard_temp_files(shard_work_dir: Path) -> None:
    """清理分片临时建库索引文件，仅保留落盘命中表。"""
    if shard_work_dir.exists():
        shutil.rmtree(shard_work_dir, ignore_errors=True)


def _needs_ascii_no_space_fallback(path_str: str) -> bool:
    """检查路径是否仍包含空格或非 ASCII 字符（Windows BLAST+ 内存映射高风险）。"""
    return (" " in path_str) or (not path_str.isascii())


def _run_single_shard(
    spec: ShardSpec,
    shard_records: list[TargetSequenceRecord],
    query_fasta_abs: Path,
    config: SearchConfig,
    makeblastdb_bin: str,
    blast_bin: str,
    threads: int,
    effective_dbsize: int,
    checkpoint: CheckpointStore,
) -> tuple[str, int, float]:
    """执行单个分片的建库、BLAST 检索、原子落盘与临时索引清理。"""
    t0 = time.perf_counter()
    preferred_dir = spec.fasta_path.parent / f"_tmp_{spec.shard_id}"
    preferred_dir.mkdir(parents=True, exist_ok=True)
    preferred_short = get_windows_short_path(preferred_dir)

    temp_fallback_dir: Path | None = None
    if _needs_ascii_no_space_fallback(preferred_short):
        temp_fallback_dir = Path(tempfile.mkdtemp(prefix=f"pblast_{spec.shard_id}_"))
        shard_work_dir = temp_fallback_dir
        run_cwd = get_windows_short_path(shard_work_dir)
    else:
        shard_work_dir = preferred_dir
        run_cwd = preferred_short

    try:
        local_subject = shard_work_dir / "subject.fasta"
        write_shard_fasta(shard_records, local_subject)

        db_prefix = "shard_db"
        short_makeblastdb = get_windows_short_path(Path(makeblastdb_bin))
        short_blast = get_windows_short_path(Path(blast_bin))
        short_query = get_windows_short_path(query_fasta_abs)
        if _needs_ascii_no_space_fallback(short_query):
            local_query = shard_work_dir / "query.fasta"
            shutil.copy2(query_fasta_abs, local_query)
            query_arg = local_query.name
        else:
            query_arg = short_query

        mk_cmd = [
            short_makeblastdb,
            "-in",
            local_subject.name,
            "-dbtype",
            spec.db_type,
            "-blastdb_version",
            "4",
            "-out",
            db_prefix,
        ]
        mk_proc = subprocess.run(
            mk_cmd,
            cwd=run_cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=600,
        )
        if mk_proc.returncode != 0:
            raise RuntimeError(
                f"makeblastdb 失败 (shard={spec.shard_id}, code={mk_proc.returncode}): "
                f"{mk_proc.stderr.strip() or mk_proc.stdout.strip()}"
            )

        tmp_out = shard_work_dir / "hits.raw.tsv"
        blast_cmd = [
            short_blast,
            "-query",
            query_arg,
            "-db",
            db_prefix,
            "-out",
            tmp_out.name,
            "-outfmt",
            BLAST_OUTFMT_SPEC,
            "-evalue",
            str(config.blast_evalue),
            "-max_target_seqs",
            str(config.max_target_seqs),
            "-num_threads",
            str(threads),
        ]
        if effective_dbsize > 0:
            blast_cmd.extend(["-dbsize", str(effective_dbsize)])
        if spec.program == "tblastn":
            blast_cmd.extend(["-db_gencode", str(config.db_gencode)])

        bl_proc = subprocess.run(
            blast_cmd,
            cwd=run_cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=1800,
        )
        if bl_proc.returncode != 0:
            raise RuntimeError(
                f"{spec.program} 失败 (shard={spec.shard_id}, code={bl_proc.returncode}): "
                f"{bl_proc.stderr.strip() or bl_proc.stdout.strip()}"
            )

        # 原子写入最终分片命中文件（带 program 前缀列）
        hit_count = 0
        tmp_final = spec.hit_tsv_path.with_suffix(".tsv.tmp")
        with (
            tmp_out.open("r", encoding="utf-8", errors="replace") as src_f,
            tmp_final.open("w", encoding="utf-8", newline="\n") as dst_f,
        ):
            for line in src_f:
                stripped = line.strip()
                if not stripped:
                    continue
                dst_f.write(f"{spec.program}\t{stripped}\n")
                hit_count += 1
        os.replace(tmp_final, spec.hit_tsv_path)

        elapsed = time.perf_counter() - t0
        checkpoint.mark_completed(spec, hit_count=hit_count, elapsed_sec=elapsed)
        return spec.shard_id, hit_count, elapsed
    except Exception as exc:
        checkpoint.mark_failed(spec, str(exc))
        raise
    finally:
        if config.clean_temp_db:
            _cleanup_shard_temp_files(preferred_dir)
            if temp_fallback_dir is not None:
                _cleanup_shard_temp_files(temp_fallback_dir)


def execute_sharded_blast(
    specs: list[ShardSpec],
    shard_record_map: dict[str, list[TargetSequenceRecord]],
    query_fasta_abs: Path,
    config: SearchConfig,
    checkpoint_path: Path,
    total_dna_bases: int,
    total_prot_residues: int,
) -> tuple[int, int, int]:
    """
    多核并发执行全部分片 BLAST 检索，支持 Checkpoint 断点续跑。
    返回: (resumed_count, executed_count, max_workers_used)
    """
    checkpoint = CheckpointStore(checkpoint_path)
    pending_specs: list[ShardSpec] = []
    resumed_count = 0

    for spec in specs:
        if config.resume and checkpoint.is_completed(spec):
            resumed_count += 1
        else:
            pending_specs.append(spec)

    if not pending_specs:
        return resumed_count, 0, 0

    makeblastdb_bin = resolve_blast_executable("makeblastdb", config.blast_bin_dir)
    needed_programs = {s.program for s in pending_specs}
    program_bins = {
        prog: resolve_blast_executable(prog, config.blast_bin_dir)
        for prog in needed_programs
    }

    max_workers, threads_per_worker = compute_parallel_plan(
        num_shards=len(pending_specs),
        requested_threads=config.threads,
    )

    # tblastn 的 -dbsize 使用翻译后等效氨基酸长度，blastp 使用总蛋白残基数
    dna_effective_dbsize = max(1, total_dna_bases // 3) if total_dna_bases > 0 else 0
    prot_effective_dbsize = total_prot_residues

    errors: list[Exception] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = []
        for spec in pending_specs:
            eff_dbsize = (
                dna_effective_dbsize if spec.program == "tblastn" else prot_effective_dbsize
            )
            futures.append(
                executor.submit(
                    _run_single_shard,
                    spec,
                    shard_record_map[spec.shard_id],
                    query_fasta_abs,
                    config,
                    makeblastdb_bin,
                    program_bins[spec.program],
                    threads_per_worker,
                    eff_dbsize,
                    checkpoint,
                )
            )
        for fut in concurrent.futures.as_completed(futures):
            try:
                fut.result()
            except Exception as exc:
                errors.append(exc)

    if errors:
        raise RuntimeError(f"分片 BLAST 执行出现 {len(errors)} 个错误，首个错误: {errors[0]}")

    return resumed_count, len(pending_specs), max_workers
