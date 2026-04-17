import logging
import os
import shutil
import sys
from pathlib import Path
from typing import Dict, Any

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

    # Remote Databases Registry (Loaded dynamically from database/registry.json)
    @classmethod
    def get_remote_registry(cls) -> Dict[str, Any]:
        registry_path = cls.DATABASE_ROOT / "registry.json"
        if not registry_path.exists():
            return {}
        try:
            import json
            with open(registry_path, 'r', encoding='utf-8') as f:
                return json.load(f).get("remotes", {})
        except Exception as e:
            logger.error(f"Failed to load database registry: {e}")
            return {}

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
