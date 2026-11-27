# -*- coding: utf-8 -*-
"""
阶段 0/1 仓库工程规范守护测试（规则 0 / 规则 2 / 规则 11）
用于持续防止 Emoji 符号、个人盘符绝对路径硬编码及缺失 UTF-8 编码声明的回归。
"""
import re
from pathlib import Path
import pytest

pytestmark = pytest.mark.offline

PROJECT_ROOT = Path(__file__).resolve().parent.parent

EMOJI_PATTERN = re.compile(
    r"[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F1E0-\U0001F1FF]"
)

# 仅针对个人开发机专属硬编码路径（不误伤 Windows 通用候选目录如 Program Files\Git）
PERSONAL_HARDCODED_PATH_PATTERN = re.compile(
    r"(?i)(?:"
    r"[def]:[/\\]ncbi\s*blast"
    r"|f:/__pyrefly_virtual__"
    r"|e:/ngcs"
    r"|/mnt/[df]/ncbi\s*blast"
    r"|/home/administrator/"
    r"|d:\\program\s+files\\ncbi\\blast-2\.16\.0\+"
    r"|c:/users/administrator/"
    r")"
)


def _iter_core_source_files():
    targets = [
        PROJECT_ROOT / "src" / "resources" / "locales",
        PROJECT_ROOT / "src" / "web-next" / "src",
        PROJECT_ROOT / "electron-shell",
        PROJECT_ROOT / "docs",
    ]
    exts = {".py", ".vue", ".ts", ".js", ".css", ".json", ".md"}
    skip = {"node_modules", "dist", "__pycache__"}
    for base in targets:
        if not base.exists():
            continue
        for p in base.rglob("*"):
            if any(part in skip for part in p.parts):
                continue
            if p.is_file() and p.suffix.lower() in exts and p.name != "package-lock.json":
                yield p


def test_rule0_no_emoji_in_core_code_and_locales():
    violations = []
    extra_files = [
        PROJECT_ROOT / "scripts" / "setup_pharokka.sh",
        PROJECT_ROOT / "scripts" / "verify_label_display_mode.js",
        PROJECT_ROOT / "README.md",
    ]
    all_files = list(_iter_core_source_files()) + [p for p in extra_files if p.exists()]
    for p in all_files:
        text = p.read_text(encoding="utf-8", errors="replace")
        matches = EMOJI_PATTERN.findall(text)
        if matches:
            codes = sorted({f"U+{ord(c):04X}" for c in matches})
            violations.append(f"{p.relative_to(PROJECT_ROOT)} -> {codes}")

    assert not violations, "发现违反规则 0 的 Emoji/符号文件:\n" + "\n".join(violations[:20])


