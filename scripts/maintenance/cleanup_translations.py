"""
清理词库中由 taxonomy_sync 自动填入的无效中文翻译词条。

问题：taxonomy_sync_service 在自动填充翻译词库时，
将英文原词直接复制为中文翻译（chinese = english），导致词库中
出现大量没有真正中文翻译的假词条。

策略：
1. 查找所有 source='taxonomy_sync' 且 english == chinese 的词条
2. 统计并展示这些无效词条
3. 删除它们
4. 去除所有完全重复的词条
"""
import sqlite3
import logging

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

DB_PATH = "translations.db"

def cleanup():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # 1. 统计全部词条
    total_count = cursor.execute("SELECT COUNT(*) FROM translations").fetchone()[0]
    logging.info(f"词库总词条数: {total_count}")

    # 2. 找出 taxonomy_sync 来源 且 中英文相同 的无效词条
    invalid_rows = cursor.execute(
        "SELECT english, chinese, category, source FROM translations "
        "WHERE source = 'taxonomy_sync' AND english = chinese"
    ).fetchall()
    logging.info(f"taxonomy_sync 自填的无效词条（中英相同）: {len(invalid_rows)} 条")

    if invalid_rows:
        for row in invalid_rows[:10]:
            logging.info(f"   示例: '{row[0]}' -> '{row[1]}' [{row[2]}]")
        if len(invalid_rows) > 10:
            logging.info(f"   ... 以及其余 {len(invalid_rows) - 10} 条")

    # 3. 删除这些无效词条
    cursor.execute(
        "DELETE FROM translations "
        "WHERE source = 'taxonomy_sync' AND english = chinese"
    )
    deleted_invalid = cursor.rowcount
    logging.info(f"已删除无效词条: {deleted_invalid} 条")

    # 4. 去重：保留 rowid 最小的那条，删除后续重复的
    cursor.execute("""
        DELETE FROM translations
        WHERE rowid NOT IN (
            SELECT MIN(rowid) FROM translations GROUP BY english
        )
    """)
    deleted_dupes = cursor.rowcount
    logging.info(f"已删除重复词条: {deleted_dupes} 条")

    conn.commit()

    # 5. 最终统计
    final_count = cursor.execute("SELECT COUNT(*) FROM translations").fetchone()[0]
    logging.info(f"清理后词库总词条数: {final_count}")

    conn.close()
    logging.info("词库清理完成。")

if __name__ == "__main__":
    cleanup()
