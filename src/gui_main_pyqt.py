"""
GUI应用程序主入口点（PyQt6版本）
"""

import sys
import os
from pathlib import Path

# 添加项目根目录到Python路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.gui.application_pyqt import main

if __name__ == "__main__":
    sys.exit(main())