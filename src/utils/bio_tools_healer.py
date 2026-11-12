# -*- coding: utf-8 -*-
"""
外部生信工具与运行时环境自检自修复模块

单一职责：
1. 修复 tools/ncbi_dist/bin/sra-tools 缺失同目录运行库 DLL (如 libwinpthread-1.dll) 问题；
2. 检验并修复 vendor/ete4 在当前虚拟环境 site-packages 中的 .pth 路径绑定；
3. 检查并自愈进化树/比对外部二进制工具 (FastTree.exe, muscle.exe, mafft.exe, iqtree.exe, mb.exe)；
4. 全盘自动定位本地 BLAST+ 与 Git 命令行工具，并将有效路径持久化回写 config.json；
5. 非阻塞探测 WSL 生信工具链与 PyTorch/CUDA GPU 可用性。

全程使用 UTF-8 编码、零 Emoji 表情、相对路径优先。
"""
import glob
import json
import os
import shutil
import site
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

EXTERNAL_BINARY_SOURCES: Dict[str, Dict[str, Any]] = {
    "iqtree.exe": {
        "url": "https://github.com/iqtree/iqtree2/releases/download/v2.2.0/iqtree-2.2.0-Windows.zip",
        "is_zip": True,
        "pattern": "iqtree",
        "exclude": ("mpi", "click"),
    },
    "mb.exe": {
        "url": "https://github.com/NBISweden/MrBayes/releases/download/v3.2.7/MrBayes-3.2.7-WIN.zip",
        "is_zip": True,
        "pattern": "mb",
        "prefer": "win64",
        "exclude": ("mpi",),
    },
    "muscle.exe": {
        "url": "https://github.com/rcedgar/muscle/releases/download/v5.1/muscle5.1.win64.exe",
        "is_zip": False,
    },
    "mafft.exe": {
        "url": "https://mafft.cbrc.jp/alignment/software/mafft-7.526-win64-signed.zip",
        "is_zip": True,
        "pattern": "mafft",
        "exclude": ("mpi",),
    },
}


def _find_site_packages_dir() -> Optional[Path]:
    """定位当前 Python 运行环境可写的 site-packages 目录。"""
    candidates: List[Path] = []
    exe_root = Path(sys.executable).resolve().parent.parent
    candidates.append(exe_root / "Lib" / "site-packages")
    try:
        for sp in site.getsitepackages():
            candidates.append(Path(sp))
    except Exception:
        pass
    for c in candidates:
        if c.is_dir() and "site-packages" in c.name.lower():
            return c
    return None


