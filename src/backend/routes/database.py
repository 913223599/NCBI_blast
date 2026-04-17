import asyncio
from fastapi import APIRouter, BackgroundTasks
from typing import Dict, Any
from ..utils.bio_db_manager import bio_db_manager
from ..utils.response import BioResponse
from ..broadcaster import broadcaster

router = APIRouter(prefix="/database", tags=["database"])

@router.get("/status")
async def get_all_db_status():
    """获取所有已注册的生物数据库状态"""
    return BioResponse.ok(bio_db_manager.list_all_status())

@router.post("/update/{db_id}")
async def trigger_db_update(db_id: str, background_tasks: BackgroundTasks):
    """触发特定数据库的自动化更新"""
    if db_id not in bio_db_manager.dbs:
        return BioResponse.fail(f"Database {db_id} not registered")
    
    # 将更新任务放入后台执行
    background_tasks.add_task(_run_update_task, db_id)
    
    return BioResponse.ok({"message": f"Update task for {db_id} started in background"})

async def _run_update_task(db_id: str):
    """
    后台更新流水线：更新物理文件并发送实时进度
    """
    db = bio_db_manager.dbs[db_id]
    
    # 开始更新
    await broadcaster.broadcast("db_update_event", {
        "db_id": db_id,
        "status": "updating",
        "progress": 5,
        "message": f"正在从官网请求 {db.name} 核心文件..."
    })

    success = await db.update_database()
    
    # 广播结果
    await broadcaster.broadcast("db_update_event", {
        "db_id": db_id,
        "status": "success" if success else "error",
        "progress": 100,
        "message": f"{db.name} 更新成功" if success else f"{db.name} 更新失败"
    })
