# -*- coding: utf-8 -*-
"""
无头浏览器配置、启动检查与自修复引擎单元测试
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


class TestHeadlessBrowserManager(unittest.TestCase):
    def test_config_healing_backfills_missing_section_and_invalid_values(self):
        from src.utils.headless_browser_manager import (
            DEFAULT_HEADLESS_BROWSER_CONFIG,
            heal_headless_browser_config,
        )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            default_cfg = {
                "language": "zh_CN",
                "headless_browser": dict(DEFAULT_HEADLESS_BROWSER_CONFIG),
            }
            (root / "config.default.json").write_text(
                json.dumps(default_cfg, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            # 模拟升级用户的旧 config.json：没有 headless_browser，且后续被写入脏值
            old_cfg = {
                "api_keys": {"dashscope": "user-key-keep"},
                "language": "zh_CN",
            }
            cfg_path = root / "config.json"
            cfg_path.write_text(json.dumps(old_cfg, ensure_ascii=False, indent=2), encoding="utf-8")

            res1 = heal_headless_browser_config(project_root=root, config_path=cfg_path)
            self.assertTrue(res1["changed"])
            reloaded = json.loads(cfg_path.read_text(encoding="utf-8"))
            self.assertEqual(reloaded["api_keys"]["dashscope"], "user-key-keep")
            self.assertEqual(reloaded["headless_browser"]["engine"], "chromium")
            self.assertTrue(reloaded["headless_browser"]["headless"])

            # 写入无效字段与不存在的自定义 exe 路径，验证自动纠偏自修复
            reloaded["headless_browser"]["launch_timeout_ms"] = -100
            reloaded["headless_browser"]["extra_args"] = "broken-string"
            reloaded["headless_browser"]["executable_path"] = str(root / "missing" / "chrome.exe")
            cfg_path.write_text(json.dumps(reloaded, ensure_ascii=False, indent=2), encoding="utf-8")

            res2 = heal_headless_browser_config(project_root=root, config_path=cfg_path)
            self.assertTrue(res2["changed"])
            fixed = json.loads(cfg_path.read_text(encoding="utf-8"))
            self.assertEqual(
                fixed["headless_browser"]["launch_timeout_ms"],
                DEFAULT_HEADLESS_BROWSER_CONFIG["launch_timeout_ms"],
            )
            self.assertIsInstance(fixed["headless_browser"]["extra_args"], list)
            self.assertEqual(fixed["headless_browser"]["executable_path"], "")
            self.assertTrue(any("executable_path" in act for act in res2["actions"]))

    def test_repair_cleans_incomplete_chromium_and_reinstalls_via_mirror(self):
        from src.utils.headless_browser_manager import (
            DEFAULT_HEADLESS_BROWSER_CONFIG,
            inspect_headless_browser,
            repair_headless_browser,
        )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg_path = root / "config.json"
            browsers_dir = root / "vendor" / "ms-playwright"
            # 模拟一次中断后残留的不完整目录（无 INSTALLATION_COMPLETE）
            broken_dir = browsers_dir / "chromium-1208" / "chrome-win64"
            broken_dir.mkdir(parents=True)
            (broken_dir / "chrome.exe").write_bytes(b"broken")

            cfg = {
                "headless_browser": {
                    **DEFAULT_HEADLESS_BROWSER_CONFIG,
                    "browsers_path": "vendor/ms-playwright",
                    "use_system_browser_fallback": False,
                }
            }
            cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")

            fake_manifest = {
                "revision": "1208",
                "version": "145.0.7632.6",
            }
            with patch(
                "src.utils.headless_browser_manager._read_playwright_package_info",
                return_value={"installed": True, "version": "1.58.0", "driver_ready": True, **fake_manifest},
            ), patch(
                "src.utils.headless_browser_manager._detect_system_browser",
                return_value=None,
            ):
                before = inspect_headless_browser(project_root=root, config_path=cfg_path, probe_launch=False)
                self.assertFalse(before["ready"])
                self.assertFalse(before["chromium_complete"])

                calls = []

                def fake_run(cmd, env=None, **kwargs):
                    host = (env or {}).get("PLAYWRIGHT_DOWNLOAD_HOST", "")
                    bpath = Path((env or {}).get("PLAYWRIGHT_BROWSERS_PATH", browsers_dir))
                    calls.append((list(cmd), host, str(bpath)))
                    # 主源故意失败一次，验证自动切换 fallback_download_host
                    if "npmmirror" in host:
                        return SimpleNamespace(returncode=1, stdout="", stderr="mirror timeout")
                    chrome_dir = bpath / "chromium-1208" / "chrome-win64"
                    chrome_dir.mkdir(parents=True, exist_ok=True)
                    (chrome_dir / "chrome.exe").write_bytes(b"MZ")
                    (bpath / "chromium-1208" / "INSTALLATION_COMPLETE").write_text("", encoding="utf-8")
                    shell_dir = bpath / "chromium_headless_shell-1208" / "chrome-headless-shell-win64"
                    shell_dir.mkdir(parents=True, exist_ok=True)
                    (shell_dir / "chrome-headless-shell.exe").write_bytes(b"MZ")
                    (bpath / "chromium_headless_shell-1208" / "INSTALLATION_COMPLETE").write_text("", encoding="utf-8")
                    return SimpleNamespace(returncode=0, stdout="ok", stderr="")

                with patch("subprocess.run", side_effect=fake_run), patch(
                    "src.utils.headless_browser_manager._check_windows_integrity_issues",
                    return_value=[],
                ):
                    report = repair_headless_browser(
                        project_root=root,
                        config_path=cfg_path,
                        auto_install=True,
                        probe_launch=False,
                    )

                self.assertTrue(report["ready"])
                self.assertEqual(report["mode"], "playwright_chromium")
                self.assertTrue(report["chromium_complete"])
                self.assertEqual(len(calls), 2)
                self.assertIn("npmmirror", calls[0][1])
                self.assertIn("azureedge", calls[1][1])

    def test_system_browser_fallback_when_playwright_install_fails(self):
        from src.utils.headless_browser_manager import (
            DEFAULT_HEADLESS_BROWSER_CONFIG,
            get_launch_options,
            repair_headless_browser,
        )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg_path = root / "config.json"
            fake_edge = root / "ProgramFiles" / "msedge.exe"
            fake_edge.parent.mkdir(parents=True)
            fake_edge.write_bytes(b"MZ")

            cfg = {
                "headless_browser": {
                    **DEFAULT_HEADLESS_BROWSER_CONFIG,
                    "browsers_path": "vendor/ms-playwright",
                    "use_system_browser_fallback": True,
                }
            }
            cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")

            with patch(
                "src.utils.headless_browser_manager._read_playwright_package_info",
                return_value={"installed": True, "version": "1.58.0", "driver_ready": True, "revision": "1208", "version_browser": "145.0"},
            ), patch(
                "src.utils.headless_browser_manager._detect_system_browser",
                return_value={"name": "msedge", "path": str(fake_edge)},
            ), patch(
                "src.utils.headless_browser_manager.subprocess.run",
                return_value=SimpleNamespace(returncode=1, stdout="", stderr="offline"),
            ), patch(
                "src.utils.headless_browser_manager._check_windows_integrity_issues",
                return_value=[],
            ):
                report = repair_headless_browser(
                    project_root=root,
                    config_path=cfg_path,
                    auto_install=True,
                    probe_launch=False,
                )
                self.assertTrue(report["ready"])
                self.assertEqual(report["mode"], "system_browser_fallback")
                opts = get_launch_options(project_root=root, config_path=cfg_path)
                self.assertEqual(opts["executable_path"], str(fake_edge))
                self.assertTrue(opts["headless"])

    def test_windows_low_integrity_repair(self):
        from src.utils.headless_browser_manager import (
            DEFAULT_HEADLESS_BROWSER_CONFIG,
            repair_headless_browser,
        )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg_path = root / "config.json"
            bpath = root / "vendor" / "ms-playwright"
            chrome_dir = bpath / "chromium-1208" / "chrome-win64"
            chrome_dir.mkdir(parents=True)
            exe_path = chrome_dir / "chrome.exe"
            exe_path.write_bytes(b"MZ")
            (bpath / "chromium-1208" / "INSTALLATION_COMPLETE").write_text("", encoding="utf-8")
            shell_dir = bpath / "chromium_headless_shell-1208" / "chrome-headless-shell-win64"
            shell_dir.mkdir(parents=True)
            (shell_dir / "chrome-headless-shell.exe").write_bytes(b"MZ")
            (bpath / "chromium_headless_shell-1208" / "INSTALLATION_COMPLETE").write_text("", encoding="utf-8")

            cfg_path.write_text(
                json.dumps(
                    {
                        "headless_browser": {
                            **DEFAULT_HEADLESS_BROWSER_CONFIG,
                            "browsers_path": "vendor/ms-playwright",
                        }
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            integrity_state = {"repaired": False}

            def fake_icacls_run(cmd, **kwargs):
                if "/setintegritylevel" in cmd:
                    integrity_state["repaired"] = True
                    return SimpleNamespace(returncode=0, stdout="Successfully processed", stderr="")
                if not integrity_state["repaired"]:
                    return SimpleNamespace(returncode=0, stdout="Mandatory Label\\Low Mandatory Level", stderr="")
                return SimpleNamespace(returncode=0, stdout="Mandatory Label\\Medium Mandatory Level", stderr="")

            with patch("src.utils.headless_browser_manager.os.name", "nt"), patch(
                "src.utils.headless_browser_manager._read_playwright_package_info",
                return_value={"installed": True, "version": "1.58.0", "driver_ready": True, "revision": "1208", "version_browser": "145.0"},
            ), patch(
                "src.utils.headless_browser_manager.subprocess.run",
                side_effect=fake_icacls_run,
            ):
                report = repair_headless_browser(
                    project_root=root,
                    config_path=cfg_path,
                    auto_install=False,
                    probe_launch=False,
                )
            self.assertTrue(integrity_state["repaired"])
            self.assertEqual(report["integrity_issue_paths"], [])
            self.assertTrue(any("Medium" in a for a in report["actions"]))

    def test_verify_and_install_deps_and_env_checker_include_playwright(self):
        from src.utils.environment_checker import EnvironmentChecker
        from src.utils.verify_and_install_deps import MODULE_IMPORT_MAP, heal_configurations

        self.assertIn("playwright", MODULE_IMPORT_MAP)
        checker = EnvironmentChecker()
        self.assertTrue(hasattr(checker, "check_headless_browser"))

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "config.default.json").write_text(
                json.dumps({"headless_browser": {"enabled": True, "headless": True}}, ensure_ascii=False),
                encoding="utf-8",
            )
            (root / "config.json").write_text(
                json.dumps({"language": "zh_CN"}, ensure_ascii=False),
                encoding="utf-8",
            )
            heal_configurations(root)
            merged = json.loads((root / "config.json").read_text(encoding="utf-8"))
            self.assertEqual(merged["language"], "zh_CN")
            self.assertIn("headless_browser", merged)

    def test_sangon_browser_session_uses_config_and_heals_on_launch_error(self):
        from src.backend.services.other_tools.sangon_downloader import SangonBrowserSession

        launch_calls = []

        class DummyChromium:
            def launch(self, **kwargs):
                launch_calls.append(dict(kwargs))
                if len(launch_calls) == 1:
                    raise RuntimeError("Executable doesn't exist at broken/chrome.exe")
                return SimpleNamespace(
                    new_context=lambda **kw: SimpleNamespace(
                        new_page=lambda: SimpleNamespace(),
                        close=lambda: None,
                    ),
                    close=lambda: None,
                )

        class DummyPWCM:
            def __enter__(self):
                return SimpleNamespace(chromium=DummyChromium())

            def __exit__(self, *args):
                return False

        with patch(
            "playwright.sync_api.sync_playwright",
            return_value=DummyPWCM(),
        ), patch(
            "src.backend.services.other_tools.sangon_downloader.get_launch_options",
            return_value={
                "enabled": True,
                "headless": True,
                "timeout_ms": 45000,
                "executable_path": "",
                "args": ["--no-sandbox"],
                "env": {"PLAYWRIGHT_BROWSERS_PATH": "vendor/ms-playwright"},
            },
        ), patch(
            "src.backend.services.other_tools.sangon_downloader.repair_headless_browser",
            return_value={"ready": True, "mode": "playwright_chromium", "actions": ["repaired"]},
        ) as repair_mock:
            with SangonBrowserSession("15000000000", "pwd") as sess:
                self.assertIsNotNone(sess)
            self.assertEqual(len(launch_calls), 2)
            self.assertEqual(launch_calls[1]["args"], ["--no-sandbox"])
            self.assertEqual(launch_calls[1]["timeout"], 45000)
            self.assertGreaterEqual(repair_mock.call_count, 1)

    def test_complete_chromium_not_shadowed_by_incomplete_higher_revision(self):
        from src.utils.headless_browser_manager import _find_chromium_artifacts, _chromium_rel_candidates

        with tempfile.TemporaryDirectory() as tmp:
            bdir = Path(tmp)
            # 更高修订号但残缺
            broken = bdir / "chromium-9999" / "chrome-win64"
            broken.mkdir(parents=True)
            (broken / "chrome.exe").write_bytes(b"broken")
            # 较旧修订号但完整
            good = bdir / "chromium-1208" / "chrome-win64"
            good.mkdir(parents=True)
            (good / "chrome.exe").write_bytes(b"MZ")
            (bdir / "chromium-1208" / "INSTALLATION_COMPLETE").write_text("", encoding="utf-8")

            res = _find_chromium_artifacts(bdir, "chromium", _chromium_rel_candidates(), expected_revision="")
            self.assertTrue(res["complete"])
            self.assertIn("chromium-1208", res["dir_path"])

    def test_disabled_browser_blocks_sangon_session(self):
        from src.backend.services.other_tools.sangon_downloader import SangonBrowserSession, SangonOrderDownloadError

        with patch(
            "src.backend.services.other_tools.sangon_downloader.get_launch_options",
            return_value={"enabled": False, "headless": True, "timeout_ms": 90000, "executable_path": "", "args": [], "env": {}},
        ):
            with self.assertRaises(SangonOrderDownloadError):
                SangonBrowserSession("15000000000", "pwd").__enter__()


if __name__ == "__main__":
    unittest.main()
