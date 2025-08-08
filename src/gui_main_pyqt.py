"""
PyQt GUI主程序入口
用于启动PyQt版本的NCBI BLAST查询工具
"""

import os
import sys

# 添加项目根目录到Python路径
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from src.gui.application_pyqt import main

if __name__ == "__main__":
    main()