import logging
import re
from typing import Dict, Any, Optional, List
from .taxonomy_provider import get_taxonomy_provider
from ..backend.strain_db import get_strain_db_manager
from .translation.translation_data_manager import get_translation_data_manager
from .translation.biology_translator import get_global_biology_translator

logger = logging.getLogger(__name__)

class TaxonomySyncService:
    def __init__(self):
        self.tax_provider = get_taxonomy_provider()
        self.db_manager = get_strain_db_manager()
        self.trans_manager = get_translation_data_manager()
        self.ai_translator = get_global_biology_translator()

    def _generate_next_code(self, current_codes: List[str], length: int, alpha: bool = False) -> str:
        """Helper to generate the next sequential code (e.g., AAA, AAB, or 01, 02)."""
        if not current_codes:
            return "A" * length if alpha else "01" if length == 2 else "0" * (length - 1) + "1"
        
        current_codes.sort()
        last_code = current_codes[-1]
        
        if alpha:
            # Increment AAA -> AAB
            val = 0
            for char in last_code:
                val = val * 26 + (ord(char) - ord('A'))
            val += 1
            res = ""
            for _ in range(length):
                res = chr(ord('A') + (val % 26)) + res
                val //= 26
            return res
        else:
            # Increment 01 -> 02
            val = int(last_code) + 1
            return str(val).zfill(length)

    def sync_taxonomy_from_name(self, full_name: str) -> Dict[str, Any]:
        """
        Parses a species string (e.g. "Aeromonas hydrophila(94%)"),
        Looks up its lineage from Taxonomy SQLite Database,
        Updates Translation Dictionary with mapping records,
        Automatically expands the Encoding Dictionary (sys_config: codeLookup),
        And returns the encoding keys for auto-form generation.
        """
        if not self.tax_provider.is_ready:
            self.tax_provider.start_build_process()
            return {"success": False, "reason": "后台正在首次编译离线分类数据库，请稍后重试。"}

        # 1. Parse genus and species name
        match = re.match(r'^[\*\s]*([A-Za-z]+)\s+([A-Za-z\.\-_0-9]+)', full_name)
        if not match:
            return {"success": False, "reason": "未能解析出标准的双名法物种名称"}
        
        genus_part = match.group(1)
        species_part = match.group(2).replace('(', '').replace(')', '').replace(',', '')
        clean_name = f"{genus_part} {species_part}".strip()
        
        logger.info(f"[TaxonomySync] Auto-resolving: {clean_name}")
        
        lineage = self.tax_provider.get_lineage_details(clean_name)
        if not lineage:
            # Fallback to genus if species not found in taxdump
            lineage = self.tax_provider.get_lineage_details(genus_part)
            if not lineage:
                return {"success": False, "reason": "Taxonomy lookup failed"}

        # 2. Add to translation DB using LocalTaxonomy
        # Mapping ETE4/NCBI ranks to our dictionary categories
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
        
        # 注意：不再自动向翻译词库写入假翻译（中英相同）。
        # 词库是中英对照字典，只应通过以下途径添加：
        #   1. 用户在"设置-词典管理"手动录入
        #   2. AI 翻译后由前端回写
        #   3. 批量导入已校对的 CSV
        # taxonomy_sync 的职责仅限于编码对照表（codeLookup）的预填。

        # 3. Synchronize Encoding Database
        # Default fallback is Bacteria
        domain_type = '1' # Bacteria
        for t in lineage:
            if t['name'].lower() == 'viruses':
                domain_type = '2'
            elif t['name'].lower() == 'fungi':
                domain_type = '4'
        
        # Pull current code lookup
        data = self.db_manager.load_all_data()
        code_lookup = data.get('codeLookup', {})
        if not code_lookup:
            code_lookup = {"entries": []}
            
        entries = code_lookup.get("entries", [])
        
        # Ensure Genus
        genus_entry = next((e for e in entries if e.get('level') == 2 and (e.get('latinName') == genus_part or e.get('name') == genus_part)), None)
        if not genus_entry:
            existing_genera = [e['code'] for e in entries if e.get('level') == 2 and e.get('parentPath') == str(domain_type)]
            new_genus_code = self._generate_next_code(existing_genera, 3, alpha=True)
            genus_entry = {
                "parentPath": str(domain_type),
                "code": new_genus_code,
                "name": genus_part,
                "latinName": genus_part,
                "level": 2,
                "fullPath": f"{domain_type}{new_genus_code}",
                "enabled": True,
                "isBuiltin": False
            }
            entries.append(genus_entry)
            
        # Ensure Species
        species_entry = next((e for e in entries if e.get('level') == 3 and e.get('parentPath') == genus_entry['fullPath'] and (e.get('latinName') == species_part or e.get('name') == clean_name)), None)
        if not species_entry:
            existing_species = [e['code'] for e in entries if e.get('level') == 3 and e.get('parentPath') == genus_entry['fullPath']]
            new_spec_code = self._generate_next_code(existing_species, 3, alpha=True)
            species_entry = {
                "parentPath": genus_entry['fullPath'],
                "code": new_spec_code,
                "name": species_part if species_part else "sp.",
                "latinName": clean_name,
                "level": 3,
                "fullPath": f"{genus_entry['fullPath']}{new_spec_code}",
                "enabled": True,
                "isBuiltin": False
            }
            entries.append(species_entry)
            
        # Save back to database — 保留完整的 codeLookup 对象，只更新 entries
        code_lookup["entries"] = entries
        self.db_manager.save_sys_config('codeLookup', code_lookup)
        
        return {
            "success": True,
            "lineage": lineage,
            "codeCategory": domain_type,
            "codeGenus": genus_entry["code"],
            "codeSpecies": species_entry["code"],
            "speciesName": clean_name
        }

_sync_service = None
def get_taxonomy_sync_service():
    global _sync_service
    if _sync_service is None:
        _sync_service = TaxonomySyncService()
    return _sync_service
