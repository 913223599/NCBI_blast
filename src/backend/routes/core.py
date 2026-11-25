
import logging
import json
import re
from pathlib import Path
from typing import Optional
from fastapi import APIRouter

logger = logging.getLogger("api_server")
router = APIRouter(tags=["Core"])
_CITATIONS_PATH = Path(__file__).resolve().parent.parent.parent / "resources" / "citations.json"

@router.get("/api/help/structure")
async def get_help_structure():
    from ...utils.help_manager import get_help_manager
    return get_help_manager().get_help_structure()

@router.get("/api/help/content/{topic_id}")
async def get_help_content(topic_id: str):
    from ...utils.help_manager import get_help_manager
    return {"content": get_help_manager().get_help_content(topic_id)}

@router.get("/api/core/annotations")
async def get_annotations(hashes: str):
    from ...utils.translation.biology_translator import get_global_biology_translator
    try:
        hash_list = json.loads(hashes)
        from ...workbench.models.annotation_manager import get_annotation_manager
        am = get_annotation_manager()
        mapping = am.get_annotations_by_hashes(hash_list)
        
        raw_names = []
        hash_to_raw = {}
        for h, identity in mapping.items():
            if identity:
                match = re.search(r'^([A-Z][a-z]+(?:\s+[a-z]+))', identity.strip())
                raw_name = match.group(1) if match else identity.split(';')[0].split(' strain')[0].split(' genome')[0].strip()
                raw_names.append(raw_name)
                hash_to_raw[h] = raw_name
            else:
                hash_to_raw[h] = None
                
        unique_raw = list(set([n for n in raw_names if n]))
        translator = get_global_biology_translator()
        translated_map = translator.translate_batch(unique_raw, category='species')
        
        clean_mapping = {}
        for h, raw in hash_to_raw.items():
            if not raw:
                clean_mapping[h] = ""
                continue
            translated = translated_map.get(raw, raw)
            if translated and translated != raw:
                if '(' in translated and ')' in translated:
                    clean_mapping[h] = translated
                else:
                    clean_mapping[h] = f"{translated}({raw})"
            else:
                clean_mapping[h] = raw
                
        return clean_mapping
    except Exception as exc:
        logger.error(f"Failed to get_annotations: {exc}")
        return {}

@router.post("/api/core/open_dir")
async def open_dir(path: str):
    """在操作系统资源管理器中打开指定目录"""
    from ...blast.manager import get_blast_manager
    get_blast_manager().open_directory(path)
    return {"status": "opened"}


@router.get("/api/core/citations")
async def get_citations(module: Optional[str] = None):
    """返回内置生信工具与科研绘图组件的标准参考文献库（支持按模块筛选）"""
    if not _CITATIONS_PATH.is_file():
        return {"schema_version": "1.0", "description": "", "count": 0, "tools": []}
    try:
        payload = json.loads(_CITATIONS_PATH.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.error(f"Failed to load citations.json: {exc}")
        return {"schema_version": "1.0", "description": "", "count": 0, "tools": []}

    tools = payload.get("tools", [])
    if module and module.strip() and module.strip().lower() != "all":
        mod_key = module.strip().lower()
        tools = [item for item in tools if str(item.get("module", "")).lower() == mod_key]
    return {
        "schema_version": payload.get("schema_version", "1.0"),
        "description": payload.get("description", ""),
        "count": len(tools),
        "tools": tools,
    }
