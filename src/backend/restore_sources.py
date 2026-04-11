import sqlite3, json

conn = sqlite3.connect('database/strain.db')
row = conn.execute('SELECT value FROM sys_config WHERE key="codeLookup"').fetchone()
if row:
    d = json.loads(row[0])
    # Restore sources if missing or empty
    if 'sources' not in d or not d['sources']:
        d['sources'] = [
            {"code": "YS", "name": "实验室", "description": "系统检测到的历史编码来源", "isBuiltin": False, "enabled": True},
            {"code": "ZC", "name": "自采", "description": "自主采样获取", "isBuiltin": False, "enabled": True},
            {"code": "GM", "name": "购买", "description": "商业渠道购买", "isBuiltin": False, "enabled": True},
            {"code": "ZS", "name": "赠送", "description": "外部单位赠送", "isBuiltin": False, "enabled": True},
            {"code": "LC", "name": "临床分离", "description": "临床样本分离提取", "isBuiltin": False, "enabled": True}
        ]
        conn.execute('UPDATE sys_config SET value=? WHERE key="codeLookup"', (json.dumps(d, ensure_ascii=False),))
        conn.commit()
        print("Successfully restored sources.")
    else:
        print("Sources already exist.")
else:
    print("No codeLookup found.")
conn.close()
