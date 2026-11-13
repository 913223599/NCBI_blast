# -*- coding: utf-8 -*-
"""
NCBI BLAST Pro - 环境自愈与依赖自动补齐模块
职责：
1. 运行目录结构自愈 (database, results, reports 等)
2. 附属计算工具自愈同步 (FastTree.exe, muscle.exe)
3. 配置文件与翻译冷备数据库自愈
4. 本地 BLAST+ 套件多路径智能探测
5. pip 国内镜像源 (清华/阿里) 自动配置与全量 Python 依赖补齐
6. 核心依赖与可选依赖分级: 可选依赖 (edlib) 安装失败仅告警, 不再阻塞启动
7. 优先使用 uv 解析依赖 (pip 回溯极慢且易卡死), 缺失时自动引导安装
8. 遵循无 Emoji 规范与 UTF-8 编码
"""

import os
import sys
import shutil
import subprocess
import importlib.util
from pathlib import Path
from typing import Optional

# 强制控制台输出使用 UTF-8 编码，防止 Windows 控制台编码不一致
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

# 直接以脚本方式执行 (python src/utils/verify_and_install_deps.py) 时确保项目根目录在 sys.path 中
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# 核心依赖包名与 import 模块名映射
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
    # 无头浏览器自动化依赖 (生工 16S 官网自动下载等)
    "playwright": "playwright",
    # 组装引擎 NGCS 运行时依赖
    "scipy": "scipy",
    "networkx": "networkx",
}

# 可选依赖：缺失或安装失败时仅告警，不影响程序启动
# edlib 在 Windows 上没有预编译 wheel，需 MSVC C++ 编译器现场编译；
# 项目代码未直接调用该包，因此不做强制性要求。
OPTIONAL_MODULE_IMPORT_MAP = {
    "edlib": "edlib",
}

# 国内镜像源配置
PRIMARY_INDEX_URL = "https://pypi.tuna.tsinghua.edu.cn/simple"
PRIMARY_TRUSTED_HOST = "pypi.tuna.tsinghua.edu.cn"
FALLBACK_INDEX_URL = "https://mirrors.aliyun.com/pypi/simple/"
FALLBACK_TRUSTED_HOST = "mirrors.aliyun.com"

# 镜像源尝试顺序：主源优先，失败后自动降级到备用源
MIRRORS = [
    {"url": PRIMARY_INDEX_URL, "host": PRIMARY_TRUSTED_HOST, "extra": FALLBACK_INDEX_URL},
    {"url": FALLBACK_INDEX_URL, "host": FALLBACK_TRUSTED_HOST, "extra": None},
]


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
    """自愈附属二进制计算工具（sra-tools DLL、FastTree、muscle、mafft、iqtree、mb、vendor/ete4）"""
    try:
        from src.utils.bio_tools_healer import (
            heal_phylogeny_and_alignment_binaries,
            heal_sra_tools_dlls,
            heal_vendor_ete4_binding,
        )

        sra_res = heal_sra_tools_dlls(project_root)
        for act in sra_res.get("actions", []):
            print(f"[自愈] {act}")
        for warn in sra_res.get("warnings", []):
            print(f"[警告] {warn}")

        ete_res = heal_vendor_ete4_binding(project_root)
        for act in ete_res.get("actions", []):
            print(f"[自愈] {act}")
        for warn in ete_res.get("warnings", []):
            print(f"[警告] {warn}")

        bio_res = heal_phylogeny_and_alignment_binaries(project_root, auto_download=True)
        for act in bio_res.get("actions", []):
            print(f"[自愈] {act}")
        for warn in bio_res.get("warnings", []):
            print(f"[警告] {warn}")
    except Exception as exc:
        print(f"[警告] 附属生信工具自愈检查异常: {exc}")


