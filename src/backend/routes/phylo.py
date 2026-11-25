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
from ...phylo.delivery.itol_client import ITOL_UPLOAD_PAGE_URL, ItolBatchClient
from ...phylo.delivery.label_formatter import enrich_node_metadata
from ...phylo.delivery.publication_renderer import PublicationTreeRenderer
from ...phylo.models.errors import InvalidInputError, PhyloError, ToolUnavailableError
from ...phylo.models.schemas import (
    AniEngineType,
    AniScreenResult,
    CapabilitiesResponse,
    DeliveryQcReport,
    DeliveryScopeConfig,
    ItolPullRequest,
    ItolPullResponse,
    LabelFormatType,
    PhyloJobConfig,
    PhyloJobRecord,
    PublicationFigureItem,
    PublicationFigureRequest,
    PublicationRenderResponse,
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
    for j in jobs:
        if j.node_metadata:
            j.node_metadata = enrich_node_metadata(j.node_metadata)
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
    if rec.node_metadata:
        rec.node_metadata = enrich_node_metadata(rec.node_metadata)
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
        rec = get_phylo_executor().reroot_saved_job(job_id, mode=req.mode, node_name=req.node_name)
        if rec.node_metadata:
            rec.node_metadata = enrich_node_metadata(rec.node_metadata)
        return rec
    except (InvalidInputError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception(f"Reroot phylo job failed ({job_id}): {exc}")
        raise HTTPException(status_code=500, detail=f"重定根失败: {exc}") from exc


def _resolve_job_dir(rec: PhyloJobRecord) -> Path:
    store = get_phylo_store()
    return Path(rec.job_dir) if rec.job_dir else (store.jobs_dir / rec.job_id)


@router.get("/jobs/{job_id}/export/itol_newick")
async def export_itol_ascii_newick(job_id: str):
    rec = get_phylo_store().get_job(job_id)
    if not rec:
        raise HTTPException(status_code=404, detail=f"未找到任务: {job_id}")
    if not rec.newick:
        raise HTTPException(status_code=400, detail="当前任务尚未生成进化树 Newick 文件。")

    try:
        ascii_nwk, _ = ItolBatchClient.sanitize_newick_for_itol(rec.newick)
    except Exception as exc:
        logger.exception(f"Sanitize iTOL Newick failed ({job_id}): {exc}")
        raise HTTPException(status_code=500, detail=f"生成 iTOL 纯 ASCII 树失败: {exc}") from exc

    return PlainTextResponse(
        content=ascii_nwk,
        media_type="text/plain; charset=ascii",
        headers={"Content-Disposition": f'attachment; filename="itol_tree_{job_id}.nwk"'},
    )


@router.get("/jobs/{job_id}/export/itol_bundle")
async def export_itol_upload_bundle(
    job_id: str,
    label_format: LabelFormatType = Query(default="name_acc"),
):
    rec = get_phylo_store().get_job(job_id)
    if not rec:
        raise HTTPException(status_code=404, detail=f"未找到任务: {job_id}")
    if not rec.newick:
        raise HTTPException(status_code=400, detail="当前任务尚未生成进化树 Newick 文件。")

    job_dir = _resolve_job_dir(rec)
    itol_dir = Path(rec.artifacts.get("itol_dir") or (job_dir / "itol"))
    enriched_meta = enrich_node_metadata(rec.node_metadata)
    try:
        bundle_path = ItolBatchClient.build_itol_upload_bundle(
            job_dir=job_dir,
            job_id=job_id,
            newick=rec.newick,
            itol_dir=itol_dir,
            node_metadata=enriched_meta,
            label_format=label_format,
        )
    except Exception as exc:
        logger.exception(f"Build iTOL upload bundle failed ({job_id}): {exc}")
        raise HTTPException(status_code=500, detail=f"生成 iTOL 上传包失败: {exc}") from exc

    return Response(
        content=bundle_path.read_bytes(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{bundle_path.name}"'},
    )


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


@router.post("/jobs/{job_id}/render-publication", response_model=PublicationRenderResponse)
async def render_publication_figure(job_id: str, req: PublicationFigureRequest):
    store = get_phylo_store()
    rec = store.get_job(job_id)
    if not rec:
        raise HTTPException(status_code=404, detail=f"未找到任务: {job_id}")
    if not rec.newick:
        raise HTTPException(status_code=400, detail="当前任务尚未生成有效的 Newick 进化树。")

    job_dir = _resolve_job_dir(rec)
    figures_dir = job_dir / "figures"
    subtitle_parts: List[str] = []
    if rec.metrics and rec.metrics.best_model:
        bic = rec.metrics.best_model_bic
        subtitle_parts.append(
            f"Model: {rec.metrics.best_model}" + (f" (BIC={bic})" if bic is not None else "")
        )
    elif rec.qc_report and rec.qc_report.best_model:
        bic = rec.qc_report.best_model_bic
        subtitle_parts.append(
            f"Model: {rec.qc_report.best_model}" + (f" (BIC={bic})" if bic is not None else "")
        )

    try:
        out_paths = PublicationTreeRenderer.render(
            newick=rec.newick,
            node_metadata=rec.node_metadata,
            out_dir=figures_dir,
            request=req,
            file_prefix="publication",
            subtitle=" | ".join(subtitle_parts),
        )
    except (InvalidInputError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception(f"Render publication figure failed ({job_id}): {exc}")
        raise HTTPException(status_code=500, detail=f"离线出版级出图失败: {exc}") from exc

    new_items = [
        PublicationFigureItem(
            filename=fp.name,
            format=fp.suffix.lstrip(".").lower(),
            layout=req.layout,
            size_bytes=fp.stat().st_size,
            download_url=f"/api/phylo/jobs/{job_id}/export/figure/{fp.name}",
        )
        for fp in out_paths
    ]

    # 按 filename 合并持久化记录，避免不同布局的成果互相覆盖
    existing_map = {
        str(item.get("filename")): item
        for item in (rec.artifacts.get("publication_figures") or [])
        if isinstance(item, dict) and item.get("filename")
    }
    for it in new_items:
        existing_map[it.filename] = it.model_dump()
    rec.artifacts["figures_dir"] = str(figures_dir)
    rec.artifacts["publication_figures"] = list(existing_map.values())
    store.save_job(rec)

    return PublicationRenderResponse(job_id=job_id, layout=req.layout, figures=new_items)


@router.get("/jobs/{job_id}/export/figure/{filename}")
async def export_phylo_figure(job_id: str, filename: str, inline: bool = False):
    rec = get_phylo_store().get_job(job_id)
    if not rec:
        raise HTTPException(status_code=404, detail=f"未找到任务: {job_id}")

    job_dir = _resolve_job_dir(rec)
    safe_name = Path(filename).name
    target: Optional[Path] = None
    for sub in ("figures", "itol_exports"):
        base_dir = (job_dir / sub).resolve()
        cand = (base_dir / safe_name).resolve()
        if cand.is_file() and cand.parent == base_dir:
            target = cand
            break

    if target is None:
        raise HTTPException(status_code=404, detail=f"未找到图件文件: {safe_name}")

    mime_map = {
        ".pdf": "application/pdf",
        ".svg": "image/svg+xml; charset=utf-8",
        ".png": "image/png",
        ".eps": "application/postscript",
    }
    media_type = mime_map.get(target.suffix.lower(), "application/octet-stream")
    disposition = "inline" if inline else "attachment"
    return Response(
        content=target.read_bytes(),
        media_type=media_type,
        headers={
            "Content-Disposition": f'{disposition}; filename="{safe_name}"',
            "Cache-Control": "no-store",
        },
    )


@router.post("/jobs/{job_id}/itol/pull", response_model=ItolPullResponse)
async def pull_itol_figure(job_id: str, req: ItolPullRequest):
    store = get_phylo_store()
    rec = store.get_job(job_id)
    if not rec:
        raise HTTPException(status_code=404, detail=f"未找到任务: {job_id}")

    job_dir = _resolve_job_dir(rec)
    itol_out_dir = job_dir / "itol_exports"
    try:
        tree_id, out_path = ItolBatchClient.export_from_itol(
            tree_id_or_url=req.tree_id_or_url,
            out_dir=itol_out_dir,
            req=req,
        )
    except InvalidInputError as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc
    except PhyloError as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc
    except Exception as exc:
        logger.exception(f"Pull iTOL figure failed ({job_id}): {exc}")
        raise HTTPException(status_code=500, detail=f"从 iTOL 拉取出图失败: {exc}") from exc

    item_dict = {
        "job_id": job_id,
        "tree_id": tree_id,
        "filename": out_path.name,
        "format": req.format,
        "size_bytes": out_path.stat().st_size,
        "download_url": f"/api/phylo/jobs/{job_id}/export/figure/{out_path.name}",
        "itol_tree_url": f"https://itol.embl.de/tree/{tree_id}",
    }
    existing_map = {
        str(item.get("filename")): item
        for item in (rec.artifacts.get("itol_exports") or [])
        if isinstance(item, dict) and item.get("filename")
    }
    existing_map[out_path.name] = item_dict
    rec.artifacts["itol_exports"] = list(existing_map.values())
    rec.artifacts["itol_upload_page_url"] = ITOL_UPLOAD_PAGE_URL
    store.save_job(rec)

    return ItolPullResponse(**item_dict)


@router.delete("/jobs/{job_id}")
async def delete_phylo_job(job_id: str):
    # 若任务仍在运行则先取消
    get_phylo_executor().cancel_job(job_id)
    deleted = get_phylo_store().delete_job(job_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"未找到任务: {job_id}")
    return {"success": True, "job_id": job_id}
