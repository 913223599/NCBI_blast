# -*- coding: utf-8 -*-
"""
基因组组装指标解析、历史自愈与深度回填服务层

将原本耦合在 routes/assembly.py 中的 FASTA 流式解析、Manifest/FASTA 互补融合、
多 Contig 深度回填、历史指标自愈与单 Contig 提取下沉至单一职责服务模块。
"""

import asyncio
import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ...assembly.utils.contig_depth import backfill_manifest_contig_depths
from ...assembly.utils.path_resolver import get_candidate_safe_work_dirs

logger = logging.getLogger("Assembly.MetricsService")


def find_assembly_fasta(task_id: str, task_dir: Path) -> Optional[Path]:
    """多级智能定位 assembly.fasta 产物路径 (兼容 assemblerstep/assembly_run/工作盘等各类结构)"""
    candidates = [
        task_dir / "assemblerstep" / "assembly_run" / "assembly.fasta",
        task_dir / "assembly_run" / "assembly.fasta",
        task_dir / "assembly.fasta",
        task_dir / "assemblerstep" / "assembly.fasta",
    ]
    for sw_dir in get_candidate_safe_work_dirs(task_id):
        candidates.append(sw_dir / "assembly_run" / "assembly.fasta")
        candidates.append(sw_dir / "assembly.fasta")
    for c in candidates:
        if c.exists() and c.stat().st_size > 0:
            return c

    if task_dir.exists():
        found = list(task_dir.rglob("assembly.fasta"))
        if found and found[0].stat().st_size > 0:
            return found[0]
    return None


def _extract_contig_depth(c: Dict[str, Any]) -> Optional[float]:
    """从 manifest contig 条目中安全提取显式声明的测序深度（兼容 depth / mean_depth / coverage）"""
    for key in ("depth", "mean_depth", "coverage"):
        val = c.get(key)
        if val is not None:
            try:
                return float(val)
            except (TypeError, ValueError):
                continue
    return None


def _read_fastp_total_bases(task_id: str, task_dir: Path) -> int:
    search_dirs = [
        task_dir / "assemblerstep" / "assembly_run",
        task_dir / "assembly_run",
        task_dir,
        *get_candidate_safe_work_dirs(task_id),
    ]
    for s_dir in search_dirs:
        fj_path = s_dir / "qc" / "fastp.json"
        if not fj_path.exists():
            fj_path = s_dir / "fastp.json"
        if fj_path.exists():
            try:
                with open(fj_path, "r", encoding="utf-8") as fj:
                    cb = json.load(fj).get("summary", {}).get("after_filtering", {}).get("total_bases", 0)
                    if cb and int(cb) > 0:
                        return int(cb)
            except Exception as exc:
                logger.debug("读取 fastp.json 总碱基失败 (%s): %s", fj_path, exc)
                continue
    return 0


