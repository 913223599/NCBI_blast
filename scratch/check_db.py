import sqlite3
import os

db_path = r"d:\NCBI blast\database\strain.db"
if not os.path.exists(db_path):
    print(f"DB not found at {db_path}")
    exit(1)

conn = sqlite3.connect(db_path)
cursor = conn.cursor()
cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='tree_history'")
if not cursor.fetchone():
    print("Table tree_history DOES NOT EXIST")
else:
    cursor.execute("SELECT count(*) FROM tree_history")
    count = cursor.fetchone()[0]
    print(f"Table tree_history exists and has {count} records")
    if count > 0:
        cursor.execute("SELECT id, name, updated_at FROM tree_history LIMIT 5")
        for row in cursor.fetchall():
            print(f" - {row[0]}: {row[1]} (Updated: {row[2]})")
conn.close()