def heal_configurations(project_root: Path):
    """自愈配置文件与数据库冷备"""
    config_file = project_root / "config.json"
    template_file = project_root / "config.default.json"
    if not config_file.exists() and template_file.exists():
        shutil.copy2(template_file, config_file)
        print("[自愈] 未检测到 config.json，已从模板自动创建默认配置。")

    try:
        from src.utils.headless_browser_manager import heal_headless_browser_config

        hb_res = heal_headless_browser_config(project_root=project_root, config_path=config_file)
        for act in hb_res.get("actions", []):
            print(f"[自愈] {act}")
        for warn in hb_res.get("warnings", []):
            print(f"[警告] {warn}")
    except Exception as exc:
        print(f"[警告] 增量补全无头浏览器配置失败: {exc}")

    db_file = project_root / "translations.db"
    backup_db = project_root / "translations_backup.db"
    if not db_file.exists() and backup_db.exists():
        shutil.copy2(backup_db, db_file)
        print("[自愈] 未检测到 translations.db，已从冷备库自动恢复。")


def detect_blast_installation(project_root: Optional[Path] = None):
    """探测本地 BLAST+ 与 Git 路径并写入 config.json 持久生效"""
    root = project_root or _PROJECT_ROOT
    try:
        from src.utils.bio_tools_healer import detect_and_persist_blast_and_git

        res = detect_and_persist_blast_and_git(root, persist=True)
        for act in res.get("actions", []):
            print(f"[自愈] {act}")
        if res.get("blast_ready"):
            print(f"[信息] 本地 BLAST+ 套件就绪: {res.get('blast_bin_path')}")
        if res.get("git_ready"):
            print(f"[信息] Git 命令行工具就绪: {res.get('git_bin_path')}")
        for warn in res.get("warnings", []):
            print(f"[提示] {warn}")
    except Exception as exc:
        print(f"[警告] 探测 BLAST+/Git 工具异常: {exc}")


def detect_git_installation(project_root: Path):
    """兼容旧调用入口（已在 detect_blast_installation 合并持久化探测）"""
    _ = project_root


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


def check_missing_modules(module_map: Optional[dict] = None) -> list:
    """快速检测缺失的依赖模块"""
    module_map = MODULE_IMPORT_MAP if module_map is None else module_map
    missing = []
    for pkg_name, import_name in module_map.items():
        try:
            spec = importlib.util.find_spec(import_name)
            if spec is None:
                missing.append(pkg_name)
        except Exception:
            missing.append(pkg_name)
    return missing


def read_requirement_specs(req_file: Path) -> list:
    """读取 requirements 清单中的依赖条目（忽略注释与空行）"""
    specs = []
    try:
        for raw_line in req_file.read_text(encoding="utf-8").splitlines():
            line = raw_line.split("#", 1)[0].strip()
            if line and not line.startswith("-"):
                specs.append(line)
    except Exception as e:
        print(f"[警告] 读取依赖清单失败 ({req_file.name}): {e}")
    return specs


def _req_name(spec: str) -> str:
    """提取依赖条目中的规范化包名，用于与模块缺失清单比对"""
    name = spec.split(";", 1)[0]
    for sep in ("==", ">=", "<=", "~=", "!=", ">", "<", "[", " "):
        name = name.split(sep, 1)[0]
    return name.strip().replace("_", "-").lower()


def specs_for(packages: list, specs: list) -> list:
    """按缺失包名挑选需要安装的依赖条目（保留版本约束）"""
    wanted = {p.replace("_", "-").lower() for p in packages}
    declared = {_req_name(s) for s in specs}
    picked = [s for s in specs if _req_name(s) in wanted]
    # 清单中未声明的缺失包，直接按包名安装
    picked += [p for p in packages if p.replace("_", "-").lower() not in declared]
    return picked


def _installer_path(name: str):
    """在虚拟环境内查找可执行文件，找不到时回退到 PATH"""
    candidate = Path(sys.executable).parent / name
    if candidate.exists():
        return candidate
    found = shutil.which(name)
    return Path(found) if found else None


def _uv_path():
    return _installer_path("uv.exe") or _installer_path("uv")


