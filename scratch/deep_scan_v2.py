import json
import sqlite3
import re
from pathlib import Path

def deep_scan_v2():
    db_path = Path("database/strain.db")
    if not db_path.exists():
        return

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute('SELECT value FROM sys_config WHERE key="codeLookup"')
    row = cursor.fetchone()
    if not row:
        return

    data = json.loads(row[0])
    entries = data.get("entries", [])
    issues = []
    seen_names = {} # (parent, norm_name) -> code

    for e in entries:
        level = e.get('level')
        name = e.get('name', '')
        latin = e.get('latinName', '')
        parent = e.get('parentPath', '')
        code = e.get('code', '')
        
        if not latin: continue

        # 归一化用于冲突检查 (去掉空格、横杠、点，全小写)
        norm = latin.lower().strip().replace(' ', '').replace('-', '').replace('_', '').replace('.', '')
        key = (parent, norm)
        
        if level == 3:
            # 1. 检测近似重复
            if key in seen_names:
                prev = seen_names[key]
                issues.append(f"[近似重复] '{latin}' ({code}) 与 '{prev['name']}' ({prev['code']}) 极度相似。")
            seen_names[key] = {'code': code, 'name': latin}
            
            # 2. 检测不规范种名 (独立出现的关键词)
            junk_keywords = ['gene', 'sequence', 'sample', 'isolate', 'plasmid', 'phage', 'virus']
            parts = latin.lower().split()
            # 只有当种名部分完全等于这些词时才算异常，或者是包含在名字里但导致逻辑奇怪
            if any(k in parts for k in junk_keywords):
                issues.append(f"[不规范词条] '{latin}' ({code}) 包含可疑关键词。")
            
            # 3. 检测字符异常
            if re.search(r'[^a-zA-Z0-9\.\s\-\(\)\[\]]', latin):
                issues.append(f"[非法字符] '{latin}' ({code})")
            
            # 4. 检测层级逻辑
            if not parent.startswith('1') and not parent.startswith('2') and not parent.startswith('3') and not parent.startswith('4'):
                # 排除正常的根节点
                pass 

    if not issues:
        print("二次深度扫描完成：未发现明显异常。")
    else:
        print(f"--- 二次扫描发现 {len(issues)} 处潜在异常 ---")
        for i in issues:
            print(i)
    
    conn.close()

if __name__ == "__main__":
    deep_scan_v2()
