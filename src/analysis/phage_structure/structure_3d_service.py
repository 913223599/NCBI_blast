# -*- coding: utf-8 -*-
"""
噬菌体蛋白 3D 结构坐标安全服务 (Structure3DService)

职责：
1. 枚举并安全读取指定结构预测任务目录下的本地 .pdb / .cif / .mmcif 文件（严防路径穿越）；
2. 支持按 UniProt Accession（AlphaFold DB）或 PDB ID（RCSB PDB）异步拉取并本地磁盘缓存 3D 坐标；
3. 强制 UTF-8 编码、显式网络超时与文件大小红线控制，防止 OOM。
"""
from __future__ import annotations

import json
import logging
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Literal

logger = logging.getLogger("analysis.phage_structure.structure_3d")

REPO_ROOT = Path(__file__).resolve().parents[3]
STRUCTURE_CACHE_DIR = REPO_ROOT / "data" / "structure_cache"

ALLOWED_EXTENSIONS = {".pdb", ".cif", ".mmcif"}
MAX_STRUCTURE_BYTES = 25 * 1024 * 1024  # 25 MB 上限

_PDB_ID_RE = re.compile(r"^[A-Za-z0-9]{4}$")
_UNIPROT_RE = re.compile(r"^[A-Za-z0-9_-]{4,20}$")


def detect_structure_format(filename: str) -> Literal["pdb", "mmcif"]:
    suffix = Path(filename).suffix.lower()
    if suffix in (".cif", ".mmcif"):
        return "mmcif"
    return "pdb"


def list_task_structure_files(task_folder: Path) -> List[Dict[str, Any]]:
    """枚举任务目录内所有合规的本地 3D 坐标文件（返回相对路径）。"""
    root = Path(task_folder).resolve()
    if not root.is_dir():
        return []

    items: List[Dict[str, Any]] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix.lower() not in ALLOWED_EXTENSIONS:
            continue
        try:
            rel = path.resolve().relative_to(root).as_posix()
            size = path.stat().st_size
        except (ValueError, OSError):
            continue
        if size <= 0 or size > MAX_STRUCTURE_BYTES:
            continue
        items.append(
            {
                "name": path.name,
                "rel_path": rel,
                "format": detect_structure_format(path.name),
                "size_bytes": size,
            }
        )
    return items


def read_task_structure_file(task_folder: Path, rel_path: str) -> Dict[str, Any]:
    """安全读取任务目录内的单个 3D 结构坐标文件，严防路径穿越。"""
    clean_rel = str(rel_path or "").strip().replace("\\", "/")
    if not clean_rel or clean_rel.startswith("/") or ".." in clean_rel.split("/"):
        raise ValueError("非法文件路径：禁止绝对路径或目录穿越")

    root = Path(task_folder).resolve()
    target = (root / clean_rel).resolve()
    try:
        resolved_rel = target.relative_to(root).as_posix()
    except ValueError as exc:
        raise ValueError("非法文件路径：目标超出任务目录边界") from exc

    if target.suffix.lower() not in ALLOWED_EXTENSIONS:
        raise ValueError(f"不支持的 3D 结构文件扩展名: {target.suffix}")
    if not target.is_file():
        raise FileNotFoundError(f"3D 结构文件不存在: {resolved_rel}")

    size = target.stat().st_size
    if size > MAX_STRUCTURE_BYTES:
        raise ValueError(f"结构文件超过 25 MB 限制 ({size} bytes)")

    content = target.read_text(encoding="utf-8", errors="replace")
    return {
        "source": "task_local",
        "filename": target.name,
        "rel_path": resolved_rel,
        "format": detect_structure_format(target.name),
        "size_bytes": size,
        "content": content,
        "cached": True,
    }


def _http_get_text(url: str, timeout: float = 20.0) -> str:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "NCBI-Bio-Station/2.1 (Structural-Viewer)",
            "Accept": "application/json, text/plain, */*",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read(MAX_STRUCTURE_BYTES + 1)
        if len(raw) > MAX_STRUCTURE_BYTES:
            raise ValueError("远端结构文件体积超过 25 MB 限制")
        return raw.decode("utf-8", errors="replace")


def fetch_public_structure(
    source: str,
    accession: str,
    *,
    cache_dir: Path | None = None,
    timeout: float = 20.0,
) -> Dict[str, Any]:
    """
    从 AlphaFold DB 或 RCSB PDB 拉取 3D 蛋白结构并落盘缓存。
    """
    src_key = str(source or "").strip().lower()
    acc = str(accession or "").strip().upper()

    if src_key == "rcsb":
        if not _PDB_ID_RE.match(acc):
            raise ValueError("PDB ID 格式无效，请输入 4 位字母/数字（如 1EMA 或 6VXX）")
        ext = ".pdb"
        fmt: Literal["pdb", "mmcif"] = "pdb"
    elif src_key == "alphafold":
        if not _UNIPROT_RE.match(acc):
            raise ValueError("UniProt ID 格式无效（如 P00533 或 Q9NQX5）")
        ext = ".pdb"
        fmt = "pdb"
    else:
        raise ValueError("不支持的公共结构来源，仅支持 alphafold 或 rcsb")

    target_dir = Path(cache_dir) if cache_dir is not None else STRUCTURE_CACHE_DIR
    target_dir.mkdir(parents=True, exist_ok=True)
    cache_file = target_dir / f"{src_key}_{acc}{ext}"

    if cache_file.is_file() and cache_file.stat().st_size > 0:
        content = cache_file.read_text(encoding="utf-8", errors="replace")
        return {
            "source": src_key,
            "accession": acc,
            "filename": cache_file.name,
            "format": fmt,
            "size_bytes": len(content.encode("utf-8")),
            "content": content,
            "cached": True,
        }

    try:
        if src_key == "rcsb":
            url = f"https://files.rcsb.org/download/{acc}.pdb"
            content = _http_get_text(url, timeout=timeout)
        else:
            meta_url = f"https://alphafold.ebi.ac.uk/api/prediction/{acc}"
            meta_raw = _http_get_text(meta_url, timeout=timeout)
            entries = json.loads(meta_raw)
            if not isinstance(entries, list) or not entries:
                raise FileNotFoundError(f"AlphaFold DB 未收录该 UniProt 条目: {acc}")
            first = entries[0]
            pdb_url = first.get("pdbUrl") or first.get("cifUrl")
            if not pdb_url:
                raise FileNotFoundError(f"AlphaFold DB 条目缺少坐标下载地址: {acc}")
            if str(pdb_url).lower().endswith(".cif"):
                ext = ".cif"
                fmt = "mmcif"
                cache_file = target_dir / f"{src_key}_{acc}{ext}"
            content = _http_get_text(str(pdb_url), timeout=timeout)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise FileNotFoundError(f"未在 {src_key.upper()} 找到结构条目: {acc}") from exc
        raise RuntimeError(f"拉取 {src_key.upper()} 结构失败 (HTTP {exc.code})") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"无法连接 {src_key.upper()} 结构服务，请检查网络或改用本地文件导入") from exc

    tmp_file = cache_file.with_name(f".{cache_file.name}.tmp")
    tmp_file.write_text(content, encoding="utf-8")
    tmp_file.replace(cache_file)

    return {
        "source": src_key,
        "accession": acc,
        "filename": cache_file.name,
        "format": fmt,
        "size_bytes": len(content.encode("utf-8")),
        "content": content,
        "cached": False,
    }
