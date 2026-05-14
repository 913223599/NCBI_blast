import sqlite3
import json

db_path = r"F:\NCBI blast\database\assembly.db"
conn = sqlite3.connect(db_path)
cur = conn.cursor()
cur.execute("SELECT results FROM assembly_tasks WHERE id='AS_1778654314959'")
row = cur.fetchone()
if row:
    with open(r"F:\NCBI blast\scratch\context_AS.json", "w", encoding="utf-8") as f:
        f.write(row[0])
    print("Exported context to scratch/context_AS.json")
else:
    print("Task not found")
