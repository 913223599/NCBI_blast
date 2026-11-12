# -*- coding: utf-8 -*-
"""
无头浏览器配置管理、启动检查与自动自修复模块

单一职责：
1. 维护并增量自愈 config.json 中的 headless_browser 配置段（模板补全、非法字段纠偏、失效路径清理）；
2. 检测 Playwright Python 包与内置驱动完整性，缺失时复用项目安装器优先通过国内镜像自动补齐；
3. 解析、校验 Chromium 与 Headless Shell 二进制及其 INSTALLATION_COMPLETE 标记，清理半成品残余并用镜像重试安装；
4. 检查并修复 Windows Low Mandatory Level 完整性标签（预防 0x80000003 静默启动崩溃）；
5. 支持离线环境探测本机 Microsoft Edge / Google Chrome 作为兜底引擎，并提供启动参数组装与探针自检。
"""
import asyncio
import importlib
import importlib.metadata
import importlib.util
import json
import logging
import os
import shutil
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("utils.headless_browser")

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

DEFAULT_HEADLESS_BROWSER_CONFIG: Dict[str, Any] = {
    "enabled": True,
    "engine": "chromium",
    "headless": True,
    "browsers_path": "",
    "executable_path": "",
    "download_host": "https://npmmirror.com/mirrors/playwright",
    "fallback_download_host": "https://playwright.azureedge.net",
    "auto_install": True,
    "use_system_browser_fallback": True,
    "launch_timeout_ms": 90000,
    "extra_args": [
        "--disable-gpu",
        "--no-sandbox",
        "--disable-dev-shm-usage",
    ],
}

_REPAIR_LOCK = threading.RLock()
_LAST_REPORT_LOCK = threading.Lock()
_LAST_REPORT: Optional[Dict[str, Any]] = None


def _set_cached_browser_report(report: Dict[str, Any]) -> None:
    global _LAST_REPORT
    with _LAST_REPORT_LOCK:
        _LAST_REPORT = dict(report)


def _emit(cb: Optional[Callable[[str], None]], msg: str) -> None:
    logger.info(msg)
    if cb is not None:
        try:
            cb(msg)
        except Exception:
            pass


def _resolve_project_path(raw: str, root: Path) -> Path:
    p = Path(raw)
    return p if p.is_absolute() else (root / p).resolve()


