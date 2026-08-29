
import os
import logging
import gc
import json
import time
import zipfile
import shutil
from pathlib import Path
from fastapi import APIRouter, HTTPException, UploadFile, File
from pydantic import BaseModel
from typing import Optional, List
from Bio.Blast import NCBIXML
from Bio import SeqIO
from ..utils.blast_utils import parse_blast_csv, select_consensus_hit

# 获取项目根目录 (相对于 src/backend/routes/)
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent

logger = logging.getLogger("api_server")
router = APIRouter(tags=["BLAST"])

# ─── 模型定义 ─────────────────────────────────────────

class BlastJobRequest(BaseModel):
    query: Optional[str] = None
    files: Optional[List[str]] = None
    program: str = "auto"
    database: str = "nt"
    evalue: float = 0.05
    hitlist_size: int = 50
    task_name: Optional[str] = None
    auto_backfill_task_id: Optional[str] = None

class RenameRequest(BaseModel):
    new_name: str

class VisDataRequest(BaseModel):
    xml_path: str
    sort_mode: Optional[str] = "evalue" 

class MakeDbRequest(BaseModel):
    input_file: str
    db_type: str  # 'nucl' or 'prot'
    title: str
    out_name: Optional[str] = None

class ProcessBlastFilesRequest(BaseModel):
    paths: List[str]

class TreeBatchBlastRequest(BaseModel):
    seq_ids: List[str]
    source_rel_path: str

# ─── 任务生命周期 ─────────────────────────────────────

@router.post("/api/blast/run")
async def run_blast_job(req: BlastJobRequest):
    from ...blast.manager import get_blast_manager
    try:
        params = req.model_dump(exclude_none=True)
        task_id = get_blast_manager().create_task(params)
        return {"status": "started", "task_id": task_id}
    except Exception as exc:
        return {"status": "error", "error": str(exc)}

@router.post("/api/blast/stop/{task_id}")
async def stop_blast(task_id: str):
    from ...blast.manager import get_blast_manager
    get_blast_manager().stop_task(task_id)
    return {"status": "stopped"}

@router.post("/api/blast/pause/{task_id}")
async def pause_blast(task_id: str):
    from ...blast.manager import get_blast_manager
    get_blast_manager().pause_task(task_id)
    return {"status": "paused"}

@router.post("/api/blast/resume/{task_id}")
async def resume_blast(task_id: str):
    from ...blast.manager import get_blast_manager
    get_blast_manager().resume_task(task_id)
    return {"status": "resumed"}

@router.get("/api/blast/status/{task_id}")
async def get_task_status(task_id: str):
    from ...blast.manager import get_blast_manager
    return get_blast_manager().get_task_status(task_id) or {}

@router.get("/api/blast/results/{task_id}")
async def get_task_results(task_id: str):
    from ...blast.manager import get_blast_manager
    results = get_blast_manager().get_task_results(task_id)
    for res in results:
        if 'csv_file' in res and os.path.exists(res['csv_file']):
            top_hits = parse_blast_csv(res['csv_file'], limit=50)
            best_hit = select_consensus_hit(top_hits)
            if best_hit:
                res['data'] = [best_hit]
                if res.get('status') == 'pending':
                    res['status'] = 'completed'
            else:
                res['data'] = []
    return results

# ─── 任务库操作 ───────────────────────────────────────

@router.get("/api/blast/tasks")
async def get_all_tasks():
    from ...blast.manager import get_blast_manager
    return get_blast_manager().list_tasks() or []

@router.post("/api/blast/clear")
async def clear_all_history():
    from ...blast.manager import get_blast_manager
    get_blast_manager().clear_history()
    gc.collect()
    return {"status": "cleared"}

@router.delete("/api/blast/task/{task_id}")
async def delete_task(task_id: str):
    from ...blast.manager import get_blast_manager
    success, failed_path = get_blast_manager().delete_task(task_id)
    return {"success": success, "failed_path": failed_path}

@router.post("/api/blast/rename/{task_id}")
async def rename_task(task_id: str, req: RenameRequest):
    from ...blast.manager import get_blast_manager
    get_blast_manager().rename_task(task_id, req.new_name)
    return {"status": "renamed"}

@router.get("/api/blast/detailed/{csv_path:path}")
async def get_detailed_results(csv_path: str):
    return parse_blast_csv(csv_path, limit=None)

# ─── 测序文件高级预处理 ───────────────────────────────

