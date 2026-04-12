import json
import sqlite3
import re
from pathlib import Path

def heavy_cleanup():
    db_path = Path("database/strain.db")
    if not db_path.exists():
        return

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute('SELECT value FROM sys_config WHERE key="codeLookup"')
    row = cursor.fetchone()
    if not row:
        return

    code_lookup = json.loads(row[0])
    entries = code_lookup.get("entries", [])
    
    # ─── 1. 合并属：marine (ABL) -> Marine (AAP) ───
    # 假设 Marine 的 fullPath 是 1AAP, marine 的 fullPath 是 1ABL
    marine_low = next((e for e in entries if e.get('level') == 2 and e.get('name') == 'marine'), None)
    marine_high = next((e for e in entries if e.get('level') == 2 and e.get('name') == 'Marine'), None)
    
    if marine_low and marine_high:
        low_path = marine_low['fullPath']
        high_path = marine_high['fullPath']
        print(f"Merging Genus '{marine_low['name']}' ({low_path}) into '{marine_high['name']}' ({high_path})")
        
        for e in entries:
            if e.get('parentPath') == low_path:
                print(f"  Remapping species: {e.get('latinName')} ({e.get('code')})")
                e['parentPath'] = high_path
                # 更新 fullPath (假设它是 parentPath + code)
                e['fullPath'] = high_path + e.get('code', '')
        
        # 删除旧属
        entries = [e for e in entries if e.get('fullPath') != low_path]
    
    # ─── 2. 剔除垃圾数据 ───
    junk_keywords = ['uncultured', 'unidentified', 'prokaryote', 'bacterium']
    original_count = len(entries)
    
    def is_junk(name):
        n = name.lower()
        if any(k in n for k in junk_keywords):
            # 特殊处理：如果是 'Enterobacter' 这种合法的属名包含关键词（虽然不包含），排除。
            # 这里主要针对 'uncultured bacterium' 这种。
            return True
        return False

    entries = [e for e in entries if not is_junk(e.get('name', '')) and not is_junk(e.get('latinName', ''))]
    
    removed = original_count - len(entries)
    print(f"Removed {removed} junk entries.")

    # ─── 3. 保存更新 ───
    code_lookup["entries"] = entries
    cursor.execute('UPDATE sys_config SET value=?, updated_at=datetime("now") WHERE key="codeLookup"', (json.dumps(code_lookup),))
    conn.commit()
    conn.close()
    print("Heavy cleanup successfully committed.")

if __name__ == "__main__":
    heavy_cleanup()
