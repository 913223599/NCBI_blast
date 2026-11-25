# -*- coding: utf-8 -*-
"""
PhyloArchiveStore - 独立 SQLite 元数据仓库与物理工作区管理
完全独立于旧版 tree_history 与 tree_results 目录。
"""
import inspect
import logging
import os
import shutil
import sqlite3
import stat
import threading
import time
import zipfile
from pathlib import Path
from typing import Any, List, Optional

from ..models.schemas import PhyloJobRecord, WorkspaceFileItem
from ..runtime.tool_registry import get_project_root

logger = logging.getLogger("phylo.storage")


def _make_writable(path: Path) -> None:
    """清除 Windows/POSIX 只读属性，防止副本或清理操作触发 PermissionError。"""
    try:
        if path.exists():
            os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
    except OSError:
        pass


def _force_remove_file(path: Path) -> None:
    """安全删除单个文件，若带只读属性则先解锁再删除。"""
    _make_writable(path)
    path.unlink()


def _rmtree_supports_onexc() -> bool:
    """判断当前运行时的 shutil.rmtree 是否支持 onexc 参数 (Python 3.12+)。"""
    try:
        return "onexc" in inspect.signature(shutil.rmtree).parameters
    except Exception:
        return False


def _rmtree_readonly(path: Path, retries: int = 3, retry_delay: float = 0.15) -> bool:
    """递归删除目录，兼容 Python <3.12 (onerror) 与 >=3.12 (onexc)，并容忍短暂句柄占用。"""
    if not path.exists():
        return True

    def _on_error(func: Any, target_path: str, _exc: Any) -> None:
        try:
            os.chmod(target_path, stat.S_IWRITE | stat.S_IREAD)
            func(target_path)
        except OSError as exc:
            logger.warning(f"强制清理失败 ({target_path}): {exc}")

    for attempt in range(max(1, retries)):
        try:
            if _rmtree_supports_onexc():
                shutil.rmtree(path, onexc=_on_error)
            else:
                shutil.rmtree(path, onerror=_on_error)  # type: ignore[call-arg]
            if not path.exists():
                return True
        except OSError as exc:
            logger.warning(f"删除目录尝试 {attempt + 1}/{retries} 失败 ({path}): {exc}")
        if attempt < retries - 1 and path.exists():
            time.sleep(retry_delay)

    if path.exists():
        logger.warning(f"目录清理未能完全完成，已忽略残留 ({path})")
        return False
    return True


