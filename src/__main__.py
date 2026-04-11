"""
使src包可以直接运行
默认启动 GUI 模式
"""


# 添加项目根目录到路径 (如果需要非 -m 启动支持)
# sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def main():
    """应用程序入口，默认启动 GUI"""
    # ─── 环境变量配置 (ETE4 数据重定向) ──────────────────
    import os
    from pathlib import Path
    PROJECT_ROOT = Path(__file__).resolve().parent.parent
    os.environ["XDG_DATA_HOME"] = str(PROJECT_ROOT / "database" / "taxonomy")
    os.environ["XDG_CONFIG_HOME"] = str(PROJECT_ROOT / "database" / "taxonomy")
    os.environ["XDG_CACHE_HOME"] = str(PROJECT_ROOT / "database" / "taxonomy")

    # 0. 配置基础日志格式
    import logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        datefmt='%H:%M:%S'
    )
    
    # 词库预热：在 GUI 加载前确保词库已迁移并就绪
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