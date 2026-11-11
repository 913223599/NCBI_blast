# -*- coding: utf-8 -*-
"""
生工 16S 本地浏览器下载压缩包扫描与归档导入服务模块
职责：
1. 扫描本机浏览器下载目录中匹配的生工测序结果压缩包（*_<10位订单号>_*.zip）；
2. 校验 zip 完整性与测序内容特征，安全复制归档到对应 <YYYYMMDD_订单号>/原始压缩包/；
3. 支持按已有待下载订单认领，或为下载目录中新发现的测序包自动建立订单三级目录。
"""
import logging
import re
import shutil
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from .sangon_mail_scanner import SangonMailIndex, create_sangon_subdirs

logger = logging.getLogger("api.other_tools.sangon_zip_importer")

_ORDER_NO_RE = re.compile(r"(?<!\d)(\d{10})(?!\d)")
_SEQ_EXTS = (".fasta", ".fa", ".fas", ".fna", ".seq", ".ab1", ".abi")


def get_default_downloads_dir() -> Path:
    return Path.home() / "Downloads"


def _is_sequencing_zip(zip_path: Path) -> bool:
    """校验压缩包合法且确实包含测序序列或峰图文件（或文件名显式标注测序结果）。"""
    if not zip_path.exists() or not zip_path.is_file():
        return False
    low_name = zip_path.name.lower()
    if low_name.endswith((".crdownload", ".part", ".tmp")):
        return False
    if low_name.endswith(".zip") is False:
        return False
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            names = zf.namelist()
            if "测序" in zip_path.name:
                return len(names) > 0
            return any(n.lower().endswith(_SEQ_EXTS) for n in names)
    except (zipfile.BadZipFile, OSError):
        return False


def scan_downloads_for_sangon_zips(
    downloads_dir: Path,
    order_nos: Optional[Iterable[str]] = None,
) -> List[Dict[str, Any]]:
    """扫描本地下载目录，返回按订单修改时间倒序排列的生工测序结果压缩包清单。"""
    d_dir = Path(downloads_dir)
    if not d_dir.exists() or not d_dir.is_dir():
        return []

    target_set = {str(o).strip() for o in order_nos if str(o).strip()} if order_nos is not None else None
    found: List[Dict[str, Any]] = []

    for zp in d_dir.glob("*.zip"):
        if not zp.is_file():
            continue
        m = _ORDER_NO_RE.search(zp.name)
        if not m:
            continue
        order_no = m.group(1)
        if target_set is not None and order_no not in target_set:
            continue
        if not _is_sequencing_zip(zp):
            continue
        st = zp.stat()
        found.append({
            "order_no": order_no,
            "zip_name": zp.name,
            "zip_path": str(zp.resolve()),
            "size_bytes": st.st_size,
            "size_kb": round(st.st_size / 1024, 1),
            "mtime": st.st_mtime,
            "mtime_str": datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
        })

    found.sort(key=lambda x: x["mtime"], reverse=True)
    return found


def import_order_zips_from_downloads(
    root_dir: Path,
    downloads_dir: Path,
    *,
    order_names: Optional[List[str]] = None,
    auto_create_order: bool = False,
) -> Dict[str, Any]:
    """
    从本地下载目录识别并归档压缩包到生工订单的 原始压缩包/ 目录。
    仅复制归档不删除下载目录原文件，同名同大小文件自动跳过防重复。
    """
    r_dir = Path(root_dir)
    d_dir = Path(downloads_dir)
    if not r_dir.exists():
        r_dir.mkdir(parents=True, exist_ok=True)

    # 构建已有订单映射：order_no -> order_dir Path
    disk_by_no: Dict[str, Path] = {}
    for child in sorted(r_dir.iterdir(), key=lambda p: p.name, reverse=True):
        if child.is_dir() and re.match(r"^\d{8}_\d+", child.name):
            ono = child.name.split("_", 1)[1]
            if ono not in disk_by_no:
                disk_by_no[ono] = child

    existing_by_no: Dict[str, Path] = {}
    target_order_nos: Optional[set] = None
    if order_names:
        target_order_nos = set()
        for name in order_names:
            ono = name.split("_", 1)[1] if "_" in name else name
            target_order_nos.add(ono)
            p = r_dir / name
            if p.exists() and p.is_dir():
                existing_by_no[ono] = p
            elif ono in disk_by_no:
                existing_by_no[ono] = disk_by_no[ono]
    else:
        existing_by_no = disk_by_no

    candidates = scan_downloads_for_sangon_zips(
        d_dir,
        order_nos=target_order_nos if (target_order_nos is not None and not auto_create_order) else None,
    )

    # 每个订单只取最新的有效测序结果包（如同时有 (4).zip 和原始 zip，优先最新修改时间）
    latest_by_order: Dict[str, Dict[str, Any]] = {}
    for item in candidates:
        ono = item["order_no"]
        if target_order_nos is not None and ono not in target_order_nos:
            continue
        if ono not in latest_by_order:
            latest_by_order[ono] = item

    idx = SangonMailIndex(r_dir)
    idx.load()
    seen_orders = (idx._data or {}).get("seen_orders", {})

    imported: List[Dict[str, Any]] = []
    skipped_existing = 0
    created_dirs: List[str] = []

    for ono, item in latest_by_order.items():
        order_dir = existing_by_no.get(ono)
        if order_dir is None:
            if not auto_create_order:
                continue
            meta = seen_orders.get(ono) if isinstance(seen_orders, dict) else None
            dir_name = (meta or {}).get("dir_name") if isinstance(meta, dict) else None
            if not dir_name:
                date_prefix = datetime.fromtimestamp(item["mtime"]).strftime("%Y%m%d")
                dir_name = f"{date_prefix}_{ono}"
            order_dir = r_dir / dir_name
            if not order_dir.exists():
                create_sangon_subdirs(order_dir)
                created_dirs.append(dir_name)
            existing_by_no[ono] = order_dir

        zip_dir = order_dir / "原始压缩包"
        zip_dir.mkdir(parents=True, exist_ok=True)
        src_zip = Path(item["zip_path"])
        dest_zip = zip_dir / src_zip.name

        # 若目标目录已有完全相同大小且同名的包，或已存在非空压缩包，避免重复拷贝
        existing_zips = list(zip_dir.glob("*.zip"))
        if any(ez.name == src_zip.name and ez.stat().st_size == item["size_bytes"] for ez in existing_zips):
            skipped_existing += 1
            continue
        if existing_zips and any(ez.stat().st_size == item["size_bytes"] for ez in existing_zips):
            skipped_existing += 1
            continue

        shutil.copy2(src_zip, dest_zip)
        imported.append({
            "order_no": ono,
            "dir_name": order_dir.name,
            "zip_name": src_zip.name,
            "dest_path": str(dest_zip),
            "size_kb": item["size_kb"],
        })

    return {
        "downloads_dir": str(d_dir),
        "scanned_zips": len(candidates),
        "matched_orders": len(latest_by_order),
        "imported_count": len(imported),
        "skipped_existing": skipped_existing,
        "created_dirs": created_dirs,
        "imported": imported,
    }
