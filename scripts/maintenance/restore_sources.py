# -*- coding: utf-8 -*-
"""恢复 database/strain.db 中缺失的 codeLookup.sources 内置项。"""
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
        if row:
            d = json.loads(row[0])
            if "sources" not in d or not d["sources"]:
                d["sources"] = [
                    {"code": "YS", "name": "实验室", "description": "系统检测到的历史编码来源", "isBuiltin": False, "enabled": True},
                    {"code": "ZC", "name": "自采", "description": "自主采样获取", "isBuiltin": False, "enabled": True},
                    {"code": "GM", "name": "购买", "description": "商业渠道购买", "isBuiltin": False, "enabled": True},
                    {"code": "ZS", "name": "赠送", "description": "外部单位赠送", "isBuiltin": False, "enabled": True},
                    {"code": "LC", "name": "临床分离", "description": "临床样本分离提取", "isBuiltin": False, "enabled": True},
                ]
                conn.execute(
                    'UPDATE sys_config SET value=? WHERE key="codeLookup"',
                    (json.dumps(d, ensure_ascii=False),),
                )
                conn.commit()
                print("Successfully restored sources.")
            else:
                print("Sources already exist.")
        else:
            print("No codeLookup found.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
