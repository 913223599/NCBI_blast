import os
import sys
from pathlib import Path


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
    MAX_THREADS = os.cpu_count() or 4

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
        # Check Tree Tools first (most commonly used)
        tree_path = cls.TREE_BIN_DIR / tool_name
        if tree_path.exists():
            return tree_path

        # Fallback to system PATH
        import shutil
        system_path = shutil.which(tool_name)
        if system_path:
            return Path(system_path)

        raise FileNotFoundError(f"Tool not found: {tool_name}")

    @classmethod
    def ensure_directories(cls):
        """Ensure necessary output directories exist."""
        cls.RESULTS_DIR.mkdir(parents=True, exist_ok=True)
