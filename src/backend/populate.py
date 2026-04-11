import os
import sys
import logging
from pathlib import Path
import sqlite3

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

project_root = Path(__file__).resolve().parents[2]
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from src.utils.taxonomy_provider import get_taxonomy_provider
from src.utils.taxonomy_sync_service import get_taxonomy_sync_service
from src.backend.strain_db import get_strain_db_manager

def prefill_code_lookup():
    tax_provider = get_taxonomy_provider()
    if not tax_provider.is_ready:
        logging.warning("Taxonomy DB not ready. Please wait for ETE4 to finish compiling.")
        return

    sync_service = get_taxonomy_sync_service()
    db_manager = get_strain_db_manager()

    # Clear current code lookup entries to start fresh, but preserve sources/counters
    logging.info("Clearing existing generic lookup entries, preserving user sources and config...")
    # Load data directly to avoid the load_all_data formatting issues
    import sqlite3 as sqlite3_local
    import json
    
    conn_db = sqlite3_local.connect(str(project_root / 'database/strain.db'))
    c_db = conn_db.cursor()
    c_db.execute('SELECT value FROM sys_config WHERE key=?', ('codeLookup',))
    row = c_db.fetchone()
    if row:
        code_lookup_obj = json.loads(row[0])
    else:
        code_lookup_obj = {}
        
    code_lookup_obj['entries'] = [] # wipe the entries
    if 'sources' not in code_lookup_obj:
        code_lookup_obj['sources'] = []
    if 'counters' not in code_lookup_obj:
        code_lookup_obj['counters'] = {}
    if 'config' not in code_lookup_obj:
        code_lookup_obj['config'] = {"assignMode": "sequential", "serialDigits": 4, "version": "1.0.0"}
        
    db_manager.save_sys_config('codeLookup', code_lookup_obj)
    conn_db.close()

    # Read all species from our translation database
    conn = sqlite3.connect(str(project_root / "translations.db"))
    c = conn.cursor()
    c.execute("SELECT english FROM translations WHERE category IN ('species')")
    species_list = c.fetchall()
    
    success_count = 0
    for (sp_name,) in species_list:
        res = sync_service.sync_taxonomy_from_name(sp_name)
        if res and res.get('success'):
            success_count += 1
            if success_count % 20 == 0:
                logging.info(f"Processed {success_count} / {len(species_list)} species...")
                
    conn.close()
    
    final_data = db_manager.load_all_data()
    entries = final_data.get('codeLookup', {}).get('entries', [])
    
    logging.info(f"Successfully finished updating code lookup.")
    logging.info(f"Generated {len(entries)} robust hierarchical records based entirely on ETE4 taxonomy relationships!")

if __name__ == "__main__":
    prefill_code_lookup()
