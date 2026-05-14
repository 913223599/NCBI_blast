import os
import sys
import hashlib
import logging
import time
from typing import List, Dict, Any, Optional
from pathlib import Path
import threading

logger = logging.getLogger(__name__)

# NCBI 在线 taxdump 下载地址
NCBI_TAXDUMP_URL = "https://ftp.ncbi.nlm.nih.gov/pub/taxonomy/taxdump.tar.gz"
NCBI_TAXDUMP_MD5_URL = "https://ftp.ncbi.nlm.nih.gov/pub/taxonomy/taxdump.tar.gz.md5"

class TaxonomyProvider:
    """
    Singleton provider for offline NCBI Taxonomy using ete4.

    职责：
      - 管理 taxa.sqlite 的生命周期（首次构建、在线更新）
      - 提供物种谱系查询接口
      - 暴露数据库状态（是否就绪、文件大小、修改日期、是否正在更新）

    不负责：编码表填充（由 TaxonomySyncService 处理）、翻译词库写入
    """
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                inst = super(TaxonomyProvider, cls).__new__(cls)
                inst._local = threading.local()
                inst._is_building = False
                inst._build_progress = ""
                cls._instance = inst
        return cls._instance

    # ────────── 路径常量 ──────────

    @property
    def _tax_dir(self) -> Path:
        project_root = Path(__file__).resolve().parents[2]
        tax_dir = project_root / "database" / "taxonomy"
        tax_dir.mkdir(parents=True, exist_ok=True)
        return tax_dir

    @property
    def db_path(self) -> str:
        return str(self._tax_dir / "taxa.sqlite")

    @property
    def _taxdump_tgz_path(self) -> Path:
        return self._tax_dir / "taxdump.tar.gz"

    @property
    def _local_md5_path(self) -> Path:
        """本地保存的上次更新时的 MD5 值。"""
        return self._tax_dir / "taxdump.tar.gz.md5"

    @property
    def _taxdmp_folder(self) -> Path:
        return self._tax_dir / "taxdmp"

    # ────────── 状态查询 ──────────

    @property
    def is_ready(self) -> bool:
        return os.path.exists(self.db_path)

    @property
    def is_building(self) -> bool:
        return self._is_building

    @property
    def build_progress(self) -> str:
        return self._build_progress

    def get_status(self) -> Dict[str, Any]:
        """返回数据库完整状态信息，供前端展示。"""
        status: Dict[str, Any] = {
            "ready": self.is_ready,
            "building": self._is_building,
            "progress": self._build_progress,
        }

        if self.is_ready:
            db_file = Path(self.db_path)
            stat = db_file.stat()
            status["fileSize"] = stat.st_size
            status["fileSizeMB"] = round(stat.st_size / (1024 * 1024), 1)
            status["lastModified"] = time.strftime(
                "%Y-%m-%d %H:%M:%S", time.localtime(stat.st_mtime)
            )
            # 用修改时间估算"过时天数"
            age_days = (time.time() - stat.st_mtime) / 86400
            status["ageDays"] = round(age_days, 1)

        # 本地 MD5
        if self._local_md5_path.exists():
            status["localMd5"] = self._local_md5_path.read_text().strip().split()[0]

        # taxdmp 原始文件信息
        if self._taxdmp_folder.exists():
            names_dmp = self._taxdmp_folder / "names.dmp"
            if names_dmp.exists():
                status["dumpDate"] = time.strftime(
                    "%Y-%m-%d", time.localtime(names_dmp.stat().st_mtime)
                )

        return status

    # ────────── ETE4 实例 ──────────

    @property
    def ncbi(self):
        if not hasattr(self._local, "ncbi"):
            if not self.is_ready:
                raise RuntimeError(
                    "Taxonomy sqlite database is not built yet. "
                    "Trigger download or compilation first."
                )
            try:
                self._ensure_ete4_path()
                from ete4.ncbi_taxonomy.ncbiquery import NCBITaxa  # type: ignore

                self._local.ncbi = NCBITaxa(dbfile=self.db_path, update=False)
                logger.info(f"ETE4 NCBITaxa initialized successfully using {self.db_path}.")
            except Exception as exc:
                logger.error(f"Failed to initialize NCBITaxa: {exc}")
                raise
        return self._local.ncbi

    # ────────── 构建 / 更新 ──────────

    def start_build_process(self):
        """首次构建：如果 taxa.sqlite 不存在，后台线程编译。"""
        if self.is_ready:
            return
        self._launch_build_thread(force_download=False, skip_if_same=False)

    def start_update_process(self, skip_if_same: bool = True):
        """
        在线更新：从 NCBI FTP 重新下载 taxdump.tar.gz 并重编译 taxa.sqlite。

        Args:
            skip_if_same: 若为 True，先比对远端 MD5。
                          若与本地一致则跳过下载+编译（智能增量检查）。
        """
        self._launch_build_thread(force_download=True, skip_if_same=skip_if_same)

    def check_for_update(self) -> Dict[str, Any]:
        """
        仅检查是否有更新可用（不触发下载/编译）。
        对比远端 MD5 和本地 MD5，返回检查结果。
        """
        result: Dict[str, Any] = {"hasUpdate": False, "localMd5": "", "remoteMd5": ""}
        try:
            local_md5 = ""
            if self._local_md5_path.exists():
                local_md5 = self._local_md5_path.read_text().strip().split()[0]
            result["localMd5"] = local_md5

            remote_md5 = self._fetch_remote_md5()
            result["remoteMd5"] = remote_md5
            result["hasUpdate"] = bool(remote_md5 and remote_md5 != local_md5)
        except Exception as exc:
            result["error"] = str(exc)
            logger.error(f"Check for update failed: {exc}")
        return result

    def _launch_build_thread(self, force_download: bool, skip_if_same: bool = False):
        with self._lock:
            if self._is_building:
                logger.warning("Taxonomy build already in progress, skipping.")
                return
            self._is_building = True
            self._build_progress = "准备中..."

        thread = threading.Thread(
            target=self._build_worker,
            args=(force_download, skip_if_same),
            daemon=True,
        )
        thread.start()

    def _build_worker(self, force_download: bool, skip_if_same: bool = False):
        """后台线程工作函数：MD5 预检（可选）+ 下载（可选）+ 编译 taxa.sqlite。"""
        try:
            self._ensure_ete4_path()

            taxdump_tgz = self._taxdump_tgz_path
            taxdmp_folder = self._taxdmp_folder

            # ── 步骤 0：MD5 智能增量检查 ──
            if force_download and skip_if_same:
                self._build_progress = "正在检查远端 MD5 ..."
                try:
                    remote_md5 = self._fetch_remote_md5()
                    local_md5 = ""
                    if self._local_md5_path.exists():
                        local_md5 = self._local_md5_path.read_text().strip().split()[0]

                    if remote_md5 and remote_md5 == local_md5:
                        self._build_progress = "已是最新版本，无需更新。"
                        logger.info(f"Taxonomy DB is up-to-date (MD5: {local_md5[:12]}...). Skipping.")
                        return
                    else:
                        logger.info(f"Update available: local={local_md5[:12] or 'N/A'} remote={remote_md5[:12]}")
                except Exception as md5_err:
                    logger.warning(f"MD5 pre-check failed ({md5_err}), proceeding with full download.")

            # ── 步骤 1：联网下载（仅 force_download 时） ──
            if force_download:
                self._build_progress = "正在从 NCBI FTP 下载 taxdump.tar.gz ..."
                logger.info(f"Downloading taxdump from {NCBI_TAXDUMP_URL} ...")
                self._download_taxdump(taxdump_tgz)
                logger.info("Download complete.")

                # 下载完成后，计算并保存本地 MD5
                self._save_local_md5(taxdump_tgz)

            # ── 步骤 2：如果只有 taxdmp/ 目录，打包为 tar.gz ──
            if not taxdump_tgz.exists() and taxdmp_folder.exists() and taxdmp_folder.is_dir():
                self._build_progress = "正在打包本地 taxdmp 目录..."
                logger.info("Packaging local taxdmp/ directory to taxdump.tar.gz ...")
                import tarfile
                with tarfile.open(taxdump_tgz, "w:gz") as tar:
                    for filename in os.listdir(taxdmp_folder):
                        filepath = taxdmp_folder / filename
                        if filepath.is_file():
                            tar.add(filepath, arcname=filename)
                logger.info("Packaging complete.")

            # ── 步骤 3：编译 SQLite ──
            self._build_progress = "正在编译 taxa.sqlite（可能耗时数分钟）..."
            logger.info(f"Building ETE4 taxonomy database -> {self.db_path} ...")

            from ete4.ncbi_taxonomy.ncbiquery import NCBITaxa  # type: ignore

            if taxdump_tgz.exists():
                tmp_ncbi = NCBITaxa(
                    dbfile=self.db_path, taxdump_file=str(taxdump_tgz), update=False
                )
            else:
                self._build_progress = "未找到本地数据，正在从 NCBI 在线下载..."
                logger.info("No local taxdump found. ETE4 will download from NCBI.")
                tmp_ncbi = NCBITaxa(dbfile=self.db_path, update=True)

            if not hasattr(self, "_local"):
                self._local = threading.local()
            self._local.ncbi = tmp_ncbi
            self._build_progress = "构建完成！"
            logger.info("Taxonomy DB built successfully.")
        except Exception as exc:
            self._build_progress = f"构建失败: {exc}"
            logger.error(f"Taxonomy DB build failed: {exc}")
        finally:
            self._is_building = False

    def _download_taxdump(self, dest_path: Path):
        """从 NCBI FTP 下载 taxdump.tar.gz，支持进度报告。"""
        import urllib.request

        # 先下载到临时文件，完成后替换
        tmp_path = dest_path.with_suffix(".tmp")
        try:
            req = urllib.request.Request(NCBI_TAXDUMP_URL)
            with urllib.request.urlopen(req, timeout=120) as response:
                total = int(response.headers.get("Content-Length", 0))
                downloaded = 0
                chunk_size = 256 * 1024  # 256 KB

                with open(tmp_path, "wb") as fout:
                    while True:
                        chunk = response.read(chunk_size)
                        if not chunk:
                            break
                        fout.write(chunk)
                        downloaded += len(chunk)
                        if total > 0:
                            pct = round(downloaded / total * 100, 1)
                            self._build_progress = f"下载中... {pct}% ({downloaded // 1024 // 1024}MB / {total // 1024 // 1024}MB)"

            # 下载完成，替换旧文件
            if dest_path.exists():
                dest_path.unlink()
            tmp_path.rename(dest_path)
        except Exception:
            if tmp_path.exists():
                tmp_path.unlink()
            raise

    def _fetch_remote_md5(self) -> str:
        """从 NCBI FTP 下载 taxdump.tar.gz.md5（几字节），提取 MD5 哈希值。"""
        import urllib.request
        req = urllib.request.Request(NCBI_TAXDUMP_MD5_URL)
        with urllib.request.urlopen(req, timeout=15) as response:
            content = response.read().decode("utf-8").strip()
            # 格式: "<md5hash>  taxdump.tar.gz"
            md5_hash = content.split()[0]
            return md5_hash

    def _save_local_md5(self, tgz_path: Path):
        """计算本地 taxdump.tar.gz 的 MD5 并保存到 .md5 文件。"""
        self._build_progress = "正在计算文件校验值..."
        md5 = hashlib.md5()
        with open(tgz_path, "rb") as fobj:
            while True:
                chunk = fobj.read(1024 * 1024)  # 1 MB
                if not chunk:
                    break
                md5.update(chunk)
        md5_hex = md5.hexdigest()
        self._local_md5_path.write_text(f"{md5_hex}  taxdump.tar.gz\n")
        logger.info(f"Saved local MD5: {md5_hex}")

    # ────────── 查询接口 ──────────

    def get_lineage_details(self, name_or_id: Any) -> List[Dict[str, str]]:
        """根据物种名或 taxid 返回完整谱系信息。"""
        if not self.is_ready:
            logger.warning("Attempted taxonomy lookup, but database is not ready.")
            return []

        try:
            if isinstance(name_or_id, str):
                if name_or_id.isdigit():
                    taxid = int(name_or_id)
                else:
                    name2id = self.ncbi.get_name_translator([name_or_id])
                    if not name2id:
                        return []
                    taxid = name2id[name_or_id][0]
            else:
                taxid = int(name_or_id)

            lineage_ids = self.ncbi.get_lineage(taxid)
            names = self.ncbi.get_taxid_translator(lineage_ids)
            ranks = self.ncbi.get_rank(lineage_ids)

            result = []
            for tid in lineage_ids:
                result.append({
                    "taxid": tid,
                    "rank": ranks.get(tid, "no rank"),
                    "name": names.get(tid, f"Unknown_{tid}"),
                })
            return result
        except Exception as exc:
            logger.error(f"Error fetching lineage for {name_or_id}: {exc}")
            return []

    # ────────── 内部工具 ──────────

    def _ensure_ete4_path(self):
        """确保 vendor/ete4 在 sys.path 中。"""
        vendor_path = os.path.join(
            os.path.dirname(__file__), "..", "..", "vendor", "ete4"
        )
        if os.path.exists(vendor_path) and vendor_path not in sys.path:
            sys.path.insert(0, vendor_path)


# ────────── 单例入口 ──────────

_provider: Optional[TaxonomyProvider] = None

def get_taxonomy_provider() -> TaxonomyProvider:
    """获取 TaxonomyProvider 全局单例。"""
    global _provider
    if _provider is None:
        _provider = TaxonomyProvider()
    return _provider
