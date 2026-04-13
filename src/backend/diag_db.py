import sqlite3
import os
import json

def analyze_db():
    db_path = "database/strain.db"
    if not os.path.exists(db_path):
        print(f"Error: Database not found at {db_path}")
        return

    print(f"Analyzing database: {db_path}")
    print(f"File size: {os.path.getsize(db_path) / (1024*1024):.2f} MB")
    print("-" * 50)

    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # 1. 检查各表的总行数
        for table in ['freezers', 'records', 'sys_config']:
            cursor.execute(f"SELECT count(*) FROM {table}")
            count = cursor.fetchone()[0]
            print(f"Table [{table}]: {count} rows")

        print("-" * 50)
        # 2. 分析 records 表中各列的平均大小
        print("Analyzing [records] table column sizes (bytes):")
        columns = [
            'id', 'name', 'metadata'
        ]
        
        for col in columns:
            cursor.execute(f"SELECT AVG(LENGTH({col})), MAX(LENGTH({col})), SUM(LENGTH({col})) FROM records")
            avg_size, max_size, sum_size = cursor.fetchone()
            print(f"Column [{col.ljust(10)}]: Avg={int(avg_size or 0):>8} | Max={int(max_size or 0):>8} | Total={int(sum_size or 0) / 1024 / 1024:>6.2f} MB")

        print("-" * 50)
        # 3. 专门检查 metadata 是否包含异常数据
        cursor.execute("SELECT id, name, LENGTH(metadata) as mlen, metadata FROM records ORDER BY mlen DESC LIMIT 3")
        rows = cursor.fetchall()
        for i, row in enumerate(rows):
            print(f"Top {i+1} Large Metadata: ID={row[0]}, Name={row[1]}, Size={row[2]/1024:.1f} KB")
            try:
                meta = json.loads(row[3])
                keys = list(meta.keys())
                print(f"   Keys in metadata: {keys[:10]}{'...' if len(keys) > 10 else ''}")
            except:
                print("   [!] Metadata is not valid JSON")

        conn.close()
    except Exception as e:
        print(f"Analysis failed: {e}")

if __name__ == "__main__":
    analyze_db()
