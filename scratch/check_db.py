import sqlite3
import os

db_path = r'd:\NCBI blast\translations.db'
if not os.path.exists(db_path):
    print(f"Error: {db_path} not found")
    exit(1)

conn = sqlite3.connect(db_path)
cursor = conn.cursor()

# Get tables
cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
tables = cursor.fetchall()
print(f"Tables: {tables}")

for table in tables:
    table_name = table[0]
    print(f"\nSchema for {table_name}:")
    cursor.execute(f"PRAGMA table_info({table_name});")
    print(cursor.fetchall())
    
    print(f"\nSample data from {table_name}:")
    cursor.execute(f"SELECT * FROM {table_name} LIMIT 5;")
    print(cursor.fetchall())

conn.close()