def heal_sra_tools_dlls(project_root: Path) -> Dict[str, Any]:
    """检查并补齐 tools/ncbi_dist/bin/sra-tools 缺失的运行时 DLL（如 libwinpthread-1.dll）。"""
    sra_dir = project_root / "tools" / "ncbi_dist" / "bin" / "sra-tools"
    actions: List[str] = []
    warnings: List[str] = []

    if not sra_dir.is_dir():
        return {
            "present": False,
            "ready": False,
            "actions": actions,
            "warnings": ["未检测到 tools/ncbi_dist/bin/sra-tools 目录（SRA 下载工具不可用）"],
        }

    dll_name = "libwinpthread-1.dll"
    target_dll = sra_dir / dll_name
    if not target_dll.is_file():
        dll_sources = [
            project_root / "tools" / "ncbi_dist" / "bin" / "tree-tools" / dll_name,
            project_root / "tools" / "_deprecated" / dll_name,
        ]
        git_which = shutil.which("git")
        if git_which:
            git_base = Path(git_which).resolve().parent.parent
            dll_sources.extend([
                git_base / "mingw64" / "bin" / dll_name,
                git_base / "usr" / "bin" / dll_name,
            ])

        copied = False
        for src in dll_sources:
            try:
                if src.is_file():
                    shutil.copy2(src, target_dll)
                    actions.append(f"已为 sra-tools 自动补齐缺失运行库: {dll_name} (来源: {src})")
                    copied = True
                    break
            except OSError as exc:
                warnings.append(f"从 {src} 复制 {dll_name} 失败: {exc}")

        if not copied and not target_dll.is_file():
            warnings.append(f"sra-tools 缺少运行库 {dll_name}，且未在本地候选目录找到备份副本")
            return {
                "present": True,
                "ready": False,
                "actions": actions,
                "warnings": warnings,
            }

    # 若存在真实大小的 prefetch.exe (>16KB)，做一次轻量版本探针核验 DLL 是否完全正常
    prefetch_exe = sra_dir / "prefetch.exe"
    probe_ok = True
    if prefetch_exe.is_file() and prefetch_exe.stat().st_size > 16384:
        try:
            res = subprocess.run(
                [str(prefetch_exe), "--version"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=8,
            )
            if res.returncode != 0:
                probe_ok = False
                warnings.append(
                    f"sra-tools/prefetch.exe 探针返回异常退出码 {res.returncode}（可能仍缺其他运行库或存在权限限制）"
                )
        except Exception as exc:
            probe_ok = False
            warnings.append(f"sra-tools 探针执行异常: {exc}")

    return {
        "present": True,
        "ready": target_dll.is_file() and probe_ok,
        "actions": actions,
        "warnings": warnings,
    }


def heal_vendor_ete4_binding(
    project_root: Path,
    site_packages_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """检验 vendor/ete4 完整性，并将当前项目 vendor/ete4 路径写入虚拟环境 .pth 实现随处可导入。"""
    vendor_ete4 = (project_root / "vendor" / "ete4").resolve()
    ete4_init = vendor_ete4 / "ete4" / "__init__.py"
    actions: List[str] = []
    warnings: List[str] = []

    if not ete4_init.is_file():
        warnings.append(f"未检测到内置分类学模块 vendor/ete4/ete4/__init__.py ({vendor_ete4})")
        return {"ready": False, "path": str(vendor_ete4), "actions": actions, "warnings": warnings}

    sp_dir = site_packages_dir or _find_site_packages_dir()
    if sp_dir is None or not sp_dir.is_dir():
        warnings.append("未能定位当前 Python 的 site-packages 目录，跳过 ete4 .pth 自愈")
        return {"ready": True, "path": str(vendor_ete4), "actions": actions, "warnings": warnings}

    pth_file = sp_dir / "ncbi_blast_vendor.pth"
    expected_line = str(vendor_ete4)
    try:
        current = pth_file.read_text(encoding="utf-8").strip() if pth_file.is_file() else ""
        if current != expected_line:
            pth_file.write_text(expected_line + "\n", encoding="utf-8")
            actions.append(f"已更新虚拟环境扩展路径绑定 ({pth_file.name} -> {expected_line})")
            if str(vendor_ete4) not in sys.path:
                sys.path.insert(0, expected_line)
    except OSError as exc:
        warnings.append(f"写入 {pth_file} 失败: {exc}")

    return {"ready": True, "path": expected_line, "pth_file": str(pth_file), "actions": actions, "warnings": warnings}


def default_external_binary_downloader(tool_key: str, dest_path: Path) -> bool:
    """下载并提取单个缺失的外部生信二进制工具到指定目标路径。"""
    spec = EXTERNAL_BINARY_SOURCES.get(tool_key)
    if not spec:
        return False

    url = str(spec["url"])
    try:
        with tempfile.TemporaryDirectory(prefix="ncbi_tool_dl_") as tmp_dir:
            tmp_root = Path(tmp_dir)
            dl_name = "pkg.zip" if spec.get("is_zip") else tool_key
            dl_path = tmp_root / dl_name

            req = urllib.request.Request(
                url,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) NCBI-BLAST-Pro"},
            )
            with urllib.request.urlopen(req, timeout=60) as resp, dl_path.open("wb") as out_fh:
                shutil.copyfileobj(resp, out_fh)

            dest_path.parent.mkdir(parents=True, exist_ok=True)
            if not spec.get("is_zip"):
                tmp_exe = dest_path.with_suffix(".exe.tmp")
                shutil.copy2(dl_path, tmp_exe)
                tmp_exe.replace(dest_path)
                return dest_path.is_file()

            extract_dir = tmp_root / "extracted"
            extract_dir.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(dl_path, "r") as zf:
                zf.extractall(extract_dir)

            pattern = str(spec.get("pattern", "")).lower()
            prefer = str(spec.get("prefer", "")).lower()
            excludes = tuple(str(x).lower() for x in spec.get("exclude", ()))

            candidates: List[Path] = []
            for exe_file in extract_dir.rglob("*.exe"):
                lname = exe_file.name.lower()
                if pattern and pattern not in lname:
                    continue
                if any(ex in lname for ex in excludes):
                    continue
                candidates.append(exe_file)

            if not candidates:
                return False

            chosen = candidates[0]
            if prefer:
                for cand in candidates:
                    if prefer in cand.name.lower():
                        chosen = cand
                        break

            tmp_exe = dest_path.with_suffix(".exe.tmp")
            shutil.copy2(chosen, tmp_exe)
            tmp_exe.replace(dest_path)
            return dest_path.is_file()
    except Exception:
        return False


def heal_phylogeny_and_alignment_binaries(
    project_root: Path,
    auto_download: bool = True,
    downloader: Optional[Callable[[str, Path], bool]] = None,
) -> Dict[str, Any]:
    """检查并补齐进化树与多序列比对外部二进制工具（FastTree, muscle, mafft, iqtree, mb）。"""
    actions: List[str] = []
    warnings: List[str] = []
    tree_tools_dir = project_root / "tools" / "ncbi_dist" / "bin" / "tree-tools"

    # 1. 本地 tree-tools -> workbench/bin 与 vendor/fasttree 镜像复制自愈
    local_mirrors = [
        (tree_tools_dir / "FastTree.exe", project_root / "src" / "workbench" / "bin" / "FastTree.exe", "src/workbench/bin/FastTree.exe"),
        (tree_tools_dir / "FastTree.exe", project_root / "vendor" / "fasttree" / "FastTree.exe", "vendor/fasttree/FastTree.exe"),
        (tree_tools_dir / "muscle.exe", project_root / "src" / "workbench" / "bin" / "muscle.exe", "src/workbench/bin/muscle.exe"),
    ]
    for src_bin, dst_bin, rel_label in local_mirrors:
        if not dst_bin.is_file() and src_bin.is_file():
            dst_bin.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_bin, dst_bin)
            actions.append(f"已自动补齐 {rel_label}")

    # 2. 核验全部 5 项外部核心计算二进制
    required_binaries = [
        ("FastTree.exe", project_root / "src" / "workbench" / "bin" / "FastTree.exe"),
        ("muscle.exe", project_root / "src" / "workbench" / "bin" / "muscle.exe"),
        ("mafft.exe", project_root / "src" / "workbench" / "bin" / "mafft.exe"),
        ("iqtree.exe", project_root / "vendor" / "iqtree3" / "iqtree.exe"),
        ("mb.exe", project_root / "vendor" / "MrBayes" / "mb.exe"),
    ]

    dl_fn = downloader or default_external_binary_downloader
    missing: List[str] = []

    for tool_key, target_path in required_binaries:
        if target_path.is_file():
            continue

        repaired = False
        if auto_download and tool_key in EXTERNAL_BINARY_SOURCES:
            if dl_fn(tool_key, target_path):
                actions.append(f"已下载并补齐缺失二进制工具: {target_path.relative_to(project_root).as_posix()}")
                repaired = True

        if not repaired:
            missing.append(tool_key)
            warnings.append(
                f"缺少外部计算工具 {tool_key} ({target_path.relative_to(project_root).as_posix()})，"
                "如需修复可运行: powershell -ExecutionPolicy Bypass -File scripts/download_externals.ps1"
            )

    return {
        "ready": len(missing) == 0,
        "missing": missing,
        "actions": actions,
        "warnings": warnings,
    }


