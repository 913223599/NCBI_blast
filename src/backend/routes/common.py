
import os
import time
import shutil
import logging
from pathlib import Path
from fastapi import APIRouter, UploadFile, File, HTTPException
from typing import List

logger = logging.getLogger("api_server")
router = APIRouter(tags=["Common Storage"])

# 获取项目根目录
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent

@router.post("/api/common/upload")
async def upload_file_generic(file: UploadFile = File(...)):
    """
    通用文件上传接口 (单一职责)
    将上传的 MultipartFile 保存到服务器的临时暂存区，并返回物理路径。
    """
    try:
        # 定义暂存根目录
        staged_root = PROJECT_ROOT / "results" / "staged_uploads"
        staged_root.mkdir(parents=True, exist_ok=True)
        
        # 按分钟划分目录，防止单目录下文件过多，同时也方便后续按批次清理
        session_id = f"up_{time.strftime('%Y%m%d_%H%M')}"
        upload_dir = staged_root / session_id
        upload_dir.mkdir(parents=True, exist_ok=True)
        
        # 安全的文件名处理 (仅保留基本字符，防止路径穿越)
        safe_filename = "".join(c for c in file.filename if c.isalnum() or c in ('.', '_', '-')).strip()
        if not safe_filename:
            safe_filename = f"unnamed_{int(time.time())}"
            
        file_path = upload_dir / safe_filename
        
        # 物理保存
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
            
        logger.info(f"🟢 [Upload] 文件已暂存: {safe_filename} -> {file_path}")
        
        return {
            "success": True,
            "filename": safe_filename,
            "path": str(file_path.resolve())
        }
    except Exception as e:
        logger.error(f"🔴 [Upload] 上传过程中发生异常: {e}")
        return {"success": False, "error": str(e)}

@router.post("/api/common/upload_batch")
async def upload_files_batch(files: List[UploadFile] = File(...)):
    """
    批量上传支持
    """
    results = []
    for f in files:
        res = await upload_file_generic(f)
        results.append(res)
    return results
