# -*- coding: utf-8 -*-
"""
测试其他功能工作台后端 API 与服务层
验证：
1. 邮件自动收件 -> 注释 -> Word 报告 -> SMTP 回传 概览接口（含完整路径与授权码掩码信息）
2. 生工 16S 测序结果自动化 BLAST 与导出流程 概览与结果读取接口
3. 目录修改后的自动迁移与 JSON 路径修正 (dir_migrator.py)
4. 邮箱 Key 读写与掩码 (secret_store.py)
5. 邮件流水线与生工 16S 历史数据清理 (history_cleaner.py)
6. 严禁 Emoji 与强制 UTF-8 合规性检查
"""

import asyncio
import json
import tempfile
from pathlib import Path

from src.backend.routes.other_tools import (
    get_mail_pipeline_overview,
    get_sangon_16s_overview,
    get_sangon_order_results,
)
from src.backend.services.other_tools.dir_migrator import migrate_directory
from src.backend.services.other_tools.history_cleaner import (
    cleanup_mail_history,
    cleanup_sangon_history,
)
from src.backend.services.other_tools.secret_store import (
    mask_secret,
    read_secret,
    write_secret,
)


def test_mail_pipeline_overview_structure():
    """验证邮件自动化流水线概览接口返回完整绝对路径、授权码状态与批次统计"""
    res = asyncio.run(get_mail_pipeline_overview())
    assert res["status"] == "success"
    assert "config" in res
    assert "auth" in res
    assert "imap_ready" in res["auth"]
    assert "imap_file" in res["auth"]
    assert Path(res["resolved_download_dir"]).is_absolute()
    assert Path(res["resolved_send_dir"]).is_absolute()
    assert isinstance(res["batches"], list)
    assert isinstance(res["outbound_packages"], list)
    assert isinstance(res["docx_reports"], list)


def test_sangon_16s_overview_and_order_results():
    """验证生工 16S 自动化 BLAST 流水线概览接口与订单 CSV 读取"""
    res = asyncio.run(get_sangon_16s_overview())
    assert res["status"] == "success"
    assert "sangon_root" in res
    assert Path(res["sangon_root"]).is_absolute()
    assert "db_16s_ready" in res
    assert isinstance(res["orders"], list)

    orders_with_csv = [o for o in res["orders"] if o.get("has_result_csv")]
    if orders_with_csv:
        first_order = orders_with_csv[0]["dir_name"]
        detail = asyncio.run(get_sangon_order_results(first_order))
        assert detail["status"] == "success"
        assert len(detail["rows"]) > 0
        assert len(detail["headers"]) == 11


