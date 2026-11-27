# -*- coding: utf-8 -*-
"""
生物数据库 Provider 定义与工厂路由 (bio_db.providers)
"""
from __future__ import annotations

import asyncio
import gzip
import json
import logging
import os
import re
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, ClassVar, Dict, List, Optional, Tuple

from ....core.http_guard import validate_http_url
from ....utils.archive_guard import TarReadMode, safe_extract_tar
from ....workbench.models.tool_config import ToolConfig
from ..compat import get_short_path_name
from .cloud_sync import sync_ncbi_blast_db_from_cloud
from .downloader import (
    DownloadCancelledError,
    DownloadConfig,
    format_download_progress,
    stream_download_with_mirrors,
)
from .subprocess_runner import (
    build_wsl_script_argv,
    check_cancelled,
    resolve_makeblastdb,
    run_subprocess_with_progress,
)

logger = logging.getLogger("api_server")

ProgressReporter = Callable[[int, str], None]


class BioDatabase:
    """通用生物数据库管理基类。"""

    _DIR_INFO_TTL = 120.0
    _dir_info_cache: ClassVar[Dict[str, Tuple[float, str, float]]] = {}

    def __init__(self, db_id: str, config: Dict[str, Any]):
        self.db_id = db_id
        self.config = config
        self.name = str(config.get("name", db_id))
        self.last_error: Optional[str] = None
        self.base_dir = ToolConfig.get_db_dir(str(config.get("local_folder", db_id)))
        self.base_dir.mkdir(parents=True, exist_ok=True)

    @classmethod
    def clear_dir_info_cache(cls) -> None:
        """清空目录体积与时间统计缓存。"""
        cls._dir_info_cache.clear()

    def invalidate_dir_info_cache(self) -> None:
        """使当前数据库目录的体积与更新时间缓存失效。"""
        BioDatabase._dir_info_cache.pop(str(self.base_dir), None)

    def _get_download_urls(self, default_url: Optional[str] = None) -> List[str]:
        """收集主下载地址与可选 mirrors 列表并校验协议白名单。"""
        raw_urls: List[str] = []
        primary = self.config.get("url") or default_url
        if isinstance(primary, str) and primary.strip() and not primary.strip().startswith("local_"):
            raw_urls.append(primary.strip())
        extra_mirrors = self.config.get("mirrors")
        if isinstance(extra_mirrors, list):
            for item in extra_mirrors:
                if isinstance(item, str) and item.strip():
                    raw_urls.append(item.strip())
        if not raw_urls:
            raise ValueError(f"未配置 {self.db_id} 的有效远程下载地址")
        return [validate_http_url(u) for u in raw_urls]

    @staticmethod
    def _emit_progress(progress_cb: Optional[ProgressReporter], progress: int, message: str) -> None:
        if progress_cb is not None:
            progress_cb(max(0, min(100, int(progress))), message)

    def _make_download_progress_cb(
        self,
        progress_cb: Optional[ProgressReporter],
        start_pct: int,
        end_pct: int,
        label: str,
    ) -> Callable[[int, int, float], None]:
        def _on_dl(downloaded: int, total: int, speed_bps: float) -> None:
            if progress_cb is None:
                return
            if total > 0:
                ratio = min(1.0, max(0.0, downloaded / total))
                pct = start_pct + int(round((end_pct - start_pct) * ratio))
            else:
                pct = min(end_pct - 1, start_pct + 5)
            self._emit_progress(progress_cb, pct, f"{label}：{format_download_progress(downloaded, total, speed_bps)}")

        return _on_dl

    def _extract_gzip_with_progress(
        self,
        src_gz: Path,
        dst_fasta: Path,
        progress_cb: Optional[ProgressReporter],
        cancel_event: Optional[threading.Event],
    ) -> None:
        """在后台线程中安全解压 gzip 文件至 FASTA（70%-84% 区间），支持取消检查。"""
        total_gz = max(1, src_gz.stat().st_size if src_gz.exists() else 1)
        last_emit = 0.0
        self._emit_progress(progress_cb, 70, f"正在解压 {self.name} 序列压缩包...")
        with gzip.open(src_gz, "rb") as f_in, open(dst_fasta, "wb") as f_out:
            while True:
                check_cancelled(cancel_event)
                chunk = f_in.read(1024 * 1024)
                if not chunk:
                    break
                f_out.write(chunk)
                now = time.monotonic()
                if progress_cb is not None and (now - last_emit) >= 0.5:
                    raw_pos = getattr(f_in, "fileobj", None)
                    pos = raw_pos.tell() if raw_pos is not None and hasattr(raw_pos, "tell") else 0
                    ratio = min(1.0, max(0.0, pos / total_gz)) if pos > 0 else 0.5
                    self._emit_progress(progress_cb, 70 + int(round(14 * ratio)), f"正在解压 {self.name} 序列数据...")
                    last_emit = now
        self._emit_progress(progress_cb, 84, f"{self.name} 解压完成")

    async def _download_and_extract_tar(
        self,
        urls: List[str],
        archive_name: str,
        progress_cb: Optional[ProgressReporter],
        cancel_event: Optional[threading.Event],
        *,
        tar_mode: TarReadMode = "r:*",
        dl_end_pct: int = 82,
    ) -> Path:
        """共享 tar 归档下载与安全解压模板方法。"""
        target_tar = self.base_dir / archive_name
        self._emit_progress(progress_cb, 8, f"正在连接 {self.name} 下载节点...")
        dl_cb = self._make_download_progress_cb(progress_cb, 10, dl_end_pct, f"下载 {self.name}")
        await asyncio.to_thread(
            stream_download_with_mirrors,
            urls,
            target_tar,
            dl_cb,
            cancel_event,
            config=DownloadConfig(log_label=self.db_id),
        )
        check_cancelled(cancel_event)
        self._emit_progress(progress_cb, dl_end_pct + 3, f"正在解压并校验 {self.name} 归档...")

        await asyncio.to_thread(safe_extract_tar, target_tar, self.base_dir, mode=tar_mode)
        check_cancelled(cancel_event)
        return target_tar

    def _update_registry_version(self, new_version: str) -> None:
        registry_path = ToolConfig.DATABASE_ROOT / "registry.json"
        try:
            data = {"remotes": ToolConfig.get_remote_registry()}
            if "remotes" in data and self.db_id in data["remotes"]:
                data["remotes"][self.db_id]["version"] = new_version
                registry_path.parent.mkdir(parents=True, exist_ok=True)
                with open(registry_path, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                self.config["version"] = new_version
                logger.info("已成功持久化更新 %s 的版本号为: %s", self.db_id, new_version)
        except Exception as e:
            logger.error("持久化更新版本号失败: %s", e)

    def _get_dir_info(self) -> Tuple[float, str]:
        cache_key = str(self.base_dir)
        cached = BioDatabase._dir_info_cache.get(cache_key)
        now = time.time()
        if cached and (now - cached[2]) < BioDatabase._DIR_INFO_TTL:
            return cached[0], cached[1]

        total_size = 0
        latest_mtime = 0.0
        try:
            if self.base_dir.exists():
                for f in self.base_dir.rglob("*"):
                    if f.is_file():
                        st = f.stat()
                        total_size += st.st_size
                        if st.st_mtime > latest_mtime:
                            latest_mtime = st.st_mtime
        except Exception as exc:
            logger.debug("扫描生物数据库目录统计元数据失败: %s", exc)

        size_mb = round(total_size / (1024 * 1024), 2)
        mtime_str = datetime.fromtimestamp(latest_mtime).strftime("%Y-%m-%d %H:%M:%S") if latest_mtime > 0 else "未知"
        BioDatabase._dir_info_cache[cache_key] = (size_mb, mtime_str, now)
        return size_mb, mtime_str

    def get_status(self) -> Dict[str, Any]:
        size_mb, mtime_str = self._get_dir_info()
        return {
            "db_id": self.db_id,
            "name": self.name,
            "installed": False,
            "version": self.config.get("version", "Unknown"),
            "size_mb": size_mb,
            "last_modified": mtime_str,
            "category": self.config.get("category", "未分类数据库"),
            "url": self.config.get("url", "local_only"),
        }

    async def update_database(
        self,
        progress_cb: Optional[ProgressReporter] = None,
        cancel_event: Optional[threading.Event] = None,
    ) -> bool:
        raise NotImplementedError(f"{self.__class__.__name__} 未实现 update_database")


class SilvaDatabase(BioDatabase):
    """16S/18S 核酸 FASTA 数据库通用管理器（SILVA / RDP 复用）。"""

    index_prefix_name: ClassVar[str] = "silva"

    def get_status(self) -> Dict[str, Any]:
        db_ver = self.config.get("version", self.index_prefix_name)
        prefix = f"{self.index_prefix_name}_{db_ver}"
        is_indexed = (self.base_dir / f"{prefix}.nsq").exists() or (self.base_dir / f"{prefix}.ndb").exists()
        status = super().get_status()
        status.update({"installed": is_indexed, "path": str(self.base_dir) if is_indexed else None})
        return status

    async def update_database(
        self,
        progress_cb: Optional[ProgressReporter] = None,
        cancel_event: Optional[threading.Event] = None,
    ) -> bool:
        self.last_error = None
        try:
            urls = self._get_download_urls()
            target_gz = self.base_dir / "download.fasta.gz"
            target_fasta = self.base_dir / "source.fasta"

            logger.info(">>> [Download] 开始载入 %s: %s", self.name, urls[0])
            self._emit_progress(progress_cb, 8, f"正在连接 {self.name} 下载节点...")
            dl_cb = self._make_download_progress_cb(progress_cb, 10, 70, f"下载 {self.name}")
            await asyncio.to_thread(
                stream_download_with_mirrors,
                urls,
                target_gz,
                dl_cb,
                cancel_event,
                config=DownloadConfig(log_label=self.db_id),
            )
            await asyncio.to_thread(self._extract_gzip_with_progress, target_gz, target_fasta, progress_cb, cancel_event)
            await self.build_index(str(target_fasta), progress_cb=progress_cb, cancel_event=cancel_event)
            self.invalidate_dir_info_cache()
            return True
        except DownloadCancelledError:
            raise
        except Exception as e:
            self.last_error = str(e)
            logger.error("%s 更新失败: %s", self.name, e)
            return False

    async def build_index(
        self,
        fasta_path: str,
        progress_cb: Optional[ProgressReporter] = None,
        cancel_event: Optional[threading.Event] = None,
    ) -> None:
        if not os.path.exists(fasta_path):
            raise FileNotFoundError(f"FASTA source not found: {fasta_path}")

        check_cancelled(cancel_event)
        fasta_size = os.path.getsize(fasta_path) / (1024 * 1024)
        self._emit_progress(progress_cb, 85, f"准备构建 BLAST 索引 ({fasta_size:.1f} MB)...")
        await asyncio.sleep(1.5)
        check_cancelled(cancel_event)

        db_ver = self.config.get("version", "latest")
        db_type = str(self.config.get("db_type", "nucl"))
        tool_path = resolve_makeblastdb()
        short_base_dir = get_short_path_name(str(self.base_dir))
        output_name = f"{self.index_prefix_name}_{db_ver}"

        for f in self.base_dir.glob(f"{output_name}.n*"):
            try:
                f.unlink()
            except OSError as exc:
                logger.debug("构建 %s 索引前清理旧分片文件失败: %s", self.name, exc)

        cmd_args = [tool_path, "-in", "source.fasta", "-dbtype", db_type, "-title", f"{self.name} {db_ver}", "-out", output_name]
        rc, tail = await run_subprocess_with_progress(
            cmd_args,
            cwd=short_base_dir,
            progress_cb=progress_cb,
            cancel_event=cancel_event,
            start_pct=86,
            end_pct=98,
            stage_label=f"构建 {self.name} 索引",
        )
        if rc != 0:
            raise RuntimeError(f"makeblastdb 索引构建失败: {tail.strip() or rc}")


class RdpDatabase(SilvaDatabase):
    """RDP 16S 训练集数据库管理器。"""

    index_prefix_name: ClassVar[str] = "rdp"


class Ncbi16SDatabase(BioDatabase):
    """NCBI RefSeq 16S 数据库：云端高速源优先，不可用时无缝回退 FTP。"""

    def get_status(self) -> Dict[str, Any]:
        is_indexed = (self.base_dir / "16S_ribosomal_RNA.nsq").exists()
        status = super().get_status()
        status.update({"installed": is_indexed, "path": str(self.base_dir) if is_indexed else None})
        return status

    @staticmethod
    def _extract_cloud_version(cloud_info: Dict[str, Any]) -> str:
        m = re.match(r"^(\d{4}-\d{2})", str(cloud_info.get("last_updated") or "").strip())
        return m.group(1) if m else datetime.now().strftime("%Y-%m")

    async def update_database(
        self,
        progress_cb: Optional[ProgressReporter] = None,
        cancel_event: Optional[threading.Event] = None,
    ) -> bool:
        self.last_error = None
        try:
            self._emit_progress(progress_cb, 8, "正在探测 NCBI 官方云端加速源 (GCP/AWS)...")
            try:
                cloud_info = await asyncio.to_thread(
                    sync_ncbi_blast_db_from_cloud,
                    "16S_ribosomal_RNA",
                    self.base_dir,
                    db_type="nucl",
                    require_taxdb=True,
                    progress_cb=progress_cb,
                    cancel_event=cancel_event,
                )
                self._emit_progress(progress_cb, 96, f"同步完成 ({cloud_info.get('source', '云端源')})，正在更新版本...")
                self._update_registry_version(self._extract_cloud_version(cloud_info))
                self.invalidate_dir_info_cache()
                return True
            except DownloadCancelledError:
                raise
            except Exception as cloud_err:
                logger.warning("NCBI 官方云端源暂不可用 (%s)，自动回退传统 NCBI FTP 下载...", cloud_err)

            urls = self._get_download_urls("https://ftp.ncbi.nlm.nih.gov/blast/db/16S_ribosomal_RNA.tar.gz")
            await self._download_and_extract_tar(urls, "16S_ribosomal_RNA.tar.gz", progress_cb, cancel_event)
            self._emit_progress(progress_cb, 96, "正在更新本地版本元数据...")
            self._update_registry_version(datetime.now().strftime("%Y-%m"))
            self.invalidate_dir_info_cache()
            return True
        except DownloadCancelledError:
            raise
        except Exception as e:
            self.last_error = str(e)
            logger.error("NCBI 同步失败: %s", e)
            return False


class PhageScopeDatabase(BioDatabase):
    """PhageScope 噬菌体高精度注释库专用管理器。"""

    def get_status(self) -> Dict[str, Any]:
        is_indexed = (self.base_dir / "phagescope_proteins.psq").exists()
        status = super().get_status()
        status.update({"installed": is_indexed, "path": str(self.base_dir) if is_indexed else None})
        return status

    async def update_database(
        self,
        progress_cb: Optional[ProgressReporter] = None,
        cancel_event: Optional[threading.Event] = None,
    ) -> bool:
        self.last_error = None
        try:
            script_path = ToolConfig.PROJECT_ROOT / "database" / "fetch_phagescope.py"
            if not script_path.exists():
                raise FileNotFoundError(f"缺少 PhageScope 部署脚本: {script_path}")

            self._emit_progress(progress_cb, 10, "正在启动 PhageScope 在线同步脚本...")
            rc, tail = await run_subprocess_with_progress(
                [sys.executable, str(script_path)],
                cwd=str(ToolConfig.PROJECT_ROOT),
                progress_cb=progress_cb,
                cancel_event=cancel_event,
                start_pct=12,
                end_pct=96,
                stage_label="同步 PhageScope 库",
            )
            if rc == 0:
                self._update_registry_version(f"v1.0-{datetime.now().strftime('%Y-%m')}")
                self.invalidate_dir_info_cache()
                return True
            self.last_error = tail.strip() or f"脚本退出码异常: {rc}"
            return False
        except DownloadCancelledError:
            raise
        except Exception as e:
            self.last_error = str(e)
            logger.error("PhageScope 同步失败: %s", e)
            return False


class _WslScriptDatabase(BioDatabase):
    """WSL 外部脚本部署型数据库通用基类（Pharokka / Phold）。"""

    script_filename: ClassVar[str] = ""
    wsl_requirement_hint: ClassVar[str] = "需要 WSL 才能运行与部署"

    def get_status(self) -> Dict[str, Any]:
        is_installed = self.base_dir.exists() and any(self.base_dir.iterdir())
        status = super().get_status()
        status.update({"installed": is_installed, "path": str(self.base_dir) if is_installed else None})
        return status

    async def update_database(
        self,
        progress_cb: Optional[ProgressReporter] = None,
        cancel_event: Optional[threading.Event] = None,
    ) -> bool:
        self.last_error = None
        try:
            from ....assembly.env.wsl_manager import WSLManager

            if not WSLManager.is_available():
                self.last_error = f"未检测到可用的 WSL(Ubuntu) 发行版，{self.name} {self.wsl_requirement_hint}"
                return False
            argv = build_wsl_script_argv(self.script_filename)
            if not argv:
                self.last_error = "无法解析项目在 WSL 中的挂载路径"
                return False

            self._emit_progress(progress_cb, 10, f"正在 WSL 中启动 {self.name} 部署...")
            rc, tail = await run_subprocess_with_progress(
                argv,
                progress_cb=progress_cb,
                cancel_event=cancel_event,
                start_pct=12,
                end_pct=96,
                stage_label=f"部署 {self.name}",
            )
            if rc == 0:
                self._update_registry_version(f"{datetime.now().strftime('%Y-%m')} (Latest)")
                self.invalidate_dir_info_cache()
                return True
            self.last_error = tail.strip() or f"部署脚本退出码异常 ({rc})"
            return False
        except DownloadCancelledError:
            raise
        except Exception as e:
            self.last_error = str(e)
            logger.error("%s 同步失败: %s", self.name, e)
            return False


class PharokkaDatabase(_WslScriptDatabase):
    script_filename: ClassVar[str] = "setup_pharokka.sh"
    wsl_requirement_hint: ClassVar[str] = "需要 WSL 才能运行与部署"


class PholdDatabase(_WslScriptDatabase):
    script_filename: ClassVar[str] = "setup_phold.sh"
    wsl_requirement_hint: ClassVar[str] = "需要 WSL + GPU 环境才能运行与部署"


class FastaProtDatabase(BioDatabase):
    """通用蛋白 FASTA 数据库管理器 (SwissProt / VFDB)。"""

    def get_status(self) -> Dict[str, Any]:
        prefix = self.config.get("index_prefix", self.db_id)
        is_indexed = (self.base_dir / f"{prefix}.psq").exists() or (self.base_dir / f"{prefix}.pin").exists()
        status = super().get_status()
        status.update({"installed": is_indexed, "path": str(self.base_dir) if is_indexed else None})
        return status

    async def update_database(
        self,
        progress_cb: Optional[ProgressReporter] = None,
        cancel_event: Optional[threading.Event] = None,
    ) -> bool:
        self.last_error = None
        try:
            urls = self._get_download_urls()
            target_gz = self.base_dir / "download.fasta.gz"
            target_fasta = self.base_dir / "source.fasta"
            prefix = str(self.config.get("index_prefix", self.db_id))

            self._emit_progress(progress_cb, 8, f"正在连接 {self.name} 下载源...")
            dl_cb = self._make_download_progress_cb(progress_cb, 10, 70, f"下载 {self.name}")
            await asyncio.to_thread(
                stream_download_with_mirrors,
                urls,
                target_gz,
                dl_cb,
                cancel_event,
                config=DownloadConfig(log_label=self.db_id),
            )
            await asyncio.to_thread(self._extract_gzip_with_progress, target_gz, target_fasta, progress_cb, cancel_event)

            tool_path = resolve_makeblastdb()
            short_base_dir = get_short_path_name(str(self.base_dir))
            rc, tail = await run_subprocess_with_progress(
                [tool_path, "-in", "source.fasta", "-dbtype", "prot", "-title", self.name, "-out", prefix],
                cwd=short_base_dir,
                progress_cb=progress_cb,
                cancel_event=cancel_event,
                start_pct=85,
                end_pct=97,
                stage_label=f"构建 {self.name} 蛋白索引",
            )
            if rc == 0:
                self._update_registry_version(datetime.now().strftime("%Y-%m"))
                self.invalidate_dir_info_cache()
                return True
            self.last_error = tail.strip() or f"makeblastdb 退出码异常 ({rc})"
            return False
        except DownloadCancelledError:
            raise
        except Exception as e:
            self.last_error = str(e)
            logger.error("%s 同步失败: %s", self.name, e)
            return False


class DefenseFinderDatabase(BioDatabase):
    """DefenseFinder & AcrDB 抗防御与原核免疫模型库。"""

    def get_status(self) -> Dict[str, Any]:
        is_installed = (self.base_dir / "defense-finder-models").exists() or any(self.base_dir.rglob("*.hmm*"))
        status = super().get_status()
        status.update({"installed": is_installed, "path": str(self.base_dir) if is_installed else None})
        return status

    async def update_database(
        self,
        progress_cb: Optional[ProgressReporter] = None,
        cancel_event: Optional[threading.Event] = None,
    ) -> bool:
        self.last_error = None
        try:
            urls = self._get_download_urls()
            await self._download_and_extract_tar(urls, "defense_finder_models.tar.gz", progress_cb, cancel_event)
            self._update_registry_version(f"v1.3-{datetime.now().strftime('%Y-%m')}")
            self.invalidate_dir_info_cache()
            return True
        except DownloadCancelledError:
            raise
        except Exception as e:
            self.last_error = str(e)
            logger.error("DefenseFinder 同步失败: %s", e)
            return False


class CardDatabase(BioDatabase):
    """CARD 耐药基因数据库。"""

    def get_status(self) -> Dict[str, Any]:
        is_installed = (
            (self.base_dir / "card_protein.psq").exists()
            or (self.base_dir / "card_protein.pin").exists()
            or (self.base_dir / "card.json").exists()
        )
        status = super().get_status()
        status.update({"installed": is_installed, "path": str(self.base_dir) if is_installed else None})
        return status

    def _locate_card_fasta(self) -> Optional[Path]:
        f_faa = self.base_dir / "protein_fasta.fasta"
        if not f_faa.exists():
            f_cand = list(self.base_dir.glob("*protein*.fasta"))
            if f_cand:
                f_faa = f_cand[0]
        return f_faa if f_faa.exists() else None

    async def update_database(
        self,
        progress_cb: Optional[ProgressReporter] = None,
        cancel_event: Optional[threading.Event] = None,
    ) -> bool:
        self.last_error = None
        try:
            urls = self._get_download_urls("https://card.mcmaster.ca/latest/data")
            await self._download_and_extract_tar(
                urls, "card_data.tar.bz2", progress_cb, cancel_event, tar_mode="r:bz2", dl_end_pct=72
            )
            faa_path = self._locate_card_fasta()
            if faa_path is not None:
                tool_path = resolve_makeblastdb()
                rc, tail = await run_subprocess_with_progress(
                    [tool_path, "-in", faa_path.name, "-dbtype", "prot", "-title", "CARD Resistome", "-out", "card_protein"],
                    cwd=get_short_path_name(str(self.base_dir)),
                    progress_cb=progress_cb,
                    cancel_event=cancel_event,
                    start_pct=84,
                    end_pct=97,
                    stage_label="构建 CARD 蛋白索引",
                )
                if rc != 0:
                    raise RuntimeError(f"CARD 索引构建失败: {tail.strip() or rc}")

            self._update_registry_version(f"v3.2-{datetime.now().strftime('%Y-%m')}")
            self.invalidate_dir_info_cache()
            return True
        except DownloadCancelledError:
            raise
        except Exception as e:
            self.last_error = str(e)
            logger.error("CARD 同步失败: %s", e)
            return False


class CddPfamDatabase(BioDatabase):
    """NCBI CDD / Pfam-A 结构域数据库。"""

    def get_status(self) -> Dict[str, Any]:
        is_installed = (
            any(self.base_dir.glob("*.smp"))
            or any(self.base_dir.glob("*.rps*"))
            or (self.base_dir / "Cdd.rps").exists()
        )
        status = super().get_status()
        status.update({"installed": is_installed, "path": str(self.base_dir) if is_installed else None})
        return status

    async def update_database(
        self,
        progress_cb: Optional[ProgressReporter] = None,
        cancel_event: Optional[threading.Event] = None,
    ) -> bool:
        self.last_error = None
        try:
            urls = self._get_download_urls()
            await self._download_and_extract_tar(urls, "cdd.tar.gz", progress_cb, cancel_event)
            self._update_registry_version(f"v3.21-{datetime.now().strftime('%Y-%m')}")
            self.invalidate_dir_info_cache()
            return True
        except DownloadCancelledError:
            raise
        except Exception as e:
            self.last_error = str(e)
            logger.error("CDD/Pfam 同步失败: %s", e)
            return False


def create_database_provider(db_id: str, config: Dict[str, Any]) -> BioDatabase:
    """按 db_id 路由实例化对应的数据库 Provider。"""
    db_id_lower = db_id.lower()
    factory_map: List[Tuple[Tuple[str, ...], type[BioDatabase]]] = [
        (("silva",), SilvaDatabase),
        (("rdp",), RdpDatabase),
        (("ncbi_16s", "16s_ribosomal"), Ncbi16SDatabase),
        (("phagescope",), PhageScopeDatabase),
        (("pharokka",), PharokkaDatabase),
        (("phold",), PholdDatabase),
        (("swissprot", "vfdb"), FastaProtDatabase),
        (("defense_finder", "anti_crispr"), DefenseFinderDatabase),
        (("card",), CardDatabase),
        (("cdd", "pfam"), CddPfamDatabase),
    ]
    for keys, cls in factory_map:
        if any(k in db_id_lower for k in keys):
            return cls(db_id, config)
    return BioDatabase(db_id, config)
