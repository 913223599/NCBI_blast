"""
使 src 包可以直接运行
新架构入口为 electron-shell/main.js (Electron 主进程)
本文件仅保留 FastAPI Sidecar 的 Python 端启动逻辑
"""

def main():
    """应用程序入口：启动 FastAPI Sidecar 后端服务"""
    # ─── 环境变量配置 (ETE4 数据重定向) ──────────────────
    import os
    from pathlib import Path
    PROJECT_ROOT = Path(__file__).resolve().parent.parent
    os.environ["XDG_DATA_HOME"] = str(PROJECT_ROOT / "database" / "taxonomy")
    os.environ["XDG_CONFIG_HOME"] = str(PROJECT_ROOT / "database" / "taxonomy")
    os.environ["XDG_CACHE_HOME"] = str(PROJECT_ROOT / "database" / "taxonomy")

    # 配置基础日志格式
    import logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        datefmt='%H:%M:%S'
    )
    
    # 词库预热：确保词库已迁移并就绪
    try:
        from .utils.translation.translation_data_manager import get_translation_data_manager
        manager = get_translation_data_manager()
        manager.preload()
    except Exception as preload_error:
        print(f"[Warning] 词库预加载失败: {preload_error}")

    # 启动 FastAPI 后端服务
    from .backend.api_server import start_server
    start_server()


if __name__ == "__main__":
    main()