# -*- coding: utf-8 -*-
"""
Assembly API Routes - 基因组拼接后端接口模块 (纯净重构版)
提供任务提交、队列调度、实时进度遥测、指标查询与产物导出接口。
"""

import re
import json
import os
import gzip
import time
import logging
from collections import Counter
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from ..broadcaster import broadcaster
from ..utils.response import BioResponse
from ..utils.assembly_storage import AssemblyStorage
from ..utils.persistent_queue import persistent_queue as assembly_queue
from ..utils.assembly_db import assembly_db
from src.assembly.manager import AssemblyManager

logger = logging.getLogger("Assembly.Routes")

# 全局管理器单例
_project_root = Path(__file__).resolve().parent.parent.parent.parent
manager = AssemblyManager(_project_root)

router = APIRouter(prefix="/assembly", tags=["assembly"])


async def execute_assembly_pipeline(payload: Dict[str, Any]):
    """
    持久化串行队列的消费者处理器函数
    """
    task_id = payload.get('task_id')
    sample_type = payload.get('sample_type', 'BACTERIA')
    config = payload.get('config', {})
    
    r1_input = payload.get('r1') or config.get('r1') or config.get('params', {}).get('r1')
    r2_input = payload.get('r2') or config.get('r2') or config.get('params', {}).get('r2')
    
    files = payload.get('files') or config.get('files') or []
    if not r1_input and files:
        r1_input = files[0]
        if len(files) > 1:
            r2_input = files[1]
            
    logger.info(f"队列调度执行任务: {task_id} | R1={r1_input} | R2={r2_input}")
    await manager.run_pipeline(
        task_id=task_id,
        sample_type=sample_type,
        r1_input=r1_input,
        r2_input=r2_input,
        config=config
    )



@router.post("/run")
async def run_assembly_job(payload: Dict[str, Any]):
    """
    提交基因组组装任务至持久化队列
    """
    task_id = payload.get('task_id')
    if not task_id:
        task_id = f"Assembly_{int(time.time() * 1000)}"
        payload['task_id'] = task_id

    # 1. 创建物理结果目录
    AssemblyStorage.get_task_dir(task_id)
    
    # 2. 持久化记录到数据库
    sample_id = payload.get('sample_id', 'Unknown')
    name = payload.get('name', 'Assembly Task')
    sample_type = payload.get('sample_type', 'BACTERIA')
    tech = payload.get('tech', 'ILLUMINA')
    config = payload.get('config', {})
    
    assembly_db.create_task(task_id, name, sample_id, sample_type, tech, config)
    
    # 3. 加入持久化队列
    await assembly_queue.add_task(payload)
    
    queue_size = assembly_queue.get_queue_size()
    return BioResponse.ok({
        "message": "Task queued successfully",
        "task_id": task_id,
        "queue_position": queue_size
    })


