# -*- coding: utf-8 -*-
"""
WSL2 pyhmmer 多核并行对抗/防御/病毒域离线 HMM 教师模块：
1. 优先通过相对项目路径定位本地 database 目录（不写死绝对盘符），并发调用 pyhmmer 扫描：
   - defense_finder: DefenseFinder 细菌防御系统 HMMs（识别宿主防御岛硬负例）
   - dbapis: dbAPIS 噬菌体 Anti-CRISPR / 反防御 HMMs（强化真实噬菌体对抗信号）
   - vs2_pfam_vir / vs2_pfam_bac / vs2_viral: VirSorter2 病毒与细菌域 Pfam/HMM
2. 全程支持分片落盘与 Checkpoint 断点保护（.tmp 原子替换），适当保留 CPU 核心防止主机卡死。
"""
from __future__ import annotations

import gzip
import json
import logging
import os
import pickle
from ...utils.resource_guard import get_safe_cpu_budget
import shlex
import subprocess
import time
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Sequence, Tuple

from .checkv_teacher import to_wsl_path

logger = logging.getLogger("phage_discovery.teachers.hmm_adversarial_teacher")


def _atomic_save_pickle_gz(path: Path, payload: Any) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(f".{target.name}.tmp.{os.getpid()}")
    with gzip.open(tmp, "wb") as fh:
        pickle.dump(payload, fh, protocol=pickle.HIGHEST_PROTOCOL)
    tmp.replace(target)


def default_project_db_root() -> Path:
    """按模块相对层级定位项目根目录下的 database 目录。"""
    return Path(__file__).resolve().parents[3] / "database"


def resolve_hmm_library_paths(
    db_root: Optional[Path] = None,
    wsl_vs2_hmm_dir: str = "/opt/virsorter2_db/hmm",
) -> Dict[str, Any]:
    """解析可用的本地 HMM 教师库路径配置（不依赖硬编码绝对路径）。"""
    root = Path(db_root).resolve() if db_root is not None else default_project_db_root()
    libs: Dict[str, Any] = {}

    dbapis = root / "phagescope" / "defense_systems" / "dbAPIS.hmm"
    if dbapis.is_file():
        libs["dbapis"] = dbapis

    df_profiles = root / "defense_finder" / "defense-finder-models" / "profiles"
    if df_profiles.is_dir():
        libs["defense_finder"] = df_profiles

    all_phrogs = root / "pharokka_db" / "all_phrogs.h3m"
    if all_phrogs.is_file():
        libs["all_phrogs"] = all_phrogs

    # WSL 侧可选 VirSorter2 HMM 目录描述（真正存在性与否由 WSL runner 校验）
    libs["wsl_vs2_pfam_vir"] = f"{wsl_vs2_hmm_dir.rstrip('/')}/pfam/Pfam-A-Viruses.hmm"
    libs["wsl_vs2_pfam_bac"] = f"{wsl_vs2_hmm_dir.rstrip('/')}/pfam/Pfam-A-Bacteria.hmm"
    libs["wsl_vs2_viral"] = f"{wsl_vs2_hmm_dir.rstrip('/')}/viral/combined.hmm"
    return libs


def _serialize_lib_specs_for_wsl(
    libs_cfg: Dict[str, Any],
    selected_libs: Sequence[str],
) -> Dict[str, str]:
    specs: Dict[str, str] = {}
    for name in selected_libs:
        val = libs_cfg.get(name)
        if val is None:
            continue
        if isinstance(val, Path):
            if val.exists():
                specs[name] = to_wsl_path(val)
        else:
            s_val = str(val)
            if s_val.startswith("/"):
                specs[name] = s_val
            elif Path(s_val).exists():
                specs[name] = to_wsl_path(Path(s_val))
    return specs


