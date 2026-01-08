#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
PyQt GUI主程序入口 - 用于打包版本
负责初始化和启动PyQt GUI应用程序
"""

import os
import sys
import traceback

# 修复在--windowed模式下丢失stdin/stdout的问题
if not hasattr(sys, 'stdout'):
    sys.stdout = open(os.devnull, 'w')
if not hasattr(sys, 'stderr'):
    sys.stderr = open(os.devnull, 'w')
if not hasattr(sys, 'stdin'):
    sys.stdin = open(os.devnull, 'r')

print("Starting GUI application...")  # 添加调试输出

try:
    # 首先进行环境检查
    print("Checking environment...")
    from src.utils.environment_checker import check_environment
    
    if not check_environment():
        print("Environment check failed. Exiting...")
        sys.exit(1)
    
    print("Environment check passed. Starting application...")

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

    print("Importing main function...")
    
    # 直接尝试导入application_pyqt模块
    try:
        # 尝试直接从src.gui导入
        from src.gui.application_pyqt import main
        print("Successfully imported from src.gui.application_pyqt")
    except ImportError as e:
        print(f"Import error from src.gui: {e}")
        # 如果上面失败，尝试直接导入
        try:
            import src.gui.application_pyqt
            main = src.gui.application_pyqt.main
            print("Successfully imported main function via module reference")
        except ImportError as e2:
            print(f"Second import error: {e2}")
            # 如果还是失败，尝试从当前目录导入
            try:
                # 添加当前目录到路径
                current_dir = os.path.dirname(os.path.abspath(__file__))
                if current_dir not in sys.path:
                    sys.path.insert(0, current_dir)
                
                import gui.application_pyqt
                main = gui.application_pyqt.main
                print("Successfully imported from gui.application_pyqt")
            except ImportError as e3:
                print(f"Final import error: {e3}")
                traceback.print_exc()
                raise

    print("Calling main function...")
    if __name__ == "__main__":
        sys.exit(main())

except Exception as e:
    print(f"Failed to start GUI application: {e}")
    print("Traceback:")
    traceback.print_exc()
    input("Press Enter to exit...")  # 添加暂停，以便查看错误信息
    sys.exit(1)