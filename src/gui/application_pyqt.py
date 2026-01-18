"""
PyQt6应用程序主类
"""

import sys
import os
from PyQt6.QtWidgets import QApplication, QWizard

from src.gui.main_window_pyqt import MainWindow
from src.utils.config_manager import get_config_manager
from src.gui.widgets.setup_wizard import SetupWizard

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
        self.app = QApplication(sys.argv)
        self.app.setApplicationName("NCBI BLAST 查询工具")
        
        self.config_manager = get_config_manager()
        
        # 检查是否需要运行配置向导
        if not self.config_manager.get_config_value('setup_completed', False):
            wizard = SetupWizard()
            if wizard.exec() == QWizard.DialogCode.Accepted:
                self._initialize_main_window()
            else:
                sys.exit(0) # 用户取消向导，退出程序
        else:
            self._initialize_main_window()
            
    def _initialize_main_window(self):
        """初始化并显示主窗口"""
        # 将配置的 BLAST 路径添加到环境变量
        blast_path = self.config_manager.get_config_value('blast_bin_path')
        if blast_path:
            os.environ["PATH"] = blast_path + os.pathsep + os.environ.get("PATH", "")
            print(f"BLAST path added to environment: {blast_path}")

        print("Creating MainWindow...")
        self.main_window = MainWindow()
        print("MainWindow created successfully")
        
    def run(self):
        """
        运行应用程序
        """
        if not hasattr(self, 'main_window'):
            return 1 # 如果向导被取消，主窗口不会被创建

        self.main_window.show()
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