def _find_blast_bin_dir(project_root: Path, configured_dir: str = "") -> Optional[Path]:
    """定位包含 blastn(.exe) 的目录。"""
    exe_name = "blastn.exe" if os.name == "nt" else "blastn"
    candidates: List[Path] = []
    if configured_dir:
        candidates.append(Path(configured_dir))

    candidates.extend([
        project_root / "tools" / "ncbi_dist" / "bin",
        project_root / "vendor" / "blast" / "bin",
        project_root / "vendor" / "ncbi-blast" / "bin",
    ])

    for drive in ("C:", "D:", "E:", "F:"):
        for pattern in (
            f"{drive}\\Program Files\\NCBI\\blast-*\\bin",
            f"{drive}\\NCBI\\blast-*\\bin",
        ):
            for match in sorted(glob.glob(pattern), reverse=True):
                candidates.append(Path(match))

    which_blast = shutil.which("blastn")
    if which_blast:
        candidates.append(Path(which_blast).resolve().parent)

    for cand in candidates:
        try:
            if (cand / exe_name).is_file():
                return cand.resolve()
        except OSError:
            continue
    return None


def _find_git_executable(project_root: Path, configured_path: str = "") -> Optional[Path]:
    """定位 git(.exe) 可执行文件。"""
    exe_name = "git.exe" if os.name == "nt" else "git"
    candidates: List[Path] = []
    if configured_path:
        cfg_p = Path(configured_path)
        candidates.append(cfg_p / exe_name if cfg_p.is_dir() else cfg_p)

    candidates.extend([
        project_root / "tools" / "git" / "cmd" / exe_name,
        project_root / "tools" / "git" / "bin" / exe_name,
        project_root / "tools" / "MinGit" / "cmd" / exe_name,
        project_root / "tools" / "portable-git" / "cmd" / exe_name,
        Path(r"C:\Program Files\Git\cmd\git.exe"),
        Path(r"C:\Program Files\Git\bin\git.exe"),
        Path(r"D:\Program Files\Git\cmd\git.exe"),
        Path(r"C:\Program Files (x86)\Git\cmd\git.exe"),
    ])
    local_appdata = os.environ.get("LOCALAPPDATA")
    if local_appdata:
        candidates.append(Path(local_appdata) / "Programs" / "Git" / "cmd" / exe_name)

    which_git = shutil.which("git")
    if which_git:
        candidates.append(Path(which_git))

    for cand in candidates:
        try:
            if cand.is_file():
                return cand.resolve()
        except OSError:
            continue
    return None


