# -*- coding: utf-8 -*-
"""远程日志诊断发现问题的回归测试套件。"""
from __future__ import annotations

import ast
import logging
import sys
import warnings
from pathlib import Path
from unittest.mock import patch

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from src.backend.utils.access_log_filter import (  # noqa: E402
    NOISY_THIRD_PARTY_LOGGERS,
    silence_noisy_third_party_loggers,
)
from src.figure_studio.palette import (  # noqa: E402
    apply_journal_rcparams,
    ensure_figure_text_fonts,
    resolve_cjk_font,
    save_publication_figure,
)
from src.utils import system_monitor  # noqa: E402
import pytest

pytestmark = pytest.mark.offline


def test_strains_route_does_not_import_api_server() -> None:
    strains_path = project_root / "src" / "backend" / "routes" / "strains.py"
    tree = ast.parse(strains_path.read_text(encoding="utf-8"), filename=str(strains_path))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module_name = node.module or ""
            assert "api_server" not in module_name
            for alias in node.names:
                assert alias.name != "api_server"
        elif isinstance(node, ast.Import):
            for alias in node.names:
                assert "api_server" not in alias.name

    with (
        patch("psutil.cpu_percent", return_value=18.5),
        patch.object(system_monitor, "_LAST_RESOURCE_LOG_AT", 0.0),
    ):
        system_monitor.log_resources(force=True)
        # 第二次在 5 秒窗口内非 force 应被节流跳过，不抛异常
        system_monitor.log_resources(force=False)


def test_silence_noisy_third_party_loggers_sets_warning_level() -> None:
    for name in NOISY_THIRD_PARTY_LOGGERS:
        logging.getLogger(name).setLevel(logging.INFO)

    silence_noisy_third_party_loggers()

    for name in NOISY_THIRD_PARTY_LOGGERS:
        assert logging.getLogger(name).level >= logging.WARNING


def test_save_publication_figure_routes_cjk_tick_labels_without_glyph_warning(tmp_path: Path) -> None:
    apply_journal_rcparams()
    cjk_font = resolve_cjk_font()
    sample_label = "附件 霍氏肠杆菌噬菌体基因组序列"

    fig, ax = plt.subplots(figsize=(5, 4))
    ax.imshow([[1.0, 0.5], [0.5, 1.0]])
    ax.set_xticks([0, 1])
    ax.set_xticklabels([sample_label, "Phage_Ref"])
    ax.set_yticks([0, 1])
    ax.set_yticklabels(["Phage_Ref", sample_label])
    sup = fig.suptitle("附件 基因组相似性矩阵分析")

    rebound_count = ensure_figure_text_fonts(fig)
    if cjk_font != "DejaVu Sans":
        assert rebound_count >= 3
        assert sup.get_fontfamily()[0] == cjk_font
        for lbl in ax.get_xticklabels() + ax.get_yticklabels():
            if sample_label in lbl.get_text():
                assert lbl.get_fontfamily()[0] == cjk_font

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        generated = save_publication_figure(
            fig,
            out_dir=tmp_path,
            prefix="cjk_check",
            formats=("png", "pdf"),
            dpi=120,
        )

    assert len(generated) == 2
    for out_file in generated:
        assert out_file.exists() and out_file.stat().st_size > 0

    missing_warnings = [
        str(w.message)
        for w in caught
        if "missing from font" in str(w.message)
    ]
    if cjk_font != "DejaVu Sans":
        assert not missing_warnings, f"仍存在缺字告警: {missing_warnings}"


def test_ui_translations_endpoint_uses_cache_unless_reload_requested() -> None:
    from src.backend.api_server import app
    from src.utils.ui_translation_manager import get_ui_translator

    translator = get_ui_translator()
    translator.load_all_translations()
    client = TestClient(app)

    with patch.object(
        translator,
        "load_all_translations",
        wraps=translator.load_all_translations,
    ) as mock_load:
        r1 = client.get("/api/settings/ui_translations?lang=zh_CN")
        r2 = client.get("/api/settings/ui_translations?lang=zh_CN")
        assert r1.status_code == 200
        assert r2.status_code == 200
        assert mock_load.call_count == 0

        r3 = client.get("/api/settings/ui_translations?lang=zh_CN&reload=true")
        assert r3.status_code == 200
        assert mock_load.call_count == 1
