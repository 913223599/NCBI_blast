import sqlite3

db_path = r"F:\NCBI blast\database\assembly.db"
conn = sqlite3.connect(db_path)
cur = conn.cursor()
cur.execute("PRAGMA table_info(assembly_tasks);")
print(cur.fetchall())
