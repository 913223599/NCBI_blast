# -*- coding: utf-8 -*-
"""
启动检查与全链路环境自修复回归测试
覆盖：
1. requirements.txt / MODULE_IMPORT_MAP / scripts/verify_and_install_deps.py 一致性
2. bio_tools_healer: SRA-Tools DLL 自修复、vendor/ete4 .pth 自愈、辅助与外部工具缺失补齐、BLAST+/Git 持久化配置
3. scripts/check_npm_deps.js 全量包校验（拦截仅保留 vite 的浅检查漏判）
4. scripts/ensure_electron.ps1 脱离 Get-FileHash 后的校验与恢复能力
5. scripts/repair_integrity.ps1 覆盖全量关键二进制的低完整性自愈
6. 新增脚本与文档零 Emoji / UTF-8 规范
"""
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


class TestStartupSelfHealing:
    """启动检查与环境自修复单元测试与沙盒集成测试"""

    def test_requirements_and_verify_scripts_complete_and_consistent(self):
        from src.utils.verify_and_install_deps import (
            MODULE_IMPORT_MAP,
            OPTIONAL_MODULE_IMPORT_MAP,
            read_requirement_specs,
            _req_name,
        )
        import scripts.verify_and_install_deps as legacy_verify

        req_specs = read_requirement_specs(REPO_ROOT / "requirements.txt")
        req_names = {_req_name(s) for s in req_specs}

        # 业务代码顶层或自动流水线强依赖的包必须全部入库并受检
        for must_pkg in ("openpyxl", "python-docx", "dashscope", "playwright", "scipy", "networkx"):
            assert must_pkg in req_names, f"requirements.txt 缺少核心依赖: {must_pkg}"

        map_norm = {k.lower().replace("_", "-") for k in MODULE_IMPORT_MAP}
        for pkg in ("openpyxl", "python-docx", "dashscope", "playwright", "scipy", "networkx"):
            assert pkg in map_norm, f"MODULE_IMPORT_MAP 缺少核心依赖: {pkg}"

        # requirements.txt 中除安装器 uv 外的全部声明包，均必须受 MODULE_IMPORT_MAP 审计
        uncovered = sorted(req_names - map_norm - {"uv"})
        assert not uncovered, f"requirements.txt 存在未纳入 MODULE_IMPORT_MAP 的包: {uncovered}"

        # edlib 必须仅在可选依赖映射中，不能阻断启动
        assert "edlib" in OPTIONAL_MODULE_IMPORT_MAP
        assert "edlib" not in MODULE_IMPORT_MAP

        # 备用脚本需与主自愈脚本保持同步，不再把 edlib 设为必装
        assert "edlib" not in legacy_verify.MODULE_IMPORT_MAP
        for pkg in ("openpyxl", "python-docx", "scipy", "networkx"):
            assert pkg in {k.lower().replace("_", "-") for k in legacy_verify.MODULE_IMPORT_MAP}

    def test_sra_tools_dll_and_vendor_ete4_healing(self, tmp_path):
        from src.utils.bio_tools_healer import heal_sra_tools_dlls, heal_vendor_ete4_binding

        # 1. 模拟 sra-tools 有 exe 但缺少 libwinpthread-1.dll，tree-tools 有该 DLL
        sra_dir = tmp_path / "tools" / "ncbi_dist" / "bin" / "sra-tools"
        tree_dir = tmp_path / "tools" / "ncbi_dist" / "bin" / "tree-tools"
        sra_dir.mkdir(parents=True)
        tree_dir.mkdir(parents=True)
        (sra_dir / "prefetch.exe").write_bytes(b"MZ")
        (sra_dir / "fasterq-dump.exe").write_bytes(b"MZ")
        (tree_dir / "libwinpthread-1.dll").write_bytes(b"DLLDATA")

        res_sra = heal_sra_tools_dlls(tmp_path)
        assert res_sra["ready"] is True
        assert (sra_dir / "libwinpthread-1.dll").read_bytes() == b"DLLDATA"
        assert any("libwinpthread-1.dll" in act for act in res_sra["actions"])

        # 2. 模拟 vendor/ete4 存在时自动修复 site-packages .pth 绑定
        ete_pkg = tmp_path / "vendor" / "ete4" / "ete4"
        ete_pkg.mkdir(parents=True)
        (ete_pkg / "__init__.py").write_text("# mock ete4\n__version__ = '4.0'\n", encoding="utf-8")
        fake_site = tmp_path / ".venv" / "Lib" / "site-packages"
        fake_site.mkdir(parents=True)

        res_ete = heal_vendor_ete4_binding(tmp_path, site_packages_dir=fake_site)
        assert res_ete["ready"] is True
        pth_file = fake_site / "ncbi_blast_vendor.pth"
        assert pth_file.is_file()
        assert str((tmp_path / "vendor" / "ete4").resolve()) in pth_file.read_text(encoding="utf-8")

    def test_phylogeny_binaries_and_persist_blast_git(self, tmp_path):
        from src.utils.bio_tools_healer import (
            detect_and_persist_blast_and_git,
            heal_phylogeny_and_alignment_binaries,
        )

        # 1. 构造 tree-tools 内的 FastTree/muscle 及缺失的 mafft/iqtree/mb，校验可精准补齐
        tree_dir = tmp_path / "tools" / "ncbi_dist" / "bin" / "tree-tools"
        tree_dir.mkdir(parents=True)
        (tree_dir / "FastTree.exe").write_bytes(b"FT")
        (tree_dir / "muscle.exe").write_bytes(b"MS")
        # 预先放一个已有工具验证不会被重复下载
        iq_dir = tmp_path / "vendor" / "iqtree3"
        iq_dir.mkdir(parents=True)
        (iq_dir / "iqtree.exe").write_bytes(b"IQ")

        downloaded_targets = []

        def fake_downloader(tool_key: str, dest_path: Path) -> bool:
            downloaded_targets.append(tool_key)
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            dest_path.write_bytes(b"DL")
            return True

        res_bio = heal_phylogeny_and_alignment_binaries(
            tmp_path,
            auto_download=True,
            downloader=fake_downloader,
        )
        assert res_bio["ready"] is True
        assert (tmp_path / "src" / "workbench" / "bin" / "FastTree.exe").is_file()
        assert (tmp_path / "vendor" / "fasttree" / "FastTree.exe").is_file()
        assert (tmp_path / "src" / "workbench" / "bin" / "muscle.exe").is_file()
        assert (tmp_path / "src" / "workbench" / "bin" / "mafft.exe").is_file()
        assert (tmp_path / "vendor" / "MrBayes" / "mb.exe").is_file()
        # iqtree 已存在不应重复下载；mafft 和 mb 缺失应精准触发
        assert "iqtree.exe" not in downloaded_targets
        assert set(downloaded_targets) == {"mafft.exe", "mb.exe"}

        # 2. 模拟 config.json 空配置自动持久化发现的 portable Git 与本地 BLAST+
        cfg_file = tmp_path / "config.json"
        cfg_file.write_text(json.dumps({"blast_bin_path": "", "git_bin_path": ""}, ensure_ascii=False), encoding="utf-8")
        portable_git = tmp_path / "tools" / "git" / "cmd" / "git.exe"
        portable_git.parent.mkdir(parents=True)
        portable_git.write_bytes(b"GIT")
        local_blast_dir = tmp_path / "vendor" / "blast" / "bin"
        local_blast_dir.mkdir(parents=True)
        (local_blast_dir / "blastn.exe").write_bytes(b"BLASTN")

        res_tools = detect_and_persist_blast_and_git(tmp_path, config_path=cfg_file, persist=True)
        saved_cfg = json.loads(cfg_file.read_text(encoding="utf-8"))
        assert res_tools["git_ready"] is True
        assert res_tools["blast_ready"] is True
        assert saved_cfg["git_bin_path"] == str(portable_git)
        assert saved_cfg["blast_bin_path"] == str(local_blast_dir)

    def test_npm_full_dependency_checker_catches_partial_missing(self, tmp_path):
        checker = REPO_ROOT / "scripts" / "check_npm_deps.js"
        assert checker.is_file(), f"缺少 npm 全量依赖校验脚本: {checker}"

        pkg_dir = tmp_path / "web"
        (pkg_dir / "node_modules" / "vite").mkdir(parents=True)
        (pkg_dir / "node_modules" / "vite" / "package.json").write_text('{"name":"vite"}', encoding="utf-8")
        (pkg_dir / "package.json").write_text(
            json.dumps(
                {
                    "dependencies": {"vue": "^3.5.0", "@vueuse/core": "^14.0.0"},
                    "devDependencies": {"vite": "^7.0.0"},
                }
            ),
            encoding="utf-8",
        )

        # 仅留 vite 时必须判定失败并列出 vue 和 @vueuse/core
        r_fail = subprocess.run(["node", str(checker), str(pkg_dir)], capture_output=True, text=True, encoding="utf-8")
        assert r_fail.returncode != 0
        assert "vue" in r_fail.stdout
        assert "@vueuse/core" in r_fail.stdout

        # 补齐全部声明依赖后必须通过
        for dep in ("vue", "@vueuse/core"):
            d = pkg_dir / "node_modules" / Path(dep)
            d.mkdir(parents=True, exist_ok=True)
            (d / "package.json").write_text(json.dumps({"name": dep}), encoding="utf-8")

        r_ok = subprocess.run(["node", str(checker), str(pkg_dir)], capture_output=True, text=True, encoding="utf-8")
        assert r_ok.returncode == 0

    def test_ensure_electron_no_longer_uses_get_filehash_and_repairs_broken_dist(self, tmp_path):
        script = REPO_ROOT / "scripts" / "ensure_electron.ps1"
        content = script.read_text(encoding="utf-8")
        assert "Get-FileHash" not in content, "ensure_electron.ps1 不得依赖部分 Windows 下缺失的 Get-FileHash"

        ec_cache = Path(os.environ.get("LOCALAPPDATA", "")) / "electron" / "Cache"
        e_pkg = REPO_ROOT / "electron-shell" / "node_modules" / "electron" / "package.json"
        if ec_cache.is_dir() and list(ec_cache.rglob("*.zip")) and e_pkg.is_file():
            e_dir = tmp_path / "electron-shell" / "node_modules" / "electron"
            e_dir.mkdir(parents=True)
            shutil.copy2(e_pkg, e_dir / "package.json")
            shutil.copy2(e_pkg.parent / "checksums.json", e_dir / "checksums.json")
            (e_dir / "dist" / "locales").mkdir(parents=True)

            res = subprocess.run(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script), "-ProjectRoot", str(tmp_path)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=60,
            )
            assert res.returncode == 0, f"ensure_electron 恢复失败: {res.stdout}\n{res.stderr}"
            assert (e_dir / "dist" / "electron.exe").is_file()
            assert (e_dir / "dist" / "version").is_file()

    def test_repair_integrity_covers_all_critical_bio_binaries(self):
        script = REPO_ROOT / "scripts" / "repair_integrity.ps1"
        text = script.read_text(encoding="utf-8")
        for expected in ("mafft.exe", "iqtree.exe", "mb.exe", "prefetch.exe", "fasterq-dump.exe", "chrome.exe"):
            assert expected in text, f"repair_integrity.ps1 遗漏关键可执行文件: {expected}"

    def test_no_emoji_in_startup_healing_files(self):
        emoji_re = re.compile(r"[\U0001F300-\U0001FAFF\u2600-\u27BF]")
        targets = [
            REPO_ROOT / "RUN_DEV_ELECTRON.bat",
            REPO_ROOT / "scripts" / "check_npm_deps.js",
            REPO_ROOT / "scripts" / "ensure_electron.ps1",
            REPO_ROOT / "scripts" / "repair_integrity.ps1",
            REPO_ROOT / "scripts" / "verify_and_install_deps.py",
            REPO_ROOT / "src" / "utils" / "verify_and_install_deps.py",
            REPO_ROOT / "src" / "utils" / "environment_checker.py",
            REPO_ROOT / "src" / "utils" / "bio_tools_healer.py",
        ]
        for p in targets:
            assert p.is_file(), f"文件不存在: {p}"
            txt = p.read_text(encoding="utf-8")
            assert not emoji_re.search(txt), f"检测到禁止的 Emoji 字符: {p}"

    def test_run_dev_electron_bat_wires_all_startup_healers(self):
        bat_text = (REPO_ROOT / "RUN_DEV_ELECTRON.bat").read_text(encoding="utf-8")
        # 关键启动检查链路与错误退出门禁不可缺失
        for token in (
            "verify_and_install_deps.py",
            'node "scripts\\check_npm_deps.js" "electron-shell"',
            'node "scripts\\check_npm_deps.js" "src\\web-next"',
            'node "scripts\\check_npm_deps.js" "."',
            "ensure_electron.ps1",
            "repair_integrity.ps1",
        ):
            assert token in bat_text, f"RUN_DEV_ELECTRON.bat 缺失关键启动检查步骤: {token}"

        # 确认批处理文件中括号块平衡（避免 cmd 解析块结构出错）
        open_parens = 0
        for raw_line in bat_text.splitlines():
            line = raw_line.strip()
            if not line or line.upper().startswith("REM "):
                continue
            # 跳过 echo 输出中的说明性括号，仅统计命令控制块括号
            if line.lower().startswith("echo "):
                continue
            if line.startswith(")"):
                open_parens -= 1
                assert open_parens >= 0, f"批处理控制块出现多余右括号: {raw_line}"
            if line.endswith("("):
                open_parens += 1
        assert open_parens == 0, f"批处理控制块括号未闭合 (余 {open_parens})"
