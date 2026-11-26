# -*- coding: utf-8 -*-
"""恢复 database/strain.db 中缺失的 codeLookup 结构（sources / config / counters）。"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def main() -> None:
    db_path = PROJECT_ROOT / "database" / "strain.db"
    conn = sqlite3.connect(str(db_path))
    try:
        row = conn.execute('SELECT value FROM sys_config WHERE key="codeLookup"').fetchone()
        if not row:
            print("No codeLookup found.")
            return

        d = json.loads(row[0])
        changed = False

        if "sources" not in d or not d["sources"]:
            d["sources"] = [
                {"code": "YS", "name": "实验室", "description": "系统检测到的历史编码来源", "isBuiltin": False, "enabled": True},
                {"code": "ZC", "name": "自采", "description": "自主采样获取", "isBuiltin": False, "enabled": True},
                {"code": "GM", "name": "购买", "description": "商业渠道购买", "isBuiltin": False, "enabled": True},
                {"code": "ZS", "name": "赠送", "description": "外部单位赠送", "isBuiltin": False, "enabled": True},
                {"code": "LC", "name": "临床分离", "description": "临床样本分离提取", "isBuiltin": False, "enabled": True},
            ]
            changed = True

        if "config" not in d:
            d["config"] = {"assignMode": "sequential", "serialDigits": 4, "version": "1.0.0"}
            changed = True

        if "counters" not in d:
            d["counters"] = {}
            try:
                rows = conn.execute(
                    "SELECT DISTINCT code_category, code_genus, code_species, MAX(code_serial) "
                    "FROM records WHERE code_category IS NOT NULL "
                    "GROUP BY code_category, code_genus, code_species"
                ).fetchall()
                for cat, gen, sp, max_serial in rows:
                    key = f"{cat}{gen}{sp}"
                    d["counters"][key] = max_serial
                print(f"Reconstructed {len(d['counters'])} counters from records.")
            except Exception as exc:
                print(f"Failed to reconstruct counters: {exc}")
            changed = True

        if changed:
            conn.execute(
                'UPDATE sys_config SET value=? WHERE key="codeLookup"',
                (json.dumps(d, ensure_ascii=False),),
            )
            conn.commit()
            print("Successfully fully restored and repaired codeLookup structure.")
        else:
            print("No structural repairs needed.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