@router.get("/history")
async def get_assembly_history():
    """获取拼接任务历史列表 (带自动健康检查与历史数据自愈)"""
    history = assembly_db.get_history(limit=100)
    for t in history:
        res = t.get('results')
        task_id = t['id']
        task_dir = AssemblyStorage.get_task_dir(task_id)
        
        # 1. 自动自愈：若任务已完成但指标全 0 或缺失，尝试从产物 assembly.fasta 重建真实指标
        is_completed = t.get('status') == 'completed'
        is_corrupted = not res or not isinstance(res, dict) or res.get('total_length', 0) <= 0 or res.get('gc_percent', 0.0) <= 0.0 or res.get('n50', 0) <= 0
        if is_completed and is_corrupted:
            asm_fasta = find_assembly_fasta(task_id, task_dir)
            if asm_fasta and asm_fasta.exists() and asm_fasta.stat().st_size > 0:
                s_recovered, _ = parse_assembly_fasta_metrics(asm_fasta, task_dir)
                if s_recovered.get('total_length', 0) > 0 and (s_recovered.get('n50', 0) > 0 or s_recovered.get('gc_percent', 0.0) > 0.0):
                    assembly_db.update_task_metrics(
                        task_id,
                        total_length=int(s_recovered['total_length']),
                        contig_count=int(s_recovered.get('contigs', 1)),
                        n50=int(s_recovered.get('n50', 0)),
                        gc_content=float(s_recovered.get('gc_percent', 0.0)),
                        is_circular=bool(s_recovered.get('is_circular', False)),
                        avg_depth=float(s_recovered.get('avg_depth', 0.0)),
                        max_contig_length=int(s_recovered.get('max_contig_length', 0))
                    )
                    t['results'] = {
                        "total_length": s_recovered['total_length'],
                        "contigs": s_recovered['contigs'],
                        "n50": s_recovered['n50'],
                        "gc_percent": s_recovered['gc_percent'],
                        "is_circular": s_recovered['is_circular'],
                        "avg_depth": s_recovered['avg_depth'],
                        "max_contig_length": s_recovered['max_contig_length']
                    }
                    res = t['results']

        if isinstance(res, dict) and res.get('total_length', 0) > 0:
            need_update = False
            
            if not res.get('max_contig_length'):
                res['max_contig_length'] = res.get('n50') or res.get('total_length', 0)
                need_update = True
                
            if not res.get('avg_depth') or float(res.get('avg_depth', 0.0)) <= 0.0:
                for s_dir in [task_dir / "assemblerstep" / "assembly_run", task_dir / "assembly_run", task_dir, Path(f"E:/NGCS_Work/tasks/{task_id}")]:
                    fj_path = s_dir / "qc" / "fastp.json"
                    if not fj_path.exists():
                        fj_path = s_dir / "fastp.json"
                    if fj_path.exists():
                        try:
                            with open(fj_path, "r", encoding="utf-8") as fj:
                                cb = json.load(fj).get("summary", {}).get("after_filtering", {}).get("total_bases", 0)
                                if cb > 0 and res['total_length'] > 0:
                                    res['avg_depth'] = round(cb / res['total_length'], 1)
                                    need_update = True
                                    break
                        except Exception:
                            pass
            if need_update and (res.get('n50', 0) > 0 or res.get('gc_percent', 0.0) > 0.0):
                assembly_db.update_task_metrics(
                    task_id,
                    total_length=res['total_length'],
                    contig_count=int(res.get('contigs') or 1),
                    n50=int(res.get('n50') or res['total_length']),
                    gc_content=float(res.get('gc_percent') or 0.0),
                    is_circular=bool(res.get('is_circular', False)),
                    avg_depth=float(res.get('avg_depth') or 0.0),
                    max_contig_length=int(res.get('max_contig_length') or 0)
                )
    return BioResponse.ok(history)


@router.get("/status/{task_id}")
async def get_assembly_status(task_id: str):
    """查询指定任务的当前状态与进度"""
    task = assembly_db.get_task(task_id)
    if not task:
        return BioResponse.fail("Task not found")

    # 检查是否在队列中排队
    waiting_tasks = assembly_db.get_queued_tasks()
    queue_pos = -1
    for idx, t in enumerate(waiting_tasks):
        if t['id'] == task_id:
            queue_pos = idx + 1
            break

    # 解析 JSON 字段
    if task.get('results') and isinstance(task['results'], str):
        try: task['results'] = json.loads(task['results'])
        except: pass
    if task.get('config') and isinstance(task['config'], str):
        try: task['config'] = json.loads(task['config'])
        except: pass

    task['queue_position'] = queue_pos
    return BioResponse.ok(task)


