import json
import sqlite3
import re
from pathlib import Path

def scan_anomalies():
    db_path = Path("database/strain.db")
    if not db_path.exists():
        print("Error: database/strain.db not found.")
        return

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute('SELECT value FROM sys_config WHERE key="codeLookup"')
    row = cursor.fetchone()
    if not row:
        print("Error: codeLookup not found in sys_config.")
        return

    data = json.loads(row[0])
    entries = [e for e in data.get("entries", [])]
    
    anomalies = []
    seen = {} # (parentPath, normalized_name) -> entry
    
    logger_issues = []

    for e in entries:
        level = e.get('level')
        name = e.get('name', '')
        latin = e.get('latinName', '')
        code = e.get('code', '')
        parent = e.get('parentPath', '')
        full_path = e.get('fullPath', '')

        # 归一化名称以便检查重复
        norm_latin = latin.lower().strip().rstrip('.')
        
        # 1. 检查层级内的名称重复 (同一属下不应有两个同名种)
        if level == 3:
            key = (parent, norm_latin)
            if key in seen:
                prev = seen[key]
                anomalies.append({
                    "type": "重复编码",
                    "detail": f"物种 '{latin}' 被赋予了两个编码: {code} 和 {prev['code']}",
                    "id": code
                })
            seen[key] = e

            # 2. 检查非正式/低质量命名
            low_quality_keywords = ['uncultured', 'environmental', 'metagenome', 'genomic', 'clone', 'artificial', 'vector']
            if any(k in latin.lower() for k in low_quality_keywords):
                anomalies.append({
                    "type": "非正式命名",
                    "detail": f"词条 '{latin}' 包含非正式物种标识符，建议清理。",
                    "id": code
                })

            # 3. 检查带编号的占位符 (如 sp. 1, sp. 2)
            if re.search(r'sp\.? \d+', latin.lower()):
                anomalies.append({
                    "type": "带编号占位符",
                    "detail": f"词条 '{latin}' 是临时编号，不建议作为标准编码。",
                    "id": code
                })

        # 4. 检查结构一致性 (父路径匹配检查)
        if level > 1 and parent:
            parent_entry = next((item for item in entries if item.get('fullPath') == parent), None)
            if not parent_entry:
                anomalies.append({
                    "type": "孤儿节点",
                    "detail": f"条目 '{latin}' ({code}) 指向的父节点 {parent} 不存在。",
                    "id": code
                })

    if not anomalies:
        print("未发现明显的编码表异常。")
    else:
        print(f"--- 发现 {len(anomalies)} 处潜在异常 ---")
        for idx, a in enumerate(anomalies, 1):
            print(f"{idx}. [{a['type']}] {a['detail']}")

if __name__ == "__main__":
    scan_anomalies()
