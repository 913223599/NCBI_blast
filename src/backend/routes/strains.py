import logging
import time
import json
import asyncio
from fastapi import APIRouter, Header
from pydantic import BaseModel
from typing import Optional, List
from ..broadcaster import broadcaster

logger = logging.getLogger("api_server")
router = APIRouter(tags=["Strains & Taxonomy"])

# 性能优化: 内存快照与硬限流
_last_load_time = 0
_cached_data = None
_LOAD_DEBOUNCE_MS = 1500
_LOAD_CACHE_MS = 2500

# ─── 模型定义 ─────────────────────────────────────────

class FreezerRequest(BaseModel):
    data: dict

class RecordRequest(BaseModel):
    data: dict

class TaxonomySyncRequest(BaseModel):
    species_name: str

# ─── 核心逻辑：缓存失效 ────────────────────────────────

def invalidate_cache():
    """彻底清除后端快照缓存，确保下一次请求命中磁盘最新值"""
    global _cached_data
    _cached_data = None
    logger.info("🧹 [Cache] 数据已变更，后端快照已即时失效")

# ─── 菌种数据 CRUD ────────────────────────────────────

@router.get("/api/strain/load")
async def strain_load_all():
    """
    性能保卫战：
    1. 内存快照机制，减少磁盘IO压力。
    2. 硬切片限流：默认只拉取前 2000 条，防止前端渲染 10 万条导致的 22GB 内存海啸。
    """
    from ...backend.strain_db import get_strain_db_manager
    from ..api_server import log_resources
    
    global _last_load_time, _cached_data
    now = time.time() * 1000
    
    # 命中快照缓存
    if _cached_data is not None and (now - _last_load_time < _LOAD_CACHE_MS):
        logger.info(f"⚡ [Cache] 命中内存快照 ({now - _last_load_time:.0f}ms)")
        return _cached_data
    
    # 强制防抖保护
    if now - _last_load_time < _LOAD_DEBOUNCE_MS:
        logger.warning(f"⚠️ [FlowControl] 请求过频且无快照，拦截以防止IO风暴")
        return {"freezers": [], "records": [], "status": "throttled"}

    try:
        start_time = time.time()
        # 记录后端资源情况
        log_resources(force=False)
        
        # 核心数据库操作
        all_data = get_strain_db_manager().load_all_data()
        elapsed = (time.time() - start_time) * 1000
        
        # --- 性能硬限流开始 ---
        # 如果样本总量巨大，这里强行只取前 2000 条。
        # 目的是从物理层切断 22GB 级别的 JS 堆内存压力（JSON解析是内存溢出主因）。
        total_records = all_data.get('records', [])
        limit = 2000
        if len(total_records) > limit:
            logger.warning(f"🚨 [MemoryGuard] 发现 {len(total_records)} 条记录，正在强制切片至前 {limit} 条以防止前端崩溃。")
            all_data['records'] = total_records[:limit]
            all_data['is_truncated'] = True
            all_data['total_count'] = len(total_records)
        # --- 性能硬限流结束 ---
        
        _cached_data = all_data
        _last_load_time = now
        
        logger.info(f"✅ [Load] 全部加载成功: {len(all_data['records'])}条记录, 耗时{elapsed:.0f}ms")
        return all_data
    except Exception as e:
        logger.error(f"❌ [Error] /api/strain/load 发生异常: {e}")
        return {"freezers": [], "records": [], "error": str(e)}

@router.post("/api/strain/freezer")
async def save_freezer(req: FreezerRequest, x_client_id: Optional[str] = Header(None, alias="X-Client-ID")):
    from ...backend.strain_db import get_strain_db_manager
    invalidate_cache()
    success = get_strain_db_manager().save_freezer(req.data)
    if success and x_client_id:
        await broadcaster.broadcast("data_updated", {"module": "strains"}, exclude_id=x_client_id)
    return {"success": success}

@router.delete("/api/strain/freezer/{freezer_id}")
async def delete_freezer(freezer_id: str, x_client_id: Optional[str] = Header(None, alias="X-Client-ID")):
    from ...backend.strain_db import get_strain_db_manager
    invalidate_cache()
    success = get_strain_db_manager().delete_freezer(freezer_id)
    if success and x_client_id:
        await broadcaster.broadcast("data_updated", {"module": "strains"}, exclude_id=x_client_id)
    return {"success": success}

@router.post("/api/strain/record")
async def save_record(req: RecordRequest, x_client_id: Optional[str] = Header(None, alias="X-Client-ID")):
    from ...backend.strain_db import get_strain_db_manager
    invalidate_cache()
    success = get_strain_db_manager().save_record(req.data)
    if success and x_client_id:
        await broadcaster.broadcast("data_updated", {"module": "strains"}, exclude_id=x_client_id)
    return {"success": success}

@router.delete("/api/strain/record/{record_id}")
async def delete_record(record_id: str, x_client_id: Optional[str] = Header(None, alias="X-Client-ID")):
    from ...backend.strain_db import get_strain_db_manager
    invalidate_cache()
    success = get_strain_db_manager().delete_record(record_id)
    if success and x_client_id:
        await broadcaster.broadcast("data_updated", {"module": "strains"}, exclude_id=x_client_id)
    return {"success": success}

@router.post("/api/strain/records/batch")
async def save_records_batch(req: dict, x_client_id: Optional[str] = Header(None, alias="X-Client-ID")):
    from ...backend.strain_db import get_strain_db_manager
    invalidate_cache()
    data_list = req.get("data", [])
    success = get_strain_db_manager().save_records_batch(data_list)
    if success and x_client_id:
        await broadcaster.broadcast("data_updated", {"module": "strains"}, exclude_id=x_client_id)
    return {"success": success}

@router.post("/api/strain/sys_config/codeLookup")
async def save_code_lookup(req: dict, x_client_id: Optional[str] = Header(None, alias="X-Client-ID")):
    from ...backend.strain_db import get_strain_db_manager
    invalidate_cache()
    success = get_strain_db_manager().save_sys_config('codeLookup', req)
    if success and x_client_id:
        await broadcaster.broadcast("data_updated", {"module": "strains"}, exclude_id=x_client_id)
    return {"success": success}

@router.post("/api/strain/clear")
async def strain_clear_all(x_client_id: Optional[str] = Header(None, alias="X-Client-ID")):
    from ...backend.strain_db import get_strain_db_manager
    invalidate_cache()
    success = get_strain_db_manager().clear_all()
    if success and x_client_id:
        await broadcaster.broadcast("data_updated", {"module": "strains"}, exclude_id=x_client_id)
    return {"success": success}

# ─── 序列、分类学等其它接口逻辑顺延保持不变 (略) ────────────────

@router.post("/api/strain/sequence")
async def save_sequence(req: dict):
    from ...backend.sequence_db import get_sequence_db_manager
    success = get_sequence_db_manager().save_sequence(req)
    return {"success": success}

@router.get("/api/strain/sequences/{sample_id}")
async def load_sequences_by_sample(sample_id: str):
    from ...backend.sequence_db import get_sequence_db_manager
    return get_sequence_db_manager().load_sequences_by_sample(sample_id) or []

@router.post("/api/taxonomy/sync")
async def sync_taxonomy(req: TaxonomySyncRequest):
    from ...utils.taxonomy_sync_service import get_taxonomy_sync_service
    return get_taxonomy_sync_service().sync_taxonomy_from_name(req.species_name)
