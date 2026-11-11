# -*- coding: utf-8 -*-
"""结果打包：把注释产物目录打成 zip（回传附件）。

设计要点：
- 支持两种输入：单个注释产物目录（含 ANNO.gbk / ANNO.tsv / features.json 等），
  或任意目录（按白名单挑选常见注释产物）。
- 打包输出到 <send_dir>/<task_id>_<时间戳>.zip，同批记录 manifest.json。
- 纯标准库（zipfile），零第三方依赖。
"""
import hashlib
import json
import logging
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("mail_download.packer")

# 常见注释产物后缀白名单（zip 内按原文件名保留；目录结构拍平，避免嵌套混乱）
DEFAULT_PRODUCT_GLOBS = [
    "*.gbk", "*.gff", "*.gff3", "*.tsv", "*.faa", "*.ffn", "*.fasta", "*.docx",
    "features.json", "summary.json", "safety_audit.json", "manifest.json",
]

DEFAULT_ZIP_SUFFIXES = {".gbk", ".gff", ".gff3", ".tsv", ".faa", ".ffn", ".fasta", ".docx", ".json"}


class ResultPacker:
    """把产物目录打包为 zip（回传附件）。"""

    def __init__(self, send_dir: Path, product_globs: Optional[List[str]] = None):
        self.send_dir = Path(send_dir)
        self.product_globs = list(product_globs or DEFAULT_PRODUCT_GLOBS)

    # ---- 主流程 ----

    def pack(self, result_dir: Path, task_id: Optional[str] = None) -> Dict[str, Any]:
        """打包产物目录。task_id 用于 zip 命名与清单；缺省用目录名。"""
        result_dir = Path(result_dir)
        if not result_dir.exists() or not result_dir.is_dir():
            raise FileNotFoundError(f"产物目录不存在: {result_dir}")

        files = self._collect(result_dir)
        if not files:
            raise ValueError(f"目录中没有匹配的注释产物: {result_dir}")

        task_id = task_id or result_dir.name
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.send_dir.mkdir(parents=True, exist_ok=True)
        zip_name = f"{task_id}_{stamp}.zip"
        zip_path = self.send_dir / zip_name

        entries = self._write_zip(zip_path, files)
        manifest = self._write_manifest(task_id, zip_path, entries)
        return {
            "task_id": task_id,
            "zip": str(zip_path),
            "zip_name": zip_name,
            "size_bytes": zip_path.stat().st_size,
            "sha256": hashlib.sha256(zip_path.read_bytes()).hexdigest(),
            "file_count": len(entries),
            "files": entries,
            "manifest": str(manifest),
        }

    # ---- 内部 ----

    def _collect(self, result_dir: Path) -> List[Path]:
        """按白名单收集产物文件（递归一层，取文件）。"""
        found: List[Path] = []
        for pattern in self.product_globs:
            for p in result_dir.rglob(pattern):
                if p.is_file():
                    found.append(p)
        # 去重并按名称排序，保证 zip 内容稳定
        seen = set()
        out = []
        for p in sorted(found, key=lambda x: x.name):
            if p.name in seen:
                continue
            seen.add(p.name)
            out.append(p)
        return out

    def _write_zip(self, zip_path: Path, files: List[Path]) -> List[Dict[str, Any]]:
        entries = []
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for p in files:
                data = p.read_bytes()
                zf.writestr(p.name, data)
                entries.append({
                    "name": p.name,
                    "size_bytes": len(data),
                    "sha256": hashlib.sha256(data).hexdigest(),
                })
        return entries

    def _write_manifest(self, task_id: str, zip_path: Path,
                        entries: List[Dict[str, Any]]) -> Path:
        manifest = {
            "task_id": task_id,
            "pack_time": datetime.now().isoformat(timespec="seconds"),
            "zip": zip_path.name,
            "zip_sha256": hashlib.sha256(zip_path.read_bytes()).hexdigest(),
            "file_count": len(entries),
            "files": entries,
        }
        manifest_path = self.send_dir / f"{zip_path.stem}.manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return manifest_path
