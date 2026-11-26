# -*- coding: utf-8 -*-
"""
Contig 真实测序深度回溯与 Manifest 补全工具
职责：
1. 动态定位组装任务对应的清洗后或原始测序 FASTQ 文件；
2. 通过 minimap2 (或 canonical 21-mer 采样降级) 流式计算每条 Contig 真实测序深度；
3. 将补全后的 per-contig 深度与汇总指标原子持久化写入 assembly_manifest.json。
"""

import gzip
import json
import logging
import os
import shutil
import subprocess
from ...utils.resource_guard import get_safe_cpu_budget
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .path_resolver import get_candidate_safe_work_dirs

logger = logging.getLogger("Assembly.ContigDepth")

_COMPLEMENT_TRANS = str.maketrans("ACGT", "TGCA")
_NO_READS_CACHE: Dict[Tuple[str, float], bool] = {}


def clear_depth_cache() -> None:
    """清空无读段/失败任务的内存负缓存（主要用于测试隔离）"""
    _NO_READS_CACHE.clear()


def _to_wsl_path(path_str: str) -> str:
    abs_path = os.path.abspath(path_str).replace("\\", "/")
    if len(abs_path) >= 2 and abs_path[1] == ":":
        return f"/mnt/{abs_path[0].lower()}" + abs_path[2:]
    return abs_path


def _get_safe_threads(threads: Optional[int] = None) -> int:
    """至少保留 2 个 CPU 核心防止主机卡死"""
    return get_safe_cpu_budget(requested=int(threads) if threads is not None and threads > 0 else 0, reserve_cores=2)


def _valid_file(path_candidate: Optional[Any]) -> Optional[Path]:
    if not path_candidate:
        return None
    try:
        p = Path(str(path_candidate))
        if p.exists() and p.is_file() and p.stat().st_size > 0:
            return p
    except OSError:
        return None
    return None


def _pick_paired_in_dir(base_dir: Path, names: List[Tuple[str, str]]) -> Tuple[Optional[Path], Optional[Path]]:
    if not base_dir.exists():
        return None, None
    for f1_name, f2_name in names:
        p1 = _valid_file(base_dir / f1_name)
        p2 = _valid_file(base_dir / f2_name)
        if p1 and p2:
            return p1, p2
    return None, None


def find_task_reads(
    task_dir: Path,
    task_id: str,
    manifest_data: Optional[Dict[str, Any]] = None,
    task_config: Optional[Dict[str, Any]] = None,
) -> Tuple[Optional[Path], Optional[Path], Optional[Path]]:
    """
    多级动态定位组装任务可用的测序读段文件。
    返回: (r1_path, r2_path, long_reads_path)
    """
    r1: Optional[Path] = None
    r2: Optional[Path] = None
    lr: Optional[Path] = None

    # 1. 任务结果目录内 qc/ 下的质控产物
    qc_pairs = [
        ("clean_1.fq.gz", "clean_2.fq.gz"),
        ("clean_1.fastq.gz", "clean_2.fastq.gz"),
        ("clean_1.fq", "clean_2.fq"),
        ("clean_1.fastq", "clean_2.fastq"),
    ]
    qc_dirs = [
        task_dir / "assemblerstep" / "assembly_run" / "qc",
        task_dir / "assembly_run" / "qc",
        task_dir / "qc",
    ]
    safe_work_dirs = get_candidate_safe_work_dirs(task_id)
    for sw in safe_work_dirs:
        qc_dirs.append(sw / "qc")

    for qd in qc_dirs:
        p1, p2 = _pick_paired_in_dir(qd, qc_pairs)
        if p1:
            r1, r2 = p1, p2
            break

    # 2. 安全隔离工作目录下的 input_r1 / input_r2 / input_lr
    if not r1:
        input_pairs = [
            ("input_r1.fq.gz", "input_r2.fq.gz"),
            ("input_r1.fastq.gz", "input_r2.fastq.gz"),
            ("input_r1.fq", "input_r2.fq"),
            ("input_r1.fastq", "input_r2.fastq"),
        ]
        for sw in safe_work_dirs:
            p1, p2 = _pick_paired_in_dir(sw, input_pairs)
            if p1:
                r1, r2 = p1, p2
                break
            for single_name in ("input_r1.fq.gz", "input_r1.fastq.gz", "input_r1.fq", "input_r1.fastq"):
                cand = _valid_file(sw / single_name)
                if cand:
                    r1 = cand
                    break
            if r1:
                break

    for sw in safe_work_dirs:
        if not lr:
            for lr_name in ("input_lr.fq.gz", "input_lr.fastq.gz", "input_lr.fq", "input_lr.fastq"):
                cand = _valid_file(sw / lr_name)
                if cand:
                    lr = cand
                    break

    # 3. Manifest 声明路径
    if manifest_data and isinstance(manifest_data, dict):
        if not r1:
            r1 = _valid_file(manifest_data.get("clean_fastq1")) or _valid_file(manifest_data.get("input_fastq1"))
        if not r2:
            r2 = _valid_file(manifest_data.get("clean_fastq2")) or _valid_file(manifest_data.get("input_fastq2"))
        if not lr:
            lr = _valid_file(manifest_data.get("input_long_reads")) or _valid_file(manifest_data.get("input_fastq"))

    # 4. 任务配置声明路径
    if task_config and isinstance(task_config, dict):
        params = task_config.get("params") if isinstance(task_config.get("params"), dict) else {}
        if not r1:
            r1 = _valid_file(task_config.get("r1")) or _valid_file(params.get("r1"))
        if not r2:
            r2 = _valid_file(task_config.get("r2")) or _valid_file(params.get("r2"))
        if not lr:
            lr = _valid_file(task_config.get("long_reads")) or _valid_file(params.get("long_reads"))

    if r1 and r2 and r1.resolve() == r2.resolve():
        r2 = None

    return r1, r2, lr


