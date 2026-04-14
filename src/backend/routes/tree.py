
import os
import re
import logging
import shutil
import zipfile
import threading
import time as _time
from datetime import datetime
from pathlib import Path
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, List, Dict
from ..broadcaster import broadcaster
from ...utils.universal_parser import UniversalParser

# 获取项目根目录 (相对于 src/backend/routes/)
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent

logger = logging.getLogger("api_server")
router = APIRouter(tags=["Phylogeny"])

# ─── 辅助函数 ─────────────────────────────────────────

def natural_sort_key(s):
    return [int(text) if text.isdigit() else text.lower() for text in re.split('([0-9]+)', s)]

def get_best_files(file_names: list[str]) -> list[str]:
    priority = {
        '.fasta': 10, '.fas': 10, '.fa': 10, '.fna': 10,
        '.seq': 8, '.txt': 5, '.ab1': 3, '.abi': 3,
        '.nwk': 1, '.newick': 1
    }
    best_map = {}
    for name in file_names:
        p = Path(name)
        stem = p.stem.lower()
        suffix = p.suffix.lower()
        prio = priority.get(suffix, 0)
        if stem not in best_map or prio > best_map[stem][0]:
            best_map[stem] = (prio, name)
    return [v[1] for v in best_map.values()]

# ─── 模型定义 ─────────────────────────────────────────

class TreeAnalyzeRequest(BaseModel):
    files: Optional[List[str]] = None
    mode: str = "standard"
    engine: str = "nj"
    msa: str = "none"
    model: str = "jc"
    bootstrap: int = 1000
    kmerSize: int = 21
    useGpu: bool = False

class TreeHistoryRequest(BaseModel):
    history: List

class RerootRequest(BaseModel):
    old_path: str
    node_id: str

class SaveSequencesRequest(BaseModel):
    content: str

class RecallRequest(BaseModel):
    source_filename: str

class TreeAddRequest(BaseModel):
    # 兼容多种前端写法：支持单路径字符串或路径列表
    path: Optional[str] = None
    paths: Optional[List[str]] = None

class DeleteFilesRequest(BaseModel):
    paths: list[str]

# ─── 核心分析流水线 ───────────────────────────────────

@router.post("/api/tree/analyze")
async def analyze_tree(req: TreeAnalyzeRequest):
    """启动进化树构建流水线 (含 TaskManager 集成)"""
    from ...workbench.pipelines.analysis_pipeline import AnalysisPipeline
    from ...workbench.wrappers.tree_archive_manager import ArchiveManager
    from ...workbench.models.tool_config import ToolConfig
    from ...workbench.models.task_manager import get_task_manager

    def worker(cancel_event=None):
        task_start = _time.time()
        try:
            workspace = (PROJECT_ROOT / "results" / "tree_workspace").resolve()
            workspace.mkdir(parents=True, exist_ok=True)
            
            found_paths = []
            if req.files:
                found_paths = [str(Path(f)) for f in req.files]
            else:
                # 核心修复：排除 .zip 和 .gz，防止 UniversalParser 重复提取已解压的文件
                for ext in ("*.fasta", "*.seq", "*.fa", "*.fna", "*.ab1", "*.abi"):
                    found_paths.extend([str(f) for f in workspace.glob(ext)])
                found_paths = get_best_files(found_paths)
            
            if not found_paths:
                broadcaster.broadcast_sync("tree_error", {"error": "工作区为空，请先上传序列"})
                return

            if cancel_event and cancel_event.is_set(): return

            # [优化] 使用专用 Job 目录管理所有过程垃圾文件，防止 results 根目录混乱
            timestamp = datetime.now().strftime("%y%m%d_%H%M%S")
            job_id = f"Tree_Job_{timestamp}"
            job_dir = (PROJECT_ROOT / "results" / "tree_workspace" / "jobs" / job_id).resolve()
            job_dir.mkdir(parents=True, exist_ok=True)
            
            merged_path = job_dir / f"{job_id}_input.fasta"
            
            sequence_count = 0
            with open(merged_path, 'w', encoding='utf-8') as tmp:
                for p_str in found_paths:
                    try:
                        # 指向通用解析模块，处理各种嵌套或压缩格式
                        for seq_info in UniversalParser.parse_iter(p_str):
                            if seq_info.get('id') and seq_info.get('sequence'):
                                tmp.write(f">{seq_info['id']}\n{seq_info['sequence']}\n")
                                sequence_count += 1
                    except Exception as e:
                        logger.error(f"Failed to extract from {p_str} using UniversalParser: {e}")
            
            if sequence_count == 0:
                broadcaster.broadcast_sync("tree_error", {"error": "未找到有效序列"})
                return

            pipeline = AnalysisPipeline()
            archiver = ArchiveManager()
            
            workflow = pipeline.run_full_pipeline(
                merged_path, 
                job_dir, # 关键：将所有中间文件限制在 Job 目录内
                method=req.mode,
                params={
                    "engine": req.engine, "msa": req.msa, "model": req.model,
                    "bootstrap": req.bootstrap, "k": req.kmerSize, "use_gpu": req.useGpu
                }
            )
            
            final_result = {}
            for step_data in workflow:
                if cancel_event and cancel_event.is_set():
                    broadcaster.broadcast_sync("tree_error", {"error": "任务已取消"})
                    return
                step_data["elapsed"] = round(_time.time() - task_start, 2)
                broadcaster.broadcast_sync("tree_progress", step_data)
                if "result" in step_data: final_result = step_data["result"]
            
            # 归档归纳
            res_files = {k: final_result[k] for k in ["tree_file", "manifest_file"] if k in final_result}
            archive_dir = archiver.create_session_archive(merged_path, res_files, job_id)
            
            tree_content = ""
            if "tree_file" in res_files:
                tree_content = Path(res_files["tree_file"]).read_text(encoding='utf-8', errors='ignore')

            broadcaster.broadcast_sync("tree_finished", {
                "tree_file_content": tree_content,
                "tree_file": str(res_files.get("tree_file", "")),
                "algorithm": f"{req.msa.upper()} / {req.engine.upper()} ({req.model.upper()})",
                "source": str(archive_dir.relative_to(PROJECT_ROOT / "results")),
                "id_to_hash": final_result.get("id_to_hash", {}),
                "elapsed": round(_time.time() - task_start, 2),
            })
            
        except Exception as e:
            logger.error(f"Tree worker error: {e}", exc_info=True)
            broadcaster.broadcast_sync("tree_error", {"error": str(e)})

    task_mgr = get_task_manager()
    if task_mgr.get_active_tasks("tree_analysis"):
        return {"status": "rejected", "reason": "分析任务运行中"}

    task_id = task_mgr.submit_task("tree_analysis", worker)
    return {"status": "started", "task_id": task_id}