def run_pyhmmer_batch_wsl(
    aa_items: Sequence[Tuple[str, str]],
    libs_cfg: Dict[str, Any],
    *,
    selected_libs: Sequence[str] = ("dbapis", "defense_finder", "wsl_vs2_pfam_vir"),
    evalue_cutoff: float = 1e-5,
    cpus: Optional[int] = None,
    timeout_sec: int = 3600,
) -> Dict[str, Dict[str, Tuple[str, float, float]]]:
    """在 WSL 中调用 pyhmmer 并发扫描一批 (qid, aa_seq)，返回 {qid: {lib_name: (hmm_name, evalue, bitscore)}}。"""
    valid_items = []
    for qid, aa in aa_items:
        cleaned = (aa or "").strip().rstrip("*")
        if cleaned and "*" not in cleaned and len(cleaned) >= 15:
            valid_items.append((qid, cleaned))
    if not valid_items:
        return {}

    wsl_specs = _serialize_lib_specs_for_wsl(libs_cfg, selected_libs)
    if not wsl_specs:
        return {}

    n_cpus = get_safe_cpu_budget(requested=int(cpus) if cpus is not None else 0, reserve_cores=4)

    # 使用 Windows 临时文件传入 WSL 暂存区避免命令行过长及空格问题
    stage = f"/tmp/pyhmmer_stage_{os.getpid()}_{int(time.time() * 1000)}"
    runner_py = f"""
import glob, json, os, pyhmmer

stage = {json.dumps(stage)}
specs = {json.dumps(wsl_specs)}
e_cut = {float(evalue_cutoff)}
n_cpus = {int(n_cpus)}

abc = pyhmmer.easel.Alphabet.amino()
seqs = []
with open(os.path.join(stage, "input.faa"), "r", encoding="utf-8") as fh:
    cur_id = None
    buf = []
    for line in fh:
        line = line.strip()
        if not line:
            continue
        if line.startswith(">"):
            if cur_id is not None and buf:
                s = "".join(buf)
                seqs.append(pyhmmer.easel.TextSequence(name=cur_id.encode("utf-8"), sequence=s).digitize(abc))
            cur_id = line[1:].split()[0]
            buf = []
        else:
            buf.append(line)
    if cur_id is not None and buf:
        s = "".join(buf)
        seqs.append(pyhmmer.easel.TextSequence(name=cur_id.encode("utf-8"), sequence=s).digitize(abc))

out_hits = {{}}

def _iter_hmms(path_str):
    if os.path.isdir(path_str):
        for p in sorted(glob.glob(os.path.join(path_str, "*.hmm"))):
            with pyhmmer.plan7.HMMFile(p) as hf:
                for h in hf:
                    yield h
    elif os.path.isfile(path_str):
        with pyhmmer.plan7.HMMFile(path_str) as hf:
            for h in hf:
                yield h

if seqs:
    for lib_name, lib_path in specs.items():
        if not os.path.exists(lib_path):
            continue
        hmms = list(_iter_hmms(lib_path))
        if not hmms:
            continue
        for top_hits in pyhmmer.hmmsearch(hmms, seqs, cpus=n_cpus, E=e_cut):
            raw_qn = getattr(getattr(top_hits, "query", None), "name", None)
            q_hmm = raw_qn.decode("utf-8", errors="replace") if isinstance(raw_qn, bytes) else str(raw_qn or "unknown_hmm")
            for hit in top_hits:
                if not hit.included:
                    continue
                qid = hit.name.decode("utf-8", errors="replace") if isinstance(hit.name, bytes) else str(hit.name)
                ev = float(hit.evalue)
                bs = float(hit.score)
                if ev > e_cut:
                    continue
                per_q = out_hits.setdefault(qid, {{}})
                prev = per_q.get(lib_name)
                if prev is None or bs > prev[2]:
                    per_q[lib_name] = [q_hmm, ev, bs]

with open(os.path.join(stage, "hits.json"), "w", encoding="utf-8") as out_fh:
    json.dump(out_hits, out_fh)
"""
    # 在工作区外先将 FASTA 与 script 直接流式写入 WSL 阶段目录（避免污染 repo 或路径含空格）
    fasta_payload = "".join(f">{qid}\n{aa}\n" for qid, aa in valid_items)
    cmd_setup = f"set -e; mkdir -p {stage}; cat > {stage}/input.faa"
    subprocess.run(
        ["wsl", "bash", "-c", cmd_setup],
        input=fasta_payload,
        text=True,
        encoding="utf-8",
        check=True,
        timeout=timeout_sec,
    )
    try:
        cmd_run = f"set -e; cat > {stage}/run.py && python3 {stage}/run.py && cat {stage}/hits.json"
        res = subprocess.run(
            ["wsl", "bash", "-c", cmd_run],
            input=runner_py,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_sec,
        )
        if res.returncode != 0:
            raise RuntimeError(f"pyhmmer WSL 扫描失败 (exit={res.returncode}): {res.stderr[-800:]}")
        raw_hits = json.loads(res.stdout or "{}")
        return {
            qid: {lib: (str(val[0]), float(val[1]), float(val[2])) for lib, val in lib_map.items()}
            for qid, lib_map in raw_hits.items()
        }
    finally:
        subprocess.run(
            ["wsl", "bash", "-c", f"rm -rf {shlex.quote(stage)}"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=60,
        )


def run_chunked_hmm_teacher(
    aa_items: Sequence[Tuple[str, str]],
    cache_path: Path,
    *,
    libs_cfg: Optional[Dict[str, Any]] = None,
    selected_libs: Sequence[str] = ("dbapis", "defense_finder", "wsl_vs2_pfam_vir"),
    chunk_size: int = 25000,
    evalue_cutoff: float = 1e-5,
    cpus: Optional[int] = None,
    batch_runner: Optional[Callable[..., Dict[str, Dict[str, Any]]]] = None,
) -> Dict[str, Any]:
    """
    分片落盘 + Checkpoint 断点保护运行 HMM 教师扫描。
    返回格式：{"done_chunks": int, "chunk_size": int, "total_items": int, "hits": {qid: {lib: (name, evalue, bitscore)}}}
    """
    cfg = libs_cfg if libs_cfg is not None else resolve_hmm_library_paths()
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
    runner = batch_runner or run_pyhmmer_batch_wsl

    for ci in range(int(state.get("done_chunks", 0)), total_chunks):
        sub = list(aa_items[ci * eff_chunk:(ci + 1) * eff_chunk])
        t0 = time.perf_counter()
        sub_hits = runner(
            sub,
            cfg,
            selected_libs=selected_libs,
            evalue_cutoff=evalue_cutoff,
            cpus=cpus,
        )
        for qid, lib_map in sub_hits.items():
            cur = state["hits"].setdefault(qid, {})
            for lib_name, rec in lib_map.items():
                prev = cur.get(lib_name)
                if prev is None or float(rec[2]) > float(prev[2]):
                    cur[lib_name] = rec
        state["done_chunks"] = ci + 1
        state["chunk_size"] = eff_chunk
        state["total_items"] = len(aa_items)
        _atomic_save_pickle_gz(cache, state)
        logger.info(
            "HMM Teacher chunk %d/%d 完成: 本批命中 %d 条, 累计命中 %d 条, 耗时 %.2fs",
            ci + 1,
            total_chunks,
            len(sub_hits),
            len(state["hits"]),
            time.perf_counter() - t0,
        )

    return state