def _read_fasta_records(fasta_path: Path) -> List[Tuple[str, str]]:
    records: List[Tuple[str, str]] = []
    if not fasta_path.exists():
        return records
    cur_name = ""
    cur_parts: List[str] = []
    with open(fasta_path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            s = line.strip()
            if not s:
                continue
            if s.startswith(">"):
                if cur_name and cur_parts:
                    records.append((cur_name, "".join(cur_parts).upper()))
                cur_name = s[1:].split()[0]
                cur_parts = []
            else:
                cur_parts.append(s)
        if cur_name and cur_parts:
            records.append((cur_name, "".join(cur_parts).upper()))
    return records


def _check_minimap2_available() -> bool:
    try:
        if os.name == "nt":
            res = subprocess.run(
                ["wsl", "which", "minimap2"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=10,
            )
            return res.returncode == 0
        return shutil.which("minimap2") is not None
    except Exception:
        return False


def _estimate_depths_minimap2(
    asm_fasta: Path,
    contig_lens: Dict[str, int],
    r1: Optional[Path],
    r2: Optional[Path],
    long_reads: Optional[Path],
    threads: int,
) -> Tuple[Dict[str, float], str]:
    read_files: List[Path] = []
    if r1 and r1.exists():
        preset = "sr"
        source = "minimap2_sr"
        read_files.append(r1)
        if r2 and r2.exists() and r2.resolve() != r1.resolve():
            read_files.append(r2)
    elif long_reads and long_reads.exists():
        preset = "map-ont"
        source = "minimap2_lr"
        read_files.append(long_reads)
    else:
        return {}, "none"

    if os.name == "nt":
        cmd = [
            "wsl",
            "minimap2",
            "-x",
            preset,
            "-t",
            str(threads),
            "--secondary=no",
            _to_wsl_path(str(asm_fasta)),
            *[_to_wsl_path(str(p)) for p in read_files],
        ]
    else:
        cmd = [
            "minimap2",
            "-x",
            preset,
            "-t",
            str(threads),
            "--secondary=no",
            str(asm_fasta),
            *[str(p) for p in read_files],
        ]

    covered_bases: Dict[str, int] = defaultdict(int)
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        encoding="utf-8",
        errors="ignore",
    )
    assert proc.stdout is not None
    for line in proc.stdout:
        parts = line.split("\t")
        if len(parts) < 11:
            continue
        tname = parts[5]
        if tname not in contig_lens:
            continue
        try:
            t_start = int(parts[7])
            t_end = int(parts[8])
        except ValueError:
            continue
        if t_end > t_start:
            covered_bases[tname] += t_end - t_start

    ret = proc.wait()
    if ret != 0:
        return {}, "failed"

    depths = {
        name: round(covered_bases.get(name, 0) / max(1, length), 1)
        for name, length in contig_lens.items()
    }
    return depths, source


def _canonical_kmer(kmer: str) -> str:
    rc = kmer.translate(_COMPLEMENT_TRANS)[::-1]
    return kmer if kmer <= rc else rc


def _estimate_depths_kmer(
    records: List[Tuple[str, str]],
    r1: Optional[Path],
    r2: Optional[Path],
    long_reads: Optional[Path],
    fastp_total_bases: int = 0,
) -> Tuple[Dict[str, float], str]:
    candidate_files: List[Path] = []
    seen_abs = set()
    for p in (r1, r2, long_reads):
        if p and p.exists():
            ap = p.resolve()
            if ap not in seen_abs:
                seen_abs.add(ap)
                candidate_files.append(p)

    if not candidate_files or not records:
        return {}, "none"

    k = 21
    contig_kmers: Dict[str, List[str]] = {}
    target_kmers: Dict[str, int] = {}

    for name, seq in records:
        seq_len = len(seq)
        if seq_len < k:
            contig_kmers[name] = []
            continue
        stride = 1 if seq_len < 5000 else (5 if seq_len < 100000 else 11)
        km_list: List[str] = []
        for pos in range(0, seq_len - k + 1, stride):
            km = seq[pos : pos + k]
            if "N" not in km:
                ckm = _canonical_kmer(km)
                km_list.append(ckm)
                target_kmers[ckm] = 0
        contig_kmers[name] = km_list

    if not target_kmers:
        return {}, "none"

    max_reads_cap = 200000
    max_bases_cap = 30000000
    per_file_read_cap = max(1, max_reads_cap // len(candidate_files))
    per_file_base_cap = max(1, max_bases_cap // len(candidate_files))

    total_sampled_bases = 0
    estimated_total_bases = 0.0
    hit_cap = False

    for fpath in candidate_files:
        is_gz = fpath.name.lower().endswith(".gz")
        opener = gzip.open if is_gz else open
        file_reads = 0
        file_bases = 0
        file_bytes_read = 0
        file_size = fpath.stat().st_size

        try:
            with opener(fpath, "rt", encoding="utf-8", errors="ignore") as f:
                for idx, line in enumerate(f):
                    if not is_gz:
                        file_bytes_read += len(line.encode("utf-8", errors="ignore"))
                    if idx % 4 != 1:
                        continue
                    seq_up = line.strip().upper()
                    rlen = len(seq_up)
                    if rlen < k:
                        continue
                    file_reads += 1
                    file_bases += rlen
                    total_sampled_bases += rlen

                    r_stride = 7 if rlen > 500 else 1
                    for pos in range(0, rlen - k + 1, r_stride):
                        km = seq_up[pos : pos + k]
                        if "N" in km:
                            continue
                        ckm = _canonical_kmer(km)
                        if ckm in target_kmers:
                            target_kmers[ckm] += r_stride

                    if file_reads >= per_file_read_cap or file_bases >= per_file_base_cap:
                        hit_cap = True
                        break
        except Exception as _exc:
            logger.debug("读取测序文件统计深度时跳过异常文件: %s", _exc)
            continue

        if fastp_total_bases <= 0 and hit_cap and not is_gz and file_bytes_read > 0 and file_size > file_bytes_read:
            estimated_total_bases += file_bases * (file_size / float(file_bytes_read))
        else:
            estimated_total_bases += file_bases

    if total_sampled_bases <= 0:
        return {}, "none"

    effective_total_bases = float(fastp_total_bases) if fastp_total_bases > 0 else estimated_total_bases
    raw_hits: Dict[str, float] = {}
    weighted_hit_sum = 0.0
    for name, seq in records:
        kms = contig_kmers.get(name, [])
        if not kms:
            raw_hits[name] = 0.0
            continue
        avg_hit = sum(target_kmers[km] for km in kms) / float(len(kms))
        raw_hits[name] = avg_hit
        weighted_hit_sum += avg_hit * len(seq)

    if weighted_hit_sum <= 0.0:
        return {}, "none"

    scale_factor = effective_total_bases / weighted_hit_sum
    depths = {
        name: round(raw_hits[name] * scale_factor, 1)
        for name, _ in records
    }
    return depths, "kmer_estimated"


def estimate_contig_depths(
    asm_fasta: Path,
    r1: Optional[Path] = None,
    r2: Optional[Path] = None,
    long_reads: Optional[Path] = None,
    fastp_total_bases: int = 0,
    threads: Optional[int] = None,
) -> Tuple[Dict[str, float], str]:
    """
    计算每条 Contig 真实覆盖深度。
    优先使用 minimap2 流式比对；不可用时降级为流式 canonical 21-mer 采样估算。
    """
    records = _read_fasta_records(asm_fasta)
    if not records:
        return {}, "none"

    contig_lens = {name: len(seq) for name, seq in records}
    safe_threads = _get_safe_threads(threads)

    if _check_minimap2_available():
        depths, source = _estimate_depths_minimap2(
            asm_fasta=asm_fasta,
            contig_lens=contig_lens,
            r1=r1,
            r2=r2,
            long_reads=long_reads,
            threads=safe_threads,
        )
        if depths and any(v > 0.0 for v in depths.values()):
            return depths, source

    return _estimate_depths_kmer(
        records=records,
        r1=r1,
        r2=r2,
        long_reads=long_reads,
        fastp_total_bases=fastp_total_bases,
    )


def backfill_manifest_contig_depths(
    task_id: str,
    task_dir: Path,
    asm_fasta: Path,
    contigs: List[Dict[str, Any]],
    manifest_path: Optional[Path] = None,
    manifest_data: Optional[Dict[str, Any]] = None,
    task_config: Optional[Dict[str, Any]] = None,
    fastp_total_bases: int = 0,
) -> Optional[Tuple[Dict[str, float], str]]:
    """
    为缺少分片段深度的多片段组装任务计算真实 per-contig 深度，并原子写回 assembly_manifest.json。
    """
    if len(contigs) <= 1 or not asm_fasta.exists():
        return None

    try:
        cache_key = (str(asm_fasta.resolve()), asm_fasta.stat().st_mtime)
    except OSError:
        return None

    if cache_key in _NO_READS_CACHE:
        return None

    r1, r2, lr = find_task_reads(
        task_dir=task_dir,
        task_id=task_id,
        manifest_data=manifest_data,
        task_config=task_config,
    )
    if not r1 and not lr:
        _NO_READS_CACHE[cache_key] = True
        return None

    depths, source = estimate_contig_depths(
        asm_fasta=asm_fasta,
        r1=r1,
        r2=r2,
        long_reads=lr,
        fastp_total_bases=fastp_total_bases,
    )
    if not depths or not any(v > 0.0 for v in depths.values()):
        _NO_READS_CACHE[cache_key] = True
        return None

    target_mf = manifest_path or (asm_fasta.parent / "assembly_manifest.json")
    existing_mf: Dict[str, Any] = {}
    if isinstance(manifest_data, dict):
        existing_mf = dict(manifest_data)
    elif target_mf.exists() and target_mf.stat().st_size > 0:
        try:
            with open(target_mf, "r", encoding="utf-8") as mf:
                loaded = json.load(mf)
                if isinstance(loaded, dict):
                    existing_mf = loaded
        except Exception:
            existing_mf = {}

    sorted_contigs = sorted(contigs, key=lambda x: int(x.get("length", 0)), reverse=True)
    mf_contigs: List[Dict[str, Any]] = []
    total_len = 0
    weighted_depth_sum = 0.0
    weighted_gc_sum = 0.0
    any_circular = False

    for idx, c in enumerate(sorted_contigs, start=1):
        cname = str(c.get("name") or f"contig_{idx}")
        clen = int(c.get("length", 0))
        cgc = float(c.get("gc_percent") if c.get("gc_percent") is not None else c.get("gc", 0.0))
        ccirc = bool(c.get("is_circular", c.get("circular", False)))
        cdepth = round(float(depths.get(cname, c.get("depth", 0.0))), 1)

        total_len += clen
        weighted_depth_sum += cdepth * clen
        weighted_gc_sum += cgc * clen
        if ccirc:
            any_circular = True

        mf_contigs.append({
            "id": idx,
            "name": cname,
            "length": clen,
            "gc": round(cgc, 2),
            "circular": ccirc,
            "depth": cdepth,
        })

    lengths = [c["length"] for c in mf_contigs]
    half_len = total_len / 2.0
    cum_len = 0
    n50_val = 0
    for length in lengths:
        cum_len += length
        if cum_len >= half_len:
            n50_val = length
            break

    safe_total = max(1, total_len)
    existing_mf["total_contigs"] = len(mf_contigs)
    existing_mf["total_length_bp"] = total_len
    existing_mf["avg_depth"] = round(weighted_depth_sum / safe_total, 1) if total_len > 0 else 0.0
    existing_mf["n50"] = existing_mf.get("n50") or n50_val
    existing_mf["max_contig_length"] = existing_mf.get("max_contig_length") or (lengths[0] if lengths else 0)
    existing_mf["gc_percent"] = existing_mf.get("gc_percent") or (round(weighted_gc_sum / safe_total, 2) if total_len > 0 else 0.0)
    existing_mf["is_circular"] = bool(existing_mf.get("is_circular") or any_circular)
    existing_mf["depth_source"] = source
    existing_mf["contigs"] = mf_contigs

    try:
        target_mf.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix=".manifest_", suffix=".json.tmp", dir=str(target_mf.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as tmp_f:
                json.dump(existing_mf, tmp_f, indent=2, ensure_ascii=False)
            os.replace(tmp_name, target_mf)
        except Exception:
            if os.path.exists(tmp_name):
                os.remove(tmp_name)
            raise
    except Exception as err:
        logger.warning(f"回写 assembly_manifest.json 失败 ({target_mf}): {err}")

    return depths, source
