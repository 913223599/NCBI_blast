# -*- coding: utf-8 -*-
"""
PhyloCore REST API 路由 (/api/phylo/*)
"""
import json
import logging
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import PlainTextResponse, Response
from pydantic import BaseModel

from ..broadcaster import broadcaster
from ...phylo.models.errors import InvalidInputError, PhyloError, ToolUnavailableError
from ...phylo.models.schemas import (
    AniEngineType,
    AniScreenResult,
    CapabilitiesResponse,
    DeliveryQcReport,
    DeliveryScopeConfig,
    PhyloJobConfig,
    PhyloJobRecord,
    ReferenceCandidate,
    SequenceProfile,
    WorkspaceInfo,
)
from ...phylo.pipeline.executor import get_phylo_executor
from ...phylo.storage.archive_store import get_phylo_store

logger = logging.getLogger("api_server.phylo")
router = APIRouter(prefix="/api/phylo", tags=["PhyloCore"])


def _bind_broadcaster() -> None:
    executor = get_phylo_executor()
    executor.set_event_callback(lambda ev, data: broadcaster.broadcast_sync(ev, data))


class WorkspaceAddRequest(BaseModel):
    paths: List[str]


class WorkspacePasteRequest(BaseModel):
    content: str
    filename: Optional[str] = None


class ProfileRequest(BaseModel):
    files: Optional[List[str]] = None


class RerootJobRequest(BaseModel):
    mode: str = "midpoint"
    node_name: Optional[str] = None


class PhageAniScreenRequest(BaseModel):
    files: Optional[List[str]] = None
    scope: Optional[DeliveryScopeConfig] = None
    ani_engine: AniEngineType = "viridic_blastn"
    threads: int = 0


class PhageCurateRefsRequest(BaseModel):
    files: Optional[List[str]] = None
    ani_result: Optional[AniScreenResult] = None
    scope: Optional[DeliveryScopeConfig] = None


def _build_workspace_info() -> WorkspaceInfo:
    store = get_phylo_store()
    executor = get_phylo_executor()
    files = store.list_workspace_files()
    profile: Optional[SequenceProfile] = None
    if files:
        try:
            profile = executor.profile_workspace()
        except Exception as exc:
            logger.debug(f"Workspace profile skipped: {exc}")
    return WorkspaceInfo(files=files, profile=profile)


@router.get("/capabilities", response_model=CapabilitiesResponse)
async def get_capabilities(refresh: bool = Query(default=False)):
    _bind_broadcaster()
    return get_phylo_executor().get_capabilities(refresh=refresh)


@router.get("/workspace", response_model=WorkspaceInfo)
async def get_workspace():
    return _build_workspace_info()


@router.post("/workspace/add", response_model=WorkspaceInfo)
async def add_workspace_files(req: WorkspaceAddRequest):
    if not req.paths:
        raise HTTPException(status_code=400, detail="未提供有效文件路径")
    try:
        get_phylo_store().add_files_to_workspace(req.paths)
        return _build_workspace_info()
    except OSError as exc:
        logger.error(f"Add workspace files failed: {exc}")
        raise HTTPException(status_code=500, detail=f"工作区文件操作失败: {exc}") from exc


@router.post("/workspace/paste", response_model=WorkspaceInfo)
async def paste_workspace_sequences(req: WorkspacePasteRequest):
    if not (req.content or "").strip():
        raise HTTPException(status_code=400, detail="粘贴的序列内容为空")
    try:
        get_phylo_store().save_pasted_sequences(req.content, req.filename)
        return _build_workspace_info()
    except OSError as exc:
        logger.error(f"Paste workspace sequences failed: {exc}")
        raise HTTPException(status_code=500, detail=f"工作区文件操作失败: {exc}") from exc