def detect_and_persist_blast_and_git(
    project_root: Path,
    config_path: Optional[Path] = None,
    persist: bool = True,
) -> Dict[str, Any]:
    """探测本地 BLAST+ 与 Git 并同步注入 PATH，必要时安全持久回写 config.json。"""
    cfg_file = config_path or (project_root / "config.json")
    cfg_data: Dict[str, Any] = {}
    if cfg_file.is_file():
        try:
            cfg_data = json.loads(cfg_file.read_text(encoding="utf-8"))
            if not isinstance(cfg_data, dict):
                cfg_data = {}
        except Exception:
            cfg_data = {}

    cur_blast_cfg = str(cfg_data.get("blast_bin_path") or "").strip()
    cur_git_cfg = str(cfg_data.get("git_bin_path") or "").strip()

    blast_dir = _find_blast_bin_dir(project_root, cur_blast_cfg)
    git_exe = _find_git_executable(project_root, cur_git_cfg)

    actions: List[str] = []
    warnings: List[str] = []
    cfg_dirty = False

    if blast_dir:
        b_str = str(blast_dir)
        if b_str not in os.environ.get("PATH", ""):
            os.environ["PATH"] = b_str + os.pathsep + os.environ.get("PATH", "")
        if persist and (not cur_blast_cfg or not Path(cur_blast_cfg).exists()):
            cfg_data["blast_bin_path"] = b_str
            cfg_dirty = True
            actions.append(f"已自动定位并持久化 BLAST+ 路径到 config.json: {b_str}")
    else:
        warnings.append(
            "未在系统 PATH 或常用磁盘目录检测到 BLAST+ (blastn)，"
            "建议安装 NCBI BLAST+ 或在 config.json 配置 blast_bin_path"
        )

    if git_exe:
        g_dir = str(git_exe.parent)
        g_str = str(git_exe)
        if g_dir not in os.environ.get("PATH", ""):
            os.environ["PATH"] = g_dir + os.pathsep + os.environ.get("PATH", "")
        if persist and (not cur_git_cfg or not Path(cur_git_cfg).exists()):
            cfg_data["git_bin_path"] = g_str
            cfg_dirty = True
            actions.append(f"已自动定位并持久化 Git 路径到 config.json: {g_str}")
    else:
        warnings.append(
            "未检测到 Git 命令行工具（软件在线更新不可用），"
            "可安装 Git for Windows 或解压便携版到 tools/git 目录"
        )

    if cfg_dirty and cfg_file.parent.exists():
        tmp_cfg = cfg_file.with_suffix(".json.tmp")
        tmp_cfg.write_text(json.dumps(cfg_data, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp_cfg.replace(cfg_file)

    return {
        "blast_ready": blast_dir is not None,
        "blast_bin_path": str(blast_dir) if blast_dir else "",
        "git_ready": git_exe is not None,
        "git_bin_path": str(git_exe) if git_exe else "",
        "actions": actions,
        "warnings": warnings,
    }


def inspect_wsl_and_gpu_capabilities() -> Dict[str, Any]:
    """非阻塞探测可选 WSL 生信工具链与 PyTorch/CUDA GPU 加速能力。"""
    wsl_available = False
    wsl_distros: List[str] = []
    wsl_tools: Dict[str, bool] = {}

    if shutil.which("wsl"):
        try:
            r = subprocess.run(["wsl", "-l", "-q"], capture_output=True, timeout=4)
            raw = r.stdout.decode("utf-16-le", errors="ignore").replace("\x00", "")
            wsl_distros = [line.strip() for line in raw.splitlines() if line.strip()]
            if wsl_distros:
                wsl_available = True
                target_distro = "Ubuntu" if "Ubuntu" in wsl_distros else wsl_distros[0]
                probe_list = ["mafft", "fastp", "unicycler", "minimap2", "samtools", "pharokka.py", "phold"]
                shell_cmd = " ; ".join(
                    f"echo {name}=$(which {name} >/dev/null 2>&1 && echo 1 || echo 0)"
                    for name in probe_list
                )
                shell_cmd += " ; echo iqtree3=$(test -x /opt/iqtree3/iqtree-3.1.1-Linux-intel/bin/iqtree3 && echo 1 || echo 0)"
                wr = subprocess.run(
                    ["wsl", "-d", target_distro, "-u", "root", "bash", "-c", shell_cmd],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="ignore",
                    timeout=5,
                )
                for line in wr.stdout.splitlines():
                    if "=" in line:
                        k, v = line.split("=", 1)
                        wsl_tools[k.strip()] = v.strip() == "1"
        except Exception:
            pass

    torch_installed = False
    cuda_available = False
    gpu_name = ""
    try:
        import importlib
        import importlib.util

        if importlib.util.find_spec("torch") is not None:
            torch_mod = importlib.import_module("torch")
            torch_installed = True
            cuda_available = bool(hasattr(torch_mod, "cuda") and torch_mod.cuda.is_available())
            if cuda_available:
                gpu_name = str(torch_mod.cuda.get_device_name(0))
    except Exception:
        pass

    return {
        "wsl_available": wsl_available,
        "wsl_distros": wsl_distros,
        "wsl_tools": wsl_tools,
        "torch_installed": torch_installed,
        "cuda_available": cuda_available,
        "gpu_name": gpu_name,
    }

