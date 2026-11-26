import logging
import re
from typing import Any, Dict, List, Optional

from ..routes.strains import invalidate_cache
from ..strain_db import get_strain_db_manager
from ...utils.taxonomy_provider import get_taxonomy_provider
from ...utils.translation.biology_translator import get_global_biology_translator
from ...utils.translation.translation_data_manager import get_translation_data_manager

logger = logging.getLogger(__name__)


class TaxonomySyncService:
    def __init__(self):
        self.tax_provider = get_taxonomy_provider()
        self.db_manager = get_strain_db_manager()
        self.trans_manager = get_translation_data_manager()
        self.ai_translator = get_global_biology_translator()

    def _generate_next_code(self, current_codes: List[str], length: int, alpha: bool = False) -> str:
        """
        [插空算法] 彻底同步前端逻辑：
        从 AAA (或 01) 开始遍历，找到第一个未被占用的位置。
        """
        from string import ascii_uppercase
        existing_set = set(current_codes)

        if alpha:
            chars = ascii_uppercase
            for i in range(26**length):
                code = ""
                temp_i = i
                for _ in range(length):
                    code = chars[temp_i % 26] + code
                    temp_i //= 26
                if code not in existing_set:
                    return code
            return "ZZZ"
        for i in range(1, 10**length):
            code = str(i).zfill(length)
            if code not in existing_set:
                return code
        return "99"

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

        logger.info(f"[TaxonomySync] Auto-resolving input: {full_name}")

        paren_match = re.search(r'\(([^)]+)\)', full_name)
        if paren_match:
            candidate = paren_match.group(1).strip()
            if re.search(r'[A-Za-z]', candidate):
                full_name = candidate

        full_name = re.sub(r'[^\x00-\x7f]', ' ', full_name).strip()

        match = re.search(r'([A-Za-z]+)\s+([A-Za-z\.\-_0-9]+)', full_name)
        if not match:
            return {"success": False, "reason": f"未能解析出标准的双名法物种名称: {full_name}"}

        genus_part = match.group(1).capitalize()
        species_suffix = match.group(2).replace('(', '').replace(')', '').replace(',', '').rstrip('.')
        clean_name = f"{genus_part} {species_suffix}".strip()

        logger.info(f"[TaxonomySync] Resolved to: {clean_name}")

        lineage = self.tax_provider.get_lineage_details(clean_name)
        if not lineage:
            lineage = self.tax_provider.get_lineage_details(genus_part)
            if not lineage:
                return {"success": False, "reason": "Taxonomy lookup failed"}

        domain_type = '1'
        for t in lineage:
            if t['name'].lower() == 'viruses':
                domain_type = '2'
            elif t['name'].lower() == 'fungi':
                domain_type = '4'

        data = self.db_manager.load_all_data()
        raw_lookup = data.get('codeLookup', {})
        code_lookup: Dict[str, Any] = raw_lookup if isinstance(raw_lookup, dict) else {"entries": []}

        entries = code_lookup.get("entries", [])

        genus_part_lower = genus_part.lower()
        genus_entry = next((e for e in entries if e.get('level') == 2 and (
            (e.get('latinName') or '').lower() == genus_part_lower or
            (e.get('name') or '').lower() == genus_part_lower
        )), None)

        if not genus_entry:
            existing_genera = [e['code'] for e in entries if e.get('level') == 2 and e.get('parentPath') == str(domain_type)]
            new_genus_code = self._generate_next_code(existing_genera, 3, alpha=True)

            translated_genus = self.ai_translator.translate_text(genus_part, category='genus')
            display_name = f"{translated_genus}({genus_part})" if translated_genus != genus_part else genus_part

            genus_entry = {
                "parentPath": str(domain_type),
                "code": new_genus_code,
                "name": display_name,
                "latinName": genus_part,
                "level": 2,
                "fullPath": f"{domain_type}{new_genus_code}",
                "enabled": True,
                "isBuiltin": False
            }
            entries.append(genus_entry)

        species_suffix_lower = species_suffix.lower()
        clean_name_lower = clean_name.lower()

        species_entry = next((e for e in entries if e.get('level') == 3
                              and e.get('parentPath') == genus_entry['fullPath']
                              and (
                                  (e.get('latinName') or '').lower() == clean_name_lower or
                                  (e.get('name') or '').lower() == species_suffix_lower
                              )), None)

        if not species_entry:
            existing_species = [e['code'] for e in entries if e.get('level') == 3 and e.get('parentPath') == genus_entry['fullPath']]
            new_spec_code = self._generate_next_code(existing_species, 3, alpha=True)

            translated_species = self.ai_translator.translate_text(clean_name, category='species')
            if translated_species == clean_name and species_suffix:
                translated_species = self.ai_translator.translate_text(species_suffix, category='species')

            final_name = translated_species
            if translated_species and translated_species != clean_name and translated_species != species_suffix:
                final_name = f"{translated_species}({clean_name})"
            elif not translated_species:
                final_name = species_suffix if species_suffix else "sp."

            species_entry = {
                "parentPath": genus_entry['fullPath'],
                "code": new_spec_code,
                "name": final_name,
                "latinName": clean_name,
                "level": 3,
                "fullPath": f"{genus_entry['fullPath']}{new_spec_code}",
                "enabled": True,
                "isBuiltin": False
            }
            entries.append(species_entry)

        code_lookup["entries"] = entries
        self.db_manager.save_sys_config('codeLookup', code_lookup)

        try:
            invalidate_cache()
        except Exception as exc:
            logger.warning("同步物种编码后刷新菌株缓存失败: %s", exc)

        return {
            "success": True,
            "lineage": lineage,
            "codeCategory": domain_type,
            "codeGenus": genus_entry["code"],
            "codeSpecies": species_entry["code"],
            "speciesName": clean_name
        }


_sync_service: Optional[TaxonomySyncService] = None


def get_taxonomy_sync_service() -> TaxonomySyncService:
    global _sync_service
    if _sync_service is None:
        _sync_service = TaxonomySyncService()
    return _sync_service