@router.delete("/workspace/{filename}", response_model=WorkspaceInfo)
async def delete_workspace_file(filename: str):
    try:
        removed = get_phylo_store().remove_workspace_file(filename)
    except OSError as exc:
        logger.error(f"Delete workspace file failed ({filename}): {exc}")
        raise HTTPException(status_code=500, detail=f"工作区文件操作失败: {exc}") from exc
    if not removed:
        raise HTTPException(status_code=404, detail=f"未找到文件: {filename}")
    return _build_workspace_info()


@router.delete("/workspace", response_model=WorkspaceInfo)
async def clear_workspace():
    try:
        get_phylo_store().clear_workspace()
        return _build_workspace_info()
    except OSError as exc:
        logger.error(f"Clear workspace failed: {exc}")
        raise HTTPException(status_code=500, detail=f"工作区文件操作失败: {exc}") from exc


@router.post("/profile", response_model=SequenceProfile)
async def profile_sequences(req: ProfileRequest):
    return get_phylo_executor().profile_workspace(req.files)


@router.post("/jobs", response_model=PhyloJobRecord)
async def submit_phylo_job(config: PhyloJobConfig):
    _bind_broadcaster()
    try:
        return get_phylo_executor().submit_job(config)
    except InvalidInputError as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc
    except ToolUnavailableError as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc
    except PhyloError as exc:
        status_code = 409 if exc.code == "JOB_CONFLICT" else 400
        raise HTTPException(status_code=status_code, detail=exc.message) from exc
    except Exception as exc:
        logger.exception(f"Submit phylo job unexpected error: {exc}")
        raise HTTPException(status_code=500, detail=f"提交分析任务失败: {exc}") from exc


@router.get("/jobs")
async def list_phylo_jobs(limit: int = Query(default=50, ge=1, le=200)):
    jobs = get_phylo_store().list_jobs(limit=limit)
    return {"jobs": [j.model_dump() for j in jobs]}


@router.get("/jobs/active")
async def list_active_phylo_jobs():
    jobs = get_phylo_executor().get_active_jobs()
    return {"jobs": [j.model_dump() for j in jobs]}


@router.get("/jobs/{job_id}", response_model=PhyloJobRecord)
async def get_phylo_job(job_id: str):
    rec = get_phylo_store().get_job(job_id)
    if not rec:
        raise HTTPException(status_code=404, detail=f"未找到任务: {job_id}")
    return rec


@router.get("/jobs/{job_id}/logs")
async def get_phylo_job_logs(job_id: str, tail: int = Query(default=300, ge=1, le=5000)):
    rec = get_phylo_store().get_job(job_id)
    if not rec:
        raise HTTPException(status_code=404, detail=f"未找到任务: {job_id}")
    lines = get_phylo_store().read_logs(job_id, tail=tail)
    return {"job_id": job_id, "lines": lines}


@router.post("/jobs/{job_id}/cancel")
async def cancel_phylo_job(job_id: str):
    ok = get_phylo_executor().cancel_job(job_id)
    return {"success": ok, "job_id": job_id}


