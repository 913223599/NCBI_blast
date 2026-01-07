#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
PyQt GUI主程序入口
负责初始化和启动PyQt GUI应用程序
"""

import sys
import os
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

    # 添加项目根目录到Python路径
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # 修改路径以正确获取项目根目录
    print(f"Project root: {project_root}")
    
    # 确保项目根目录在Python路径中
    if project_root not in sys.path:
        sys.path.insert(0, project_root)
    
    # 如果是在打包后的环境中，添加内部目录到路径
    if getattr(sys, 'frozen', False):
        # 如果是PyInstaller打包的可执行文件
        application_path = os.path.dirname(sys.executable)
        internal_path = os.path.join(application_path, "_internal")
        if os.path.exists(internal_path) and internal_path not in sys.path:
            sys.path.insert(0, internal_path)
        # 同时将src目录添加到路径
        src_path = os.path.join(application_path, "_internal", "src")
        if os.path.exists(src_path) and src_path not in sys.path:
            sys.path.insert(0, src_path)
    else:
        # 如果是在开发环境中运行
        if project_root not in sys.path:
            sys.path.insert(0, project_root)
        src_path = os.path.join(project_root, "src")
        if src_path not in sys.path:
            sys.path.insert(0, src_path)
    
    print("Importing main function...")
    # 尝试不同的导入方式
    try:
        from gui.application_pyqt import main
    except ImportError as e:
        print(f"Import error: {e}")
        # 尝试从src.gui导入
        try:
            from src.gui.application_pyqt import main
        except ImportError as e2:
            print(f"Alternative import error: {e2}")
            # 如果上述都失败，尝试动态添加路径并导入
            try:
                # 确保src路径在sys.path中
                current_dir = os.path.dirname(os.path.abspath(__file__))  # src目录
                gui_dir = os.path.join(current_dir, "gui")
                if gui_dir not in sys.path:
                    sys.path.insert(0, gui_dir)
                    sys.path.insert(0, current_dir)
                
                from application_pyqt import main
            except ImportError as e3:
                print(f"Final import error: {e3}")
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