def find_assembly_fasta(task_id: str, task_dir: Path) -> Optional[Path]:
    """多级智能定位 assembly.fasta 产物路径 (兼容 assemblerstep/assembly_run/工作盘等各类结构)"""
    candidates = [
        task_dir / "assemblerstep" / "assembly_run" / "assembly.fasta",
        task_dir / "assembly_run" / "assembly.fasta",
        task_dir / "assembly.fasta",
        task_dir / "assemblerstep" / "assembly.fasta",
        Path(f"E:/NGCS_Work/tasks/{task_id}/assembly_run/assembly.fasta"),
        Path(f"E:/NGCS_Work/tasks/{task_id}/assembly.fasta")
    ]
    for c in candidates:
        if c.exists() and c.stat().st_size > 0:
            return c

    # 深度递归扫描兜底
    if task_dir.exists():
        found = list(task_dir.rglob("assembly.fasta"))
        if found and found[0].stat().st_size > 0:
            return found[0]
    return None


def parse_assembly_fasta_metrics(asm_fasta: Path, task_dir: Optional[Path] = None) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """
    单遍流式解析 assembly.fasta 产物，精准提取全部 contigs 列表、N50、最大长度、全基因组加权 GC% 及深度指标
    """
    contigs: List[Dict[str, Any]] = []
    total_len = 0
    cur_h = None
    cur_seq = []

    def flush_c(h_str: str, s_parts: List[str]):
        nonlocal total_len
        if not h_str or not s_parts: return
        seq_str = "".join(s_parts)
        s_len = len(seq_str)
        if s_len == 0: return
        h_l = h_str.lower()
        c_n = h_str.split()[0].lstrip(">")

        # 深度提取
        d_m = re.search(r"(?:depth[=:]|cov[=_:]|coverage[=:])(\d+\.?\d*)", h_l)
        d_val = float(d_m.group(1)) if d_m else 0.0

        # 拓扑判定
        is_c = "circular=true" in h_l or "circular=y" in h_l or "topology=circular" in h_l or "_circular" in h_l

        # GC 含量 (优先 Header 显式声明，兜底单序列碱基计算)
        gc_m = re.search(r"(?:gc[=:]|gc_percent[=:])(\d+\.?\d*)%?", h_l)
        if gc_m:
            gc_p = float(gc_m.group(1))
        else:
            s_up = seq_str.upper()
            gc_c = s_up.count("G") + s_up.count("C")
            gc_p = round((gc_c / s_len * 100.0), 2) if s_len > 0 else 0.0

        contigs.append({
            "name": c_n,
            "header": h_str.lstrip(">"),
            "length": s_len,
            "gc_percent": gc_p,
            "depth": d_val,
            "is_circular": is_c,
            "sequence": seq_str
        })
        total_len += s_len

    try:
        with open(asm_fasta, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                l_str = line.strip()
                if l_str.startswith(">"):
                    if cur_h: flush_c(cur_h, cur_seq)
                    cur_h = l_str
                    cur_seq = []
                else:
                    cur_seq.append(l_str)
            if cur_h: flush_c(cur_h, cur_seq)
    except Exception as err:
        logger.warning(f"读取 FASTA 失败 ({asm_fasta}): {err}")
        return {}, []

    total_len = sum(c["length"] for c in contigs)
    safe_total_len = max(1, total_len)

    contigs.sort(key=lambda x: x["length"], reverse=True)
    for c in contigs:
        c["length_ratio"] = round((c["length"] / safe_total_len * 100.0), 1) if total_len > 0 else 0.0

    # 精准计算 N50
    half_len = total_len / 2.0
    cum_len = 0
    n50_val = 0
    for c in contigs:
        cum_len += c["length"]
        if cum_len >= half_len:
            n50_val = c["length"]
            break

    # 加权平均 GC 含量与平均测序深度
    avg_gc = round(sum(c["gc_percent"] * c["length"] for c in contigs) / safe_total_len, 2)
    avg_depth = round(sum(c["depth"] * c["length"] for c in contigs) / safe_total_len, 1)

    # 深度容错补全：若 Header 未显式包含深度，尝试从 fastp.json 过滤后碱基推算
    if avg_depth <= 0.0 and task_dir:
        for s_dir in [task_dir / "assemblerstep" / "assembly_run", task_dir / "assembly_run", task_dir]:
            fj_path = s_dir / "qc" / "fastp.json"
            if not fj_path.exists():
                fj_path = s_dir / "fastp.json"
            if fj_path.exists():
                try:
                    with open(fj_path, "r", encoding="utf-8") as fj:
                        cb = json.load(fj).get("summary", {}).get("after_filtering", {}).get("total_bases", 0)
                        if cb > 0 and total_len > 0:
                            avg_depth = round(cb / safe_total_len, 1)
                            for c in contigs:
                                if c["depth"] <= 0.0: c["depth"] = avg_depth
                            break
                except Exception:
                    pass

    stats = {
        "total_length": total_len,
        "contigs": len(contigs),
        "n50": n50_val,
        "gc_percent": avg_gc,
        "is_circular": any(c["is_circular"] for c in contigs),
        "avg_depth": avg_depth,
        "max_contig_length": contigs[0]["length"] if contigs else 0
    }
    return stats, contigs


@router.get("/result/{task_id}")
async def get_assembly_result(task_id: str):
    """获取组装结果指标与产物路径 (Manifest 与 FASTA 深度融合版)"""
    task_dir = AssemblyStorage.get_task_dir(task_id)
    if not task_dir.exists():
        return BioResponse.fail("Task directory not found")

    task = assembly_db.get_task(task_id) or {}
    
    # 定位 assembly.fasta 文件
    asm_fasta = find_assembly_fasta(task_id, task_dir)
    fasta_exists = asm_fasta is not None and asm_fasta.exists() and asm_fasta.stat().st_size > 0
    fasta_size_bytes = asm_fasta.stat().st_size if (fasta_exists and asm_fasta is not None) else 0

    stats: Dict[str, Any] = {}
    contig_list: List[Dict[str, Any]] = []

    # 1. 尝试对接 NGCS 拼接引擎生成的 assembly_manifest.json
    search_dirs = [
        task_dir / "assemblerstep" / "assembly_run",
        task_dir / "assemblerstep",
        task_dir / "assembly_run",
        task_dir,
        Path(f"E:/NGCS_Work/tasks/{task_id}")
    ]

    manifest_data = None
    for s_dir in search_dirs:
        mf_path = s_dir / "assembly_manifest.json"
        if mf_path.exists() and mf_path.stat().st_size > 0:
            try:
                with open(mf_path, "r", encoding="utf-8") as mf:
                    manifest_data = json.load(mf)
                    break
            except Exception:
                pass

    if manifest_data:
        tot_bp = manifest_data.get("total_length_bp") or manifest_data.get("total_bp", 0)
        stats = {
            "total_length": tot_bp,
            "contigs": manifest_data.get("total_contigs", 0),
            "n50": manifest_data.get("n50", 0),
            "gc_percent": manifest_data.get("gc_percent", 0.0),
            "is_circular": bool(manifest_data.get("is_circular", False)),
            "avg_depth": float(manifest_data.get("avg_depth") or 0.0),
            "max_contig_length": manifest_data.get("max_contig_length", 0)
        }
        raw_c_list = manifest_data.get("contigs", [])
        if raw_c_list:
            for c in raw_c_list:
                c_len = c.get("length", 0)
                ratio = round((c_len / float(tot_bp) * 100.0), 1) if tot_bp > 0 else 0.0
                contig_list.append({
                    "name": c.get("name"),
                    "header": f"{c.get('name')} length={c_len} depth={c.get('depth', stats['avg_depth'])}x",
                    "length": c_len,
                    "gc_percent": c.get("gc", 0.0),
                    "depth": round(float(c.get("depth") or stats["avg_depth"]), 1),
                    "is_circular": bool(c.get("circular", False)),
                    "length_ratio": ratio,
                    "sequence": c.get("sequence", "")
                })

    # 2. 互补融合与深度解析：若 Manifest 缺少 contigs 明细或缺少 N50/GC 指标，无缝解析 FASTA 补全
    need_fasta_parse = (len(contig_list) == 0 or stats.get("n50", 0) <= 0 or stats.get("gc_percent", 0.0) <= 0.0)
    if need_fasta_parse and fasta_exists and asm_fasta:
        f_stats, f_contigs = parse_assembly_fasta_metrics(asm_fasta, task_dir)
        if f_stats.get("total_length", 0) > 0:
            if len(contig_list) == 0:
                contig_list = f_contigs
            if stats.get("total_length", 0) <= 0:
                stats["total_length"] = f_stats["total_length"]
            if stats.get("contigs", 0) <= 0:
                stats["contigs"] = f_stats["contigs"]
            if stats.get("n50", 0) <= 0:
                stats["n50"] = f_stats["n50"]
            if stats.get("gc_percent", 0.0) <= 0.0:
                stats["gc_percent"] = f_stats["gc_percent"]
            if not stats.get("is_circular"):
                stats["is_circular"] = f_stats["is_circular"]
            if stats.get("avg_depth", 0.0) <= 0.0:
                stats["avg_depth"] = f_stats["avg_depth"]
            if stats.get("max_contig_length", 0) <= 0:
                stats["max_contig_length"] = f_stats["max_contig_length"]

    # 3. 排序与数据库状态同步 (安全防御：仅当解析出有效指标且非全 0 时才更新数据库)
    contig_list.sort(key=lambda x: x["length"], reverse=True)
    if stats.get("total_length", 0) > 0 and (stats.get("n50", 0) > 0 or stats.get("gc_percent", 0.0) > 0.0):
        assembly_db.update_task_metrics(
            task_id,
            total_length=int(stats["total_length"]),
            contig_count=int(stats.get("contigs", len(contig_list))),
            n50=int(stats.get("n50", 0)),
            gc_content=float(stats.get("gc_percent", 0.0)),
            is_circular=bool(stats.get("is_circular", False)),
            avg_depth=float(stats.get("avg_depth", 0.0)),
            max_contig_length=int(stats.get("max_contig_length", 0))
        )

    return BioResponse.ok({
        "task_id": task_id,
        "name": task.get("name"),
        "status": task.get("status"),
        "stats": stats,
        "contigs": contig_list,
        "fasta_exists": fasta_exists,
        "fasta_path": str(asm_fasta.resolve()) if fasta_exists and asm_fasta else None,
        "fasta_size_bytes": fasta_size_bytes,
        "created_at": task.get("created_at"),
        "updated_at": task.get("updated_at"),
        "duration_seconds": task.get("duration_seconds", 0)
    })


@router.get("/download/{task_id}")
async def download_assembly_fasta(task_id: str):
    """一键下载组装产物 FASTA"""
    task_dir = AssemblyStorage.get_task_dir(task_id)
    asm_fasta = find_assembly_fasta(task_id, task_dir)

    if not asm_fasta or not asm_fasta.exists():
        raise HTTPException(status_code=404, detail="Assembly FASTA file not found")

    task = assembly_db.get_task(task_id) or {}
    safe_name = (task.get("name") or task_id).replace(" ", "_")
    download_filename = f"{safe_name}_assembly.fasta"

    return FileResponse(
        path=str(asm_fasta),
        filename=download_filename,
        media_type="application/octet-stream"
    )


@router.get("/download/{task_id}/contig/{contig_name}")
async def download_single_contig(task_id: str, contig_name: str):
    """单独下载指定 Contig 的 FASTA 文件 (流式切片提取)"""
    task_dir = AssemblyStorage.get_task_dir(task_id)
    asm_fasta = find_assembly_fasta(task_id, task_dir)
    if not asm_fasta or not asm_fasta.exists():
        raise HTTPException(status_code=404, detail="Assembly FASTA file not found")

    task = assembly_db.get_task(task_id) or {}
    safe_task_name = (task.get("name") or task_id).replace(" ", "_")
    clean_target = contig_name.strip().lstrip(">")

    found_header = None
    seq_lines = []
    is_target = False

    with open(asm_fasta, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            if line.startswith(">"):
                if is_target:
                    break
                header_line = line.strip()
                cur_name = header_line.split()[0].lstrip(">")
                if cur_name == clean_target:
                    is_target = True
                    found_header = header_line
            elif is_target:
                seq_lines.append(line.strip())

    if not found_header:
        raise HTTPException(status_code=404, detail=f"Contig '{clean_target}' not found")

    fasta_content = f"{found_header}\n" + "\n".join(seq_lines) + "\n"
    safe_contig_name = clean_target.replace("/", "_").replace("\\", "_")
    download_filename = f"{safe_task_name}_{safe_contig_name}.fasta"

    from fastapi.responses import Response
    return Response(
        content=fasta_content.encode("utf-8"),
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": f'attachment; filename="{download_filename}"'
        }
    )


@router.post("/open-folder/{task_id}")
async def open_task_folder(task_id: str):
    """在系统资源管理器中高亮定位组装产物所在目录"""
    task_dir = AssemblyStorage.get_task_dir(task_id)
    run_dir = task_dir / "assembly_run"
    target_dir = run_dir if run_dir.exists() else task_dir
    
    # 兼容查找
    if not target_dir.exists():
        # 尝试查找 fallback 目录
        alt_dirs = list(task_dir.glob("**/assembly.fasta"))
        if alt_dirs:
            target_dir = alt_dirs[0].parent

    if not target_dir.exists():
        return BioResponse.fail("产物目录不存在")

    import subprocess
    asm_fasta = target_dir / "assembly.fasta"
    try:
        if asm_fasta.exists():
            subprocess.Popen(f'explorer /select,"{str(asm_fasta.resolve())}"', shell=True)
        else:
            subprocess.Popen(f'explorer "{str(target_dir.resolve())}"', shell=True)
        return BioResponse.ok({"message": "已打开产物目录", "path": str(target_dir)})
    except Exception as e:
        return BioResponse.fail(f"打开目录失败: {e}")


@router.post("/stop/{task_id}")
async def stop_assembly_task(task_id: str):
    """取消/终止组装任务"""
    # 1. 尝试从等待队列中剔除
    assembly_queue.remove_task_from_queue(task_id)
    # 2. 终止运行中的进程
    stopped_id = manager.stop_task(task_id)
    # 3. 广播状态
    await broadcaster.broadcast("assembly_progress", {
        "task_id": task_id,
        "step": "已由用户手动终止",
        "progress": 0,
        "status": "aborted"
    })
    return BioResponse.ok({"message": f"Task {task_id} stopped", "stopped_id": stopped_id})


@router.delete("/tasks/{task_id}")
async def delete_assembly_task(task_id: str):
    """删除拼接任务记录与物理文件"""
    assembly_queue.remove_task_from_queue(task_id)
    assembly_db.delete_task(task_id)
    
    task_dir = AssemblyStorage.get_task_dir(task_id)
    if task_dir.exists():
        import shutil
        shutil.rmtree(task_dir, ignore_errors=True)

    return BioResponse.ok(f"Task {task_id} and its files have been removed.")


@router.get("/queue")
async def get_assembly_queue_status():
    """获取当前队列状态"""
    waiting = assembly_db.get_queued_tasks()
    running = [t for t in assembly_db.get_incomplete_tasks() if t.get('status') == 'running']
    
    return BioResponse.ok({
        "running_task": running[0] if running else None,
        "waiting_count": len(waiting),
        "waiting_tasks": waiting,
        "is_busy": len(running) > 0
    })
