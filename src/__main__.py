"""
使src包可以直接运行
支持命令行和GUI模式
"""

import os
import sys

# 添加src目录到Python路径
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

def main():
    # 检查是否指定了--gui参数
    if "--gui" in sys.argv:
        # 运行GUI模式
        from .gui.application_pyqt import main as gui_main
        gui_main()

if __name__ == "__main__":
    main()