@router.post("/jobs/{job_id}/reroot", response_model=PhyloJobRecord)
async def reroot_phylo_job(job_id: str, req: RerootJobRequest):
    try:
        return get_phylo_executor().reroot_saved_job(job_id, mode=req.mode, node_name=req.node_name)
    except (InvalidInputError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception(f"Reroot phylo job failed ({job_id}): {exc}")
        raise HTTPException(status_code=500, detail=f"重定根失败: {exc}") from exc


@router.get("/jobs/{job_id}/export/{fmt}")
async def export_phylo_job(job_id: str, fmt: str):
    rec = get_phylo_store().get_job(job_id)
    if not rec:
        raise HTTPException(status_code=404, detail=f"未找到任务: {job_id}")

    fmt_low = fmt.lower().strip()
    if fmt_low == "newick":
        if not rec.newick:
            raise HTTPException(status_code=400, detail="当前任务暂无可导出的 Newick 树")
        return PlainTextResponse(
            content=rec.newick,
            media_type="text/plain; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{job_id}.nwk"'},
        )

    if fmt_low == "distance_csv":
        csv_path_str = rec.artifacts.get("distance_csv")
        if not csv_path_str or not Path(csv_path_str).is_file():
            raise HTTPException(status_code=404, detail="当前任务未生成距离矩阵文件")
        content = Path(csv_path_str).read_text(encoding="utf-8", errors="replace")
        return PlainTextResponse(
            content=content,
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{job_id}_distance.csv"'},
        )

    if fmt_low == "report_json":
        payload = json.dumps(rec.model_dump(), ensure_ascii=False, indent=2)
        return Response(
            content=payload.encode("utf-8"),
            media_type="application/json; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{job_id}_report.json"'},
        )

    if fmt_low == "delivery_zip":
        zip_str = rec.artifacts.get("delivery_zip")
        if not zip_str or not Path(zip_str).is_file():
            raise HTTPException(status_code=404, detail="当前任务未生成完整交付 ZIP 归档")
        return Response(
            content=Path(zip_str).read_bytes(),
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="phylo_delivery_{job_id}.zip"'},
        )

    raise HTTPException(status_code=400, detail=f"不支持的导出格式: {fmt}")


@router.post("/phage/ani-screen", response_model=AniScreenResult)
async def phage_ani_screen(req: PhageAniScreenRequest):
    try:
        return get_phylo_executor().run_phage_ani_screen(
            filenames=req.files,
            scope=req.scope,
            ani_engine=req.ani_engine,
            threads=req.threads,
        )
    except InvalidInputError as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc
    except ToolUnavailableError as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc
    except PhyloError as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc
    except Exception as exc:
        logger.exception(f"Phage ANI screen failed: {exc}")
        raise HTTPException(status_code=500, detail=f"ANI 预判失败: {exc}") from exc


@router.post("/phage/curate-refs", response_model=List[ReferenceCandidate])
async def phage_curate_references(req: PhageCurateRefsRequest):
    try:
        return get_phylo_executor().curate_phage_references(
            filenames=req.files,
            ani_result=req.ani_result,
            scope=req.scope,
        )
    except InvalidInputError as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc
    except PhyloError as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc
    except Exception as exc:
        logger.exception(f"Phage curate refs failed: {exc}")
        raise HTTPException(status_code=500, detail=f"参考集构建失败: {exc}") from exc


@router.get("/jobs/{job_id}/qc", response_model=DeliveryQcReport)
async def get_phylo_job_qc(job_id: str):
    rec = get_phylo_store().get_job(job_id)
    if not rec:
        raise HTTPException(status_code=404, detail=f"未找到任务: {job_id}")
    if not rec.qc_report:
        raise HTTPException(status_code=404, detail="当前任务未包含交付质检报告")
    return rec.qc_report


@router.get("/jobs/{job_id}/export/itol/{filename}")
async def export_phylo_itol_file(job_id: str, filename: str):
    rec = get_phylo_store().get_job(job_id)
    if not rec:
        raise HTTPException(status_code=404, detail=f"未找到任务: {job_id}")
    itol_dir_str = rec.artifacts.get("itol_dir")
    if not itol_dir_str:
        raise HTTPException(status_code=404, detail="当前任务未生成 iTOL 注释模板目录")
    safe_name = Path(filename).name
    target = (Path(itol_dir_str) / safe_name).resolve()
    if not target.is_file() or target.parent != Path(itol_dir_str).resolve():
        raise HTTPException(status_code=404, detail=f"未找到 iTOL 注释文件: {safe_name}")
    return PlainTextResponse(
        content=target.read_text(encoding="utf-8", errors="replace"),
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{safe_name}"'},
    )


@router.delete("/jobs/{job_id}")
async def delete_phylo_job(job_id: str):
    # 若任务仍在运行则先取消
    get_phylo_executor().cancel_job(job_id)
    deleted = get_phylo_store().delete_job(job_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"未找到任务: {job_id}")
    return {"success": True, "job_id": job_id}