def test_rule2_no_personal_hardcoded_paths_in_core_files():
    checked_files = [
        PROJECT_ROOT / "pyrightconfig.json",
        PROJECT_ROOT / ".vscode" / "settings.json",
        PROJECT_ROOT / "run_auto_pipeline.bat",
        PROJECT_ROOT / "build_release.py",
        PROJECT_ROOT / "src" / "backend" / "services" / "diversity_engine.py",
        PROJECT_ROOT / "src" / "backend" / "utils" / "bio_db_manager.py",
        PROJECT_ROOT / "src" / "phylo" / "runtime" / "process_runner.py",
        PROJECT_ROOT / "src" / "phylo" / "runtime" / "tool_registry.py",
        PROJECT_ROOT / "src" / "web-next" / "src" / "components" / "strain" / "FreezerDetailPanel.vue",
        PROJECT_ROOT / "scripts" / "setup_phold.sh",
        PROJECT_ROOT / "scripts" / "setup_pharokka.sh",
        PROJECT_ROOT / "scripts" / "fix_minced.sh",
        PROJECT_ROOT / "scripts" / "inspect_sangon_mail.py",
        PROJECT_ROOT / "scripts" / "process_user_downloads.py",
    ]
    scripts_dir = PROJECT_ROOT / "scripts"
    tracked_script_py_files = []
    if scripts_dir.exists():
        import subprocess

        try:
            out = subprocess.check_output(
                ["git", "-c", "core.quotepath=false", "ls-files", "scripts/*.py", "scripts/**/*.py"],
                cwd=PROJECT_ROOT,
                text=True,
                encoding="utf-8",
            )
            tracked_script_py_files = sorted(
                PROJECT_ROOT / rel.strip() for rel in out.splitlines() if rel.strip()
            )
        except Exception:
            tracked_script_py_files = sorted(scripts_dir.rglob("*.py"))
    # 全量扫描 src/**/*.py 与受 Git 跟踪的 scripts/**/*.py，杜绝白名单盲区漏检个人盘符路径
    src_py_files = sorted(
        p
        for p in (PROJECT_ROOT / "src").rglob("*.py")
        if not any(part in {"__pycache__", "node_modules", "dist"} for part in p.parts)
    )
    all_checked = list(dict.fromkeys([*checked_files, *src_py_files, *tracked_script_py_files]))
    drive_pattern = re.compile(r"(?i)(?<![A-Za-z0-9_])([C-Z]:[\\/][^\s\"'<>|]{2,})")
    # 允许通用的 Windows 系统/标准软件安装目录探测（禁止个人盘符/业务数据盘符）
    system_probe_re = re.compile(r"(?i)^[C-E]:[\\/](?:Windows\b|Program Files(?:\s*\(x86\))?(?:[\\/'\"\s]|$))")
    violations = []
    for p in all_checked:
        if not p.exists():
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        for idx, line in enumerate(text.splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if PERSONAL_HARDCODED_PATH_PATTERN.search(line):
                violations.append(f"{p.relative_to(PROJECT_ROOT)}:{idx}: {stripped[:90]}")
                continue
            if p.suffix == ".py" and ("src" in p.parts or "scripts" in p.parts):
                for m in drive_pattern.finditer(line):
                    if not system_probe_re.match(line[m.start(1):]):
                        violations.append(f"{p.relative_to(PROJECT_ROOT)}:{idx}: {stripped[:90]}")
                        break

    assert not violations, "发现违反规则 2 的个人机器硬编码绝对路径:\n" + "\n".join(violations)


def test_no_raw_extractall_in_src():
    """除 archive_guard.py 内部实现外，src/ 禁止直接调用未受控的 extractall()。"""
    violations = []
    for p in sorted((PROJECT_ROOT / "src").rglob("*.py")):
        if any(part in {"__pycache__", "node_modules", "dist"} for part in p.parts) or p.name == "archive_guard.py":
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        for idx, line in enumerate(text.splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if ".extractall(" in line:
                violations.append(f"{p.relative_to(PROJECT_ROOT)}:{idx}: {stripped[:90]}")
    assert not violations, "发现未经过 archive_guard 的直接 extractall() 调用:\n" + "\n".join(violations)


def test_frontend_production_no_raw_console_log():
    """前端生产源码禁用散落 console.* 与 (window as any)，统一使用 logger.ts 与 electron.d.ts。"""
    web_src = PROJECT_ROOT / "src" / "web-next" / "src"
    console_violations = []
    window_any_violations = []
    console_re = re.compile(r"\bconsole\.(?:log|warn|error|debug|info)\s*\(")
    window_any_re = re.compile(r"\(\s*window\s+as\s+any\s*\)")
    for p in sorted(web_src.rglob("*")):
        if not p.is_file() or p.suffix not in (".ts", ".vue"):
            continue
        if "__tests__" in p.parts or p.name == "logger.ts":
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        for idx, line in enumerate(text.splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith(("//", "*")):
                continue
            if console_re.search(line):
                console_violations.append(f"{p.relative_to(PROJECT_ROOT)}:{idx}: {stripped[:80]}")
            if window_any_re.search(line):
                window_any_violations.append(f"{p.relative_to(PROJECT_ROOT)}:{idx}: {stripped[:80]}")
    assert not console_violations, "发现未收敛至 logger.ts 的前端裸 console.*:\n" + "\n".join(console_violations)
    assert not window_any_violations, "发现未收敛至 types/electron.d.ts 的 (window as any):\n" + "\n".join(
        window_any_violations
    )


def test_legacy_pyqt_bridge_and_misplaced_web_root_files_removed():
    assert not (PROJECT_ROOT / "src" / "web-next" / "src" / "bridge" / "pyqt-bridge.ts").exists()
    assert not (PROJECT_ROOT / "src" / "web-next" / "verify_label_display_mode.js").exists()
    assert not (PROJECT_ROOT / "src" / "web-next" / "LABEL_DISPLAY_MODE_FIX_REPORT.md").exists()
    assert (PROJECT_ROOT / "scripts" / "verify_label_display_mode.js").is_file()
    assert (PROJECT_ROOT / "docs" / "archive" / "label_display_mode_fix_report.md").is_file()


def test_rule11_src_python_files_utf8_clean():
    import ast

    enc_gbk_re = re.compile(
        r"(?i)(?:encoding\s*=\s*['\"](?:gbk|cp936|gb2312|gb18030)['\"]"
        r"|\.(?:decode|encode)\s*\(\s*['\"](?:gbk|cp936|gb2312|gb18030)['\"])"
    )
    violations = []
    for p in (PROJECT_ROOT / "src").rglob("*.py"):
        if any(part in {"__pycache__", "node_modules", "dist"} for part in p.parts):
            continue
        raw = p.read_bytes()
        if raw.startswith(b"\xef\xbb\xbf"):
            violations.append(f"{p.relative_to(PROJECT_ROOT)}: 存在 UTF-8 BOM")
            continue
        text = raw.decode("utf-8")
        for idx, line in enumerate(text.splitlines(), 1):
            if enc_gbk_re.search(line):
                violations.append(f"{p.relative_to(PROJECT_ROOT)}:{idx}: 禁止使用 GBK/CP936 编码")
        try:
            tree = ast.parse(text)
        except SyntaxError as exc:
            violations.append(f"{p.relative_to(PROJECT_ROOT)}: 语法错误 {exc}")
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if not (isinstance(node.func, ast.Name) and node.func.id == "open"):
                continue
            kw_map = {kw.arg: kw.value for kw in node.keywords if kw.arg}
            if "encoding" in kw_map:
                continue
            # 检查 mode 是否为二进制模式（如 'rb'/'wb'/'ab'）
            mode_node = kw_map.get("mode") or (node.args[1] if len(node.args) >= 2 else None)
            if isinstance(mode_node, ast.Constant) and isinstance(mode_node.value, str) and "b" in mode_node.value:
                continue
            violations.append(f"{p.relative_to(PROJECT_ROOT)}:{node.lineno}: 文本 open() 缺失 encoding='utf-8'")

    assert not violations, "发现违反规则 11 的编码问题:\n" + "\n".join(violations[:20])


def test_locales_zh_en_keys_fully_aligned():
    import json

    zh_dir = PROJECT_ROOT / "src" / "resources" / "locales" / "zh_CN"
    en_dir = PROJECT_ROOT / "src" / "resources" / "locales" / "en_US"
    zh_files = {p.name for p in zh_dir.glob("*.json")}
    en_files = {p.name for p in en_dir.glob("*.json")}
    assert zh_files == en_files

    diffs = []
    for fname in sorted(zh_files):
        zh_keys = set(json.loads((zh_dir / fname).read_text(encoding="utf-8")).keys())
        en_keys = set(json.loads((en_dir / fname).read_text(encoding="utf-8")).keys())
        missing_en = sorted(zh_keys - en_keys)
        missing_zh = sorted(en_keys - zh_keys)
        if missing_en or missing_zh:
            diffs.append(f"{fname}: missing_en={missing_en[:5]}, missing_zh={missing_zh[:5]}")
    assert not diffs, "中英文词典键不一致:\n" + "\n".join(diffs)


def test_readme_license_help_and_citations_integrity():
    import json
    from src.utils.help_manager import get_help_manager

    assert (PROJECT_ROOT / "LICENSE").is_file()
    assert (PROJECT_ROOT / "docs" / "INDEX.md").is_file()

    readme = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")
    assert "TailwindCSS" not in readme
    assert "Phylotree.js" not in readme
    assert "src/analysis/protein_compare" not in readme

    citations = json.loads((PROJECT_ROOT / "src" / "resources" / "citations.json").read_text(encoding="utf-8"))
    assert len(citations.get("tools", [])) >= 10

    help_mgr = get_help_manager()
    structure = help_mgr.get_help_structure()
    total_topics = sum(len(g["topics"]) for g in structure)
    assert total_topics >= 10
    for group in structure:
        for topic in group["topics"]:
            md_path = PROJECT_ROOT / "resources" / "help" / f"{topic['id']}.md"
            assert md_path.is_file(), f"帮助目录引用了缺失文件: {md_path}"


def test_subprocess_text_calls_specify_utf8_and_routes_forbid_shell_true():
    import ast

    enc_violations = []
    for base in (PROJECT_ROOT / "src", PROJECT_ROOT / "scripts"):
        if not base.exists():
            continue
        for p in base.rglob("*.py"):
            if any(part in {"__pycache__", "node_modules", "dist"} for part in p.parts):
                continue
            tree = ast.parse(p.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                    continue
                if (
                    node.func.attr in {"run", "Popen", "check_output"}
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "subprocess"
                ):
                    kw_map = {kw.arg: kw.value for kw in node.keywords if kw.arg}
                    tv = kw_map.get("text") or kw_map.get("universal_newlines")
                    if isinstance(tv, ast.Constant) and tv.value is True and "encoding" not in kw_map:
                        enc_violations.append(f"{p.relative_to(PROJECT_ROOT)}:{node.lineno}")
    assert not enc_violations, "发现 subprocess(text=True) 缺失 encoding='utf-8':\n" + "\n".join(enc_violations)

    shell_violations = []
    for p in (PROJECT_ROOT / "src" / "backend" / "routes").rglob("*.py"):
        if "__pycache__" in p.parts:
            continue
        text = p.read_text(encoding="utf-8")
        if "shell=True" in text:
            shell_violations.append(str(p.relative_to(PROJECT_ROOT)))
    assert not shell_violations, "后端路由禁止使用 shell=True:\n" + "\n".join(shell_violations)


def test_frontend_i18n_keys_exist_in_zh_and_en_locales():
    import json

    zh_keys = set()
    en_keys = set()
    for p in (PROJECT_ROOT / "src" / "resources" / "locales" / "zh_CN").glob("*.json"):
        zh_keys.update(json.loads(p.read_text(encoding="utf-8")).keys())
    for p in (PROJECT_ROOT / "src" / "resources" / "locales" / "en_US").glob("*.json"):
        en_keys.update(json.loads(p.read_text(encoding="utf-8")).keys())

    used_keys = set()
    web_src = PROJECT_ROOT / "src" / "web-next" / "src"
    for p in web_src.rglob("*"):
        if "__tests__" in p.parts or p.suffix not in {".vue", ".ts"}:
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        for m in re.findall(r"(?<![.\w$])t\(\s*['\"]([a-zA-Z0-9_.-]+)['\"]", text):
            used_keys.add(m)

    missing_zh = sorted(used_keys - zh_keys)
    missing_en = sorted(used_keys - en_keys)
    assert not missing_zh and not missing_en, f"前端引用的翻译键缺失: zh={missing_zh}, en={missing_en}"


def test_version_single_source_brand_citations_and_three_types_alignment():
    import json

    version_meta = json.loads((PROJECT_ROOT / "version.json").read_text(encoding="utf-8"))
    expected_version = version_meta["version"]
    assert version_meta["name"] == "NCBI Bio-Station"
    assert re.match(r"^\d+\.\d+\.\d+", expected_version)

    for pkg_rel in ("package.json", "electron-shell/package.json", "src/web-next/package.json"):
        pkg = json.loads((PROJECT_ROOT / pkg_rel).read_text(encoding="utf-8"))
        assert pkg.get("version") == expected_version, f"{pkg_rel} 版本未与 version.json 对齐"

    web_pkg = json.loads((PROJECT_ROOT / "src" / "web-next" / "package.json").read_text(encoding="utf-8"))
    three_ver = str(web_pkg["dependencies"]["three"]).lstrip("^~")
    types_three_ver = str(web_pkg["devDependencies"]["@types/three"]).lstrip("^~")
    assert three_ver.split(".")[:2] == types_three_ver.split(".")[:2], (
        f"three ({three_ver}) 与 @types/three ({types_three_ver}) 主次版本不一致"
    )

    main_js = (PROJECT_ROOT / "electron-shell" / "main.js").read_text(encoding="utf-8")
    assert "NCBI BLAST Pro" not in main_js
    assert (PROJECT_ROOT / "src" / "web-next" / "src" / "types" / "electron.d.ts").is_file()

    citations = json.loads((PROJECT_ROOT / "src" / "resources" / "citations.json").read_text(encoding="utf-8"))
    tool_ids = {t["id"] for t in citations.get("tools", [])}
    assert len(tool_ids) >= 18
    assert {"phold", "lovis4u", "mmseqs2", "checkv", "proksee_cgview"} <= tool_ids


def test_dead_zombie_modules_and_backend_maintenance_scripts_cleaned():
    """防止已清理的零引用僵尸模块、重复配置与生产包运维脚本回流。"""
    assert not (PROJECT_ROOT / "src" / "modules" / "tooltip").exists()
    assert not (PROJECT_ROOT / "src" / "web-next" / "src" / "modules" / "AssemblyCoordinator").exists()
    assert not (PROJECT_ROOT / "src" / "workbench" / "pipelines").exists()
    assert not (PROJECT_ROOT / "src" / "workbench" / "wrappers").exists()
    assert not (PROJECT_ROOT / "src" / "pyrightconfig.json").exists()
    assert not (PROJECT_ROOT / "third_party" / "PhageTailFinder" / "scripts").exists()
    for obsolete_tool in (
        "1.py",
        "fix_imports_batch.py",
        "fix_init_files.py",
        "fix_json_comments.py",
        "fix_ncbi_component.py",
        "project_fixer.py",
        "quick_fix_component.py",
    ):
        assert not (PROJECT_ROOT / "tools" / obsolete_tool).exists()
    for legacy_script in (
        "cleanup_translations.py",
        "diag_db.py",
        "fully_restore_config.py",
        "populate.py",
        "populate_pathogens.py",
        "restore_sources.py",
        "upgrade_dictionaries.py",
    ):
        assert not (PROJECT_ROOT / "src" / "backend" / legacy_script).exists()
        assert (PROJECT_ROOT / "scripts" / "maintenance" / legacy_script).is_file()


def test_no_large_binaries_or_third_party_quast_tracked_in_git():
    """规则 15：严禁将第三方 quast 源码库、tools/ncbi_dist 或预编译二进制纳入 Git 跟踪。"""
    import subprocess

    out = subprocess.check_output(
        ["git", "-c", "core.quotepath=false", "ls-files"],
        cwd=PROJECT_ROOT,
        text=True,
        encoding="utf-8",
    )
    tracked = [line.strip() for line in out.splitlines() if line.strip()]
    forbidden_prefixes = ("quast/", "tools/ncbi_dist/", "tools/datasets", "tools/docs/")
    forbidden_exts = (".exe", ".dll", ".a", ".so", ".dylib")

    bad = [
        f
        for f in tracked
        if f.startswith(forbidden_prefixes) or f.lower().endswith(forbidden_exts)
    ]
    assert not bad, "发现违反规则 15 的受跟踪二进制或外置第三方库:\n" + "\n".join(bad[:20])


def test_frontend_vue_buttons_specify_type():
    """防止 Vue 模板中的 <button> 遗漏显式 type 属性（避免表单内意外 submit）。"""
    web_src = PROJECT_ROOT / "src" / "web-next" / "src"
    has_type_re = re.compile(r"(?:^|\s)(?::|v-bind:)?type\s*=", re.IGNORECASE)
    violations = []

    for p in sorted(web_src.rglob("*.vue")):
        if "__tests__" in p.parts:
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        start_m = re.search(r"<template(?:\s[^>]*)?>", text)
        end_idx = text.rfind("</template>")
        if not start_m or end_idx == -1:
            continue
        tpl = text[start_m.end():end_idx]
        tpl_base = start_m.end()
        i = 0
        n = len(tpl)
        while i < n:
            if tpl.startswith("<!--", i):
                end_c = tpl.find("-->", i + 4)
                i = n if end_c == -1 else end_c + 3
                continue
            if tpl[i] == "<":
                m_btn = re.match(r"<button(?=[\s/>])", tpl[i:], re.IGNORECASE)
                if m_btn:
                    j = i + m_btn.end()
                    quote = None
                    while j < n:
                        ch = tpl[j]
                        if quote:
                            if ch == quote:
                                quote = None
                        elif ch in ('"', "'"):
                            quote = ch
                        elif ch == ">":
                            break
                        j += 1
                    tag_text = tpl[i : j + 1]
                    if not has_type_re.search(tag_text):
                        ln = text[: tpl_base + i].count("\n") + 1
                        violations.append(f"{p.relative_to(PROJECT_ROOT)}:{ln}: {tag_text[:80]}")
                    i = j + 1
                    continue
            i += 1

    assert not violations, "发现缺失 type 属性的 Vue <button>:\n" + "\n".join(violations[:20])
