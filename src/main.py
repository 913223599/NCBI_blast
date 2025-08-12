"""
主程序入口
NCBI BLAST查询和结果分析工具
"""

import os
import sys
from pathlib import Path

# 添加项目根目录到Python路径
project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

try:
    from src.gui.main_window_pyqt import create_main_window
    GUI_AVAILABLE = True
except ImportError:
    GUI_AVAILABLE = False



def main():
    """主函数"""
    print("NCBI BLAST查询和结果分析工具")
    print("=" * 50)


if __name__ == "__main__":
    main()