class PhyloArchiveStore:
    """管理 results/phylo/ 下的工作区文件、作业目录、缓存目录及 SQLite 任务表。"""

    VALID_SEQ_EXTS = {".fasta", ".fas", ".fa", ".fna", ".seq", ".txt", ".ab1", ".abi"}

    def __init__(self, base_dir: Optional[Path] = None) -> None:
        self.base_dir = (base_dir or (get_project_root() / "results" / "phylo")).resolve()
        self.workspace_dir = self.base_dir / "workspace"
        self.jobs_dir = self.base_dir / "jobs"
        self.cache_dir = self.base_dir / "cache"
        self.db_path = self.base_dir / "phylo.db"
        self._db_lock = threading.Lock()

        for d in (self.base_dir, self.workspace_dir, self.jobs_dir, self.cache_dir):
            d.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=15)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._db_lock, self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS phylo_jobs (
                    job_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    status TEXT NOT NULL,
                    resolved_track TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    finished_at REAL,
                    elapsed_sec REAL DEFAULT 0.0,
                    record_json TEXT NOT NULL
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_phylo_created ON phylo_jobs(created_at DESC)")
            conn.commit()

    # ─── 工作区管理 ─────────────────────────────────────────
    def list_workspace_files(self) -> List[WorkspaceFileItem]:
        items: List[WorkspaceFileItem] = []
        if not self.workspace_dir.exists():
            return items
        for entry in sorted(self.workspace_dir.iterdir(), key=lambda p: p.name.lower()):
            if entry.is_file() and entry.suffix.lower() in (self.VALID_SEQ_EXTS | {".gz"}):
                st = entry.stat()
                items.append(
                    WorkspaceFileItem(
                        name=entry.name,
                        size=st.st_size,
                        modified_at=st.st_mtime,
                        ext=entry.suffix.lower(),
                    )
                )
        return items

    def get_workspace_paths(self, filenames: Optional[List[str]] = None) -> List[Path]:
        if filenames:
            paths: List[Path] = []
            for raw in filenames:
                p = Path(raw)
                cand = p if p.is_absolute() and p.is_file() else (self.workspace_dir / p.name)
                if cand.is_file():
                    paths.append(cand.resolve())
            return paths
        return [
            p.resolve()
            for p in sorted(self.workspace_dir.iterdir(), key=lambda x: x.name.lower())
            if p.is_file() and p.suffix.lower() in (self.VALID_SEQ_EXTS | {".gz"})
        ]

    def add_files_to_workspace(self, source_paths: List[str]) -> List[str]:
        added: List[str] = []
        for raw in source_paths:
            src = Path(raw)
            if not src.is_file():
                continue
            ext = src.suffix.lower()
            if ext == ".zip":
                try:
                    with zipfile.ZipFile(src, "r") as zf:
                        for member in zf.namelist():
                            if member.endswith("/") or member.startswith("__MACOSX"):
                                continue
                            m_path = Path(member)
                            if m_path.suffix.lower() in self.VALID_SEQ_EXTS:
                                safe_name = m_path.name
                                dest = self.workspace_dir / safe_name
                                _make_writable(dest)
                                with zf.open(member) as src_f, open(dest, "wb") as dst_f:
                                    shutil.copyfileobj(src_f, dst_f)
                                _make_writable(dest)
                                added.append(safe_name)
                except Exception as exc:
                    logger.warning(f"解压 ZIP 失败 ({src.name}): {exc}")
            elif ext in (self.VALID_SEQ_EXTS | {".gz"}):
                dest = self.workspace_dir / src.name
                _make_writable(dest)
                shutil.copyfile(src, dest)
                _make_writable(dest)
                added.append(src.name)
        return added

    def save_pasted_sequences(self, content: str, filename: Optional[str] = None) -> str:
        import time

        safe_name = filename or f"pasted_{time.strftime('%Y%m%d_%H%M%S')}.fasta"
        safe_name = "".join(c for c in Path(safe_name).name if c.isalnum() or c in "._-") or "pasted.fasta"
        if not safe_name.lower().endswith((".fasta", ".fas", ".fa")):
            safe_name += ".fasta"
        dest = self.workspace_dir / safe_name
        dest.write_text(content, encoding="utf-8")
        return safe_name

    def remove_workspace_file(self, filename: str) -> bool:
        target = (self.workspace_dir / Path(filename).name).resolve()
        if target.parent == self.workspace_dir and target.is_file():
            _force_remove_file(target)
            return True
        return False

    def clear_workspace(self) -> None:
        if self.workspace_dir.exists():
            for entry in self.workspace_dir.iterdir():
                if entry.is_file():
                    _force_remove_file(entry)
                elif entry.is_dir():
                    _rmtree_readonly(entry)

    # ─── 作业元数据持久化 ─────────────────────────────────────
    def save_job(self, record: PhyloJobRecord) -> None:
        payload = record.model_dump_json()
        with self._db_lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO phylo_jobs (job_id, title, status, resolved_track, created_at, finished_at, elapsed_sec, record_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(job_id) DO UPDATE SET
                    title = excluded.title,
                    status = excluded.status,
                    resolved_track = excluded.resolved_track,
                    finished_at = excluded.finished_at,
                    elapsed_sec = excluded.elapsed_sec,
                    record_json = excluded.record_json
                """,
                (
                    record.job_id,
                    record.title,
                    record.status,
                    record.resolved_track,
                    record.created_at,
                    record.finished_at,
                    record.elapsed_sec,
                    payload,
                ),
            )
            conn.commit()

    def get_job(self, job_id: str) -> Optional[PhyloJobRecord]:
        with self._db_lock, self._connect() as conn:
            row = conn.execute("SELECT record_json FROM phylo_jobs WHERE job_id = ?", (job_id,)).fetchone()
            if not row:
                return None
            return PhyloJobRecord.model_validate_json(row["record_json"])

    def list_jobs(self, limit: int = 50) -> List[PhyloJobRecord]:
        with self._db_lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT record_json FROM phylo_jobs ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
            out: List[PhyloJobRecord] = []
            for r in rows:
                try:
                    out.append(PhyloJobRecord.model_validate_json(r["record_json"]))
                except Exception:
                    continue
            return out

    def delete_job(self, job_id: str) -> bool:
        with self._db_lock, self._connect() as conn:
            cur = conn.execute("DELETE FROM phylo_jobs WHERE job_id = ?", (job_id,))
            conn.commit()
            deleted = cur.rowcount > 0
        jdir = self.jobs_dir / job_id
        if jdir.exists() and jdir.is_dir():
            _rmtree_readonly(jdir)
        return deleted

    def recover_interrupted_jobs(self) -> int:
        """服务启动时自愈残留的 pending/running 僵尸任务。"""
        import time

        recovered = 0
        with self._db_lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT record_json FROM phylo_jobs WHERE status IN ('pending', 'running')"
            ).fetchall()
            now = time.time()
            for row in rows:
                try:
                    rec = PhyloJobRecord.model_validate_json(row["record_json"])
                    rec.status = "failed"
                    rec.finished_at = now
                    rec.error = "服务重启导致任务中断"
                    rec.message = "服务重启导致任务中断"
                    for st in rec.stages:
                        if st.status in ("running", "pending"):
                            st.status = "failed"
                            st.message = "中断"
                    conn.execute(
                        "UPDATE phylo_jobs SET status = ?, finished_at = ?, record_json = ? WHERE job_id = ?",
                        ("failed", now, rec.model_dump_json(), rec.job_id),
                    )
                    recovered += 1
                except Exception:
                    continue
            if recovered > 0:
                conn.commit()
        return recovered

    def append_log(self, job_id: str, line: str) -> None:
        log_file = self.jobs_dir / job_id / "job.log"
        log_file.parent.mkdir(parents=True, exist_ok=True)
        with open(log_file, "a", encoding="utf-8", newline="\n") as fh:
            fh.write(line.rstrip("\r\n") + "\n")

    def read_logs(self, job_id: str, tail: int = 200) -> List[str]:
        log_file = self.jobs_dir / job_id / "job.log"
        if not log_file.is_file():
            return []
        lines = log_file.read_text(encoding="utf-8", errors="replace").splitlines()
        return lines[-tail:] if tail > 0 else lines


_store_singleton: Optional[PhyloArchiveStore] = None
_store_lock = threading.Lock()


def get_phylo_store() -> PhyloArchiveStore:
    global _store_singleton
    with _store_lock:
        if _store_singleton is None:
            _store_singleton = PhyloArchiveStore()
        return _store_singleton
