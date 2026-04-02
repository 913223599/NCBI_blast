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
    # 词库预热：在 GUI 加载前确保词库已迁移并就绪
    # 1. 初始化路径环境
    sys.path.append(os.path.dirname(os.path.abspath(__file__)))
    
    # 2. 静默通知用户数据加载中
    try:
        from .utils.translation.translation_data_manager import get_translation_data_manager
        mgr = get_translation_data_manager()
        mgr.preload()
    except Exception as e:
        print(f"[Warning] 词库预加载失败: {e}")

    # 3. 启动 GUI
    from .gui.application_pyqt import main as gui_main
    gui_main()


if __name__ == "__main__":
    main()