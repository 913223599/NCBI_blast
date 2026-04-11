import sys
import os
from pathlib import Path

# Add project root to sys.path
project_root = Path(r"D:\NCBI blast")
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

print(f"Current Working Directory: {os.getcwd()}")
print(f"Python sys.path: {sys.path[:3]}")

try:
    from src.workbench.wrappers.base_wrapper import BaseWrapper
    print("SUCCESS: Imported BaseWrapper")
except ImportError as e:
    print(f"FAILURE: Could not import BaseWrapper: {e}")

try:
    from src.workbench.wrappers.tree_factory import TreeFactory
    print("SUCCESS: Imported TreeFactory")
except ImportError as e:
    print(f"FAILURE: Could not import TreeFactory: {e}")
