import sqlite3
import os
import json
import time
from pathlib import Path

def reconstruct_history():
    db_path = r"d:\NCBI blast\database\strain.db"
    results_dir = Path(r"d:\NCBI blast\results\tree_results")
    
    if not results_dir.exists():
        print("Results dir not found.")
        return

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Ensure table exists
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS tree_history (
            id TEXT PRIMARY KEY,
            source_file TEXT,
            name TEXT,
            items_json TEXT,
            updated_at TEXT
        )
    ''')
    
    # Map project_id -> list of session items
    history_map = {}
    
    for project_dir in results_dir.iterdir():
        if not project_dir.is_dir(): continue
        
        project_id = project_dir.name
        if project_id not in history_map:
            history_map[project_id] = []
            
        for session_dir in project_dir.iterdir():
            if not session_dir.is_dir(): continue
            
            # Find nwk and fasta
            nwk_file = next(session_dir.glob("*.nwk"), None)
            fasta_file = next(session_dir.glob("*.fasta"), None)
            
            if not nwk_file: continue
            
            try:
                nwk_content = nwk_file.read_text(encoding='utf-8', errors='ignore')
                mtime = session_dir.stat().st_mtime
                
                # Check for manifest (fingerprints)
                manifest_file = session_dir / "fingerprints.json" # Hypothetical
                idToHash = None
                if manifest_file.exists():
                    try: idToHash = json.loads(manifest_file.read_text())
                    except: pass
                
                item = {
                    "id": os.urandom(4).hex(),
                    "algorithm": "Recovered Archive",
                    "nwk": nwk_content,
                    "filePath": str(fasta_file) if fasta_file else "",
                    "archiveFile": f"{project_id}/{session_dir.name}/{fasta_file.name}" if fasta_file else "",
                    "idToHash": idToHash,
                    "time": int(mtime * 1000)
                }
                history_map[project_id].append(item)
            except Exception as e:
                print(f"Error processing {session_dir}: {e}")

    # Insert into DB
    for project_id, items in history_map.items():
        if not items: continue
        
        # Sort items by time desc
        items.sort(key=lambda x: x['time'], reverse=True)
        
        # logicalId cleanup
        import re
        logical_id = re.sub(r'^Tree_\d+_\d+_', '', project_id)
        display_name = logical_id.replace(".fasta", "").replace(".seq", "")
        
        gid = os.urandom(5).hex()
        items_json = json.dumps(items)
        updated_at = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(items[0]['time']/1000))
        
        cursor.execute('''
            INSERT OR REPLACE INTO tree_history (id, source_file, name, items_json, updated_at)
            VALUES (?, ?, ?, ?, ?)
        ''', (gid, logical_id, display_name, items_json, updated_at))
        print(f"Reconstructed group: {display_name} ({len(items)} items)")

    conn.commit()
    conn.close()
    print("Reconstruction complete.")

if __name__ == "__main__":
    reconstruct_history()