def _load_json_dict(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
        return loaded if isinstance(loaded, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _load_template_browser_defaults(root: Path) -> Dict[str, Any]:
    merged: Dict[str, Any] = {
        k: (list(v) if isinstance(v, list) else v)
        for k, v in DEFAULT_HEADLESS_BROWSER_CONFIG.items()
    }
    tpl_path = root / "config.default.json"
    tpl_data = _load_json_dict(tpl_path)
    raw_hb = tpl_data.get("headless_browser")
    if isinstance(raw_hb, dict):
        for k, v in raw_hb.items():
            merged[k] = list(v) if isinstance(v, list) else v
    return merged


def _coerce_bool(val: Any, default: bool) -> Tuple[bool, bool]:
    if isinstance(val, bool):
        return val, False
    if isinstance(val, (int, float)) and val in (0, 1):
        return val == 1, True
    if isinstance(val, str):
        low = val.strip().lower()
        if low in ("true", "1", "yes", "on"):
            return True, True
        if low in ("false", "0", "no", "off"):
            return False, True
    return default, True


def heal_headless_browser_config(
    project_root: Optional[Path] = None,
    config_path: Optional[Path] = None,
    patch: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """检查并增量自修复 config.json 中的 headless_browser 配置段，同时兼容 patch 更新。"""
    root = (project_root or PROJECT_ROOT).resolve()
    cfg_path = (config_path or (root / "config.json")).resolve()
    defaults = _load_template_browser_defaults(root)

    actions: List[str] = []
    warnings: List[str] = []
    changed = False

    if cfg_path.exists():
        full_cfg = _load_json_dict(cfg_path)
        if not full_cfg and cfg_path.stat().st_size > 0:
            warnings.append(f"配置文件解析异常，已按默认值重建缺失段: {cfg_path.name}")
            changed = True
    else:
        tpl_path = root / "config.default.json"
        full_cfg = _load_json_dict(tpl_path)
        changed = True
        actions.append(f"已从默认模板生成配置文件: {cfg_path.name}")

    raw_hb = full_cfg.get("headless_browser")
    if not isinstance(raw_hb, dict):
        hb: Dict[str, Any] = {}
        changed = True
        actions.append("已在配置中补齐 headless_browser 默认配置段")
    else:
        hb = dict(raw_hb)

    if patch:
        for k, v in patch.items():
            if k in defaults and v is not None:
                if hb.get(k) != v:
                    hb[k] = v
                    changed = True

    # 1. 补齐缺失子字段并纠偏非法类型
    for key, def_val in defaults.items():
        if key not in hb or hb[key] is None:
            hb[key] = list(def_val) if isinstance(def_val, list) else def_val
            changed = True
            actions.append(f"补齐 headless_browser.{key} 默认值")

    for bool_key in ("enabled", "headless", "auto_install", "use_system_browser_fallback"):
        coerced, modified = _coerce_bool(hb.get(bool_key), bool(defaults[bool_key]))
        if modified:
            hb[bool_key] = coerced
            changed = True
            actions.append(f"纠偏 headless_browser.{bool_key} 布尔配置")

    engine = (hb.get("engine") if isinstance(hb.get("engine"), str) else "").strip().lower()
    if engine != "chromium":
        hb["engine"] = "chromium"
        changed = True
        actions.append("重置不支持的无头引擎类型为 chromium")
    else:
        hb["engine"] = engine

    timeout_raw = hb.get("launch_timeout_ms")
    if not isinstance(timeout_raw, int) or isinstance(timeout_raw, bool) or timeout_raw < 5000 or timeout_raw > 600000:
        hb["launch_timeout_ms"] = int(defaults["launch_timeout_ms"])
        changed = True
        actions.append("重置越界或无效的 launch_timeout_ms 为 90000ms")

    extra_raw = hb.get("extra_args")
    if not isinstance(extra_raw, list) or not all(isinstance(x, str) for x in extra_raw):
        hb["extra_args"] = list(defaults["extra_args"])
        changed = True
        actions.append("修复无效的 extra_args 启动参数列表")

    for str_key in ("browsers_path", "executable_path", "download_host", "fallback_download_host"):
        val = hb.get(str_key)
        if not isinstance(val, str):
            hb[str_key] = defaults[str_key]
            changed = True
            actions.append(f"纠偏 headless_browser.{str_key} 为字符串类型")
        else:
            cleaned = val.strip()
            if cleaned != val:
                hb[str_key] = cleaned
                changed = True

    if not hb["download_host"]:
        hb["download_host"] = defaults["download_host"]
        changed = True
    if not hb["fallback_download_host"]:
        hb["fallback_download_host"] = defaults["fallback_download_host"]
        changed = True

    # 2. 检验显式配置路径是否失效
    custom_exe = hb.get("executable_path", "")
    if custom_exe:
        exe_file = _resolve_project_path(custom_exe, root)
        if not exe_file.is_file():
            warnings.append(f"配置的自定义浏览器路径不存在，已清空并切回自动探测: {custom_exe}")
            actions.append("已清空失效的 headless_browser.executable_path")
            hb["executable_path"] = ""
            changed = True

    full_cfg["headless_browser"] = hb

    if changed:
        try:
            cfg_path.parent.mkdir(parents=True, exist_ok=True)
            cfg_path.write_text(
                json.dumps(full_cfg, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError as exc:
            warnings.append(f"写回配置文件失败 ({cfg_path}): {exc}")

    return {
        "changed": changed,
        "config": hb,
        "config_path": str(cfg_path),
        "actions": actions,
        "warnings": warnings,
    }


def _read_playwright_package_info() -> Dict[str, Any]:
    """检查当前 Python 环境是否已安装 Playwright 包及底层 Node 驱动/browsers.json。"""
    spec = importlib.util.find_spec("playwright")
    if spec is None:
        return {
            "installed": False,
            "version": "",
            "driver_ready": False,
            "revision": "",
            "version_browser": "",
        }

    pkg_version = ""
    try:
        pkg_version = importlib.metadata.version("playwright")
    except Exception:
        pass

    driver_ready = False
    revision = ""
    browser_version = ""
    try:
        pw_mod = importlib.import_module("playwright")
        pkg_file = getattr(pw_mod, "__file__", "") or ""
        pkg_dir = Path(pkg_file).resolve().parent if pkg_file else None
        if pkg_dir is not None:
            manifest_path = pkg_dir / "driver" / "package" / "browsers.json"
            node_name = "node.exe" if os.name == "nt" else "node"
            node_bin = pkg_dir / "driver" / node_name
            if manifest_path.is_file() and node_bin.is_file():
                driver_ready = True
                data = json.loads(manifest_path.read_text(encoding="utf-8"))
                for item in data.get("browsers", []):
                    if item.get("name") == "chromium":
                        revision = str(item.get("revision") or "").strip()
                        browser_version = str(item.get("browserVersion") or "").strip()
                        break
    except Exception:
        driver_ready = False

    return {
        "installed": True,
        "version": pkg_version,
        "driver_ready": driver_ready,
        "revision": revision,
        "version_browser": browser_version,
    }


def _default_system_pw_browsers_dir() -> Path:
    if os.name == "nt":
        local_app = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(local_app) / "ms-playwright"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Caches" / "ms-playwright"
    xdg_cache = os.environ.get("XDG_CACHE_HOME")
    if xdg_cache:
        return Path(xdg_cache) / "ms-playwright"
    return Path.home() / ".cache" / "ms-playwright"


def _find_chromium_artifacts(
    browsers_dir: Path,
    dir_prefix: str,
    rel_candidates: Tuple[Tuple[str, ...], ...],
    expected_revision: str,
) -> Dict[str, Any]:
    """检测指定 browsers 目录下的 Chromium 或 Headless Shell 目录、二进制与 INSTALLATION_COMPLETE 状态。"""
    if not browsers_dir.is_dir():
        return {"dir_exists": False, "dir_path": "", "exe_path": "", "complete": False}

    search_dirs: List[Path] = []
    if expected_revision:
        exact_dir = browsers_dir / f"{dir_prefix}-{expected_revision}"
        if exact_dir.is_dir():
            search_dirs.append(exact_dir)
    for child in sorted(browsers_dir.glob(f"{dir_prefix}-*"), reverse=True):
        if child.is_dir() and child not in search_dirs:
            search_dirs.append(child)

    first_incomplete: Optional[Dict[str, Any]] = None
    for cand_dir in search_dirs:
        exe_found: Optional[Path] = None
        for rel in rel_candidates:
            candidate_exe = cand_dir.joinpath(*rel)
            if candidate_exe.is_file() and candidate_exe.stat().st_size > 0:
                exe_found = candidate_exe
                break
        complete_marker = cand_dir / "INSTALLATION_COMPLETE"
        is_complete = exe_found is not None and complete_marker.is_file()
        item = {
            "dir_exists": True,
            "dir_path": str(cand_dir),
            "exe_path": str(exe_found) if exe_found is not None else "",
            "complete": is_complete,
        }
        if is_complete:
            return item
        if first_incomplete is None:
            first_incomplete = item

    if first_incomplete is not None:
        return first_incomplete

    return {"dir_exists": False, "dir_path": "", "exe_path": "", "complete": False}


def _chromium_rel_candidates() -> Tuple[Tuple[str, ...], ...]:
    if os.name == "nt":
        return (
            ("chrome-win64", "chrome.exe"),
            ("chrome-win", "chrome.exe"),
        )
    if sys.platform == "darwin":
        return (
            ("chrome-mac-arm64", "Google Chrome for Testing.app", "Contents", "MacOS", "Google Chrome for Testing"),
            ("chrome-mac-x64", "Google Chrome for Testing.app", "Contents", "MacOS", "Google Chrome for Testing"),
            ("chrome-mac", "Chromium.app", "Contents", "MacOS", "Chromium"),
        )
    return (
        ("chrome-linux64", "chrome"),
        ("chrome-linux", "chrome"),
    )


def _headless_shell_rel_candidates() -> Tuple[Tuple[str, ...], ...]:
    if os.name == "nt":
        return (
            ("chrome-headless-shell-win64", "chrome-headless-shell.exe"),
            ("chrome-headless-shell-win", "chrome-headless-shell.exe"),
        )
    if sys.platform == "darwin":
        return (
            ("chrome-headless-shell-mac-arm64", "chrome-headless-shell"),
            ("chrome-headless-shell-mac-x64", "chrome-headless-shell"),
        )
    return (
        ("chrome-headless-shell-linux64", "chrome-headless-shell"),
        ("chrome-headless-shell-linux", "chrome-headless-shell"),
    )


def _resolve_effective_browsers_dir(
    root: Path,
    configured_browsers_path: str,
    expected_revision: str,
) -> Tuple[Path, bool]:
    """
    解析生效的 PLAYWRIGHT_BROWSERS_PATH。
    返回 (resolved_dir, explicit_configured)。
    - 若配置中显式指定非 'auto' 路径，优先严格使用配置目录（相对路径按 project_root 解析）；
    - 若配置留空或为 'auto'：先看环境变量 -> 再看项目 vendor/ms-playwright -> 再复用系统既有完整 ms-playwright -> 否则默认指向 vendor/ms-playwright。
    """
    cfg_val = (configured_browsers_path or "").strip()
    if cfg_val and cfg_val.lower() != "auto":
        return _resolve_project_path(cfg_val, root), True

    env_val = (os.environ.get("PLAYWRIGHT_BROWSERS_PATH") or "").strip()
    if env_val and env_val != "0" and env_val.lower() != "auto":
        return _resolve_project_path(env_val, root), True

    vendor_dir = (root / "vendor" / "ms-playwright").resolve()
    vendor_info = _find_chromium_artifacts(
        vendor_dir, "chromium", _chromium_rel_candidates(), expected_revision
    )
    if vendor_info["complete"]:
        return vendor_dir, False

    sys_dir = _default_system_pw_browsers_dir().resolve()
    sys_info = _find_chromium_artifacts(
        sys_dir, "chromium", _chromium_rel_candidates(), expected_revision
    )
    if sys_info["complete"]:
        return sys_dir, False

    return vendor_dir, False


def _detect_system_browser() -> Optional[Dict[str, str]]:
    """探测本机已安装的系统级 Edge 或 Chrome，作为无头内核下载失败时的兜底引擎。"""
    candidates: List[Tuple[str, Path]] = []
    if os.name == "nt":
        roots = [
            os.environ.get("ProgramFiles") or r"C:\Program Files",
            os.environ.get("ProgramFiles(x86)") or r"C:\Program Files (x86)",
            os.environ.get("LOCALAPPDATA") or "",
        ]
        for base in roots:
            if not base:
                continue
            bp = Path(base)
            candidates.append(("msedge", bp / "Microsoft" / "Edge" / "Application" / "msedge.exe"))
            candidates.append(("chrome", bp / "Google" / "Chrome" / "Application" / "chrome.exe"))
        for cmd_name, bin_name in (("msedge", "msedge.exe"), ("chrome", "chrome.exe")):
            found = shutil.which(bin_name)
            if found:
                candidates.append((cmd_name, Path(found)))
    else:
        for cmd_name, cmd_bin in (
            ("chrome", "google-chrome"),
            ("chromium", "chromium"),
            ("chromium", "chromium-browser"),
            ("msedge", "microsoft-edge"),
        ):
            found = shutil.which(cmd_bin)
            if found:
                candidates.append((cmd_name, Path(found)))

    seen = set()
    for name, path in candidates:
        key = str(path).lower()
        if key in seen:
            continue
        seen.add(key)
        try:
            if path.is_file():
                return {"name": name, "path": str(path)}
        except OSError:
            continue
    return None


def _is_low_integrity(target: Path) -> bool:
    if os.name != "nt" or not target.exists():
        return False
    try:
        proc = subprocess.run(
            ["icacls", str(target)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            check=False,
        )
        out = (proc.stdout or "") + "\n" + (proc.stderr or "")
        return "Low Mandatory Level" in out or "低强制级别" in out
    except Exception:
        return False


def _check_windows_integrity_issues(paths: List[Path]) -> List[str]:
    if os.name != "nt":
        return []
    issues: List[str] = []
    seen = set()
    for p in paths:
        if not p or not p.exists():
            continue
        key = str(p).lower()
        if key in seen:
            continue
        seen.add(key)
        if _is_low_integrity(p):
            issues.append(str(p))
    return issues


def _repair_windows_integrity(paths: List[str]) -> List[str]:
    if os.name != "nt" or not paths:
        return []
    repaired: List[str] = []
    for raw in paths:
        target = Path(raw)
        if not target.exists():
            continue
        try:
            proc = subprocess.run(
                ["icacls", str(target), "/setintegritylevel", "Medium"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=15,
                check=False,
            )
            if proc.returncode == 0:
                repaired.append(raw)
        except Exception:
            continue
    return repaired


def _probe_browser_launch(launch_opts: Dict[str, Any]) -> Tuple[bool, str, str]:
    """真实触发一次短周期浏览器启动探针并返回 (ok, version_str, error_msg)。"""
    def _run_sync() -> Tuple[bool, str, str]:
        try:
            from playwright.sync_api import sync_playwright
        except Exception as exc:
            return False, "", f"无法导入 playwright.sync_api: {exc}"

        old_env = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
        bpath_env = (launch_opts.get("env") or {}).get("PLAYWRIGHT_BROWSERS_PATH")
        try:
            if bpath_env:
                os.environ["PLAYWRIGHT_BROWSERS_PATH"] = bpath_env
            kwargs: Dict[str, Any] = {
                "headless": bool(launch_opts.get("headless", True)),
                "timeout": int(launch_opts.get("timeout_ms", 45000)),
            }
            if launch_opts.get("args"):
                kwargs["args"] = list(launch_opts["args"])
            if launch_opts.get("executable_path"):
                kwargs["executable_path"] = launch_opts["executable_path"]

            with sync_playwright() as p:
                browser = p.chromium.launch(**kwargs)
                version = str(getattr(browser, "version", "") or "")
                ctx = browser.new_context()
                page = ctx.new_page()
                page.set_content("<html><title>probe</title></html>")
                ctx.close()
                browser.close()
            return True, version, ""
        except Exception as exc:
            return False, "", str(exc)
        finally:
            if bpath_env:
                if old_env is None:
                    os.environ.pop("PLAYWRIGHT_BROWSERS_PATH", None)
                else:
                    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = old_env

    # 避免在 asyncio 事件循环线程中调用 sync_playwright
    in_event_loop = False
    try:
        asyncio.get_running_loop()
        in_event_loop = True
    except RuntimeError:
        in_event_loop = False

    if not in_event_loop:
        return _run_sync()

    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(_run_sync).result(timeout=60)


def inspect_headless_browser(
    project_root: Optional[Path] = None,
    config_path: Optional[Path] = None,
    probe_launch: bool = False,
) -> Dict[str, Any]:
    """执行只读无头浏览器健康检查并返回结构化诊断报告（不主动下载或修改文件）。"""
    root = (project_root or PROJECT_ROOT).resolve()
    cfg_path = (config_path or (root / "config.json")).resolve()

    raw_full = _load_json_dict(cfg_path)
    raw_hb = raw_full.get("headless_browser")
    defaults = _load_template_browser_defaults(root)
    config_missing = not isinstance(raw_hb, dict)
    effective_cfg: Dict[str, Any] = dict(defaults)
    if isinstance(raw_hb, dict):
        for k, v in raw_hb.items():
            if v is not None:
                effective_cfg[k] = v

    enabled = bool(effective_cfg.get("enabled", True))
    pkg = _read_playwright_package_info()
    revision = str(pkg.get("revision") or "")
    pkg_installed = bool(pkg.get("installed", False))
    pkg_driver_ready = bool(pkg.get("driver_ready", False))
    effective_bdir, explicit_bpath = _resolve_effective_browsers_dir(
        root,
        str(effective_cfg.get("browsers_path") or ""),
        revision,
    )

    chromium_info = _find_chromium_artifacts(
        effective_bdir, "chromium", _chromium_rel_candidates(), revision
    )
    shell_info = _find_chromium_artifacts(
        effective_bdir, "chromium_headless_shell", _headless_shell_rel_candidates(), revision
    )

    custom_exe_raw = str(effective_cfg.get("executable_path") or "").strip()
    custom_exe_valid = False
    custom_exe_resolved = ""
    if custom_exe_raw:
        p = _resolve_project_path(custom_exe_raw, root)
        custom_exe_resolved = str(p)
        custom_exe_valid = p.is_file()

    system_browser = _detect_system_browser()
    allow_fallback = bool(effective_cfg.get("use_system_browser_fallback", True))

    check_paths: List[Path] = []
    if chromium_info["exe_path"]:
        check_paths.append(Path(chromium_info["exe_path"]))
    if shell_info["exe_path"]:
        check_paths.append(Path(shell_info["exe_path"]))
    if custom_exe_valid and custom_exe_resolved:
        check_paths.append(Path(custom_exe_resolved))
    integrity_issues = _check_windows_integrity_issues(check_paths)

    issues: List[Dict[str, Any]] = []
    if config_missing:
        issues.append({
            "code": "config_missing",
            "level": "warning",
            "message": "config.json 缺少 headless_browser 配置段，可由自修复自动补齐",
            "auto_fixable": True,
        })
    if custom_exe_raw and not custom_exe_valid:
        issues.append({
            "code": "invalid_executable_path",
            "level": "warning",
            "message": f"配置的浏览器路径不存在: {custom_exe_raw}",
            "auto_fixable": True,
        })
    if not pkg_installed or not pkg_driver_ready:
        issues.append({
            "code": "playwright_missing",
            "level": "error",
            "message": "缺少 Playwright Python 包或内部驱动文件",
            "auto_fixable": True,
        })

    need_headless_shell = bool(effective_cfg.get("headless", True))
    pw_chromium_ok = bool(pkg_installed and pkg_driver_ready and chromium_info["complete"] and (shell_info["complete"] if need_headless_shell else True))
    if pkg_installed and not pw_chromium_ok and not custom_exe_valid:
        if chromium_info["dir_exists"] and not chromium_info["complete"]:
            issues.append({
                "code": "chromium_incomplete",
                "level": "error",
                "message": "检测到残缺的 Chromium 内核目录（缺少 INSTALLATION_COMPLETE 标记），需清理重装",
                "auto_fixable": True,
            })
        else:
            issues.append({
                "code": "chromium_missing",
                "level": "error",
                "message": f"未检测到可用 Playwright Chromium 内核 ({effective_bdir})",
                "auto_fixable": True,
            })

    if integrity_issues:
        issues.append({
            "code": "low_integrity_label",
            "level": "error",
            "message": "检测到 Windows Low Mandatory Level 完整性标签，可能导致浏览器静默崩溃 (0x80000003)",
            "auto_fixable": True,
        })

    # 综合可用模式判断
    if not enabled:
        mode = "disabled"
        ready = False
        issues.append({
            "code": "browser_disabled",
            "level": "info",
            "message": "config.json 已配置 headless_browser.enabled=false，无头浏览器自动下载功能已暂停",
            "auto_fixable": True,
        })
    elif not pkg_installed or not pkg_driver_ready:
        mode = "unavailable"
        ready = False
    elif custom_exe_valid and not integrity_issues:
        mode = "custom_executable"
        ready = True
    elif pw_chromium_ok and not integrity_issues:
        mode = "playwright_chromium"
        ready = True
    elif allow_fallback and system_browser is not None and not integrity_issues:
        mode = "system_browser_fallback"
        ready = True
    else:
        mode = "unavailable"
        ready = False

    launch_probe_ok: Optional[bool] = None
    launched_version = ""
    if probe_launch and ready and enabled:
        opts = _build_launch_options_from_state(effective_cfg, effective_bdir, mode, system_browser, custom_exe_resolved)
        ok, ver, err = _probe_browser_launch(opts)
        launch_probe_ok = ok
        launched_version = ver
        if not ok:
            ready = False
            mode = "unavailable"
            issues.append({
                "code": "launch_probe_failed",
                "level": "error",
                "message": f"浏览器启动探针失败: {err}",
                "auto_fixable": True,
            })

    report: Dict[str, Any] = {
        "enabled": enabled,
        "ready": ready,
        "mode": mode,
        "python_package_ready": pkg_installed,
        "playwright_version": str(pkg.get("version") or ""),
        "playwright_driver_ready": pkg_driver_ready,
        "expected_revision": revision,
        "expected_version": launched_version or str(pkg.get("version_browser") or pkg.get("version") or ""),
        "configured_browsers_path": str(effective_cfg.get("browsers_path") or ""),
        "effective_browsers_path": str(effective_bdir),
        "explicit_browsers_path": explicit_bpath,
        "chromium_executable": chromium_info["exe_path"],
        "chromium_exists": bool(chromium_info["exe_path"]),
        "chromium_complete": bool(chromium_info["complete"]),
        "headless_shell_executable": shell_info["exe_path"],
        "headless_shell_exists": bool(shell_info["exe_path"]),
        "headless_shell_complete": bool(shell_info["complete"]),
        "integrity_issue_paths": integrity_issues,
        "system_fallback_browser": system_browser,
        "launch_probe_ok": launch_probe_ok,
        "issues": issues,
        "config": effective_cfg,
        "actions": [],
        "warnings": [],
    }
    _set_cached_browser_report(report)
    return report


def _install_playwright_package(root: Path, progress_cb: Optional[Callable[[str], None]] = None) -> bool:
    """使用项目既有国内镜像安装工具补齐 playwright 包。"""
    _emit(progress_cb, "[无头浏览器自愈] 正在通过国内镜像安装 Playwright Python 驱动包...")
    try:
        from src.utils.verify_and_install_deps import install_packages, read_requirement_specs, specs_for

        req_file = root / "requirements.txt"
        specs = read_requirement_specs(req_file) if req_file.exists() else []
        target_specs = specs_for(["playwright"], specs)
        failed = install_packages(root, target_specs or ["playwright>=1.48.0"], "无头浏览器驱动 (Playwright)")
        if failed:
            return False
        importlib.invalidate_caches()
        return _read_playwright_package_info()["driver_ready"]
    except Exception as exc:
        logger.warning(f"自动安装 playwright 包失败: {exc}")
        return False


def _cleanup_incomplete_chromium_dirs(browsers_dir: Path) -> List[str]:
    removed: List[str] = []
    if not browsers_dir.is_dir():
        return removed
    for prefix in ("chromium-", "chromium_headless_shell-"):
        for sub in browsers_dir.glob(f"{prefix}*"):
            if not sub.is_dir():
                continue
            marker = sub / "INSTALLATION_COMPLETE"
            if not marker.is_file():
                try:
                    shutil.rmtree(sub, ignore_errors=True)
                    removed.append(sub.name)
                except Exception:
                    pass
    return removed


def _install_chromium_binaries(
    browsers_dir: Path,
    cfg: Dict[str, Any],
    progress_cb: Optional[Callable[[str], None]] = None,
) -> Tuple[bool, List[str]]:
    """通过 PLAYWRIGHT_DOWNLOAD_HOST 优先从国内镜像安装 Chromium 内核，失败回退官方源。"""
    notes: List[str] = []
    browsers_dir.mkdir(parents=True, exist_ok=True)
    hosts: List[str] = []
    primary = str(cfg.get("download_host") or "").strip()
    fallback = str(cfg.get("fallback_download_host") or "").strip()
    if primary:
        hosts.append(primary)
    if fallback and fallback not in hosts:
        hosts.append(fallback)
    if "" not in hosts:
        hosts.append("")

    for host in hosts:
        env = os.environ.copy()
        env["PLAYWRIGHT_BROWSERS_PATH"] = str(browsers_dir)
        if host:
            env["PLAYWRIGHT_DOWNLOAD_HOST"] = host
        else:
            env.pop("PLAYWRIGHT_DOWNLOAD_HOST", None)

        label = host or "Playwright 默认官方源"
        _emit(progress_cb, f"[无头浏览器自愈] 正在从 {label} 下载/校验 Chromium 内核至 {browsers_dir}...")
        try:
            proc = subprocess.run(
                [sys.executable, "-m", "playwright", "install", "chromium"],
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=300,
                check=False,
            )
            if proc.returncode == 0:
                notes.append(f"已从 {label} 成功安装 Playwright Chromium 内核")
                return True, notes
            err_tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-1:] or ["未知错误"]
            notes.append(f"从 {label} 下载失败 (exit={proc.returncode}): {err_tail[0]}")
        except Exception as exc:
            notes.append(f"执行 playwright install 异常 ({label}): {exc}")

    return False, notes


def repair_headless_browser(
    project_root: Optional[Path] = None,
    config_path: Optional[Path] = None,
    *,
    auto_install: Optional[bool] = None,
    probe_launch: bool = True,
    patch_config: Optional[Dict[str, Any]] = None,
    progress_cb: Optional[Callable[[str], None]] = None,
) -> Dict[str, Any]:
    """
    执行无头浏览器全链路启动检查与自修复：
    1. 修复与补全 headless_browser 配置段及失效路径；
    2. 校验并自动修复 Windows Low Mandatory Level 标签；
    3. 缺失 Playwright Python 包/驱动时通过国内源自动安装；
    4. 缺失或残缺 Chromium 内核时清理半成品并优先从国内镜像补齐；
    5. 同步激活 PLAYWRIGHT_BROWSERS_PATH 并按需触发真实启动探针验证。
    """
    root = (project_root or PROJECT_ROOT).resolve()
    cfg_path = (config_path or (root / "config.json")).resolve()

    with _REPAIR_LOCK:
        all_actions: List[str] = []
        all_warnings: List[str] = []

        heal_res = heal_headless_browser_config(root, cfg_path, patch=patch_config)
        cfg = heal_res["config"]
        all_actions.extend(heal_res["actions"])
        all_warnings.extend(heal_res["warnings"])

        if not bool(cfg.get("enabled", True)):
            rep = inspect_headless_browser(root, cfg_path, probe_launch=False)
            rep["actions"] = all_actions + ["配置已显式禁用无头浏览器 (enabled=false)"]
            rep["warnings"] = all_warnings
            _set_cached_browser_report(rep)
            return rep

        allow_install = bool(cfg.get("auto_install", True)) if auto_install is None else auto_install

        # 激活配置中的浏览器目录
        pkg_before = _read_playwright_package_info()
        if (not pkg_before["installed"] or not pkg_before["driver_ready"]) and allow_install:
            if _install_playwright_package(root, progress_cb=progress_cb):
                all_actions.append("已自动补齐 Playwright Python 运行依赖")
            else:
                all_warnings.append("Playwright Python 包自动安装失败，请检查网络或手动执行 pip install playwright")

        report = inspect_headless_browser(root, cfg_path, probe_launch=False)
        effective_bdir = Path(report["effective_browsers_path"])

        # 先激活环境变量确保进程后续同步调用同一内核路径
        if effective_bdir.is_dir() or report["explicit_browsers_path"]:
            os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(effective_bdir)

        # 修复已有文件的低完整性标签
        if report["integrity_issue_paths"]:
            repaired_paths = _repair_windows_integrity(report["integrity_issue_paths"])
            if repaired_paths:
                all_actions.append(
                    f"已修复 {len(repaired_paths)} 个浏览器二进制的 Windows Medium 完整性标签"
                )

        need_headless_shell = bool(cfg.get("headless", True))
        chromium_ok = bool(
            report["chromium_complete"]
            and (report["headless_shell_complete"] if need_headless_shell else True)
        )

        # 若 Playwright 已可用但内核缺失/半残缺，尝试自动清残与重装
        if report["python_package_ready"] and report["playwright_driver_ready"] and not chromium_ok and allow_install:
            cleaned = _cleanup_incomplete_chromium_dirs(effective_bdir)
            if cleaned:
                all_actions.append(f"已清理不完整的浏览器残留目录: {', '.join(cleaned)}")

            ok_install, install_notes = _install_chromium_binaries(
                effective_bdir, cfg, progress_cb=progress_cb
            )
            for note in install_notes:
                if ok_install and "成功" in note:
                    all_actions.append(note)
                else:
                    all_warnings.append(note)

            if ok_install:
                os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(effective_bdir)
                post_check = inspect_headless_browser(root, cfg_path, probe_launch=False)
                if post_check["integrity_issue_paths"]:
                    rep_new = _repair_windows_integrity(post_check["integrity_issue_paths"])
                    if rep_new:
                        all_actions.append(
                            f"已为新安装浏览器修复 {len(rep_new)} 处完整性标签"
                        )

        final_report = inspect_headless_browser(root, cfg_path, probe_launch=probe_launch)

        # 如果启动探针失败但存在残缺/被破坏的 Chromium 且允许自动安装，自动执行清残重装再探针一次
        if (
            probe_launch
            and final_report.get("launch_probe_ok") is False
            and allow_install
            and final_report["python_package_ready"]
        ):
            all_warnings.append("初次浏览器启动探针失败，尝试重装 Chromium 后二次验证...")
            _cleanup_incomplete_chromium_dirs(Path(final_report["effective_browsers_path"]))
            ok_retry, retry_notes = _install_chromium_binaries(
                Path(final_report["effective_browsers_path"]),
                cfg,
                progress_cb=progress_cb,
            )
            if ok_retry:
                all_actions.extend(retry_notes)
                final_report = inspect_headless_browser(root, cfg_path, probe_launch=True)

        final_report["actions"] = all_actions
        final_report["warnings"] = all_warnings

        _set_cached_browser_report(final_report)
        return final_report


def _build_launch_options_from_state(
    cfg: Dict[str, Any],
    effective_bdir: Path,
    mode: str,
    system_browser: Optional[Dict[str, str]],
    custom_exe_resolved: str,
) -> Dict[str, Any]:
    executable_path = ""
    if mode == "custom_executable" and custom_exe_resolved:
        executable_path = custom_exe_resolved
    elif mode == "system_browser_fallback" and system_browser:
        executable_path = system_browser["path"]

    return {
        "enabled": bool(cfg.get("enabled", True)),
        "headless": bool(cfg.get("headless", True)),
        "timeout_ms": int(cfg.get("launch_timeout_ms", 90000)),
        "executable_path": executable_path,
        "args": [str(x) for x in (cfg.get("extra_args") or [])],
        "env": {
            "PLAYWRIGHT_BROWSERS_PATH": str(effective_bdir),
        },
        "mode": mode,
    }


def get_launch_options(
    project_root: Optional[Path] = None,
    config_path: Optional[Path] = None,
    *,
    headless_override: Optional[bool] = None,
) -> Dict[str, Any]:
    """为运行时下载器提供统一规范化的 Playwright Chromium 启动参数，并激活环境目录。"""
    report = inspect_headless_browser(project_root=project_root, config_path=config_path, probe_launch=False)
    cfg = report["config"]
    custom_exe = str(cfg.get("executable_path") or "").strip()
    root = (project_root or PROJECT_ROOT).resolve()
    custom_resolved = str(_resolve_project_path(custom_exe, root)) if custom_exe else ""

    opts = _build_launch_options_from_state(
        cfg=cfg,
        effective_bdir=Path(report["effective_browsers_path"]),
        mode=str(report["mode"]),
        system_browser=report.get("system_fallback_browser"),
        custom_exe_resolved=custom_resolved,
    )
    if headless_override is not None:
        opts["headless"] = headless_override

    bpath_env = (opts.get("env") or {}).get("PLAYWRIGHT_BROWSERS_PATH")
    if bpath_env and Path(bpath_env).is_dir():
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = bpath_env
    return opts


def get_cached_browser_report(
    project_root: Optional[Path] = None,
    config_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """优先返回最近一次内存检查结果，尚无缓存时执行一次快速非探针检查。"""
    with _LAST_REPORT_LOCK:
        if _LAST_REPORT is not None:
            return dict(_LAST_REPORT)
    return inspect_headless_browser(project_root=project_root, config_path=config_path, probe_launch=False)