def test_directory_migration_and_json_rewrite():
    """验证修改目录后旧目录内容自动迁移至新目录并修正 JSON 内的旧绝对路径"""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        old_dir = root / "old_downloads"
        new_dir = root / "new_downloads"
        batch_dir = old_dir / "up_20261111_000001"
        batch_dir.mkdir(parents=True)

        fasta_file = batch_dir / "sample.fasta"
        fasta_file.write_text(">seq1\nATGC\n", encoding="utf-8")

        idx_file = old_dir / "processed_index.json"
        idx_file.write_text(
            json.dumps(
                {
                    "abc123": {
                        "sha256": "abc123",
                        "path": str(fasta_file.resolve()),
                    }
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        mig = migrate_directory(old_dir, new_dir)
        assert mig["migrated"] is True
        assert mig["moved_count"] == 2
        assert mig["json_rewritten"] == 1
        assert not old_dir.exists()
        assert (new_dir / "up_20261111_000001" / "sample.fasta").exists()

        rewritten = json.loads((new_dir / "processed_index.json").read_text(encoding="utf-8"))
        assert rewritten["abc123"]["path"] == str((new_dir.resolve() / "up_20261111_000001" / "sample.fasta"))


def test_secret_store_read_write_mask():
    """验证邮箱 Key 的写入、读取、掩码与清空删除"""
    with tempfile.TemporaryDirectory() as tmp:
        key_path = Path(tmp) / ".mail_auth"
        assert read_secret(key_path) is None
        write_secret(key_path, "abcdef123456")
        val = read_secret(key_path)
        assert val == "abcdef123456"
        assert mask_secret(val) == "ab********56"

        write_secret(key_path, "")
        assert not key_path.exists()
        assert read_secret(key_path) is None


def test_mail_and_sangon_history_cleanup():
    """验证邮件流水线与生工 16S 历史数据按需清理"""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        dl = root / "dl"
        send = root / "send"
        anno = root / "anno"
        dl.mkdir()
        send.mkdir()
        anno.mkdir()

        # 构造邮件批次与回传产物
        b1 = dl / "up_20261111_01"
        b1.mkdir()
        (b1 / "a.fasta").write_text(">a\nAA\n", encoding="utf-8")
        (dl / "processed_index.json").write_text(
            json.dumps({"sha1": {"batch": "up_20261111_01", "first_seen": "2026-11-11T10:00:00"}}),
            encoding="utf-8",
        )
        (send / "TASK1.zip").write_bytes(b"PK\x03\x04test")
        (send / "TASK1.manifest.json").write_text(
            json.dumps({"task_id": "TASK1", "zip": "TASK1.zip"}), encoding="utf-8"
        )
        (anno / "TASK1").mkdir()
        (anno / "TASK1" / "inter.txt").write_text("temp", encoding="utf-8")

        res = cleanup_mail_history(dl, send, anno, targets=["batches", "outbound", "annotations"])
        assert res["removed_count"] >= 3
        assert not b1.exists()
        assert not (send / "TASK1.zip").exists()
        assert not (anno / "TASK1").exists()
        # 未勾选 index 时去重索引保留
        idx_after = json.loads((dl / "processed_index.json").read_text(encoding="utf-8"))
        assert "sha1" in idx_after

        # 勾选 index 时清理去重记录
        res2 = cleanup_mail_history(dl, send, anno, targets=["index"])
        assert res2["index_removed"] == 1

        # 构造生工 16S 订单清理测试
        sangon_root = root / "sangon"
        blast_root = root / "blast"
        order_dir = sangon_root / "20261111_1234567890"
        (order_dir / "原始压缩包").mkdir(parents=True)
        (order_dir / "原始数据").mkdir(parents=True)
        (order_dir / "BLAST结果").mkdir(parents=True)
        (order_dir / "原始压缩包" / "raw.zip").write_bytes(b"zip")
        (order_dir / "原始数据" / "seq.1.fasta").write_text(">s\nAA\n", encoding="utf-8")
        (order_dir / "BLAST结果" / "16S鉴定结果.csv").write_text("col1,col2\n", encoding="utf-8")
        (blast_root / "20261111_1234567890_16s").mkdir(parents=True)

        s_res = cleanup_sangon_history(
            sangon_root,
            blast_root,
            ["20261111_1234567890"],
            targets=["raw_extracted", "blast_cache", "result_csv"],
        )
        assert s_res["removed_count"] >= 3
        assert (order_dir / "原始压缩包" / "raw.zip").exists()
        assert not (order_dir / "原始数据" / "seq.1.fasta").exists()
        assert not (order_dir / "BLAST结果" / "16S鉴定结果.csv").exists()
        assert not (blast_root / "20261111_1234567890_16s").exists()


def test_no_emoji_and_utf8_in_new_files():
    """验证新增与修改的前后端代码文件全部采用 UTF-8 且不含任何 Emoji 字符"""
    repo_root = Path(__file__).resolve().parents[1]
    target_files = [
        repo_root / "src" / "mail_download" / "config.py",
        repo_root / "src" / "backend" / "routes" / "other_tools.py",
        repo_root / "src" / "backend" / "services" / "other_tools" / "dir_migrator.py",
        repo_root / "src" / "backend" / "services" / "other_tools" / "history_cleaner.py",
        repo_root / "src" / "backend" / "services" / "other_tools" / "sangon_settings.py",
        repo_root / "src" / "backend" / "services" / "other_tools" / "secret_store.py",
        repo_root / "src" / "web-next" / "src" / "views" / "OtherToolsView.vue",
        repo_root / "src" / "web-next" / "src" / "views" / "OtherTools" / "api.ts",
        repo_root / "src" / "web-next" / "src" / "views" / "OtherTools" / "components" / "PathField.vue",
        repo_root / "src" / "web-next" / "src" / "views" / "OtherTools" / "components" / "CleanupDialog.vue",
        repo_root / "src" / "web-next" / "src" / "views" / "OtherTools" / "modules" / "MailAutoPipelineModule.vue",
        repo_root / "src" / "web-next" / "src" / "views" / "OtherTools" / "modules" / "Sangon16SPipelineModule.vue",
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
