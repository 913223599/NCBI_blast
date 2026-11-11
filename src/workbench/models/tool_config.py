import json
import logging
import os
import shutil
import sys
from pathlib import Path
from typing import Dict, Any, Optional

logger = logging.getLogger("ToolConfig")


class ToolConfig:
    """
    Central configuration for NCBI Workbench tools.
    Manages paths to local binaries and validates environment.
    """

    # Base paths
    PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
    TOOLS_ROOT = PROJECT_ROOT / "tools" / "ncbi_dist" / "bin"
    TREE_BIN_DIR = TOOLS_ROOT / "tree-tools"

    # Output directories
    RESULTS_DIR = PROJECT_ROOT / "results"
    ASSEMBLY_RESULTS_DIR = RESULTS_DIR / "assembly"

    # Assembly / 16S Databases Configuration
    DATABASE_ROOT = PROJECT_ROOT / "database"
    # 历史遗留：部分安装把参考库放进了 database/database 之下（多套了一层）。
    # 读取时统一通过 get_db_dir() 解析，两处均可命中，避免"库存在却显示未部署"。
    LEGACY_DATABASE_ROOT = DATABASE_ROOT / "database"
    AMPLICON_DATABASES = {
        "silva": DATABASE_ROOT / "16s" / "silva_138.fasta",
        "greengenes": DATABASE_ROOT / "16s" / "gg_13_8.fasta",
        "rdp": DATABASE_ROOT / "16s" / "rdp_train_18.fasta"
    }

    # Common Primers (V3-V4 etc)
    PRIMERS = {
        "V3-V4_F": "CCTACGGGNGGCWGCAG",
        "V3-V4_R": "GACTACHVGGGTATCTAATCC"
    }

    # ------------------------------------------------------------------
    # 配置与路径解析
    # ------------------------------------------------------------------
    @classmethod
    def get_config(cls) -> Dict[str, Any]:
        """读取运行时配置 (config.json)，缺失时回退到 config.default.json"""
        for name in ("config.json", "config.default.json"):
            path = cls.PROJECT_ROOT / name
            if not path.exists():
                continue
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Failed to load {name}: {e}")
        return {}

    @classmethod
    def _dir_has_content(cls, path: Path) -> bool:
        """目录存在且至少含一个条目（空目录视为未部署）"""
        try:
            if not path.exists() or not path.is_dir():
                return False
            next(iter(path.iterdir()))
            return True
        except StopIteration:
            return False
        except OSError:
            return False

    @classmethod
    def get_db_dir(cls, rel_folder: str) -> Path:
        """
        解析数据库物理目录（唯一权威入口）。

        优先 database/<rel_folder>；若该目录缺失或为空，则回退到历史遗留的
        database/database/<rel_folder>。这样无论历史安装是否多套了一层目录，
        都能连接到同一份已下载的库。
        """
        rel = Path(str(rel_folder).replace("\\", "/"))
        primary = cls.DATABASE_ROOT / rel
        legacy = cls.LEGACY_DATABASE_ROOT / rel
        if cls._dir_has_content(primary):
            return primary
        if cls._dir_has_content(legacy):
            return legacy
        return primary

    @classmethod
    def resolve_bio_tool(cls, tool_name: str) -> Optional[Path]:
        """
        定位 BLAST+ 等生物信息可执行文件。

        顺序：config.json 的 blast_bin_path -> 项目内置 bin -> NCBI 安装目录
        (自动挑选最高版本，避免配置里写死旧版本号) -> 系统 PATH。
        """
        exe = f"{tool_name}.exe" if os.name == "nt" else tool_name
        candidates = []

        bin_dir = str((cls.get_config() or {}).get("blast_bin_path") or "").strip()
        if bin_dir:
            configured = Path(bin_dir)
            candidates.extend([configured / exe, configured / tool_name])

        candidates.extend([
            cls.TOOLS_ROOT / exe,
            cls.TOOLS_ROOT / tool_name,
            cls.PROJECT_ROOT / "vendor" / "blast" / "bin" / exe,
            cls.PROJECT_ROOT / "vendor" / "ncbi-blast" / "bin" / exe,
        ])

        if os.name == "nt":
            ncbi_root = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "NCBI"
            if ncbi_root.exists():
                def _version_key(p: Path):
                    import re
                    m = re.search(r"blast-([0-9]+(?:\.[0-9]+)*)", p.name)
                    return tuple(int(x) for x in m.group(1).split(".")) if m else ()

                for ver_dir in sorted(ncbi_root.glob("blast-*"), key=_version_key, reverse=True):
                    candidates.append(ver_dir / "bin" / exe)

        for candidate in candidates:
            try:
                if candidate.exists():
                    return candidate
            except OSError:
                continue

        found = shutil.which(tool_name)
        return Path(found) if found else None

    # Remote Databases Registry (Loaded dynamically from database/registry.json)
    @classmethod
    def get_remote_registry(cls) -> Dict[str, Any]:
        """
        加载数据库注册表。

        主注册表 (database/registry.json) 优先；同时合并历史遗留目录下的注册表，
        使 Swiss-Prot / CDD / VFDB / CARD / DefenseFinder 等已在磁盘上的库也能被
        实例化、显示状态并参与注释，而不是"库有文件、界面却没有条目"。
        """
        merged: Dict[str, Any] = {}
        sources = [cls.DATABASE_ROOT / "registry.json", cls.LEGACY_DATABASE_ROOT / "registry.json"]
        for registry_path in sources:
            if not registry_path.exists():
                continue
            try:
                with open(registry_path, "r", encoding="utf-8") as f:
                    remotes = (json.load(f) or {}).get("remotes", {}) or {}
            except Exception as e:
                logger.error(f"Failed to load database registry {registry_path}: {e}")
                continue
            for db_id, config in remotes.items():
                merged.setdefault(db_id, config)
        return merged

    @classmethod
    def sync_registry(cls) -> bool:
        """将合并后的注册表回写主 registry.json（仅在内容变化时），保证版本号可持久化"""
        merged = cls.get_remote_registry()
        if not merged:
            return False
        target = cls.DATABASE_ROOT / "registry.json"
        try:
            existing = {}
            if target.exists():
                with open(target, "r", encoding="utf-8") as f:
                    existing = (json.load(f) or {}).get("remotes", {}) or {}
            if set(existing.keys()) >= set(merged.keys()):
                return False
            target.parent.mkdir(parents=True, exist_ok=True)
            with open(target, "w", encoding="utf-8") as f:
                json.dump({"remotes": merged}, f, ensure_ascii=False, indent=2)
            logger.info(f"Registry merged and persisted: {sorted(merged.keys())}")
            return True
        except Exception as e:
            logger.warning(f"Failed to persist merged database registry: {e}")
            return False

    # Performance
    MAX_THREADS = max(1, (os.cpu_count() or 4) - 1)

    # Initialize environment for vendor tools
    @classmethod
    def initialize_env(cls):
        """Setup special environment variables for vendor modules (e.g. ETE4)"""
        # 1. Fix ETE4 HOME requirement on Windows
        if os.name == 'nt' and 'HOME' not in os.environ:
            os.environ['HOME'] = os.environ.get('USERPROFILE', '')
            
        # 2. Inject vendor python paths
        vendor_ete4 = cls.PROJECT_ROOT / "vendor" / "ete4"
        if vendor_ete4.exists() and str(vendor_ete4) not in sys.path:
            sys.path.insert(0, str(vendor_ete4))
            # Also ensure sub-ete4 is reachable if it's nested
            if (vendor_ete4 / "ete4").exists():
                 # Should already be reachable if parent is added
                 pass

    @classmethod
    def get_tool_path(cls, tool_name: str) -> Path:
        """
        Locate a tool binary by name in Tree tools directory or system PATH.

        Args:
            tool_name: Name of the executable (e.g., 'makeDistTree.exe')

        Returns:
            Path object to the executable.

        Raises:
            FileNotFoundError: If the tool is not found.
        """
        # 1. Check project local bin
        local_bin = cls.PROJECT_ROOT / "src" / "workbench" / "bin" / tool_name
        if local_bin.exists():
            return local_bin

        # 2. Check Vendor Directory (Auto-search subfolders for the binary)
        vendor_root = cls.PROJECT_ROOT / "vendor"
        if vendor_root.exists():
            # Common subfolders for binaries in vendor/
            for vendor_subdir in vendor_root.iterdir():
                if vendor_subdir.is_dir():
                    candidate = vendor_subdir / tool_name
                    if candidate.exists():
                        return candidate

        # 3. Check Tree Tools (Legacy / native ones)
        tree_path = cls.TREE_BIN_DIR / tool_name
        if tree_path.exists():
            return tree_path

        # Fallback to system PATH
        system_path = shutil.which(tool_name)
        if system_path:
            return Path(system_path)

        raise FileNotFoundError(f"Tool not found: {tool_name}")

    @classmethod
    def ensure_directories(cls):
        """Ensure necessary output directories exist."""
        cls.RESULTS_DIR.mkdir(parents=True, exist_ok=True)
