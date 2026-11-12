# -*- coding: utf-8 -*-
"""
Python 环境依赖自动校验与国内镜像源补齐模块
职责：
1. 快速检查 requirements.txt 中定义的所有核心模块是否存在。
2. 若发现缺失依赖，自动使用国内清华/阿里镜像源加速安装。
3. 遵循无 Emoji 规范与 UTF-8 编码。
"""

import sys
import subprocess
import importlib.util
from pathlib import Path

# 强制 UTF-8 标准输出
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

# 包名称与 import 导入名称映射表（与 src/utils/verify_and_install_deps.py 保持一致）
MODULE_IMPORT_MAP = {
    "fastapi": "fastapi",
    "uvicorn": "uvicorn",
    "pydantic": "pydantic",
    "biopython": "Bio",
    "numpy": "numpy",
    "pandas": "pandas",
    "openpyxl": "openpyxl",
    "python-docx": "docx",
    "requests": "requests",
    "beautifulsoup4": "bs4",
    "lxml": "lxml",
    "psutil": "psutil",
    "matplotlib": "matplotlib",
    "python-dotenv": "dotenv",
    "PyYAML": "yaml",
    "websockets": "websockets",
    "watchfiles": "watchfiles",
    "anyio": "anyio",
    "starlette": "starlette",
    "python-multipart": "multipart",
    "openai": "openai",
    "dashscope": "dashscope",
    "playwright": "playwright",
    "scipy": "scipy",
    "networkx": "networkx",
}

# 国内镜像源配置
PRIMARY_INDEX_URL = "https://pypi.tuna.tsinghua.edu.cn/simple"
PRIMARY_TRUSTED_HOST = "pypi.tuna.tsinghua.edu.cn"
FALLBACK_INDEX_URL = "https://mirrors.aliyun.com/pypi/simple/"
FALLBACK_TRUSTED_HOST = "mirrors.aliyun.com"


def check_missing_modules():
    """检测缺失的依赖模块"""
    missing = []
    for pkg_name, import_name in MODULE_IMPORT_MAP.items():
        try:
            spec = importlib.util.find_spec(import_name)
            if spec is None:
                missing.append(pkg_name)
        except Exception:
            missing.append(pkg_name)
    return missing


def install_requirements(req_file: Path):
    """使用国内镜像源安装依赖"""
    print(f"[INFO] 正在通过清华镜像源 ({PRIMARY_INDEX_URL}) 下载补齐 Python 依赖...")
    cmd = [
        sys.executable,
        "-m",
        "pip",
        "install",
        "-r",
        str(req_file),
        "-i",
        PRIMARY_INDEX_URL,
        "--trusted-host",
        PRIMARY_TRUSTED_HOST,
        "--extra-index-url",
        FALLBACK_INDEX_URL,
    ]

    try:
        ret = subprocess.run(cmd, check=False)
        if ret.returncode != 0:
            print("[WARN] 清华源安装出现异常，尝试切换至阿里云备用镜像源...")
            cmd_fallback = [
                sys.executable,
                "-m",
                "pip",
                "install",
                "-r",
                str(req_file),
                "-i",
                FALLBACK_INDEX_URL,
                "--trusted-host",
                FALLBACK_TRUSTED_HOST,
            ]
            ret_fallback = subprocess.run(cmd_fallback, check=False)
            if ret_fallback.returncode != 0:
                print(f"[ERROR] 依赖安装失败，退出码: {ret_fallback.returncode}")
                return False
        return True
    except Exception as e:
        print(f"[ERROR] 执行 pip install 发生异常: {e}")
        return False


def main():
    project_root = Path(__file__).resolve().parent.parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

    try:
        from src.utils.verify_and_install_deps import main as primary_main

        return int(primary_main())
    except ImportError:
        pass

    req_file = project_root / "requirements.txt"

    if not req_file.exists():
        print(f"[WARN] 未找到 requirements.txt 文件: {req_file}")
        return 0

    missing = check_missing_modules()
    if not missing:
        print("[INFO] Python 所有核心依赖包已完整就绪。")
    else:
        print(f"[WARN] 检测到缺失的 Python 依赖包 ({len(missing)}项): {', '.join(missing)}")
        success = install_requirements(req_file)
        if not success:
            return 1

        # 安装完成后再次验证
        remaining_missing = check_missing_modules()
        if remaining_missing:
            print(f"[ERROR] 仍有未安装成功的包: {', '.join(remaining_missing)}")
            return 1

        print("[INFO] Python 依赖包已全部自动补齐成功。")

    try:
        from src.utils.headless_browser_manager import repair_headless_browser

        rep = repair_headless_browser(project_root=project_root, probe_launch=False, progress_cb=print)
        if rep.get("ready"):
            print(f"[INFO] 无头浏览器就绪 ({rep.get('mode')})。")
        elif rep.get("enabled", True):
            print("[WARN] 无头浏览器尚未完全就绪，可在界面「无头浏览器自检与修复」中重试。")
    except Exception as exc:
        print(f"[WARN] 无头浏览器检查异常（忽略继续启动）: {exc}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
