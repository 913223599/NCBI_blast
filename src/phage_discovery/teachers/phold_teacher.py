# -*- coding: utf-8 -*-
"""
WSL2 GPU phold (ProstT5 3Di + Foldseek all_phold_structures) 结构同源离线教师模块：
1. 专门面向序列同源盲区（DIAMOND 与 MMseqs2 PHROGs 均未命中的暗物质 ORF）提取三维折叠结构语义；
2. 精确解析 `phold_per_cds_predictions.tsv` 中的 `phrog` 来源标识，严格区分真实噬菌体同源 (`phrog` 编号 / `acr`)
   与非噬菌体宿主耐药/毒力/防御/毒素-抗毒素结构 (`card` / `vfdb` / `defensefinder` / `netflax`)；
3. 全程强制使用本地缓存的 ProstT5_fp16（禁止联网下载额外权重），并实现分片落盘与 Checkpoint 断点保护。
"""
from __future__ import annotations

import csv
import gzip
import io
import logging
import os
from ...utils.resource_guard import get_safe_cpu_budget
import pickle
import shlex
import subprocess
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from .checkv_teacher import to_wsl_path
from .hmm_adversarial_teacher import _atomic_save_pickle_gz, default_project_db_root

logger = logging.getLogger("phage_discovery.teachers.phold_teacher")

HOST_ADVERSARIAL_SOURCES = frozenset({"card", "vfdb", "defensefinder", "netflax"})


def default_phold_db_dir() -> Path:
    """按相对路径定位默认 phold_db 目录。"""
    return default_project_db_root() / "phold_db"


def _classify_phold_source_type(phrog_val: str) -> str:
    pv = (phrog_val or "").strip().lower()
    if not pv or pv in {"no_phrog", "none", "nan"}:
        return "none"
    if pv.isdigit() or pv.startswith("phrog_"):
        return "phrog"
    for known in ("card", "vfdb", "defensefinder", "acr", "netflax"):
        if known in pv:
            return known
    return pv


def parse_phold_predictions_text(tsv_text: str) -> Dict[str, Dict[str, Any]]:
    """直接从 TSV 文本解析 phold 结构比对结果。"""
    out: Dict[str, Dict[str, Any]] = {}
    if not tsv_text or not tsv_text.strip():
        return out

    reader = csv.DictReader(io.StringIO(tsv_text), delimiter="\t")
    for row in reader:
        qid = str(row.get("cds_id", "")).strip()
        if not qid:
            continue
        phrog_raw = str(row.get("phrog", "")).strip()
        func_raw = str(row.get("function", "")).strip()
        prod_raw = str(row.get("product", "")).strip()
        conf_raw = str(row.get("annotation_confidence", "")).strip().lower()
        src_type = _classify_phold_source_type(phrog_raw)

        if src_type == "none" and func_raw.lower() in {"", "unknown function"}:
            continue

        try:
            bitscore = float(row.get("bitscore") or 0.0)
        except (TypeError, ValueError):
            bitscore = 0.0
        try:
            evalue = float(row.get("evalue") or 1.0)
        except (TypeError, ValueError):
            evalue = 1.0
        try:
            prostt5_conf = float(row.get("prostt5_confidence") or 0.0)
        except (TypeError, ValueError):
            prostt5_conf = 0.0

        out[qid] = {
            "source_type": src_type,
            "phrog": phrog_raw,
            "function": func_raw,
            "product": prod_raw,
            "confidence": conf_raw,
            "bitscore": bitscore,
            "evalue": evalue,
            "prostt5_confidence": prostt5_conf,
            "tophit_protein": str(row.get("tophit_protein", "")).strip(),
        }
    return out


def parse_phold_predictions_tsv(tsv_path: Path) -> Dict[str, Dict[str, Any]]:
    """解析 phold_per_cds_predictions.tsv 文件。"""
    path = Path(tsv_path)
    if not path.is_file():
        return {}
    return parse_phold_predictions_text(path.read_text(encoding="utf-8", errors="replace"))


