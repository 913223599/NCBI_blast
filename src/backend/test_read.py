import sqlite3, json

conn = sqlite3.connect('database/strain.db')
data = conn.execute('SELECT value FROM sys_config WHERE key="codeLookup"').fetchone()
if data:
    d = json.loads(data[0])
    print(f"Top level keys: {list(d.keys())}")
    if 'config' in d:
        print(f"Config: {d['config']}")
    if 'counters' in d:
        print(f"Number of counters: {len(d['counters'])}")
    if 'sources' in d:
        print(f"Number of sources: {len(d['sources'])}")
else:
    print("No codeLookup found.")
