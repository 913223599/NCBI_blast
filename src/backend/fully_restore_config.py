import sqlite3, json

conn = sqlite3.connect('database/strain.db')
row = conn.execute('SELECT value FROM sys_config WHERE key="codeLookup"').fetchone()
if row:
    d = json.loads(row[0])
    changed = False
    
    if 'sources' not in d or not d['sources']:
        d['sources'] = [
            {"code": "YS", "name": "实验室", "description": "系统检测到的历史编码来源", "isBuiltin": False, "enabled": True},
            {"code": "ZC", "name": "自采", "description": "自主采样获取", "isBuiltin": False, "enabled": True},
            {"code": "GM", "name": "购买", "description": "商业渠道购买", "isBuiltin": False, "enabled": True},
            {"code": "ZS", "name": "赠送", "description": "外部单位赠送", "isBuiltin": False, "enabled": True},
            {"code": "LC", "name": "临床分离", "description": "临床样本分离提取", "isBuiltin": False, "enabled": True}
        ]
        changed = True
        
    if 'config' not in d:
        d['config'] = {"assignMode": "sequential", "serialDigits": 4, "version": "1.0.0"}
        changed = True
        
    if 'counters' not in d:
        d['counters'] = {}
        # Try to reconstruct counters from existing records
        try:
            # We need to find the max serial for each taxonomyPath (A+BBB+CCC)
            # Full code: XX A BBB CCC P NNNN
            # taxonomyPath in useSerialCounter is A+BBB+CCC (pos 3 to 9)
            # Actually, useSerialCounter.ts says: taxonomyPath = cat + genus + species
            rows = conn.execute('SELECT DISTINCT code_category, code_genus, code_species, MAX(code_serial) FROM records WHERE code_category IS NOT NULL GROUP BY code_category, code_genus, code_species').fetchall()
            for cat, gen, sp, max_serial in rows:
                key = f"{cat}{gen}{sp}"
                d['counters'][key] = max_serial
            print(f"Reconstructed {len(d['counters'])} counters from records.")
        except Exception as e:
            print(f"Failed to reconstruct counters: {e}")
        changed = True
        
    if changed:
        conn.execute('UPDATE sys_config SET value=? WHERE key="codeLookup"', (json.dumps(d, ensure_ascii=False),))
        conn.commit()
        print("Successfully fully restored and repaired codeLookup structure.")
    else:
        print("No structural repairs needed.")
else:
    print("No codeLookup found.")
conn.close()
