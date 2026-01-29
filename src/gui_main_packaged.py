#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
PyQt GUI主程序入口 - 用于打包版本
负责初始化和启动PyQt GUI应用程序
"""

import os
import sys
import traceback
import logging
import faulthandler
from datetime import datetime

# 确保 log 目录存在
log_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'logs')
if getattr(sys, 'frozen', False):
    # 如果是打包环境，logs 在可执行文件同级
    log_dir = os.path.join(os.path.dirname(sys.executable), 'logs')

os.makedirs(log_dir, exist_ok=True)

# 1. 启用 Fault Handler 以捕获硬崩溃 (如 0xC0000409)
try:
    crash_log_path = os.path.join(log_dir, 'crash_dump.log')
    crash_log = open(crash_log_path, 'wb', buffering=0) 
    faulthandler.enable(file=crash_log, all_threads=True)
except Exception as e:
    print(f"Failed to enable faulthandler: {e}")

# 2. 配置日志记录到文件
log_filename = os.path.join(log_dir, f"application_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")
logging.basicConfig(
    filename=log_filename,
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s',
    encoding='utf-8'
)

# 3. 双向重定向 stdout/stderr: 既输出到控制台(如有)，也写入日志文件
class DualLogger:
    def __init__(self, original_stream, logger_func):
        self.original_stream = original_stream
        self.logger_func = logger_func

    def write(self, message):
        if message.strip():
            self.logger_func(message.strip())
        # 尝试写入原始流 (如果有)
        try:
            if self.original_stream and not self.original_stream.closed:
                self.original_stream.write(message)
                self.original_stream.flush()
        except Exception:
            pass

    def flush(self):
        try:
            if self.original_stream and not self.original_stream.closed:
                self.original_stream.flush()
        except Exception:
            pass

    def isatty(self):
        try:
            return self.original_stream.isatty()
        except Exception:
            return False
            
sys.stdout = DualLogger(sys.stdout, logging.info)
sys.stderr = DualLogger(sys.stderr, logging.error)

print(f"Logging initialized to {log_filename}")
print("Starting GUI application...")  # 添加调试输出

try:
    # 动态添加必要的路径
    if getattr(sys, 'frozen', False):
        # 如果是PyInstaller打包的可执行文件
        application_path = os.path.dirname(sys.executable)
        internal_path = os.path.join(application_path, "_internal")
        
        # 确保所有必要的路径都在sys.path中
        paths_to_add = [
            application_path,  # 应用程序目录
            internal_path,     # 内部库目录
            os.path.join(internal_path, "src"),  # src目录
            os.path.join(internal_path, "src", "gui"),  # gui目录
            os.path.join(internal_path, "src", "utils"),  # utils目录
            os.path.join(internal_path, "src", "utils", "translation"),  # translation目录
            os.path.join(internal_path, "src", "blast"),  # blast目录
        ]
        
        for path in paths_to_add:
            if os.path.exists(path) and path not in sys.path:
                sys.path.insert(0, path)
    else:
        # 开发环境路径
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if project_root not in sys.path:
            sys.path.insert(0, project_root)

    # 首先进行环境检查
    print("Checking environment...")
    from src.utils.environment_checker import check_environment
    
    if not check_environment():
        print("Environment check failed. Exiting...")
        sys.exit(1)
    
    print("Environment check passed. Starting application...")

    print("Importing main function...")
    
    def try_import_main():
        # 尝试直接从src.gui导入
        try:
            from src.gui.application_pyqt import main
            print("Successfully imported from src.gui.application_pyqt")
            return main
        except ImportError as e1:
            print(f"Import error from src.gui: {e1}")
            # 如果上面失败，尝试从当前目录导入
            try:
                # 添加当前目录到路径
                current_dir = os.path.dirname(os.path.abspath(__file__))
                if current_dir not in sys.path:
                    sys.path.insert(0, current_dir)
                
                from application_pyqt import main
                print("Successfully imported from application_pyqt")
                return main
            except ImportError as e2:
                print(f"Final import error: {e2}")
                traceback.print_exc()
                raise

    main = try_import_main()

    print("Calling main function...")
    if __name__ == "__main__":
        try:
            # 在调用main之前，先检查是否有GUI显示问题
            import ctypes
            import platform
            
            # 在Windows上尝试修复DPI缩放问题
            if platform.system() == "Windows":
                try:
                    # 启用高DPI缩放感知
                    ctypes.windll.shcore.SetProcessDpiAwareness(1)
                except Exception as dpi_error:
                    print(f"Could not set DPI awareness: {dpi_error}")
            
            # 尝试实例化Application类而不立即运行，以检查初始化错误
            print("Attempting to create Application instance...")
            from src.gui.application_pyqt import Application
            app_instance = Application()
            print("Application instance created successfully")
            
            # 现在运行应用
            result = app_instance.run()
            print(f"Main function returned: {result}")
            sys.exit(result)
        except Exception as e:
            print(f"Error occurred in main function: {e}")
            import traceback
            traceback.print_exc()
            print("主界面无法启动，可能的原因：")
            print("1. 缺少必要的GUI库（如PyQt6）")
            print("2. 显示驱动或图形界面环境问题")
            print("3. 权限问题导致无法创建窗口")
            print("4. 其他GUI初始化错误")
            input("Press Enter to exit...")  # 添加暂停，以便查看错误信息
            sys.exit(1)

except Exception as e:
    print(f"Failed to start GUI application: {e}")
    print("Traceback:")
    traceback.print_exc()
    input("Press Enter to exit...")  # 添加暂停，以便查看错误信息
    sys.exit(1)