# ─── 任务控制 ─────────────────────────────────────────

@router.get("/api/tree/task/{task_id}")
async def get_tree_task_status(task_id: str):
    from ...workbench.models.task_manager import get_task_manager
    st = get_task_manager().get_task_status(task_id)
    return {"found": st is not None, **(st or {})}

@router.post("/api/tree/task/{task_id}/cancel")
async def cancel_tree_task(task_id: str):
    from ...workbench.models.task_manager import get_task_manager
    return {"success": get_task_manager().cancel_task(task_id)}

@router.get("/api/tree/tasks")
async def list_tree_tasks():
    from ...workbench.models.task_manager import get_task_manager
    return {"tasks": get_task_manager().get_active_tasks("tree_analysis")}

# ─── 进化树操作 (Reroot, Content) ──────────────────────

@router.post("/api/tree/reroot")
async def reroot_tree(req: RerootRequest):
    from ...workbench.wrappers.tree_factory import TreeFactory
    try:
        old_path = Path(req.old_path)
        new_path = old_path.parent / f"{old_path.stem}_rerooted.nwk"
        TreeFactory().tree_reroot(old_path, req.node_id, new_path)
        return {"success": True, "newick": new_path.read_text(encoding='utf-8'), "source": old_path.name.replace('.nwk', '') + '.fasta'}
    except Exception as exc:
        return {"success": False, "error": str(exc)}

@router.get("/api/tree/content/{filename}")
async def get_tree_content(filename: str):
    path = PROJECT_ROOT / "results" / "tree_workspace" / filename
    return {"content": path.read_text(encoding='utf-8', errors='ignore') if path.exists() else ""}

# ─── 工作区管理 (Save, Recall, Delete, Clear) ──────────

@router.post("/api/tree/save_sequences")
async def save_tree_sequences(req: SaveSequencesRequest):
    try:
        workspace = (PROJECT_ROOT / "results" / "tree_workspace").resolve()
        workspace.mkdir(parents=True, exist_ok=True)
        first_header = "Station_Input"
        match = re.search(r'^>\s*(.+)', req.content, re.M)
        if match:
            first_header = "".join(c if c.isalnum() or c in (' ', '.', '_', '-') else '_' for c in match.group(1).strip()).replace(' ', '_')[:40]
        file_name = f"{first_header}_{datetime.now().strftime('%y%m%d_%H%M')}.fasta"
        (workspace / file_name).write_text(req.content, encoding="utf-8")
        return {"success": True, "file_name": file_name}
    except Exception as exc:
        return {"success": False, "error": str(exc)}

@router.post("/api/tree/recall")
async def recall_tree_sequences(req: RecallRequest):
    try:
        res_dir = (PROJECT_ROOT / "results" / "tree_results").resolve()
        ws_dir = (PROJECT_ROOT / "results" / "tree_workspace").resolve()
        potential = res_dir / req.source_filename
        if not potential.exists():
            matches = list(res_dir.rglob(req.source_filename)) or list(res_dir.rglob(f"{req.source_filename}*"))
            if not matches: return {"success": False, "error": "未找到原始文件"}
            potential = matches[0]
        pure_name = re.sub(r'^Tree_\d{8}_\d{6}_', '', potential.name)
        shutil.copy2(potential, ws_dir / pure_name)
        broadcaster.broadcast_sync("recall_result", {"success": True, "recalled_name": pure_name})
        return {"success": True, "recalled_name": pure_name}
    except Exception as exc:
        broadcaster.broadcast_sync("recall_result", {"success": False, "message": str(exc)})
        return {"success": False, "error": str(exc)}

