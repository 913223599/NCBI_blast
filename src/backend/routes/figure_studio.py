# -*- coding: utf-8 -*-
"""
Figure Studio 科研绘图工坊 FastAPI REST 路由。
提供跨模块数据检索、六大顶刊图型渲染、历史记录管理与安全内联预览接口。
"""
import logging
from typing import Any, Dict, List, Tuple

from fastapi import APIRouter, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response

from ...figure_studio import data_bridge
from ...figure_studio.models import (
    DiversityRenderRequest,
    GenomeMapRenderRequest,
    HostMatrixRenderRequest,
    NetworkRenderRequest,
    ParsedGenomeInput,
    StudioRenderResponse,
    SyntenyRenderRequest,
    ViridicRenderRequest,
)
from ...figure_studio.renderers import (
    DiversityWindowRenderer,
    GeneNetworkRenderer,
    GenomeMapRenderer,
    HostMatrixRenderer,
    SyntenyRibbonRenderer,
    ViridicHeatmapRenderer,
)
from ...phylo.storage.archive_store import PhyloArchiveStore

logger = logging.getLogger("api.figure_studio")
router = APIRouter(prefix="/api/figure-studio", tags=["FigureStudio"])


@router.get("/sources")
async def get_studio_sources():
    return await run_in_threadpool(data_bridge.list_available_sources)


@router.get("/history")
async def get_studio_history(limit: int = 30):
    items = await run_in_threadpool(data_bridge.list_render_history, limit)
    return {"items": [it.model_dump() for it in items]}


@router.get("/files/{render_id}/{filename}")
async def get_studio_file(render_id: str, filename: str, inline: bool = False):
    target = data_bridge.resolve_render_file(render_id, filename)
    if target is None:
        raise HTTPException(status_code=404, detail=f"未找到图件文件: {filename}")
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
            "Content-Disposition": f'{disposition}; filename="{target.name}"',
            "Cache-Control": "no-store",
        },
    )


def _execute_viridic(req: ViridicRenderRequest) -> Dict[str, Any]:
    resolved_req = req.model_copy(deep=True)
    if req.use_demo or (not req.labels and not req.phylo_job_id):
        demo = data_bridge.get_demo_viridic_payload()
        resolved_req.labels = demo["labels"]
        resolved_req.wgani_matrix = demo["wgani_matrix"]
        resolved_req.af_matrix = demo["af_matrix"]
        resolved_req.genome_lengths = demo["genome_lengths"]
    elif req.phylo_job_id and not req.labels:
        job = PhyloArchiveStore().get_job(req.phylo_job_id)
        if not job or not job.ani_result or len(job.ani_result.wgani_matrix) < 2:
            raise ValueError(f"系统发育任务 {req.phylo_job_id} 不包含足够的 wgANI 矩阵")
        ani = job.ani_result
        resolved_req.labels = list(ani.matrix_labels)
        resolved_req.wgani_matrix = [list(r) for r in ani.wgani_matrix]
        resolved_req.af_matrix = [list(r) for r in ani.af_matrix]
        meta = job.node_metadata or {}
        hit_len = {h.accession: h.genome_length for h in ani.top_hits}
        resolved_req.genome_lengths = [
            int((meta.get(lbl) or {}).get("genome_length") or hit_len.get(lbl) or 50000)
            for lbl in resolved_req.labels
        ]
        if job.newick and not resolved_req.newick:
            resolved_req.newick = job.newick

    render_id, out_dir = data_bridge.create_render_dir("viridic")
    paths = ViridicHeatmapRenderer.render(out_dir=out_dir, req=resolved_req)
    return data_bridge.build_figure_files_and_save_meta(render_id, "viridic", resolved_req.title, out_dir, paths)


