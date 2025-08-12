#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
PyQt GUI主程序入口
负责初始化和启动PyQt GUI应用程序
"""

import sys
import os
import traceback

print("Starting GUI application...")  # 添加调试输出

try:
    # 添加项目根目录到Python路径
    project_root = os.path.dirname(os.path.abspath(__file__))
    if project_root not in sys.path:
        sys.path.insert(0, project_root)
    
    print(f"Project root: {project_root}")  # 添加调试输出
    
    from src.gui.application_pyqt import main
    
    if __name__ == '__main__':
        print("Calling main function...")  # 添加调试输出
        main()
        
except Exception as e:
    print(f"Failed to start GUI application: {e}")
    traceback.print_exc()
    sys.exit(1)