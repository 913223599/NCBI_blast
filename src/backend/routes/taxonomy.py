import logging
from fastapi import APIRouter
from ...utils.taxonomy_provider import get_taxonomy_provider

logger = logging.getLogger("api_server")
router = APIRouter(tags=["Taxonomy Management"])

@router.get("/api/taxonomy/status")
async def get_taxonomy_status():
    """获取本地 NCBI Taxonomy 数据库的状态"""
    try:
        return get_taxonomy_provider().get_status()
    except Exception as e:
        logger.error(f"Failed to get taxonomy status: {e}")
        return {"ready": False, "error": str(e)}

@router.post("/api/taxonomy/update")
async def trigger_taxonomy_update():
    """从 NCBI 在线更新分类数据库 (后台异步进行)"""
    try:
        get_taxonomy_provider().start_update_process()
        return {"success": True, "message": "Update started in background"}
    except Exception as e:
        logger.error(f"Failed to trigger taxonomy update: {e}")
        return {"success": False, "error": str(e)}

@router.get("/api/taxonomy/check")
async def check_taxonomy_update():
    """检查 NCBI FTP 上是否有更新版本"""
    try:
        return get_taxonomy_provider().check_for_update()
    except Exception as e:
        logger.error(f"Failed to check taxonomy update: {e}")
        return {"hasUpdate": False, "error": str(e)}