def _split_aa_by_length_buckets(
    valid_items: Sequence[Tuple[str, str]],
    *,
    base_batch_size: int = 24,
) -> List[Tuple[str, int, List[Tuple[str, str]]]]:
    """
    按氨基酸序列长度分桶并匹配安全 batch_size，避免 Transformer O(L^2) padding 膨胀触发 8GB 显存溢出。
    """
    short_b = [(q, a) for q, a in valid_items if len(a) <= 280]
    mid_b = [(q, a) for q, a in valid_items if 280 < len(a) <= 450]
    long_b = [(q, a) for q, a in valid_items if len(a) > 450]
    buckets: List[Tuple[str, int, List[Tuple[str, str]]]] = []
    if short_b:
        buckets.append(("short", max(1, int(base_batch_size)), sorted(short_b, key=lambda x: len(x[1]))))
    if mid_b:
        buckets.append(("mid", max(1, min(12, int(base_batch_size) // 2 or 8)), sorted(mid_b, key=lambda x: len(x[1]))))
    if long_b:
        buckets.append(("long", max(1, min(6, int(base_batch_size) // 4 or 4)), sorted(long_b, key=lambda x: len(x[1]))))
    return buckets


def run_phold_batch_wsl(
    aa_items: Sequence[Tuple[str, str]],
    *,
    db_dir: Optional[Path] = None,
    batch_size: int = 24,
    max_aa_len: int = 600,
    threads: Optional[int] = None,
    evalue_cutoff: float = 1e-3,
    timeout_sec: int = 7200,
) -> Dict[str, Dict[str, Any]]:
    """
    在 WSL 中对一批蛋白序列运行单次 `phold proteins-predict`（内置长度排序与 max_residues=5000 动态控批）+ `phold proteins-compare`。
    强制使用本地缓存 ProstT5_fp16，并限制 max_aa_len 与 --batch_size 严控 8GB 物理显存红线、避免重复加载模型开销。
    """
    valid_items = []
    for qid, aa in aa_items:
        cleaned = (aa or "").strip().rstrip("*")
        if cleaned and "*" not in cleaned and 25 <= len(cleaned) <= int(max_aa_len):
            valid_items.append((qid, cleaned))
    if not valid_items:
        return {}

    resolved_db = Path(db_dir).resolve() if db_dir is not None else default_phold_db_dir()
    if not resolved_db.exists():
        raise FileNotFoundError(f"phold_db 目录不存在: {resolved_db}")
    wsl_db = to_wsl_path(resolved_db)

    n_threads = get_safe_cpu_budget(requested=int(threads) if threads is not None else 0, reserve_cores=4)
    stage = f"/tmp/phold_stage_{os.getpid()}_{int(time.time() * 1000)}"

    # 按长度降序预排序后再写入 FASTA（配合 phold 内部 max_residues=5000 进一步降低 padding 与显存波动）
    sorted_items = sorted(valid_items, key=lambda x: len(x[1]), reverse=True)
    full_fasta = "".join(f">{qid}\n{aa}\n" for qid, aa in sorted_items)
    subprocess.run(
        ["wsl", "bash", "-c", f"set -e; mkdir -p {stage}; cat > {stage}/input.faa"],
        input=full_fasta,
        text=True,
        encoding="utf-8",
        check=True,
        timeout=timeout_sec,
    )

    try:
        db_q = shlex.quote(wsl_db)
        db_link = f"{stage}/phold_db_link"
        cmd = (
            f"set -e; "
            f"ln -sfn {db_q} {db_link}; "
            f"phold proteins-predict -i {stage}/input.faa -o {stage}/pred -d {db_link} "
            f"--batch_size {max(1, int(batch_size))} -t {n_threads} -f 1>&2; "
            f"phold proteins-compare -i {stage}/input.faa --predictions_dir {stage}/pred "
            f"-o {stage}/cmp -d {db_link} -t {n_threads} -e {float(evalue_cutoff)} -f 1>&2; "
            f"cat {stage}/cmp/phold_per_cds_predictions.tsv"
        )
        res = subprocess.run(
            ["wsl", "bash", "-c", cmd],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_sec,
        )
        if res.returncode != 0:
            raise RuntimeError(f"phold WSL 运行失败 (exit={res.returncode}): {res.stderr[-800:]}")

        return parse_phold_predictions_text(res.stdout or "")
    finally:
        subprocess.run(
            ["wsl", "bash", "-c", f"rm -rf {shlex.quote(stage)}"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=60,
        )


def run_chunked_phold_teacher(
    aa_items: Sequence[Tuple[str, str]],
    cache_path: Path,
    *,
    db_dir: Optional[Path] = None,
    chunk_size: int = 5000,
    batch_size: int = 24,
    max_aa_len: int = 600,
    threads: Optional[int] = None,
    evalue_cutoff: float = 1e-3,
    chunk_runner: Optional[Callable[..., Dict[str, Dict[str, Any]]]] = None,
) -> Dict[str, Any]:
    """
    分片落盘 + Checkpoint 断点保护运行 phold 结构教师扫描。
    返回格式：{"done_chunks": int, "chunk_size": int, "total_items": int, "hits": {qid: {...}}}
    """
    cache = Path(cache_path)
    state: Dict[str, Any] = {
        "done_chunks": 0,
        "chunk_size": int(chunk_size),
        "total_items": len(aa_items),
        "hits": {},
    }
    if cache.exists():
        with gzip.open(cache, "rb") as fh:
            loaded = pickle.load(fh)
        if isinstance(loaded, dict) and "hits" in loaded:
            state = loaded

    eff_chunk = max(1, int(state.get("chunk_size", chunk_size)))
    total_chunks = (len(aa_items) + eff_chunk - 1) // eff_chunk
    runner = chunk_runner or run_phold_batch_wsl

    for ci in range(int(state.get("done_chunks", 0)), total_chunks):
        sub = list(aa_items[ci * eff_chunk:(ci + 1) * eff_chunk])
        t0 = time.perf_counter()
        sub_hits = runner(
            sub,
            db_dir=db_dir,
            batch_size=batch_size,
            max_aa_len=max_aa_len,
            threads=threads,
            evalue_cutoff=evalue_cutoff,
        )
        state["hits"].update(sub_hits)
        state["done_chunks"] = ci + 1
        state["chunk_size"] = eff_chunk
        state["total_items"] = len(aa_items)
        _atomic_save_pickle_gz(cache, state)
        logger.info(
            "phold Teacher chunk %d/%d 完成: 本批结构召回 %d/%d 条, 累计命中 %d 条, 耗时 %.2fs",
            ci + 1,
            total_chunks,
            len(sub_hits),
            len(sub),
            len(state["hits"]),
            time.perf_counter() - t0,
        )

    return state