@router.post("/render/viridic", response_model=StudioRenderResponse)
async def render_viridic(req: ViridicRenderRequest):
    try:
        payload = await run_in_threadpool(_execute_viridic, req)
        return StudioRenderResponse(**payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("VIRIDIC render error: %s", exc)
        raise HTTPException(status_code=500, detail=f"VIRIDIC 出图失败: {exc}") from exc


def _execute_genome_map(req: GenomeMapRenderRequest) -> Dict[str, Any]:
    if req.use_demo or (not req.annotation_task_id and not req.gbk_path and not req.gbk_content):
        genome = data_bridge._build_demo_genomes()[0]
    elif req.annotation_task_id:
        genome = data_bridge.load_annotation_genome(req.annotation_task_id)
    else:
        genome = data_bridge.parse_gbk_source(gbk_path=req.gbk_path, gbk_content=req.gbk_content)

    render_id, out_dir = data_bridge.create_render_dir("genome_map")
    paths = GenomeMapRenderer.render(genome=genome, out_dir=out_dir, req=req)
    title = req.title or f"{genome.name} ({req.mode})"
    return data_bridge.build_figure_files_and_save_meta(render_id, "genome_map", title, out_dir, paths)


@router.post("/render/genome-map", response_model=StudioRenderResponse)
async def render_genome_map(req: GenomeMapRenderRequest):
    try:
        payload = await run_in_threadpool(_execute_genome_map, req)
        return StudioRenderResponse(**payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Genome map render error: %s", exc)
        raise HTTPException(status_code=500, detail=f"全基因组图谱出图失败: {exc}") from exc


def _execute_synteny(req: SyntenyRenderRequest) -> Dict[str, Any]:
    genomes: List[ParsedGenomeInput] = []
    if req.use_demo or (not req.annotation_task_ids and not req.gbk_paths):
        genomes = data_bridge._build_demo_genomes()
    else:
        for tid in req.annotation_task_ids:
            genomes.append(data_bridge.load_annotation_genome(tid))
        for gp in req.gbk_paths:
            genomes.append(data_bridge.parse_gbk_source(gbk_path=gp))

    render_id, out_dir = data_bridge.create_render_dir("synteny")
    paths = SyntenyRibbonRenderer.render(genomes=genomes, out_dir=out_dir, req=req)
    return data_bridge.build_figure_files_and_save_meta(render_id, "synteny", req.title, out_dir, paths)


@router.post("/render/synteny", response_model=StudioRenderResponse)
async def render_synteny(req: SyntenyRenderRequest):
    try:
        payload = await run_in_threadpool(_execute_synteny, req)
        return StudioRenderResponse(**payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Synteny render error: %s", exc)
        raise HTTPException(status_code=500, detail=f"共线性比较出图失败: {exc}") from exc


def _execute_diversity(req: DiversityRenderRequest) -> Dict[str, Any]:
    if req.use_demo or (not req.ref_annotation_task_id and not req.fasta_content):
        demos = data_bridge._build_demo_genomes()
        ref_genome = demos[0]
        seqs: List[Tuple[str, str]] = [(g.name, g.sequence) for g in demos]
    else:
        ref_genome = (
            data_bridge.load_annotation_genome(req.ref_annotation_task_id)
            if req.ref_annotation_task_id
            else ParsedGenomeInput(name="Reference", sequence="", length=1000)
        )
        seqs = []
        if ref_genome.sequence:
            seqs.append((ref_genome.name, ref_genome.sequence))
        for tid in req.compare_annotation_task_ids:
            if tid == req.ref_annotation_task_id:
                continue
            cg = data_bridge.load_annotation_genome(tid)
            if cg.sequence:
                seqs.append((cg.name, cg.sequence))
        if req.fasta_content and req.fasta_content.strip():
            seqs.extend(data_bridge.parse_fasta_text(req.fasta_content))

    render_id, out_dir = data_bridge.create_render_dir("diversity")
    paths = DiversityWindowRenderer.render(ref_genome=ref_genome, sequences=seqs, out_dir=out_dir, req=req)
    return data_bridge.build_figure_files_and_save_meta(render_id, "diversity", req.title, out_dir, paths)


@router.post("/render/diversity", response_model=StudioRenderResponse)
async def render_diversity(req: DiversityRenderRequest):
    try:
        payload = await run_in_threadpool(_execute_diversity, req)
        return StudioRenderResponse(**payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Diversity render error: %s", exc)
        raise HTTPException(status_code=500, detail=f"多样性热点出图失败: {exc}") from exc


def _execute_network(req: NetworkRenderRequest) -> Dict[str, Any]:
    nodes: List[Dict[str, Any]] = []
    edges: List[Dict[str, Any]] = []

    if req.edges_csv and req.edges_csv.strip():
        seen_n: set[str] = set()
        for line in req.edges_csv.strip().splitlines():
            parts = [p.strip() for p in line.replace("\t", ",").split(",")]
            if len(parts) < 2 or parts[0].lower() in ("source", "from"):
                continue
            u, v = parts[0], parts[1]
            w = float(parts[2]) if len(parts) > 2 else 0.8
            grp = parts[3] if len(parts) > 3 else "Custom Cluster"
            for nid in (u, v):
                if nid not in seen_n:
                    seen_n.add(nid)
                    nodes.append({"id": nid, "label": nid, "group": grp, "is_query": "query" in nid.lower()})
            edges.append({"source": u, "target": v, "weight": w})
    elif req.phylo_job_id:
        job = PhyloArchiveStore().get_job(req.phylo_job_id)
        if not job or not job.ani_result:
            raise ValueError(f"系统发育任务 {req.phylo_job_id} 缺乏 ANI 与元数据")
        meta = job.node_metadata or {}
        ani = job.ani_result
        for lbl in ani.matrix_labels:
            info = meta.get(lbl) or {}
            grp = str(info.get(req.color_by) or info.get("family") or info.get("genus") or "Unclassified")
            is_q = str(info.get("role") or "").lower() == "query" or lbl in ani.query_ids
            nodes.append({"id": lbl, "label": lbl, "group": grp, "is_query": is_q})
        n_m = len(ani.matrix_labels)
        for i in range(n_m):
            for j in range(i + 1, n_m):
                sim = float(ani.wgani_matrix[i][j]) / 100.0
                if sim >= req.min_weight:
                    edges.append({"source": ani.matrix_labels[i], "target": ani.matrix_labels[j], "weight": sim})
    else:
        # 内置代表性多家族蛋白共享示范网络
        demo_specs = [
            ("Query_Phage", "Demerecviridae", True),
            ("T5_ref", "Demerecviridae", False),
            ("EPS7_ref", "Demerecviridae", False),
            ("DT57C", "Demerecviridae", False),
            ("T4_ref", "Straboviridae", False),
            ("RB49", "Straboviridae", False),
            ("JS98", "Straboviridae", False),
            ("T7_ref", "Autographiviridae", False),
            ("SP6_ref", "Autographiviridae", False),
            ("K1F_ref", "Autographiviridae", False),
            ("Singleton_A", "Microviridae", False),
            ("Singleton_B", "Microviridae", False),
        ]
        nodes = [{"id": n, "label": n, "group": g, "is_query": q} for n, g, q in demo_specs]
        edges = [
            {"source": "Query_Phage", "target": "T5_ref", "weight": 0.94},
            {"source": "Query_Phage", "target": "EPS7_ref", "weight": 0.86},
            {"source": "T5_ref", "target": "EPS7_ref", "weight": 0.88},
            {"source": "T5_ref", "target": "DT57C", "weight": 0.72},
            {"source": "T4_ref", "target": "RB49", "weight": 0.85},
            {"source": "T4_ref", "target": "JS98", "weight": 0.81},
            {"source": "RB49", "target": "JS98", "weight": 0.77},
            {"source": "T7_ref", "target": "SP6_ref", "weight": 0.79},
            {"source": "T7_ref", "target": "K1F_ref", "weight": 0.74},
            {"source": "Singleton_A", "target": "Singleton_B", "weight": 0.65},
        ]

    render_id, out_dir = data_bridge.create_render_dir("network")
    paths = GeneNetworkRenderer.render(nodes=nodes, edges=edges, out_dir=out_dir, req=req)
    return data_bridge.build_figure_files_and_save_meta(render_id, "network", req.title, out_dir, paths)


@router.post("/render/network", response_model=StudioRenderResponse)
async def render_network(req: NetworkRenderRequest):
    try:
        payload = await run_in_threadpool(_execute_network, req)
        return StudioRenderResponse(**payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Network render error: %s", exc)
        raise HTTPException(status_code=500, detail=f"基因共享网络出图失败: {exc}") from exc


def _execute_host_matrix(req: HostMatrixRenderRequest) -> Dict[str, Any]:
    resolved_req = req.model_copy(deep=True)
    if req.use_demo or (not req.matrix_csv and not req.row_labels):
        resolved_req.row_labels = [
            "E. coli K12",
            "S. enterica LT2",
            "C. werkmanii",
            "K. pneumoniae K2",
            "K. pneumoniae K25",
            "P. putida KT2440",
            "P. fluorescens",
            "S. marcescens",
        ]
        resolved_req.col_labels = ["T5_E1", "PRD1", "PRDmint", "PRDjuniper", "KP24_gp300", "KLEO13_dep", "S2_dep"]
        resolved_req.col_groups = ["Siphovirus", "Podovirus", "Podovirus", "Podovirus", "Jumbo myovirus", "Siphovirus", "Myovirus"]
        if req.mode == "sparse_specificity":
            resolved_req.values = [
                [95, 100, 88, 0, 0, 0, 0],
                [85, 92, 90, 80, 0, 0, 0],
                [0, 82, 85, 76, 0, 0, 0],
                [0, 0, 0, 0, 96, 84, 0],
                [0, 0, 0, 0, 92, 0, 89],
                [0, 0, 75, 94, 0, 0, 0],
                [0, 0, 62, 86, 0, 0, 0],
                [0, 0, 0, 0, 0, 78, 91],
            ]
        else:
            resolved_req.values = [
                [92, 88, 76, 15, 5, 12, 8],
                [85, 94, 82, 68, 8, 10, 4],
                [24, 80, 79, 72, 4, 6, 5],
                [6, 12, 8, 10, 95, 86, 18],
                [5, 8, 11, 7, 91, 14, 89],
                [12, 42, 74, 93, 6, 5, 10],
                [8, 35, 62, 84, 4, 8, 6],
                [10, 18, 12, 9, 12, 79, 92],
            ]
    elif req.matrix_csv and req.matrix_csv.strip():
        r_lbls, c_lbls, vals, r_grps, c_grps = data_bridge.parse_numeric_matrix_csv(req.matrix_csv)
        resolved_req.row_labels = r_lbls
        resolved_req.col_labels = c_lbls
        resolved_req.values = vals
        if not resolved_req.col_groups and c_grps:
            resolved_req.col_groups = c_grps

    render_id, out_dir = data_bridge.create_render_dir("host_matrix")
    paths = HostMatrixRenderer.render(out_dir=out_dir, req=resolved_req)
    return data_bridge.build_figure_files_and_save_meta(render_id, "host_matrix", resolved_req.title, out_dir, paths)


@router.post("/render/host-matrix", response_model=StudioRenderResponse)
async def render_host_matrix(req: HostMatrixRenderRequest):
    try:
        payload = await run_in_threadpool(_execute_host_matrix, req)
        return StudioRenderResponse(**payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Host matrix render error: %s", exc)
        raise HTTPException(status_code=500, detail=f"宿主谱矩阵出图失败: {exc}") from exc
