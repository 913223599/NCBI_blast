"""
PyQt应用程序模块
负责启动和管理GUI应用程序
"""

import os
import sys

# 添加src目录到Python路径
src_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if src_path not in sys.path:
    sys.path.insert(0, src_path)

from PyQt6.QtWidgets import QApplication
from src.gui.main_window_pyqt import MainWindow


class Application:
    """
    PyQt应用程序类
    负责启动和管理GUI应用程序
    """
    
    def __init__(self):
        """
        初始化应用程序
        """
        # 创建QApplication
        self.app = QApplication(sys.argv)
        self.app.setApplicationName("NCBI BLAST 查询工具")
        
        # 创建主窗口
        self.main_window = MainWindow()
    
    def run(self):
        """
        运行应用程序
        """
        # 显示主窗口
        self.main_window.show()
        
        # 启动GUI主循环
        sys.exit(self.app.exec())


def main():
    """
    PyQt应用程序入口
    """
    app = Application()
    app.run()


if __name__ == "__main__":
    main()