@router.post("/api/blast/process_files")
async def process_blast_files(req: ProcessBlastFilesRequest):
    """处理 BLAST 上传文件：解压缩并基于优先级去重"""
    extracted_root = PROJECT_ROOT / "results" / "extracted"
    extracted_root.mkdir(parents=True, exist_ok=True)
    session_dir = extracted_root / f"staged_{int(time.time())}_{os.getpid()}"
    session_dir.mkdir(parents=True, exist_ok=True)
    
    input_paths = []
    valid_exts = {'.fasta', '.fas', '.fa', '.seq', '.txt', '.fna', '.ab1', '.abi'}
    priority_cfg = {'.fasta': 10, '.fas': 10, '.fa': 10, '.fna': 10, '.seq': 8, '.txt': 5, '.ab1': 3, '.abi': 3}
    
    try:
        for p_str in req.paths:
            src_path = Path(p_str)
            if not src_path.exists(): continue
            if src_path.suffix.lower() == '.zip':
                with zipfile.ZipFile(src_path, 'r') as zf:
                    m_map = {}
                    for name in zf.namelist():
                        if name.endswith('/') or '__MACOSX' in name: continue
                        m_path = Path(name)
                        if m_path.suffix.lower() in valid_exts:
                            stem = m_path.stem.lower()
                            prio = priority_cfg.get(m_path.suffix.lower(), 0)
                            if stem not in m_map or prio > m_map[stem][0]:
                                m_map[stem] = (prio, name)
                    for _, (_, name) in m_map.items():
                        target = session_dir / Path(name).name
                        with zf.open(name) as s, open(target, 'wb') as t: shutil.copyfileobj(s, t)
                        input_paths.append(str(target.resolve()))
            else:
                input_paths.append(str(src_path.resolve()))
        
        final_map = {}
        for p in input_paths:
            obj = Path(p)
            stem, prio = obj.stem.lower(), priority_cfg.get(obj.suffix.lower(), 0)
            if stem not in final_map or prio > final_map[stem][0]: final_map[stem] = (prio, p)
                
        return {"success": True, "paths": [v[1] for v in final_map.values()]}
    except Exception as exc:
        return {"success": False, "error": str(exc)}

# ─── 数据库管理 ───────────────────────────────────────

@router.get("/api/blast/databases")
async def list_databases():
    from ...blast.database_manager import DatabaseManager
    from ..utils.bio_db_manager import bio_db_manager
    
    # 1. 获取用户自建数据库
    user_dbs = DatabaseManager().list_local_databases()
    
    # 2. 获取已就绪的系统级生物数据库
    bio_dbs = []
    for db in bio_db_manager.list_all_status():
        if db.get('installed'):
            bio_dbs.append({
                'name': db.get('db_id'),
                'type': 'nucl',
                'path': db.get('db_id'), # 逻辑路径
                'display_name': f"[系统库] {db.get('name')} ({db.get('version')})"
            })
            
    return user_dbs + bio_dbs

@router.post("/api/blast/database/make")
async def make_database(req: MakeDbRequest):
    from ...blast.database_manager import DatabaseManager
    s, m = DatabaseManager().make_blast_db(req.input_file, req.db_type, req.title, req.out_name)
    return {"success": s, "message": m}

@router.delete("/api/blast/database/{name}")
async def delete_database(name: str):
    from ...blast.database_manager import DatabaseManager
    return {"success": DatabaseManager().delete_database(name)}

# ─── 跨模块联动：从分析树发起比对 ───────────────────────

@router.post("/api/blast/batch_from_tree")
async def batch_blast_from_tree(req: TreeBatchBlastRequest):
    """从进化树工作区发起批量比对，自动查找原始序列"""
    from ...blast.manager import get_blast_manager
    try:
        results_dir = PROJECT_ROOT / "results" / "tree_results"
        full_path = results_dir / req.source_rel_path
        if not full_path.exists():
            matches = list(results_dir.rglob(Path(req.source_rel_path).name))
            if not matches: return {"status": "error", "error": "找不到源文件"}
            full_path = matches[0]

        target_file = full_path
        if full_path.is_dir():
            fasta_files = [f for f in full_path.rglob("*") if f.suffix.lower() in ('.fasta', '.fa', '.seq', '.txt') and "aligned" not in f.name.lower()]
            if not fasta_files: return {"status": "error", "error": "未找到原始序列"}
            target_file = fasta_files[0]

        sid_set = {sid for sid in req.seq_ids} | {sid.replace(' ', '_') for sid in req.seq_ids} | {sid.replace('_', ' ') for sid in req.seq_ids}
        queries = [f">{rec.id}\n{str(rec.seq)}" for rec in SeqIO.parse(target_file, "fasta") if rec.id.strip() in sid_set or rec.id.strip().replace('_', ' ') in sid_set]

        if not queries: return {"status": "error", "error": "未找到匹配序列"}
        
        task_id = get_blast_manager().create_task({"query": "\n".join(queries), "program": "auto", "database": "nt", "task_name": f"Identify_{len(queries)}_Seqs_From_Tree"})
        return {"status": "started", "task_id": task_id}
    except Exception as exc:
        return {"status": "error", "error": str(exc)}

# ─── 可视化 ───────────────────────────────────────────

@router.post("/api/blast/visualization/data")
async def get_visualization_data(req: VisDataRequest):
    if not os.path.exists(req.xml_path): return {"error": "XML not found"}
    try:
        with open(req.xml_path, 'r', encoding='utf-8') as f:
            records = list(NCBIXML.parse(f))
        if not records:
            return {"error": "未在比对结果中发现有效的记录"}
        record = records[0]
        hits = []
        for alignment in record.alignments:
            hit = {'title': alignment.title, 'length': alignment.length, 'hsps': [{'query_start': h.query_start, 'query_end': h.query_end, 'score': h.score, 'evalue': h.expect, 'identity': h.identities / h.align_length if h.align_length > 0 else 0} for h in alignment.hsps]}
            hits.append(hit)
        if req.sort_mode == "evalue": hits.sort(key=lambda x: min([float(h['evalue']) for h in x['hsps']] + [1.0]))
        elif req.sort_mode == "score": hits.sort(key=lambda x: max([float(h['score']) for h in x['hsps']] + [0]), reverse=True)
        return {"query_name": record.query, "query_length": record.query_length, "hits": hits[:100]}
    except Exception as e: return {"error": str(e)}