def parse_assembly_fasta_metrics(
    asm_fasta: Path,
    task_dir: Optional[Path] = None,
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """
    单遍流式解析 assembly.fasta 产物，精准提取全部 contigs 列表、N50、最大长度、全基因组加权 GC% 及深度指标
    """
    contigs: List[Dict[str, Any]] = []
    cur_h: Optional[str] = None
    cur_seq: List[str] = []

    def flush_c(h_str: str, s_parts: List[str]) -> None:
        if not h_str or not s_parts:
            return
        seq_str = "".join(s_parts)
        s_len = len(seq_str)
        if s_len == 0:
            return
        h_l = h_str.lower()
        c_n = h_str.split()[0].lstrip(">")
        d_m = re.search(r"(?:depth[=:]|cov[=_:]|coverage[=:])(\d+\.?\d*)", h_l)
        d_val = float(d_m.group(1)) if d_m else 0.0
        is_c = "circular=true" in h_l or "circular=y" in h_l or "topology=circular" in h_l or "_circular" in h_l
        gc_m = re.search(r"(?:gc[=:]|gc_percent[=:])(\d+\.?\d*)%?", h_l)
        if gc_m:
            gc_p = float(gc_m.group(1))
        else:
            s_up = seq_str.upper()
            gc_c = s_up.count("G") + s_up.count("C")
            gc_p = round((gc_c / s_len * 100.0), 2) if s_len > 0 else 0.0

        contigs.append({
            "name": c_n,
            "header": h_str.lstrip(">"),
            "length": s_len,
            "gc_percent": gc_p,
            "depth": d_val,
            "is_circular": is_c,
            "sequence": seq_str,
        })

    try:
        with open(asm_fasta, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                l_str = line.strip()
                if l_str.startswith(">"):
                    if cur_h:
                        flush_c(cur_h, cur_seq)
                    cur_h = l_str
                    cur_seq = []
                else:
                    cur_seq.append(l_str)
            if cur_h:
                flush_c(cur_h, cur_seq)
    except Exception as err:
        logger.warning(f"读取 FASTA 失败 ({asm_fasta}): {err}")
        return {}, []

    total_len = sum(c["length"] for c in contigs)
    safe_total_len = max(1, total_len)

    contigs.sort(key=lambda x: x["length"], reverse=True)
    for c in contigs:
        c["length_ratio"] = round((c["length"] / safe_total_len * 100.0), 1) if total_len > 0 else 0.0

    half_len = total_len / 2.0
    cum_len = 0
    n50_val = 0
    for c in contigs:
        cum_len += c["length"]
        if cum_len >= half_len:
            n50_val = c["length"]
            break

    avg_gc = round(sum(c["gc_percent"] * c["length"] for c in contigs) / safe_total_len, 2)
    avg_depth = round(sum(c["depth"] * c["length"] for c in contigs) / safe_total_len, 1)

    if avg_depth <= 0.0 and task_dir:
        cb = _read_fastp_total_bases(task_dir.name, task_dir)
        if cb > 0 and total_len > 0:
            avg_depth = round(cb / safe_total_len, 1)
            if len(contigs) == 1 and contigs[0]["depth"] <= 0.0:
                contigs[0]["depth"] = avg_depth

    stats = {
        "total_length": total_len,
        "contigs": len(contigs),
        "n50": n50_val,
        "gc_percent": avg_gc,
        "is_circular": any(c["is_circular"] for c in contigs),
        "avg_depth": avg_depth,
        "max_contig_length": contigs[0]["length"] if contigs else 0,
    }
    return stats, contigs


def heal_assembly_history_items(
    history: List[Dict[str, Any]],
    *,
    assembly_db_obj: Any,
    storage_cls: Any,
) -> List[Dict[str, Any]]:
    """遍历历史任务，自动重建损坏指标、补全最大 contig/深度并附加 fasta_path。"""
    for t in history:
        res = t.get("results")
        task_id = t["id"]
        t["task_id"] = task_id
        task_dir = storage_cls.get_task_dir(task_id)

        is_completed = t.get("status") == "completed"
        asm_fasta: Optional[Path] = None
        is_corrupted = (
            not res
            or not isinstance(res, dict)
            or res.get("total_length", 0) <= 0
            or res.get("gc_percent", 0.0) <= 0.0
            or res.get("n50", 0) <= 0
        )
        if is_completed and is_corrupted:
            asm_fasta = find_assembly_fasta(task_id, task_dir)
            if asm_fasta and asm_fasta.exists() and asm_fasta.stat().st_size > 0:
                s_recovered, _ = parse_assembly_fasta_metrics(asm_fasta, task_dir)
                if s_recovered.get("total_length", 0) > 0 and (
                    s_recovered.get("n50", 0) > 0 or s_recovered.get("gc_percent", 0.0) > 0.0
                ):
                    assembly_db_obj.update_task_metrics(
                        task_id,
                        total_length=int(s_recovered["total_length"]),
                        contig_count=int(s_recovered.get("contigs", 1)),
                        n50=int(s_recovered.get("n50", 0)),
                        gc_content=float(s_recovered.get("gc_percent", 0.0)),
                        is_circular=bool(s_recovered.get("is_circular", False)),
                        avg_depth=float(s_recovered.get("avg_depth", 0.0)),
                        max_contig_length=int(s_recovered.get("max_contig_length", 0)),
                    )
                    t["results"] = {
                        "total_length": s_recovered["total_length"],
                        "contigs": s_recovered["contigs"],
                        "n50": s_recovered["n50"],
                        "gc_percent": s_recovered["gc_percent"],
                        "is_circular": s_recovered["is_circular"],
                        "avg_depth": s_recovered["avg_depth"],
                        "max_contig_length": s_recovered["max_contig_length"],
                    }
                    res = t["results"]

        if isinstance(res, dict) and res.get("total_length", 0) > 0:
            need_update = False
            if not res.get("max_contig_length"):
                res["max_contig_length"] = res.get("n50") or res.get("total_length", 0)
                need_update = True
            if not res.get("avg_depth") or float(res.get("avg_depth", 0.0)) <= 0.0:
                cb = _read_fastp_total_bases(task_id, task_dir)
                if cb > 0 and res["total_length"] > 0:
                    res["avg_depth"] = round(cb / res["total_length"], 1)
                    need_update = True
            if need_update and (res.get("n50", 0) > 0 or res.get("gc_percent", 0.0) > 0.0):
                assembly_db_obj.update_task_metrics(
                    task_id,
                    total_length=res["total_length"],
                    contig_count=int(res.get("contigs") or 1),
                    n50=int(res.get("n50") or res["total_length"]),
                    gc_content=float(res.get("gc_percent") or 0.0),
                    is_circular=bool(res.get("is_circular", False)),
                    avg_depth=float(res.get("avg_depth") or 0.0),
                    max_contig_length=int(res.get("max_contig_length") or 0),
                )

        if is_completed and not t.get("fasta_path"):
            if asm_fasta is None:
                asm_fasta = find_assembly_fasta(task_id, task_dir)
            if asm_fasta and asm_fasta.exists() and asm_fasta.stat().st_size > 0:
                resolved_fa = str(asm_fasta)
                t["fasta_path"] = resolved_fa
                t["assembly_fasta"] = resolved_fa
                t["contigs_path"] = resolved_fa
    return history


def _load_assembly_manifest(task_id: str, task_dir: Path) -> Tuple[Optional[Dict[str, Any]], Optional[Path]]:
    search_dirs = [
        task_dir / "assemblerstep" / "assembly_run",
        task_dir / "assemblerstep",
        task_dir / "assembly_run",
        task_dir,
        *get_candidate_safe_work_dirs(task_id),
    ]
    for s_dir in search_dirs:
        mf_path = s_dir / "assembly_manifest.json"
        if mf_path.exists() and mf_path.stat().st_size > 0:
            try:
                with open(mf_path, "r", encoding="utf-8") as mf:
                    return json.load(mf), mf_path
            except Exception as exc:
                logger.debug("读取 assembly_manifest.json 失败 (%s): %s", mf_path, exc)
    return None, None


def _parse_manifest_payload(manifest_data: Dict[str, Any]) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    tot_bp = manifest_data.get("total_length_bp") or manifest_data.get("total_bp", 0)
    stats = {
        "total_length": tot_bp,
        "contigs": manifest_data.get("total_contigs", 0),
        "n50": manifest_data.get("n50", 0),
        "gc_percent": manifest_data.get("gc_percent", 0.0),
        "is_circular": bool(manifest_data.get("is_circular", False)),
        "avg_depth": float(manifest_data.get("avg_depth") or 0.0),
        "max_contig_length": manifest_data.get("max_contig_length", 0),
    }
    contig_list: List[Dict[str, Any]] = []
    for c in manifest_data.get("contigs", []):
        c_len = c.get("length", 0)
        ratio = round((c_len / float(tot_bp) * 100.0), 1) if tot_bp > 0 else 0.0
        raw_d = _extract_contig_depth(c)
        d_val = round(raw_d, 1) if raw_d is not None else 0.0
        d_header = f" depth={d_val}x" if d_val > 0 else ""
        gc_val = c.get("gc") if c.get("gc") is not None else c.get("gc_percent", 0.0)
        circ_val = bool(c.get("circular", c.get("is_circular", False)))
        contig_list.append({
            "name": c.get("name"),
            "header": f"{c.get('name')} length={c_len}{d_header}",
            "length": c_len,
            "gc_percent": gc_val,
            "depth": d_val,
            "is_circular": circ_val,
            "length_ratio": ratio,
            "sequence": c.get("sequence", ""),
        })
    return stats, contig_list


def _merge_fasta_metrics_into_result(
    stats: Dict[str, Any],
    contig_list: List[Dict[str, Any]],
    asm_fasta: Path,
    task_dir: Path,
) -> List[Dict[str, Any]]:
    f_stats, f_contigs = parse_assembly_fasta_metrics(asm_fasta, task_dir)
    if f_stats.get("total_length", 0) <= 0:
        return contig_list
    if len(contig_list) == 0:
        contig_list = f_contigs
    else:
        f_by_name = {fc["name"]: fc for fc in f_contigs if fc.get("name")}
        for c in contig_list:
            fc = f_by_name.get(c.get("name"))
            if fc:
                if not c.get("sequence"):
                    c["sequence"] = fc.get("sequence", "")
                if not c.get("gc_percent"):
                    c["gc_percent"] = fc.get("gc_percent", 0.0)
                if c.get("depth", 0.0) <= 0.0 and fc.get("depth", 0.0) > 0.0:
                    c["depth"] = fc["depth"]
    for key in ("total_length", "contigs", "n50", "max_contig_length"):
        if stats.get(key, 0) <= 0:
            stats[key] = f_stats[key]
    for key in ("gc_percent", "avg_depth"):
        if stats.get(key, 0.0) <= 0.0:
            stats[key] = f_stats[key]
    if not stats.get("is_circular"):
        stats["is_circular"] = f_stats["is_circular"]
    return contig_list


async def _backfill_multi_contig_depths(
    task_id: str,
    task: Dict[str, Any],
    task_dir: Path,
    asm_fasta: Path,
    contig_list: List[Dict[str, Any]],
    stats: Dict[str, Any],
    manifest_path: Optional[Path],
    manifest_data: Optional[Dict[str, Any]],
    depth_locks: Dict[str, asyncio.Lock],
) -> None:
    task_config = task.get("config")
    if isinstance(task_config, str):
        try:
            task_config = json.loads(task_config)
        except Exception as exc:
            logger.debug("解析 task_config JSON 失败 (%s): %s", task_id, exc)
            task_config = None
    fastp_bases = _read_fastp_total_bases(task_id, task_dir)
    lock = depth_locks.setdefault(task_id, asyncio.Lock())
    async with lock:
        target_mf_path = manifest_path or (asm_fasta.parent / "assembly_manifest.json")
        backfilled = None
        if target_mf_path.exists() and target_mf_path.stat().st_size > 0:
            try:
                with open(target_mf_path, "r", encoding="utf-8") as mf_check:
                    mf_latest = json.load(mf_check)
                if mf_latest.get("contigs") and any(
                    (_extract_contig_depth(item) or 0.0) > 0.0 for item in mf_latest["contigs"]
                ):
                    backfilled = (
                        {
                            item["name"]: round(float(_extract_contig_depth(item) or 0.0), 1)
                            for item in mf_latest["contigs"]
                            if item.get("name")
                        },
                        mf_latest.get("depth_source", "manifest"),
                    )
            except Exception as exc:
                logger.debug("校验最新 assembly_manifest.json 深度信息失败 (%s): %s", target_mf_path, exc)
        if backfilled is None:
            backfilled = await asyncio.to_thread(
                backfill_manifest_contig_depths,
                task_id,
                task_dir,
                asm_fasta,
                contig_list,
                target_mf_path,
                manifest_data,
                task_config if isinstance(task_config, dict) else None,
                fastp_bases,
            )
        if backfilled:
            depth_map, _source = backfilled
            for c in contig_list:
                cname = c.get("name")
                if cname and cname in depth_map:
                    d_val = round(float(depth_map[cname]), 1)
                    c["depth"] = d_val
                    if d_val > 0 and "depth=" not in str(c.get("header", "")):
                        c["header"] = f"{c.get('header', cname)} depth={d_val}x"
            tot_len_sum = sum(int(c.get("length", 0)) for c in contig_list)
            if tot_len_sum > 0:
                weighted_d = round(
                    sum(float(c.get("depth", 0.0)) * int(c.get("length", 0)) for c in contig_list) / tot_len_sum,
                    1,
                )
                if weighted_d > 0.0:
                    stats["avg_depth"] = weighted_d


async def build_assembly_result_payload(
    task_id: str,
    task: Dict[str, Any],
    task_dir: Path,
    *,
    assembly_db_obj: Any,
    depth_locks: Dict[str, asyncio.Lock],
) -> Dict[str, Any]:
    """融合 Manifest、FASTA 与异步深度回填，构建 /assembly/result/{task_id} 响应载荷。"""
    asm_fasta = find_assembly_fasta(task_id, task_dir)
    fasta_exists = asm_fasta is not None and asm_fasta.exists() and asm_fasta.stat().st_size > 0
    fasta_size_bytes = asm_fasta.stat().st_size if (fasta_exists and asm_fasta is not None) else 0

    stats: Dict[str, Any] = {}
    contig_list: List[Dict[str, Any]] = []
    manifest_data, manifest_path = _load_assembly_manifest(task_id, task_dir)
    if manifest_data:
        stats, contig_list = _parse_manifest_payload(manifest_data)

    need_fasta_parse = (
        len(contig_list) == 0
        or stats.get("n50", 0) <= 0
        or stats.get("gc_percent", 0.0) <= 0.0
        or any(not c.get("sequence") for c in contig_list)
    )
    if need_fasta_parse and fasta_exists and asm_fasta is not None:
        contig_list = _merge_fasta_metrics_into_result(stats, contig_list, asm_fasta, task_dir)

    if (
        len(contig_list) > 1
        and all(float(c.get("depth", 0.0)) <= 0.0 for c in contig_list)
        and fasta_exists
        and asm_fasta is not None
    ):
        await _backfill_multi_contig_depths(
            task_id, task, task_dir, asm_fasta, contig_list, stats, manifest_path, manifest_data, depth_locks
        )

    contig_list.sort(key=lambda x: x["length"], reverse=True)
    if stats.get("total_length", 0) > 0 and (stats.get("n50", 0) > 0 or stats.get("gc_percent", 0.0) > 0.0):
        assembly_db_obj.update_task_metrics(
            task_id,
            total_length=int(stats["total_length"]),
            contig_count=int(stats.get("contigs", len(contig_list))),
            n50=int(stats.get("n50", 0)),
            gc_content=float(stats.get("gc_percent", 0.0)),
            is_circular=bool(stats.get("is_circular", False)),
            avg_depth=float(stats.get("avg_depth", 0.0)),
            max_contig_length=int(stats.get("max_contig_length", 0)),
        )

    return {
        "task_id": task_id,
        "name": task.get("name"),
        "status": task.get("status"),
        "stats": stats,
        "contigs": contig_list,
        "fasta_exists": fasta_exists,
        "fasta_path": str(asm_fasta.resolve()) if fasta_exists and asm_fasta else None,
        "fasta_size_bytes": fasta_size_bytes,
        "created_at": task.get("created_at"),
        "updated_at": task.get("updated_at"),
        "duration_seconds": task.get("duration_seconds", 0),
    }


def extract_single_contig_fasta(asm_fasta: Path, contig_name: str) -> Optional[Tuple[str, str]]:
    """流式切片提取指定 Contig 的 FASTA 内容，返回 (clean_target, fasta_content) 或 None。"""
    clean_target = contig_name.strip().lstrip(">")
    found_header: Optional[str] = None
    seq_lines: List[str] = []
    is_target = False

    with open(asm_fasta, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            if line.startswith(">"):
                if is_target:
                    break
                header_line = line.strip()
                cur_name = header_line.split()[0].lstrip(">")
                if cur_name == clean_target:
                    is_target = True
                    found_header = header_line
            elif is_target:
                seq_lines.append(line.strip())

    if not found_header:
        return None
    return clean_target, f"{found_header}\n" + "\n".join(seq_lines) + "\n"
