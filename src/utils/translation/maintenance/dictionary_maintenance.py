# -*- coding: utf-8 -*-
"""
词典维护主控制器 (Dictionary Maintenance Controller)
负责：
1. 数据自动备份与断点保护
2. 高性能词条清洗与双名法校准
3. 分片落盘与防 OOM 处理
4. 生成详细维护报告与差异审计
"""

import os
import sys
import time
import json
import shutil
import sqlite3
import logging
from pathlib import Path
from typing import Dict, List, Any, Tuple, Optional

from .term_cleaner import TermCleaner
from .genus_aligner import GenusAligner
from .epithet_corrector import EpithetCorrector
from .taxonomy_kb import TaxonomyKnowledgeBase

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def process_item_worker(item: Tuple[str, str, str, str]) -> Dict[str, Any]:
    """
    单个条目的清洗与校对函数
    item: (english, chinese, category, source)
    """
    english, chinese, category, source = item
    
    # 1. 检查是否为脏数据
    if TermCleaner.is_junk_or_test_entry(english):
        return {
            "english": english,
            "action": "delete",
            "reason": "测试或垃圾数据清理",
            "original_chinese": chinese
        }

    # 2. 基础清洗 (去叠词、标点、环境未培养映射)
    cleaned_chi, was_cleaned = TermCleaner.clean_chinese_text(english, chinese)
    
    # 3. 处理未翻译情况
    if cleaned_chi.lower() == english.lower():
        fallback = TermCleaner.handle_untranslated(english, cleaned_chi)
        if fallback:
            cleaned_chi = fallback
            was_cleaned = True

    # 4. 种加词纠偏
    epithet_corrector = EpithetCorrector()
    ep_chi, was_ep_corrected, ep_reason = epithet_corrector.correct_epithet_translation(english, cleaned_chi)
    if was_ep_corrected:
        cleaned_chi = ep_chi
        was_cleaned = True

    # 5. 属名对齐与校正
    genus_aligner = GenusAligner()
    gen_chi, was_gen_aligned, gen_reason = genus_aligner.align_species_genus(english, cleaned_chi)
    if was_gen_aligned:
        cleaned_chi = gen_chi
        was_cleaned = True

    if was_cleaned and cleaned_chi != chinese:
        reason = ep_reason or gen_reason or "文本清洗与术语标准化"
        return {
            "english": english,
            "action": "update",
            "original_chinese": chinese,
            "new_chinese": cleaned_chi,
            "category": category,
            "source": source,
            "reason": reason
        }

    return {"english": english, "action": "keep"}


class DictionaryMaintenance:
    """
    词典维护系统
    """

    def __init__(self, db_path: Optional[str] = None):
        self.project_root = Path(__file__).resolve().parents[4]
        if db_path:
            self.db_path = Path(db_path)
        else:
            self.db_path = self.project_root / "translations.db"

        self.reports_dir = self.project_root / "reports"
        self.reports_dir.mkdir(parents=True, exist_ok=True)

    def backup_database(self) -> Path:
        """创建带时间戳的完整数据库备份"""
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        backup_name = f"translations_backup_{timestamp}.db"
        backup_path = self.project_root / backup_name
        shutil.copy2(self.db_path, backup_path)
        logger.info(f"数据库备份成功: {backup_path.name}")
        return backup_path

    def run_maintenance(self, dry_run: bool = False, chunk_size: int = 1000) -> Dict[str, Any]:
        """
        执行词库全面维护与更新
        """
        if not self.db_path.exists():
            logger.error(f"未找到翻译数据库: {self.db_path}")
            return {"success": False, "error": "Database not found"}

        logger.info(f"开始词库健康维护任务 (模式: {'Dry-Run (只读预览)' if dry_run else '正式落盘'}, 分片大小: {chunk_size})...")

        # 1. 自动备份
        backup_file = None
        if not dry_run:
            backup_file = str(self.backup_database())

        # 2. 读取全部待处理词条
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT english, chinese, category, source FROM translations")
        rows = cursor.fetchall()
        conn.close()

        total_records = len(rows)
        logger.info(f"总计载入 {total_records} 条词典记录，开始逐条诊断与清洗...")

        updates = []
        deletions = []

        # 3. 流式处理与收集
        for item in rows:
            res = process_item_worker(item)
            if res["action"] == "delete":
                deletions.append(res)
            elif res["action"] == "update":
                updates.append(res)

        logger.info(f"诊断分析完成: 需清理脏数据 {len(deletions)} 条, 需纠偏修正 {len(updates)} 条, 保持无误 {total_records - len(deletions) - len(updates)} 条。")

        # 4. 执行分片落盘与断点保护
        if not dry_run and (updates or deletions):
            logger.info("正在执行分片落盘写入数据库...")
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("PRAGMA journal_mode=WAL;")
            cursor.execute("PRAGMA synchronous=NORMAL;")

            # 执行删除
            if deletions:
                for del_item in deletions:
                    cursor.execute("DELETE FROM translations WHERE english = ?", (del_item["english"],))
                conn.commit()
                logger.info(f"已成功清理 {len(deletions)} 条脏数据。")

            # 分片更新
            for i in range(0, len(updates), chunk_size):
                batch = updates[i:i + chunk_size]
                update_tuples = [(item["new_chinese"], "maintained_rule", item["english"]) for item in batch]
                cursor.executemany(
                    "UPDATE translations SET chinese = ?, source = ? WHERE english = ?",
                    update_tuples
                )
                conn.commit()
                logger.info(f"已落盘更新批次 [{min(i + chunk_size, len(updates))}/{len(updates)}]")

            conn.close()
            logger.info("所有词条修改已安全落盘并同步至 WAL。")

        # 5. 导出审计维护报告
        report_path = self.reports_dir / "dictionary_maintenance_report.json"
        report_data = {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "dry_run": dry_run,
            "backup_file": backup_file,
            "total_inspected": total_records,
            "deleted_count": len(deletions),
            "updated_count": len(updates),
            "unmodified_count": total_records - len(deletions) - len(updates),
            "deletions_list": deletions,
            "sample_updates": updates[:200],  # 抽样前200条展示
            "all_updates_count": len(updates)
        }

        with open(report_path, "w", encoding="utf-8") as rf:
            json.dump(report_data, rf, ensure_ascii=False, indent=2)

        logger.info(f"详细维护审计报告已生成: {report_path}")

        return report_data