@router.get("/api/tree/sequences")
async def list_tree_sequences():
    try:
        ws = (PROJECT_ROOT / "results" / "tree_workspace").resolve()
        files = []
        # 增加对目录内解压后文件的识别
        for ext in ("*.fasta", "*.seq", "*.fa", "*.fna", "*.nwk", "*.txt", "*.zip", "*.gz", "*.ab1", "*.abi"):
            files.extend([f.name for f in ws.glob(ext)])
        return sorted(get_best_files(list(set(files))), key=natural_sort_key)
    except Exception: return []

@router.post("/api/tree/workspace/add")
async def add_to_workspace(req: TreeAddRequest):
    """将上传后的临时文件转移/归纳到进化树工作区"""
    try:
        source_paths = req.paths if req.paths else ([req.path] if req.path else [])
        if not source_paths:
            return {"success": False, "error": "未提供有效路径"}
            
        ws_dir = (PROJECT_ROOT / "results" / "tree_workspace").resolve()
        ws_dir.mkdir(parents=True, exist_ok=True)
        
        counts = {"files": 0, "sequences": 0}
        for p_str in source_paths:
            staged_path = Path(p_str)
            if not staged_path.exists(): continue
                
            target_name = staged_path.name
            dest_file = ws_dir / target_name
            
            # 将原始文件（或是压缩包）保存到工作区
            shutil.copy2(staged_path, dest_file)
            counts["files"] += 1
            
            # 使用 UniversalParser 进行 ZIP 自动展开探测 (如果需要)
            if target_name.lower().endswith(".zip"):
                try:
                    with zipfile.ZipFile(dest_file, 'r') as zip_ref:
                        # 仅提取序列相关后缀的文件，防止污染工作区
                        valid_exts = ('.fasta', '.fas', '.fa', '.fna', '.seq', '.txt', '.ab1', '.abi', '.nwk')
                        for member in zip_ref.namelist():
                            if member.lower().endswith(valid_exts) and not member.startswith('__MACOSX'):
                                zip_ref.extract(member, ws_dir)
                except: pass

        logger.info(f"📂 [PhyloWS] 已同步进工作区: {counts['files']}个资源")
        return {"success": True, "count": counts["files"]}
    except Exception as e:
        logger.error(f"Tree workspace add error: {e}")
        return {"success": False, "error": str(e)}

@router.delete("/api/tree/workspace")
async def clear_tree_workspace():
    try:
        ws = (PROJECT_ROOT / "results" / "tree_workspace").resolve()
        if ws.exists():
            for f in ws.iterdir():
                if f.is_file(): f.unlink()
                elif f.is_dir(): shutil.rmtree(f)
        return {"success": True}
    except Exception as exc: return {"success": False, "error": str(exc)}

# ─── 历史记录 ─────────────────────────────────────────

@router.get("/api/tree/history")
async def load_tree_history():
    from ...backend.strain_db import get_strain_db_manager
    return get_strain_db_manager().load_tree_history()

@router.post("/api/tree/history")
async def save_tree_history(req: TreeHistoryRequest):
    from ...backend.strain_db import get_strain_db_manager
    success = get_strain_db_manager().save_tree_history(req.history)
    if success: await broadcaster.broadcast("data_updated", {"module": "tree"})
    return {"success": success}

@router.delete("/api/tree/history/{group_id}")
async def delete_tree_history(group_id: str, physical: bool = False):
    from ...backend.strain_db import get_strain_db_manager
    try:
        success = get_strain_db_manager().delete_tree_history_group(group_id)
        if physical:
            # 1. 清理正式归档目录
            archive_dir = (PROJECT_ROOT / "results" / "tree_results" / group_id).resolve()
            if archive_dir.exists() and archive_dir.is_dir():
                shutil.rmtree(archive_dir)
            
            # 2. 【核心优化】清理过程产生的 Job 目录（垃圾文件集中地）
            # 映射规则：group_id 包含 timestamp，找到对应 jobs 目录
            # 示例：Tree_History_240414_102214 -> Tree_Job_240414_102214
            job_id_guess = group_id.replace("Tree_History_", "Tree_Job_")
            job_dir = (PROJECT_ROOT / "results" / "tree_workspace" / "jobs" / job_id_guess).resolve()
            if job_dir.exists() and job_dir.is_dir():
                logger.info(f"🧹 清理过程垃圾文件夹: {job_dir}")
                shutil.rmtree(job_dir)
        return {"success": success}
    except Exception as exc:
        return {"success": False, "error": str(exc)}