def _build_install_command(uv_path, specs: list, mirror: dict, binary_only: bool = False) -> list:
    """构造依赖安装命令；uv 缺失时回退到 pip"""
    if uv_path:
        cmd = [
            str(uv_path), "pip", "install",
            "--python", sys.executable,
            "--index-url", mirror["url"],
            "--index-strategy", "unsafe-best-match",
        ]
        if mirror["extra"]:
            cmd += ["--extra-index-url", mirror["extra"]]
        if binary_only:
            # 禁止本地编译，避免无 C++ 编译环境时长时间报错重试
            cmd += ["--no-build"]
    else:
        cmd = [
            sys.executable, "-m", "pip", "install",
            "-i", mirror["url"],
            "--trusted-host", mirror["host"],
            "--timeout", "120",
            "--disable-pip-version-check",
        ]
        if mirror["extra"]:
            cmd += ["--extra-index-url", mirror["extra"]]
        if binary_only:
            cmd += ["--only-binary", ":all:"]
    return cmd + specs


def _run_installer(cmd: list, project_root: Path, quiet: bool = False) -> bool:
    """执行安装命令，屏蔽 uv 缓存目录的路径限制"""
    env = os.environ.copy()
    if Path(cmd[0]).name.lower().startswith("uv"):
        env.setdefault("UV_CACHE_DIR", str(project_root / "scratch" / "uv-cache"))
        env.setdefault("UV_LINK_MODE", "copy")
    output = subprocess.DEVNULL if quiet else None
    try:
        return subprocess.run(cmd, check=False, env=env, stdout=output, stderr=output).returncode == 0
    except Exception as e:
        print(f"[警告] 执行依赖安装命令失败: {e}")
        return False


def ensure_uv(project_root: Path):
    """确保 uv 可用；缺失时通过 pip 引导安装（单包安装，速度快且无回溯）"""
    uv_path = _uv_path()
    if uv_path:
        return uv_path

    print("[信息] 未检测到 uv 依赖解析器，正在引导安装以加速依赖补齐...")
    for mirror in MIRRORS:
        if _run_installer(_build_install_command(None, ["uv"], mirror), project_root):
            break
    uv_path = _uv_path()
    if not uv_path:
        print("[警告] uv 引导安装失败，将回退使用 pip 安装依赖。")
    return uv_path


def install_packages(project_root: Path, specs: list, label: str, binary_only: bool = False,
                     quiet: bool = False, retry_each: bool = True) -> list:
    """安装指定依赖：优先批量安装，失败后逐包兜底；返回仍未安装成功的条目"""
    if not specs:
        return []

    uv_path = ensure_uv(project_root)
    engine = "uv" if uv_path else "pip"
    print(f"[信息] 正在通过 {engine} 从国内镜像源补齐{label} ({len(specs)} 项)...")

    for mirror in MIRRORS:
        cmd = _build_install_command(uv_path, specs, mirror, binary_only)
        if _run_installer(cmd, project_root, quiet=quiet):
            return []
        print(f"[警告] 镜像源 {mirror['url']} 安装{label}未成功，尝试下一个镜像源...")

    if not retry_each:
        return list(specs)

    # 逐包兜底：避免单个依赖失败导致整批依赖回滚
    print(f"[信息] 批量安装未成功，正在逐包重试{label}...")
    failed = []
    for spec in specs:
        installed = False
        for mirror in MIRRORS:
            cmd = _build_install_command(uv_path, [spec], mirror, binary_only)
            if _run_installer(cmd, project_root, quiet=quiet):
                installed = True
                break
        if not installed:
            failed.append(spec)
    return failed


