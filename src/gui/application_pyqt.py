"""
PyQt6应用程序主类
"""

import sys

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
        print("Creating QApplication...")
        # 创建QApplication
        self.app = QApplication(sys.argv)
        self.app.setApplicationName("NCBI BLAST 查询工具")
        
        print("Creating MainWindow...")
        # 创建主窗口
        self.main_window = MainWindow()
        print("MainWindow created successfully")
    
    def run(self):
        """
        运行应用程序
        """
        # 显示主窗口
        self.main_window.show()
        
        # 确保窗口获得焦点并处于前台
        self.main_window.raise_()
        self.main_window.activateWindow()
        
        print(f"Main window geometry: {self.main_window.geometry()}")
        print(f"Main window visible: {self.main_window.isVisible()}")
        
        return self.app.exec()


def main():
    """
    PyQt应用程序入口
    """
    app = Application()
    return app.run()


if __name__ == "__main__":
    sys.exit(main())