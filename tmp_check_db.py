import sqlite3
import json
from pathlib import Path
db_path = Path(r'f:\NCBI blast\database\assembly.db')
conn = sqlite3.connect(db_path)
cur = conn.cursor()
cur.execute('SELECT id, status, last_step, progress FROM assembly_tasks ORDER BY created_at DESC LIMIT 20')
rows = cur.fetchall()
for row in rows:
    print(f"ID: {row[0]} | Status: {row[1]} | Step: {row[2]}")
conn.close()