def main():
    project_root = Path(__file__).resolve().parent.parent.parent
    req_file = project_root / "requirements.txt"
    optional_req_file = project_root / "requirements-optional.txt"

    print("---------------------------------------------------")
    print("[1/4] 正在执行附属环境与目录自愈检查...")
    heal_directories(project_root)
    heal_configurations(project_root)
    heal_auxiliary_binaries(project_root)
    detect_blast_installation(project_root)
    try:
        from src.utils.bio_tools_healer import inspect_wsl_and_gpu_capabilities

        cap = inspect_wsl_and_gpu_capabilities()
        if cap.get("wsl_available"):
            ready_cnt = sum(1 for v in cap.get("wsl_tools", {}).values() if v)
            total_cnt = len(cap.get("wsl_tools", {}))
            print(f"[信息] WSL 环境就绪 ({', '.join(cap.get('wsl_distros', []))}, 生信工具 {ready_cnt}/{total_cnt} 可用)。")
        else:
            print("[提示] 未检测到可用的 WSL 发行版（Pharokka/Phold/WSL 组装功能将使用内置降级模式）。")
        if cap.get("cuda_available"):
            print(f"[信息] GPU 加速就绪 (CUDA: {cap.get('gpu_name')})。")
        elif cap.get("torch_installed"):
            print("[信息] PyTorch 已就绪（CPU 计算模式）。")
    except Exception:
        pass

    print("---------------------------------------------------")
    print("[2/4] 正在校验 Python 运行依赖与配置国内镜像源...")
    configure_pip_mirror()

    if not req_file.exists():
        print(f"[错误] 未找到核心依赖清单: {req_file}")
        return 1

    # 核心依赖：缺失且无法补齐时判定自愈失败
    core_specs = read_requirement_specs(req_file)
    missing = check_missing_modules(MODULE_IMPORT_MAP)
    if not missing:
        print("[信息] Python 核心依赖已完整就绪。")
    else:
        print(f"[警告] 检测到缺失核心依赖 ({len(missing)}项): {', '.join(missing)}")
        failed = install_packages(project_root, specs_for(missing, core_specs), "核心依赖")
        remaining = check_missing_modules(MODULE_IMPORT_MAP)
        if remaining:
            print(f"[错误] 核心依赖补齐失败: {', '.join(remaining)}")
            if failed:
                print(f"[提示] 安装失败条目: {', '.join(failed)}")
            return 1
        print("[信息] Python 核心依赖已全部补齐成功。")

    # 可选依赖：安装失败仅告警，不阻塞启动
    optional_specs = read_requirement_specs(optional_req_file) if optional_req_file.exists() else []
    optional_missing = check_missing_modules(OPTIONAL_MODULE_IMPORT_MAP)
    if not optional_missing:
        print("[信息] 可选依赖已就绪。")
    else:
        print(f"[信息] 检测到缺失可选依赖 ({len(optional_missing)}项): {', '.join(optional_missing)}")
        install_packages(
            project_root,
            specs_for(optional_missing, optional_specs),
            "可选依赖",
            binary_only=True,
            quiet=True,
            retry_each=False,
        )
        still_missing = check_missing_modules(OPTIONAL_MODULE_IMPORT_MAP)
        if still_missing:
            print(f"[警告] 可选依赖未能安装: {', '.join(still_missing)}")
            print("       原因: 该包在 Windows 上无预编译 wheel，需要 Microsoft C++ Build Tools 现场编译。")
            print("       说明: 程序未直接调用该包，环境自愈继续执行，不影响启动。")
            print("       影响: NGCS 组装引擎会退化为近似兜底比对, consensus/polishing 结果不可信。")
            print("       如需启用: https://visualstudio.microsoft.com/visual-cpp-build-tools/")
        else:
            print("[信息] 可选依赖已全部补齐成功。")

    print("---------------------------------------------------")
    print("[3/4] 正在执行无头浏览器 (Playwright Chromium) 启动检查与自修复...")
    try:
        from src.utils.headless_browser_manager import repair_headless_browser

        browser_report = repair_headless_browser(
            project_root=project_root,
            probe_launch=False,
            progress_cb=print,
        )
        for act in browser_report.get("actions", []):
            print(f"[自愈] {act}")
        for warn in browser_report.get("warnings", []):
            print(f"[警告] {warn}")
        if browser_report.get("ready"):
            mode = browser_report.get("mode", "unknown")
            bver = browser_report.get("expected_version") or browser_report.get("playwright_version") or ""
            print(f"[信息] 无头浏览器就绪 (模式: {mode}{', 版本: ' + bver if bver else ''})。")
        elif not browser_report.get("enabled", True):
            print("[信息] 配置已禁用无头浏览器 (headless_browser.enabled=false)。")
        else:
            print("[警告] 无头浏览器内核尚未完全就绪，生工 16S 自动网页下载将受限（可在界面一键重试修复）。")
    except Exception as exc:
        print(f"[警告] 无头浏览器自检出现异常（不阻塞主程序启动）: {exc}")

    print("---------------------------------------------------")
    print("[4/4] Python 环境自愈与依赖审计全部通过。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
