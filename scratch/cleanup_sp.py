import json
import sqlite3
from pathlib import Path

def merge_sp_entries():
    db_path = Path(r"d:\NCBI blast\database\strain.db")
    if not db_path.exists():
        print("Database not found.")
        return

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # 1. 读取当前的 codeLookup
    cursor.execute('SELECT value FROM sys_config WHERE key="codeLookup"')
    row = cursor.fetchone()
    if not row:
        print("codeLookup not found.")
        return
    
    code_lookup = json.loads(row[0])
    entries = code_lookup.get("entries", [])
    
    # 2. 扫描重复的 sp 条目
    # 逻辑：在同一个父级路径（同属）下，如果存在拉丁名为 Genus sp 和 Genus sp. 的，进行合并
    unique_map = {} # (parentPath, normalized_name) -> entry
    to_keep = []
    removed_count = 0

    for entry in entries:
        if entry.get('level') == 3:
            raw_latin = entry.get('latinName', '')
            # 归一化：Staphylococcus sp. -> Staphylococcus sp (忽略大小写)
            norm_latin = raw_latin.strip().rstrip('.').lower()
            parent = entry.get('parentPath')
            
            key = (parent, norm_latin)
            if key in unique_map:
                print(f"Found duplicate: {raw_latin} ({entry.get('code')}) will be merged into {unique_map[key].get('code')}")
                removed_count += 1
                continue
            else:
                unique_map[key] = entry
                to_keep.append(entry)
        else:
            to_keep.append(entry)

    if removed_count > 0:
        code_lookup["entries"] = to_keep
        cursor.execute('UPDATE sys_config SET value=?, updated_at=datetime("now") WHERE key="codeLookup"', (json.dumps(code_lookup),))
        conn.commit()
        print(f"Cleanup finished: Merged {removed_count} redundant 'sp/sp.' entries.")
    else:
        print("No duplicates found to merge.")
    
    conn.close()

if __name__ == "__main__":
    merge_sp_entries()
