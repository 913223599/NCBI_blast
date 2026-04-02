"""
PyQt6应用程序主类
"""

import sys
import os
import psutil
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
        # 深度解决 Windows + NVIDIA/AMD 环境下的 GPU 闪烁 (Flickering) 问题
        # 1. 禁用 DirectComposition 和 MPO (这是闪烁的头号元凶)
        # 2. 强制使用 D3D11 后端
        os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = (
            "--ignore-gpu-blocklist "
            "--enable-gpu-rasterization "
            "--enable-threaded-compositing "
            "--disable-direct-composition "
            "--disable-gpu-compositing "
            "--disable-background-timer-throttling "
            "--disable-features=Translate,MojoVideoEncodeAccelerator"
        )
        
        # 强制 Qt 使用桌面级 D3D 渲染，避免软件层与硬件层的频率冲突
        if sys.platform == 'win32':
             os.environ["QT_OPENGL"] = "desktop"
             # 补充：禁止底层叠加层
             os.environ["QT_ENABLE_HIGHDPI_SCALING"] = "1"
        
        # 启用高性能 UI 渲染属性
        from PyQt6.QtCore import Qt
        QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
        # Note: AA_EnableHighDpiScaling and AA_UseHighDpiPixmaps are default in PyQt6 and removed from enum.
        
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
        
        exit_code = self.app.exec()
        
        # 退出前同步翻译数据库（冷热备份策略）
        try:
            from src.utils.translation.translation_data_manager import get_translation_data_manager
            manager = get_translation_data_manager()
            manager.prepare_shutdown()
        except Exception as e:
            print(f"退出同步翻译数据库时出错: {e}")

        # 退出前清理所有子进程
        self._cleanup_processes()
        
        return exit_code

    def _cleanup_processes(self):
        """清理当前进程及其子进程"""
        try:
            current_process = psutil.Process(os.getpid())
            children = current_process.children(recursive=True)
            for child in children:
                try:
                    child.terminate()
                except psutil.NoSuchProcess:
                    pass
            
            # 等待子进程结束
            _, alive = psutil.wait_procs(children, timeout=3)
            for p in alive:
                try:
                    p.kill() # 强制杀死
                except psutil.NoSuchProcess:
                    pass
                    
            print("所有子进程已清理")
        except Exception as e:
            print(f"清理进程时出错: {e}")


def main():
    """
    PyQt应用程序入口
    """
    app = Application()
    return app.run()


if __name__ == "__main__":
    sys.exit(main())
