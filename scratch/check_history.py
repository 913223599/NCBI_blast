import sqlite3
import json
import os

def check():
    conn = sqlite3.connect('database/strain.db')
    cursor = conn.execute('SELECT id, items_json FROM tree_history')
    for row in cursor:
        group_id = row[0]
        try:
            items = json.loads(row[1])
            print(f"Group {group_id}:")
            for i in items:
                h_size = len(i.get('idToHash')) if i.get('idToHash') else 0
                f_path = i.get('filePath')
                archive = i.get('archiveFile')
                print(f"  - Item {i.get('id')}: idToHash size={h_size}, archive={archive}, path={f_path}")
        except Exception as e:
            print(f"Group {group_id}: Error parsing JSON: {e}")
    conn.close()

if __name__ == "__main__":
    check()
