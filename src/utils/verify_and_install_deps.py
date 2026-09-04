# -*- coding: utf-8 -*-
"""
NCBI BLAST Pro - 环境自愈与依赖自动补齐模块
职责：
1. 运行目录结构自愈 (database, results, reports 等)
2. 附属计算工具自愈同步 (FastTree.exe, muscle.exe)
3. 配置文件与翻译冷备数据库自愈
4. 本地 BLAST+ 套件多路径智能探测
5. pip 国内镜像源 (清华/阿里) 自动配置与全量 Python 依赖补齐
6. 遵循无 Emoji 规范与 UTF-8 编码
"""

import os
import sys
import glob
import shutil
import subprocess
import importlib.util
from pathlib import Path

# 强制控制台输出使用 UTF-8 编码，防止 Windows 控制台编码不一致
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

# 核心依赖包名与 import 模块名映射
MODULE_IMPORT_MAP = {
    "fastapi": "fastapi",
    "uvicorn": "uvicorn",
    "pydantic": "pydantic",
    "biopython": "Bio",
    "numpy": "numpy",
    "pandas": "pandas",
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
    "edlib": "edlib",
    "openai": "openai",
}

# 国内镜像源配置
PRIMARY_INDEX_URL = "https://pypi.tuna.tsinghua.edu.cn/simple"
PRIMARY_TRUSTED_HOST = "pypi.tuna.tsinghua.edu.cn"
FALLBACK_INDEX_URL = "https://mirrors.aliyun.com/pypi/simple/"
FALLBACK_TRUSTED_HOST = "mirrors.aliyun.com"


def heal_directories(project_root: Path):
    """自愈运行目录结构"""
    required_dirs = [
        project_root / "database" / "taxonomy",
        project_root / "database" / "16s",
        project_root / "results",
        project_root / "reports",
        project_root / "scratch",
        project_root / "src" / "workbench" / "bin",
        project_root / "vendor" / "fasttree",
        project_root / "vendor" / "iqtree3",
        project_root / "vendor" / "MrBayes",
    ]
    created = 0
    for d in required_dirs:
        if not d.exists():
            d.mkdir(parents=True, exist_ok=True)
            created += 1
    if created > 0:
        print(f"[自愈] 已自动创建并补齐 {created} 个必要的运行目录。")


def heal_auxiliary_binaries(project_root: Path):
    """自愈附属二进制计算工具"""
    tree_tools_dir = project_root / "tools" / "ncbi_dist" / "bin" / "tree-tools"

    # 1. FastTree.exe
    src_fasttree = tree_tools_dir / "FastTree.exe"
    dst_wb_fasttree = project_root / "src" / "workbench" / "bin" / "FastTree.exe"
    dst_vendor_fasttree = project_root / "vendor" / "fasttree" / "FastTree.exe"

    if src_fasttree.exists():
        if not dst_wb_fasttree.exists():
            shutil.copy2(src_fasttree, dst_wb_fasttree)
            print("[自愈] 已自动补齐 src/workbench/bin/FastTree.exe")
        if not dst_vendor_fasttree.exists():
            shutil.copy2(src_fasttree, dst_vendor_fasttree)
            print("[自愈] 已自动补齐 vendor/fasttree/FastTree.exe")

    # 2. muscle.exe
    src_muscle = tree_tools_dir / "muscle.exe"
    dst_wb_muscle = project_root / "src" / "workbench" / "bin" / "muscle.exe"
    if src_muscle.exists() and not dst_wb_muscle.exists():
        shutil.copy2(src_muscle, dst_wb_muscle)
        print("[自愈] 已自动补齐 src/workbench/bin/muscle.exe")


def heal_configurations(project_root: Path):
    """自愈配置文件与数据库冷备"""
    config_file = project_root / "config.json"
    template_file = project_root / "config.default.json"
    if not config_file.exists() and template_file.exists():
        shutil.copy2(template_file, config_file)
        print("[自愈] 未检测到 config.json，已从模板自动创建默认配置。")

    db_file = project_root / "translations.db"
    backup_db = project_root / "translations_backup.db"
    if not db_file.exists() and backup_db.exists():
        shutil.copy2(backup_db, db_file)
        print("[自愈] 未检测到 translations.db，已从冷备库自动恢复。")


