
import logging
import json
import re
from typing import Optional
from fastapi import APIRouter

from ...utils.app_metadata import get_app_metadata
from ...utils.citations_loader import load_citations_payload
from ...utils.resource_guard import GpuGuard, get_safe_cpu_budget, get_total_logical_cores

logger = logging.getLogger("api_server")
router = APIRouter(tags=["Core"])

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


@router.get("/api/core/version")
async def get_app_version_info():
    """返回应用统一元数据（单一事实源：根目录 version.json）"""
    return get_app_metadata()


@router.get("/api/core/system_metrics")
async def get_system_metrics():
    """返回工作站实时硬件微监控指标（CPU、内存、留核安全并发预算与 GPU 显存状态）"""
    cpu_percent: Optional[float] = None
    memory_percent: Optional[float] = None
    memory_used_gb: Optional[float] = None
    memory_total_gb: Optional[float] = None
    try:
        import psutil

        cpu_percent = round(float(psutil.cpu_percent(interval=None)), 1)
        vm = psutil.virtual_memory()
        memory_percent = round(float(vm.percent), 1)
        memory_used_gb = round(float(vm.used) / (1024 ** 3), 2)
        memory_total_gb = round(float(vm.total) / (1024 ** 3), 2)
    except Exception as exc:
        logger.debug("psutil metrics unavailable: %s", exc)

    return {
        "cpu_percent": cpu_percent,
        "memory_percent": memory_percent,
        "memory_used_gb": memory_used_gb,
        "memory_total_gb": memory_total_gb,
        "cpu_cores": get_total_logical_cores(),
        "safe_cpu_budget": get_safe_cpu_budget(),
        "gpu": GpuGuard.probe(),
    }


@router.get("/api/core/citations")
async def get_citations(module: Optional[str] = None):
    """返回内置生信工具与科研绘图组件的标准参考文献库（支持按模块筛选）"""
    return load_citations_payload(module=module)
