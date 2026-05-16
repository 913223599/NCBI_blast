import logging
import time
import json
import asyncio
from fastapi import APIRouter, Header
from pydantic import BaseModel
from typing import Any, Optional, List
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
    2. 数据库层已做序列字段脱水优化（load_all_data 不含 sequence），安全全量下发。
    3. 始终附带 total_count 供前端准确显示。
    """
    from ...backend.strain_db import get_strain_db_manager
    from ..api_server import log_resources
    
    global _last_load_time, _cached_data
    now = time.time() * 1000
    
    # 命中快照缓存
    if _cached_data is not None and (now - _last_load_time < _LOAD_CACHE_MS):
        logger.info(f"[Cache] 命中内存快照 ({now - _last_load_time:.0f}ms)")
        return _cached_data
    
    # 强制防抖保护
    if now - _last_load_time < _LOAD_DEBOUNCE_MS:
        logger.warning(f"[FlowControl] 请求过频且无快照，拦截以防止IO风暴")
        return {"freezers": [], "records": [], "status": "throttled"}

    try:
        start_time = time.time()
        # 记录后端资源情况
        log_resources(force=False)
        
        # 核心数据库操作 (load_all_data 已在 SQL 层排除 sequence/metadata 大字段)
        all_data: dict[str, Any] = get_strain_db_manager().load_all_data()
        elapsed = (time.time() - start_time) * 1000
        
        # 始终附带 total_count，确保前端可以准确报告数据总量
        total_records = all_data.get('records') or []
        all_data['total_count'] = len(total_records)
        
        _cached_data = all_data
        _last_load_time = now
        
        logger.info(f"[Load] 全部加载成功: {len(total_records)}条记录, 耗时{elapsed:.0f}ms")
        return all_data
    except Exception as e:
        logger.error(f"[Error] /api/strain/load 发生异常: {e}")
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

@router.post("/api/strain/records/delete_batch")
async def delete_records_batch(req: dict, x_client_id: Optional[str] = Header(None, alias="X-Client-ID")):
    from ...backend.strain_db import get_strain_db_manager
    invalidate_cache()
    ids = req.get("ids", [])
    success = get_strain_db_manager().delete_records_batch(ids)
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
        # 词典变更只广播 dictionary 信号，避免触发全量 strains 重载循环
        await broadcaster.broadcast("data_updated", {"module": "dictionary"}, exclude_id=x_client_id)
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

@router.post("/api/strains/import_paths")
async def import_strains_from_paths(req: dict, x_client_id: Optional[str] = Header(None, alias="X-Client-ID")):
    """支持通过物理路径批量导入菌种 (复用 Common 上传后的暂存路径)"""
    from ...utils.file_handler import FileHandler
    from ...backend.strain_db import get_strain_db_manager
    
    paths = req.get("paths", [])
    if not paths:
        return {"success": False, "error": "未提供有效路径"}
    
    fh = FileHandler()
    db = get_strain_db_manager()
    
    try:
        invalidate_cache()
        # 收集所有序列到列表，统一批量写入，避免逐条事务造成的 I/O 风暴
        batch_records = []
        now_str = time.strftime('%Y-%m-%d %H:%M:%S')
        for p in paths:
            # 使用 FileHandler 的迭代读取功能 (支持 ZIP/GZ/ABI)
            for seq_info in fh.read_fasta_file_iter(p):
                batch_records.append({
                    "sampleId": seq_info['id'],
                    "species": seq_info.get('description', ''),
                    "sequence": seq_info['sequence'],
                    "createdAt": now_str,
                    "updatedAt": now_str
                })
        
        count = 0
        if batch_records:
            # 单事务批量写入
            success = db.save_records_batch(batch_records)
            if success:
                count = len(batch_records)
        
        if count > 0 and x_client_id:
            await broadcaster.broadcast("data_updated", {"module": "strains"}, exclude_id=x_client_id)
            
        return {"success": True, "count": count}
    except Exception as e:
        logger.error(f"批量导入路径失败: {e}")
        return {"success": False, "error": str(e)}
