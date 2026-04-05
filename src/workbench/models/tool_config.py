import os
import sys
from pathlib import Path
import shutil
import logging

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
