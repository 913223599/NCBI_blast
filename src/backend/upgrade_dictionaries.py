import os
import sys
import json
import sqlite3
import logging
from pathlib import Path

# Setup simple logging
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

# Ensure project root is in sys.path
project_root = Path(__file__).resolve().parents[2]
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from src.utils.taxonomy_provider import get_taxonomy_provider
from src.utils.taxonomy_sync_service import get_taxonomy_sync_service
from src.utils.translation.translation_data_manager import get_translation_data_manager
from src.backend.strain_db import get_strain_db_manager

def upgrade_all():
    logging.info("Starting Bulk Dictionary and Encoding Database Upgrade...")
    
    tax_provider = get_taxonomy_provider()
    if not tax_provider.is_ready:
        logging.warning("Taxonomy database is not ready yet. Please ensure ETE4 DB is built.")
        logging.info("We will wait for taxonomy DB to be ready... Please run this script after it's compiled.")
        return

    sync_service = get_taxonomy_sync_service()
    trans_manager = get_translation_data_manager()
    db_manager = get_strain_db_manager()

    # 1. 升级所有的现有词条别名 (Translation DB)
    logging.info("1. Scanning Translation Database...")
    
    conn = sqlite3.connect(trans_manager.db_path)
    c = conn.cursor()
    c.execute("SELECT english, category FROM translations")
    translations = c.fetchall()
    
    upgrade_count = 0
    # Map rank to our extended dictionary categories
    rank_to_cat = {
        'superkingdom': 'kingdom',
        'kingdom': 'kingdom',
        'phylum': 'phylum',
        'class': 'class_rank',
        'order': 'order',
        'family': 'family',
        'genus': 'genus',
        'species': 'species'
    }

    for word, cat in translations:
        # If it's labeled 'other' or 'species'/'genus' but is actually a phylum, we correct it
        if not word or len(word) < 3:
            continue
            
        lineage = tax_provider.get_lineage_details(word)
        if lineage:
            # Check the rank of the last matching taxon
            target_taxon = lineage[-1]
            rank = target_taxon.get('rank', 'no rank')
            expected_cat = rank_to_cat.get(rank)
            
            # If we found a proper category, update it in DB
            if expected_cat and expected_cat != cat:
                c2 = conn.cursor()
                c2.execute("UPDATE translations SET category = ? WHERE english = ?", (expected_cat, word))
                conn.commit()
                upgrade_count += 1
                logging.info(f"   [Dict Upgrade] {word}: {cat} -> {expected_cat}")
                
    conn.close()

    logging.info(f"Finished Dictionary Upgrade. {upgrade_count} items updated.")

    # 2. 升级所有的物种预置记录到最新 14位编码连带关系并填充上级
    logging.info("2. Scanning Strain Database & Encoding System...")
    data = db_manager.load_all_data()
    records = data.get('records', [])
    
    # Update from records
    record_upgrade = 0
    for rec in records:
        sp = rec.get('species')
        if sp:
            res = sync_service.sync_taxonomy_from_name(sp)
            if res and res.get('success'):
                # Also save the generated IDs sequentially back to the record if missing
                if not rec.get('codeCategory') and res.get('codeCategory'):
                    rec['codeCategory'] = res['codeCategory']
                    rec['codeGenus'] = res['codeGenus']
                    rec['codeSpecies'] = res['codeSpecies']
                    db_manager.save_record(rec)
                    record_upgrade += 1

    logging.info(f"Finished Encoding Upgrade. Processed {record_upgrade} records via Taxonomy Sync.")
    logging.info("Bulk Upgrade Completed Successfully.")

if __name__ == "__main__":
    upgrade_all()
