# -*- coding: utf-8 -*-
"""
测试其他功能工作台后端 API (src/backend/routes/other_tools.py)
验证：
1. 邮件自动收件 → 注释 → Word 报告 → SMTP 回传 概览接口
2. 生工 16S 测序结果自动化 BLAST 与导出流程 概览与结果读取接口
3. 严禁 Emoji 与强制 UTF-8 合规性检查
"""

import asyncio
from pathlib import Path
from src.backend.routes.other_tools import (
    get_mail_pipeline_overview,
    get_sangon_16s_overview,
    get_sangon_order_results,
)


def test_mail_pipeline_overview_structure():
    """验证邮件自动化流水线概览接口返回完整的配置、运行时与真实本地批次统计"""
    res = asyncio.run(get_mail_pipeline_overview())
    assert res["status"] == "success"
    assert "config" in res
    assert "auth_ready" in res
    assert "runtime" in res
    assert isinstance(res["batches"], list)
    assert isinstance(res["outbound_packages"], list)
    assert isinstance(res["docx_reports"], list)
    assert isinstance(res["pipeline_logs"], list)


def test_sangon_16s_overview_and_order_results():
    """验证生工 16S 自动化 BLAST 流水线概览接口与订单 CSV 读取"""
    res = asyncio.run(get_sangon_16s_overview())
    assert res["status"] == "success"
    assert "sangon_root" in res
    assert "db_16s_ready" in res
    assert isinstance(res["orders"], list)

    orders_with_csv = [o for o in res["orders"] if o.get("has_result_csv")]
    if orders_with_csv:
        first_order = orders_with_csv[0]["dir_name"]
        detail = asyncio.run(get_sangon_order_results(first_order))
        assert detail["status"] == "success"
        assert len(detail["rows"]) > 0
        assert len(detail["headers"]) == 11


def test_no_emoji_and_utf8_in_new_files():
    """验证新增前后端代码文件全部采用 UTF-8 且不含任何 Emoji 字符"""
    repo_root = Path(__file__).resolve().parents[1]
    target_files = [
        repo_root / "src" / "backend" / "routes" / "other_tools.py",
        repo_root / "src" / "web-next" / "src" / "views" / "OtherToolsView.vue",
        repo_root / "src" / "web-next" / "src" / "views" / "OtherTools" / "modules" / "MailAutoPipelineModule.vue",
        repo_root / "src" / "web-next" / "src" / "views" / "OtherTools" / "modules" / "Sangon16SPipelineModule.vue",
        repo_root / "src" / "web-next" / "src" / "components" / "layout" / "AppSidebar.vue",
        repo_root / "src" / "web-next" / "src" / "router" / "index.ts",
    ]
    for path in target_files:
        assert path.exists(), f"Missing file: {path}"
        content = path.read_text(encoding="utf-8")
        for ch in content:
            code = ord(ch)
            is_emoji = (
                0x1F300 <= code <= 0x1FAFF
                or 0x2600 <= code <= 0x27BF
                or 0xFE00 <= code <= 0xFE0F
            )
            assert not is_emoji, f"Emoji character U+{code:04X} found in {path}"
