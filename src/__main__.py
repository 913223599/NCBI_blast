"""
使src包可以直接运行
默认启动 GUI 模式
"""

import os
import sys

# 添加src目录到Python路径
sys.path.append(os.path.dirname(os.path.abspath(__file__)))


def main():
    """应用程序入口，默认启动 GUI"""
    from .gui.application_pyqt import main as gui_main
    gui_main()


if __name__ == "__main__":
    main()