def detect_blast_installation():
    """探测本地 BLAST+ 套件安装状态"""
    if shutil.which("blastn"):
        print("[信息] 本地 BLAST+ 套件 (blastn) 已在 PATH 中就绪。")
        return

    # 搜索 Windows 常见安装目录
    search_patterns = [
        r"C:\Program Files\NCBI\blast-*\bin",
        r"D:\Program Files\NCBI\blast-*\bin",
        r"E:\Program Files\NCBI\blast-*\bin",
    ]
    found_bin = None
    for pattern in search_patterns:
        matches = glob.glob(pattern)
        for m in matches:
            if os.path.exists(os.path.join(m, "blastn.exe")):
                found_bin = m
                break
        if found_bin:
            break

    if found_bin:
        print(f"[信息] 自动发现本地 BLAST+ 安装路径: {found_bin}")
        # 注入当前运行环境 PATH
        os.environ["PATH"] = found_bin + os.pathsep + os.environ.get("PATH", "")
    else:
        print("[提示] 未在系统 PATH 或常见安装目录检测到 BLAST+ 套件 (blastn/makeblastdb)。")
        print("       如需使用本地离线比对加速，建议安装: https://ftp.ncbi.nlm.nih.gov/blast/executables/blast+/LATEST/")


def configure_pip_mirror():
    """配置虚拟环境内部 pip 国内镜像源"""
    try:
        subprocess.run(
            [sys.executable, "-m", "pip", "config", "set", "global.index-url", PRIMARY_INDEX_URL],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        subprocess.run(
            [sys.executable, "-m", "pip", "config", "set", "global.extra-index-url", FALLBACK_INDEX_URL],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        subprocess.run(
            [sys.executable, "-m", "pip", "config", "set", "global.trusted-host", PRIMARY_TRUSTED_HOST],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        subprocess.run(
            [sys.executable, "-m", "pip", "config", "set", "global.timeout", "120"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except Exception as e:
        print(f"[警告] 配置 pip 镜像源时出错: {e}")


def check_missing_modules():
    """快速检测缺失的依赖模块"""
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
    """使用国内镜像源加速下载并补齐缺失依赖"""
    print(f"[信息] 正在通过清华镜像源 ({PRIMARY_INDEX_URL}) 下载并补齐 Python 依赖...")
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
            print("[警告] 清华镜像源连接出现异常，尝试使用阿里云备用镜像源...")
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
                print(f"[错误] Python 依赖安装失败，退出码: {ret_fallback.returncode}")
                return False
        return True
    except Exception as e:
        print(f"[错误] 执行 pip install 时发生异常: {e}")
        return False


def main():
    project_root = Path(__file__).resolve().parent.parent.parent
    req_file = project_root / "requirements.txt"

    print("---------------------------------------------------")
    print("[1/3] 正在执行附属环境与目录自愈检查...")
    heal_directories(project_root)
    heal_auxiliary_binaries(project_root)
    heal_configurations(project_root)
    detect_blast_installation()

    print("---------------------------------------------------")
    print("[2/3] 正在校验 Python 运行依赖与配置国内镜像源...")
    configure_pip_mirror()

    missing = check_missing_modules()
    if not missing:
        print("[信息] Python 所有核心依赖已完整就绪。")
    else:
        print(f"[警告] 检测到缺失依赖包 ({len(missing)}项): {', '.join(missing)}")
        if req_file.exists():
            success = install_requirements(req_file)
            if not success:
                return 1
            remaining = check_missing_modules()
            if remaining:
                print(f"[错误] 仍有未成功安装的依赖包: {', '.join(remaining)}")
                return 1
            print("[信息] Python 依赖包已全部补齐成功。")
        else:
            print(f"[错误] 未找到 requirements.txt 文件: {req_file}")
            return 1

    print("---------------------------------------------------")
    print("[3/3] Python 环境自愈与依赖审计全部通过。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
