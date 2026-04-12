# ═══════════════════════════════════════════════════
# REST 端点：进化树核心功能 (前置声明)
# ═══════════════════════════════════════════════════
"""
api_server.py — Electron Sidecar 模式的 Python API 服务器
用 FastAPI 替代 QWebChannel，暴露所有业务逻辑为 REST + WebSocket 端点。
"""
import asyncio
import json
import logging
import os
import sys
import threading
import re
import shutil
import zipfile
import time
from datetime import datetime
from contextlib import asynccontextmanager
from pathlib import Path

def natural_sort_key(s):
    """
    实现自然排序算法的 Key 函数 (例如使得 2 位于 10 之前)
    """
    return [int(text) if text.isdigit() else text.lower() for text in re.split('([0-9]+)', s)]

def get_best_files(file_names: list[str]) -> list[str]:
    """
    根据优先级对同名但不同后缀的文件进行去重。
    优先级顺序: .fasta > .seq > .ab1
    """
    priority = {
        '.fasta': 10, '.fas': 10, '.fa': 10, '.fna': 10,
        '.seq': 8,
        '.txt': 5,
        '.ab1': 3, '.abi': 3,
        '.nwk': 1, '.newick': 1
    }
    
    # stem -> (best_prio, best_name)
    best_map = {}
    for name in file_names:
        p = Path(name)
        stem = p.stem.lower()
        suffix = p.suffix.lower()
        prio = priority.get(suffix, 0)
        
        if stem not in best_map or prio > best_map[stem][0]:
            best_map[stem] = (prio, name)
            
    return [v[1] for v in best_map.values()]

# 确保项目根目录在 sys.path 中
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# ─── 核心环境初始化 ───────────────────────────────
from ..workbench.models.tool_config import ToolConfig
ToolConfig.initialize_env()

# ─── 环境变量配置 (数据重定向) ─────────────────────
# 强制 ETE4 分类学数据库存放在项目 database 目录下
os.environ["XDG_DATA_HOME"] = str(PROJECT_ROOT / "database" / "taxonomy")
os.environ["XDG_CONFIG_HOME"] = str(PROJECT_ROOT / "database" / "taxonomy")
os.environ["XDG_CACHE_HOME"] = str(PROJECT_ROOT / "database" / "taxonomy")

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List, Dict, Any

# ─── 日志 ─────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%H:%M:%S',
    stream=sys.stdout
)
logger = logging.getLogger("api_server")

# 立即打印启动日志，帮助诊断 Electron 环境下的启动问题
print(">>> Python API Server Process Started", flush=True)
logger.info("Initializing API Server environment...")

# ─── WebSocket 事件广播管理器 ─────────────────────
class EventBroadcaster:
    """管理所有 WebSocket 连接，向前端推送实时事件"""

    def __init__(self):
        self.active_connections: list[WebSocket] = []
        self._lock = threading.Lock()

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        with self._lock:
            self.active_connections.append(websocket)
        logger.info(f"WebSocket 已连接，当前连接数: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        with self._lock:
            if websocket in self.active_connections:
                self.active_connections.remove(websocket)
        logger.info(f"WebSocket 已断开，当前连接数: {len(self.active_connections)}")

    async def broadcast(self, event_type: str, data: dict):
        """向所有前端连接推送事件"""
        message = json.dumps({"type": event_type, "data": data}, ensure_ascii=False)
        disconnected = []
        for connection in self.active_connections:
            try:
                await connection.send_text(message)
            except Exception:
                disconnected.append(connection)
        for conn in disconnected:
            self.disconnect(conn)

    def broadcast_sync(self, event_type: str, data: dict):
        """从同步线程中安全推送事件（用于 BLAST worker 等回调）"""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.ensure_future(self.broadcast(event_type, data))
            else:
                loop.run_until_complete(self.broadcast(event_type, data))
        except RuntimeError:
            # 如果没有事件循环（从非 asyncio 线程调用），创建新的
            asyncio.run(self.broadcast(event_type, data))


broadcaster = EventBroadcaster()

# ─── 生命周期管理 ──────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用启动/关闭时初始化/清理资源"""
    # 启动时：预热翻译库
    logger.info("API Server 启动中...")
    try:
        from ..utils.translation.translation_data_manager import get_translation_data_manager
        mgr = get_translation_data_manager()
        mgr.preload()
        logger.info("翻译词库预热完成")
    except Exception as exc:
        logger.warning(f"词库预加载失败: {exc}")

    # 初始化 BLAST Manager 并注册实时推送回调
    from ..blast.manager import get_blast_manager
    blast_mgr = get_blast_manager()
    blast_mgr.result_listeners.append(_on_blast_result)
    logger.info("BLAST Manager 已初始化")

    yield

    # 关闭时：同步翻译数据库
    try:
        from ..utils.translation.translation_data_manager import get_translation_data_manager
        get_translation_data_manager().prepare_shutdown()
        logger.info("翻译数据库已安全关闭")
    except Exception as exc:
        logger.error(f"关闭翻译数据库失败: {exc}")


def _on_blast_result(task_id: str, data: dict):
    """BLAST 实时结果回调 → WebSocket 推送"""
    import re
    from collections import Counter

    best_hit = None
    if 'csv_file' in data and os.path.exists(data['csv_file']):
        top_hits = _parse_blast_csv(data['csv_file'], limit=50)
        best_hit = _select_consensus_hit(top_hits)
        data['data'] = [best_hit] if best_hit else []

    broadcaster.broadcast_sync("single_result_update", {
        "task_id": task_id,
        "result": data
    })

    # 同步到 Annotation Manager
    if best_hit:
        try:
            from ..workbench.models.annotation_manager import get_annotation_manager
            identity = best_hit.get('speciesName') or best_hit.get('species') or best_hit.get('title')
            if identity:
                match = re.search(r'^([A-Z][a-z]+(?:\s+[a-z]+)?)', identity.strip())
                if match:
                    identity = match.group(1)
                else:
                    identity = identity.split(';')[0].split(' strain')[0].split(' genome')[0].strip()
                get_annotation_manager().update_annotation(
                    sequence_hash=data.get('sequence_id'),
                    last_known_id=data.get('sequence_id'),
                    blast_identity=identity
                )
        except Exception as exc:
            logger.error(f"Failed to sync consensus annotation: {exc}")


# ─── FastAPI 应用 ──────────────────────────────────
app = FastAPI(title="NCBI Bio-Station API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── WebSocket 端点 ────────────────────────────────
@app.get("/")
async def root_health():
    return {"status": "ok", "service": "NCBI Bio-Station API"}

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await broadcaster.connect(websocket)
    try:
        while True:
            # 保持连接活跃，接收前端心跳
            msg = await websocket.receive_text()
            if msg == "ping":
                await websocket.send_text(json.dumps({"type": "pong"}))
    except WebSocketDisconnect:
        broadcaster.disconnect(websocket)


# ═══════════════════════════════════════════════════
# REST 端点：BLAST
# ═══════════════════════════════════════════════════

class BlastJobRequest(BaseModel):
    query: Optional[str] = None
    files: Optional[list[str]] = None
    program: str = "auto"
    database: str = "nt"
    evalue: float = 0.05
    hitlist_size: int = 50
    task_name: Optional[str] = None


@app.post("/api/blast/run")
async def run_blast_job(req: BlastJobRequest):
    from ..blast.manager import get_blast_manager
    try:
        params = req.model_dump(exclude_none=True)
        task_id = get_blast_manager().create_task(params)
        return {"status": "started", "task_id": task_id}
    except Exception as exc:
        return {"status": "error", "error": str(exc)}


@app.post("/api/blast/stop/{task_id}")
async def stop_blast(task_id: str):
    from ..blast.manager import get_blast_manager
    get_blast_manager().stop_task(task_id)
    return {"status": "stopped"}


@app.post("/api/blast/pause/{task_id}")
async def pause_blast(task_id: str):
    from ..blast.manager import get_blast_manager
    get_blast_manager().pause_task(task_id)
    return {"status": "paused"}


@app.post("/api/blast/resume/{task_id}")
async def resume_blast(task_id: str):
    from ..blast.manager import get_blast_manager
    get_blast_manager().resume_task(task_id)
    return {"status": "resumed"}


@app.get("/api/blast/status/{task_id}")
async def get_task_status(task_id: str):
    from ..blast.manager import get_blast_manager
    status = get_blast_manager().get_task_status(task_id)
    return status or {}


@app.get("/api/blast/results/{task_id}")
async def get_task_results(task_id: str):
    from ..blast.manager import get_blast_manager
    results = get_blast_manager().get_task_results(task_id)
    for res in results:
        if 'csv_file' in res and os.path.exists(res['csv_file']):
            top_hits = _parse_blast_csv(res['csv_file'], limit=50)
            best_hit = _select_consensus_hit(top_hits)
            if best_hit:
                res['data'] = [best_hit]
                # [FIX] 如果磁盘上已有解析成功的数据，确保状态为 completed，防止 UI 卡在 pending
                if res.get('status') == 'pending':
                    res['status'] = 'completed'
            else:
                res['data'] = []
    return results


@app.get("/api/blast/tasks")
async def get_all_tasks():
    from ..blast.manager import get_blast_manager
    return get_blast_manager().list_tasks() or []


@app.post("/api/blast/clear")
async def clear_all_history():
    from ..blast.manager import get_blast_manager
    import gc
    failed = get_blast_manager().clear_history()
    _result_cache.clear()
    gc.collect()
    return {"status": "cleared", "failed_count": len(failed) if failed else 0}


@app.delete("/api/blast/task/{task_id}")
async def delete_task(task_id: str):
    from ..blast.manager import get_blast_manager
    success, failed_path = get_blast_manager().delete_task(task_id)
    return {"success": success, "failed_path": failed_path}


class RenameRequest(BaseModel):
    new_name: str

@app.post("/api/blast/rename/{task_id}")
async def rename_task(task_id: str, req: RenameRequest):
    from ..blast.manager import get_blast_manager
    get_blast_manager().rename_task(task_id, req.new_name)
    return {"status": "renamed"}


@app.get("/api/blast/detailed/{csv_path:path}")
async def get_detailed_results(csv_path: str):
    hits = _parse_blast_csv(csv_path, limit=None)
    return hits


# ═══════════════════════════════════════════════════
# REST 端点：本地数据库管理
# ═══════════════════════════════════════════════════

@app.get("/api/blast/databases")
async def list_databases():
    from ..blast.database_manager import DatabaseManager
    mgr = DatabaseManager()
    return mgr.list_local_databases()


class MakeDbRequest(BaseModel):
    input_file: str
    db_type: str  # 'nucl' or 'prot'
    title: str
    out_name: Optional[str] = None

@app.post("/api/blast/database/make")
async def make_database(req: MakeDbRequest):
    from ..blast.database_manager import DatabaseManager
    mgr = DatabaseManager()
    success, message = mgr.make_blast_db(
        req.input_file, req.db_type, req.title, req.out_name
    )
    return {"success": success, "message": message}


@app.delete("/api/blast/database/{name}")
async def delete_database(name: str):
    from ..blast.database_manager import DatabaseManager
    mgr = DatabaseManager()
    success = mgr.delete_database(name)
    return {"success": success}


# ═══════════════════════════════════════════════════
# REST 端点：可视化数据接口
# ═══════════════════════════════════════════════════

class VisDataRequest(BaseModel):
    xml_path: str
    sort_mode: Optional[str] = "evalue" # evalue, score, start

@app.post("/api/blast/visualization/data")
async def get_visualization_data(req: VisDataRequest):
    from Bio.Blast import NCBIXML
    import os
    
    if not os.path.exists(req.xml_path):
        return {"error": f"XML file not found: {req.xml_path}"}
        
    try:
        with open(req.xml_path, 'r') as f:
            blast_records = list(NCBIXML.parse(f))
            
        if not blast_records:
            return {"error": "No BLAST records found in file"}
            
        record = blast_records[0]
        query_len = record.query_length
        query_name = record.query
        
        hits = []
        for alignment in record.alignments:
            hit_info = {
                'title': alignment.title,
                'length': alignment.length,
                'hsps': []
            }
            for hsp in alignment.hsps:
                hit_info['hsps'].append({
                    'query_start': hsp.query_start,
                    'query_end': hsp.query_end,
                    'score': hsp.score,
                    'evalue': hsp.expect,
                    'identity': hsp.identities / hsp.align_length if hsp.align_length > 0 else 0
                })
            hits.append(hit_info)
            
        # 排序逻辑 (复刻 legacy 逻辑)
        if req.sort_mode == "evalue":
            hits.sort(key=lambda x: min([float(h['evalue']) for h in x['hsps']] + [1.0]))
        elif req.sort_mode == "score":
            hits.sort(key=lambda x: max([float(h['score']) for h in x['hsps']] + [0]), reverse=True)
        elif req.sort_mode == "start":
            hits.sort(key=lambda x: min([int(h['query_start']) for h in x['hsps']] + [999999]))
            
        return {
            "query_name": query_name,
            "query_length": query_len,
            "hits": hits[:100] # 限制前100条
        }
    except Exception as e:
        return {"error": str(e)}


# ═══════════════════════════════════════════════════
# REST 端点：翻译
# ═══════════════════════════════════════════════════

class TranslateRequest(BaseModel):
    text: str
    category: str = "species"

@app.post("/api/translate/single")
async def translate_single(req: TranslateRequest):
    from ..utils.translation.biology_translator import get_global_biology_translator
    try:
        translator = get_global_biology_translator()
        result = translator.translate_text(req.text, category=req.category)
        return {"original": req.text, "translated": result}
    except Exception as exc:
        return {"original": req.text, "translated": req.text, "error": str(exc)}


class BatchTranslateRequest(BaseModel):
    texts: list[str]
    category: str = "species"

@app.post("/api/translate/batch")
async def translate_batch(req: BatchTranslateRequest):
    """批量翻译，结果通过 WebSocket 逐条推送"""
    from ..utils.translation.biology_translator import get_global_biology_translator
    try:
        translator = get_global_biology_translator()

        def worker():
            CHUNK_SIZE = 20
            chunks = [req.texts[i:i + CHUNK_SIZE] for i in range(0, len(req.texts), CHUNK_SIZE)]
            for chunk in chunks:
                try:
                    results = translator.translate_batch(chunk, category=req.category)
                    for orig, tran in results.items():
                        if tran and tran != orig:
                            broadcaster.broadcast_sync("translation_done", {
                                "original": orig, "translated": tran
                            })
                except Exception as exc:
                    logger.error(f"Batch translation chunk error: {exc}")

        threading.Thread(target=worker, daemon=True).start()
        return {"status": "started", "count": len(req.texts)}
    except Exception as exc:
        return {"status": "error", "error": str(exc)}


# ═══════════════════════════════════════════════════
# REST 端点：词典管理
# ═══════════════════════════════════════════════════

@app.get("/api/dictionary/search")
async def search_dictionary(query: str, proofread_mode: bool = False):
    from ..utils.translation.biology_translator import get_global_biology_translator
    try:
        translator = get_global_biology_translator()
        if translator.translation_data_manager:
            results = translator.translation_data_manager.search_translations(query)
        else:
            results = []
        if proofread_mode:
            results = [r for r in results if r.get('source') in ('ai', 'ai_batch')]
        return results
    except Exception as exc:
        return []


@app.get("/api/dictionary/all")
async def get_all_terms(proofread_mode: bool = False, limit: int = 2000):
    from ..utils.translation.biology_translator import get_global_biology_translator
    import sqlite3
    try:
        translator = get_global_biology_translator()
        data_mgr = translator.translation_data_manager
        if not data_mgr:
            return []
        conn = sqlite3.connect(data_mgr.db_path)
        cursor = conn.cursor()
        
        # 增加 LIMIT 防止前端处理数万条记录时卡死
        if proofread_mode:
            cursor.execute("SELECT english, chinese, category, source FROM translations WHERE source IN ('ai', 'ai_batch') ORDER BY created_at DESC LIMIT ?", (limit,))
        else:
            cursor.execute('SELECT english, chinese, category, source FROM translations ORDER BY created_at DESC LIMIT ?', (limit,))
            
        terms = [{'english': r[0], 'chinese': r[1], 'category': r[2], 'source': r[3]} for r in cursor.fetchall()]
        conn.close()
        return terms
    except Exception as exc:
        logger.error(f"Dict load error: {exc}")
        return []

@app.get("/api/dictionary/search")
async def search_dictionary(query: str, proofread_mode: bool = False):
    from ..utils.translation.biology_translator import get_global_biology_translator
    import sqlite3
    try:
        translator = get_global_biology_translator()
        data_mgr = translator.translation_data_manager
        if not data_mgr: return []
        
        conn = sqlite3.connect(data_mgr.db_path)
        cursor = conn.cursor()
        
        q = f"%{query}%"
        if proofread_mode:
            cursor.execute("SELECT english, chinese, category, source FROM translations WHERE (english LIKE ? OR chinese LIKE ?) AND source IN ('ai', 'ai_batch') ORDER BY created_at DESC LIMIT 500", (q, q))
        else:
            cursor.execute("SELECT english, chinese, category, source FROM translations WHERE (english LIKE ? OR chinese LIKE ?) ORDER BY created_at DESC LIMIT 500", (q, q))
            
        terms = [{'english': r[0], 'chinese': r[1], 'category': r[2], 'source': r[3]} for r in cursor.fetchall()]
        conn.close()
        return terms
    except Exception as exc:
        logger.error(f"Dict search error: {exc}")
        return []



class DictTermRequest(BaseModel):
    english: str
    chinese: str
    category: str = "species"

@app.post("/api/dictionary/save")
async def save_term(req: DictTermRequest):
    from ..utils.translation.biology_translator import get_global_biology_translator
    try:
        translator = get_global_biology_translator()
        success = translator.translation_data_manager.add_translation(
            req.english, req.chinese, req.category, source='manual_web')
        return {"success": success}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


@app.delete("/api/dictionary/term/{english}")
async def delete_term(english: str):
    from ..utils.translation.biology_translator import get_global_biology_translator
    import sqlite3
    try:
        translator = get_global_biology_translator()
        data_mgr = translator.translation_data_manager
        if data_mgr and data_mgr.db_path.exists():
            conn = sqlite3.connect(data_mgr.db_path)
            cursor = conn.cursor()
            cursor.execute('DELETE FROM translations WHERE english = ?', (english,))
            success = conn.total_changes > 0
            conn.commit()
            conn.close()
            if english in data_mgr._cache:
                del data_mgr._cache[english]
            return {"success": success}
        return {"success": False}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


@app.post("/api/dictionary/verify/{english}")
async def verify_term(english: str):
    from ..utils.translation.biology_translator import get_global_biology_translator
    import sqlite3
    try:
        translator = get_global_biology_translator()
        data_mgr = translator.translation_data_manager
        if data_mgr and data_mgr.db_path.exists():
            conn = sqlite3.connect(data_mgr.db_path)
            cursor = conn.cursor()
            cursor.execute("UPDATE translations SET source = 'verified' WHERE english = ?", (english,))
            success = conn.total_changes > 0
            conn.commit()
            conn.close()
            return {"success": success}
        return {"success": False}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


# (Legacy tree section removed - see modern Advanced Features section below)

# (Redundant tree endpoints removed - see Advanced Features section at the end of file)


# ═══════════════════════════════════════════════════
# REST 端点：设置
# ═══════════════════════════════════════════════════

@app.get("/api/settings/api_key/{service}")
async def get_api_key(service: str):
    from ..utils.config_manager import get_config_manager
    return {"key": get_config_manager().get_api_key(service)}


class ApiKeyRequest(BaseModel):
    key: str

@app.post("/api/settings/api_key/{service}")
async def save_api_key(service: str, req: ApiKeyRequest):
    from ..utils.config_manager import get_config_manager
    try:
        get_config_manager().set_api_key(service, req.key)
        return {"success": True}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


@app.get("/api/settings/ai_model")
async def get_ai_model():
    from ..utils.config_manager import get_config_manager
    settings = get_config_manager().get_advanced_settings()
    return {"model": settings.get("ai_model", "deepseek-r1")}


class ModelRequest(BaseModel):
    model_key: str

@app.post("/api/settings/ai_model")
async def save_ai_model(req: ModelRequest):
    from ..utils.config_manager import get_config_manager
    try:
        config = get_config_manager()
        config.set_advanced_settings({'ai_model': req.model_key})
        import src.utils.translation.biology_translator as bt
        bt._global_translator = None
        return {"success": True}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


@app.get("/api/settings/ai_models")
async def get_ai_models():
    from ..utils.config_manager import get_config_manager
    models = get_config_manager().get_supported_models()
    if isinstance(models, dict):
        return [{"key": k, "name": v} for k, v in models.items()]
    return models


class AddModelRequest(BaseModel):
    key: str
    name: str

@app.post("/api/settings/ai_models")
async def add_ai_model(req: AddModelRequest):
    from ..utils.config_manager import get_config_manager
    try:
        get_config_manager().add_supported_model(req.key, req.name)
        return {"success": True}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


@app.delete("/api/settings/ai_models/{key}")
async def delete_ai_model(key: str):
    from ..utils.config_manager import get_config_manager
    try:
        get_config_manager().remove_supported_model(key)
        return {"success": True}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


@app.get("/api/settings/ui_language")
async def get_ui_language():
    from ..utils.ui_translation_manager import get_ui_translator
    return {"language": get_ui_translator().get_language()}


@app.get("/api/settings/ui_translations")
async def get_ui_translations():
    from ..utils.ui_translation_manager import get_ui_translator
    translator = get_ui_translator()
    logger.info(f"UI 翻译请求: 语种={translator.get_language()}, 路径={translator.locales_path}")
    translator.load_all_translations()
    data = translator.get_all_translations_for_current_lang()
    logger.info(f"加载翻译完成: 键值对数量={len(data)}")
    return data


# ═══════════════════════════════════════════════════
# REST 端点：菌种库
# ═══════════════════════════════════════════════════

@app.get("/api/strain/load")
async def strain_load_all():
    from ..backend.strain_db import get_strain_db_manager
    try:
        return get_strain_db_manager().load_all_data()
    except Exception as exc:
        return {"freezers": [], "records": []}


class FreezerRequest(BaseModel):
    data: dict

@app.post("/api/strain/freezer")
async def save_freezer(req: FreezerRequest):
    from ..backend.strain_db import get_strain_db_manager
    return {"success": get_strain_db_manager().save_freezer(req.data)}


@app.delete("/api/strain/freezer/{freezer_id}")
async def delete_freezer(freezer_id: str):
    from ..backend.strain_db import get_strain_db_manager
    return {"success": get_strain_db_manager().delete_freezer(freezer_id)}


class RecordRequest(BaseModel):
    data: dict

@app.post("/api/strain/record")
async def save_record(req: RecordRequest):
    from ..backend.strain_db import get_strain_db_manager
    return {"success": get_strain_db_manager().save_record(req.data)}


@app.delete("/api/strain/record/{record_id}")
async def delete_record(record_id: str):
    from ..backend.strain_db import get_strain_db_manager
    return {"success": get_strain_db_manager().delete_record(record_id)}


@app.post("/api/strain/sys_config/codeLookup")
async def save_code_lookup(req: dict):
    from ..backend.strain_db import get_strain_db_manager
    try:
        return {"success": get_strain_db_manager().save_sys_config('codeLookup', req)}
    except Exception as exc:
        return {"success": False, "error": str(exc)}

@app.post("/api/strain/clear")
async def strain_clear_all():
    from ..backend.strain_db import get_strain_db_manager
    return {"success": get_strain_db_manager().clear_all()}


class TaxonomySyncRequest(BaseModel):
    species_name: str

@app.post("/api/taxonomy/sync")
async def sync_taxonomy(req: TaxonomySyncRequest):
    from ..utils.taxonomy_sync_service import get_taxonomy_sync_service
    try:
        res = get_taxonomy_sync_service().sync_taxonomy_from_name(req.species_name)
        return res
    except Exception as exc:
        return {"success": False, "error": str(exc)}

@app.get("/api/taxonomy/status")
async def taxonomy_status():
    """查询物种分类数据库的当前状态（文件大小、更新时间、是否正在构建等）。"""
    from ..utils.taxonomy_provider import get_taxonomy_provider
    try:
        return get_taxonomy_provider().get_status()
    except Exception as exc:
        return {"ready": False, "error": str(exc)}

@app.post("/api/taxonomy/update")
async def taxonomy_update():
    """
    触发物种分类数据库在线更新（后台线程执行）。
    默认开启 MD5 智能检查：如果远端文件未变化，自动跳过下载和编译。
    """
    from ..utils.taxonomy_provider import get_taxonomy_provider
    provider = get_taxonomy_provider()
    if provider.is_building:
        return {"success": False, "reason": "数据库正在更新中，请稍后再试。"}
    try:
        provider.start_update_process(skip_if_same=True)
        return {"success": True, "message": "已在后台启动更新（含 MD5 增量检查）。"}
    except Exception as exc:
        return {"success": False, "error": str(exc)}

@app.get("/api/taxonomy/check")
async def taxonomy_check():
    """检查 NCBI 是否有更新可用（仅比对 MD5，不下载数据）。"""
    from ..utils.taxonomy_provider import get_taxonomy_provider
    try:
        return get_taxonomy_provider().check_for_update()
    except Exception as exc:
        return {"hasUpdate": False, "error": str(exc)}


@app.get("/api/tree/history")
async def load_tree_history():
    from ..backend.strain_db import get_strain_db_manager
    return get_strain_db_manager().load_tree_history()

class TreeHistoryRequest(BaseModel):
    history: list

@app.post("/api/tree/history")
async def save_tree_history(req: TreeHistoryRequest):
    from ..backend.strain_db import get_strain_db_manager
    return {"success": get_strain_db_manager().save_tree_history(req.history)}

@app.delete("/api/tree/history/{group_id}")
async def delete_tree_history(group_id: str):
    from ..backend.strain_db import get_strain_db_manager
    return {"success": get_strain_db_manager().delete_tree_history_group(group_id)}

@app.post("/api/strain/sequence")
async def save_sequence(req: dict):
    from ..backend.sequence_db import get_sequence_db_manager
    try:
        return {"success": get_sequence_db_manager().save_sequence(req)}
    except Exception as exc:
        return {"success": False, "error": str(exc)}

@app.get("/api/strain/sequences/{sample_id}")
async def load_sequences_by_sample(sample_id: str):
    from ..backend.sequence_db import get_sequence_db_manager
    try:
        data = get_sequence_db_manager().load_sequences_by_sample(sample_id)
        return data
    except Exception as exc:
        return []

@app.get("/api/strain/sequences/search")
async def search_sequences(keyword: str):
    from ..backend.sequence_db import get_sequence_db_manager
    try:
        data = get_sequence_db_manager().search_sequences(keyword)
        return data
    except Exception as exc:
        return []

@app.delete("/api/strain/sequence/{seq_id}")
async def delete_sequence(seq_id: str):
    from ..backend.sequence_db import get_sequence_db_manager
    try:
        return {"success": get_sequence_db_manager().delete_sequence(seq_id)}
    except Exception as exc:
        return {"success": False, "error": str(exc)}



# ═══════════════════════════════════════════════════
# REST 端点：帮助 / 核心
# ═══════════════════════════════════════════════════

@app.get("/api/help/structure")
async def get_help_structure():
    from ..utils.help_manager import get_help_manager
    return get_help_manager().get_help_structure()


@app.get("/api/help/content/{topic_id}")
async def get_help_content(topic_id: str):
    from ..utils.help_manager import get_help_manager
    return {"content": get_help_manager().get_help_content(topic_id)}


@app.get("/api/core/annotations")
async def get_annotations(hashes: str):
    from ..utils.translation.biology_translator import get_global_biology_translator
    import re
    try:
        hash_list = json.loads(hashes)
        from ..workbench.models.annotation_manager import get_annotation_manager
        am = get_annotation_manager()
        mapping = am.get_annotations_by_hashes(hash_list)
        
        raw_names = []
        hash_to_raw = {}
        for h, identity in mapping.items():
            if identity:
                match = re.search(r'^([A-Z][a-z]+(?:\s+[a-z]+))', identity.strip())
                raw_name = match.group(1) if match else identity.split(';')[0].split(' strain')[0].split(' genome')[0].strip()
                raw_names.append(raw_name)
                hash_to_raw[h] = raw_name
            else:
                hash_to_raw[h] = None
                
        # 执行批量翻译
        unique_raw = list(set([n for n in raw_names if n]))
        translator = get_global_biology_translator()
        translated_map = translator.translate_batch(unique_raw, category='species')
        
        clean_mapping = {}
        for h, raw in hash_to_raw.items():
            if not raw:
                clean_mapping[h] = ""
                continue
            
            translated = translated_map.get(raw, raw)
            # 用户规则：格式化为 中文(拉丁文)
            if translated and translated != raw:
                if '(' in translated and ')' in translated:
                    clean_mapping[h] = translated
                else:
                    clean_mapping[h] = f"{translated}({raw})"
            else:
                clean_mapping[h] = raw
                
        return clean_mapping
    except Exception as exc:
        logger.error(f"Failed to get_annotations: {exc}")
        return {}


@app.post("/api/core/open_dir")
async def open_dir(path: str):
    from ..blast.manager import get_blast_manager
    get_blast_manager().open_directory(path)
    return {"status": "opened"}


# ═══════════════════════════════════════════════════
# REST 端点：进化树高级功能
# ═══════════════════════════════════════════════════

class TreeAnalyzeRequest(BaseModel):
    files: Optional[list[str]] = None
    mode: str = "standard"
    engine: str = "nj"
    msa: str = "none"
    model: str = "jc"
    bootstrap: int = 1000
    kmerSize: int = 21
    useGpu: bool = False

@app.post("/api/tree/analyze")
async def analyze_tree(req: TreeAnalyzeRequest):
    """
    启动进化树构建流水线（后台任务，线程安全）。

    Issue #1: 使用 TaskManager 替代裸 threading.Thread，
    防止多次点击启动重复任务，并支持任务追踪/取消。
    """
    from ..workbench.pipelines.analysis_pipeline import AnalysisPipeline
    from ..workbench.wrappers.tree_archive_manager import ArchiveManager
    from ..workbench.models.tool_config import ToolConfig
    from ..workbench.models.task_manager import get_task_manager

    def worker(cancel_event=None):
        # Issue #15: 性能监控 - 记录总耗时
        import time as _time
        task_start = _time.time()

        try:
            # 找到要处理的文件
            abs_workspace = (PROJECT_ROOT / "results" / "tree_workspace").resolve()
            abs_workspace.mkdir(parents=True, exist_ok=True)
            
            logger.info(f"[Tree] CWD: {os.getcwd()}")
            logger.info(f"[Tree] Absolute Workspace: {abs_workspace}")
            
            all_entries = os.listdir(abs_workspace)
            logger.info(f"[Tree] Directory entries: {all_entries}")
            
            paths = []
            if req.files:
                paths = [str(Path(f)) for f in req.files]
            else:
                # 扩大识别范围，支持压缩包和测序原始文件 (与 BLAST 对齐)
                found_paths = []
                for ext in ("*.fasta", "*.seq", "*.fa", "*.fna", "*.zip", "*.gz", "*.ab1", "*.abi"):
                    found = list(abs_workspace.glob(ext))
                    found_paths.extend([str(f) for f in found])
                
                # 关键修复：根据文件名 stem 进行去重 (优先 fasta > seq > ab1)
                paths = get_best_files(found_paths)
                logger.info(f"[Tree] Deduplicated paths: {paths}")
            
            if not paths:
                msg = f"工作区为空 (路径: {abs_workspace}), 现有文件: {len(all_entries)} 个"
                logger.warning(msg)
                broadcaster.broadcast_sync("tree_error", {"error": "工作区为空，请先上传序列并等待预处理完成"})
                return

            # Issue #1: 检查取消信号
            if cancel_event and cancel_event.is_set():
                logger.info("[Tree] Task cancelled before file merge")
                broadcaster.broadcast_sync("tree_error", {"error": "任务已取消"})
                return

            target_path = Path(paths[0])
            # 统一使用 FileHandler 提取序列 (支持 ZIP, GZ, AB1, 编码自动识别)
            from ..utils.file_handler import FileHandler
            fh = FileHandler()

            # 如果有多个文件，或者包含压缩包/ABI等需要转换的文件，统一合并并标准化为 FASTA
            # 注意：合并后的文件存放在 results 根目录，避免污染 tree_workspace (会被 glob 重复加载)
            timestamp = datetime.now().strftime("%m%d_%H%M%S")
            merge_name = f"Tree_Job_Input_{timestamp}.fasta"
            merged_path = (PROJECT_ROOT / "results" / merge_name).resolve()
            
            sequence_count = 0
            with open(merged_path, 'w', encoding='utf-8') as tmp:
                for p_str in paths:
                    try:
                        for seq_info in fh.read_fasta_file_iter(p_str):
                            sid = seq_info.get('id', 'unknown')
                            seq = seq_info.get('sequence', '')
                            if sid and seq:
                                tmp.write(f">{sid}\n{seq}\n")
                                sequence_count += 1
                    except Exception as e:
                        logger.error(f"Failed to extract from {p_str}: {e}")
            
            if sequence_count == 0:
                broadcaster.broadcast_sync("tree_error", {"error": "未能在选定文件中找到有效序列 (可能格式不符或压缩包内无序列)"})
                return
                
            target_path = merged_path

            # Issue #1: 检查取消信号（文件合并后）
            if cancel_event and cancel_event.is_set():
                logger.info("[Tree] Task cancelled after file merge")
                broadcaster.broadcast_sync("tree_error", {"error": "任务已取消"})
                return

            pipeline = AnalysisPipeline()
            archiver = ArchiveManager()
            
            workflow = pipeline.run_full_pipeline(
                target_path, 
                ToolConfig.RESULTS_DIR, 
                method=req.mode,
                params={
                    "engine": req.engine,
                    "msa": req.msa,
                    "model": req.model,
                    "bootstrap": req.bootstrap,
                    "k": req.kmerSize,
                    "use_gpu": req.useGpu
                }
            )
            
            final_result = {}
            for step_data in workflow:
                # Issue #1: 每一步检查取消信号
                if cancel_event and cancel_event.is_set():
                    logger.info("[Tree] Task cancelled during pipeline execution")
                    broadcaster.broadcast_sync("tree_error", {"error": "任务已取消"})
                    return

                # Issue #15: 在进度推送中附加阶段耗时
                step_data["elapsed"] = round(_time.time() - task_start, 2)
                # 实时推送进度
                broadcaster.broadcast_sync("tree_progress", step_data)
                if "result" in step_data:
                    final_result = step_data["result"]
            
            # 归档处理
            project_id = target_path.stem
            result_files = {}
            if "tree_file" in final_result:
                result_files["tree_file"] = final_result["tree_file"]
            if "manifest_file" in final_result:
                result_files["manifest_file"] = final_result["manifest_file"]
            
            archive_dir = archiver.create_session_archive(
                source_fasta=target_path,
                result_files=result_files,
                project_id=project_id
            )
            
            # 读取最终 Newick 内容回传
            tree_content = ""
            if "tree_file" in result_files:
                try:
                    tree_content = Path(result_files["tree_file"]).read_text(encoding='utf-8', errors='ignore')
                except Exception as e:
                    logger.error(f"Failed to read result newick: {e}")

            # 构造算法描述供历史记录显示
            algorithm = f"{req.msa.upper()} / {req.engine.upper()} ({req.model.upper()})"

            # Issue #15: 总耗时记录
            total_elapsed = round(_time.time() - task_start, 2)
            logger.info(f"[Tree] Pipeline completed in {total_elapsed}s (sequences: {sequence_count})")

            # 推送最终完成信号
            finish_payload = {
                "tree_file_content": tree_content,
                "tree_file": str(result_files.get("tree_file", "")),
                "algorithm": algorithm,
                "source": str(archive_dir.relative_to(PROJECT_ROOT / "results")),
                "id_to_hash": final_result.get("id_to_hash", {}),
                "elapsed": total_elapsed,
            }
            broadcaster.broadcast_sync("tree_finished", finish_payload)
            
        except Exception as e:
            logger.error(f"Tree worker error: {e}", exc_info=True)
            broadcaster.broadcast_sync("tree_error", {"error": str(e)})

    # Issue #1: 使用 TaskManager 替代裸线程
    task_mgr = get_task_manager()
    
    # 检查是否已有同类型任务正在运行
    active = task_mgr.get_active_tasks("tree_analysis")
    if active:
        return {
            "status": "rejected",
            "reason": "已有一个进化树分析任务正在运行中，请等待完成后再启动新任务",
            "active_task_id": active[0]["task_id"],
        }

    task_id = task_mgr.submit_task("tree_analysis", worker)
    if task_id is None:
        return {"status": "rejected", "reason": "任务提交失败，系统繁忙"}
    
    return {"status": "started", "task_id": task_id}


# Issue #10: 统一的异步任务查询接口
@app.get("/api/tree/task/{task_id}")
async def get_tree_task_status(task_id: str):
    """查询进化树分析任务的当前状态"""
    from ..workbench.models.task_manager import get_task_manager
    status = get_task_manager().get_task_status(task_id)
    if status is None:
        return {"found": False, "error": f"Task {task_id} not found"}
    return {"found": True, **status}


@app.post("/api/tree/task/{task_id}/cancel")
async def cancel_tree_task(task_id: str):
    """请求取消一个正在执行的进化树任务"""
    from ..workbench.models.task_manager import get_task_manager
    success = get_task_manager().cancel_task(task_id)
    return {"success": success}


@app.get("/api/tree/tasks")
async def list_tree_tasks():
    """列出所有活跃的进化树分析任务"""
    from ..workbench.models.task_manager import get_task_manager
    return {"tasks": get_task_manager().get_active_tasks("tree_analysis")}


class RerootRequest(BaseModel):
    old_path: str
    node_id: str

@app.post("/api/tree/reroot")
async def reroot_tree(req: RerootRequest):
    from ..workbench.wrappers.tree_factory import TreeFactory
    try:
        old_path = Path(req.old_path)
        if not old_path.exists():
            return {"success": False, "error": "文件不存在"}
            
        new_path = old_path.parent / f"{old_path.stem}_rerooted.nwk"
        factory = TreeFactory()
        factory.tree_reroot(old_path, req.node_id, new_path)
        
        with open(new_path, 'r', encoding='utf-8') as f:
            newick = f.read()
            
        return {
            "success": True, 
            "newick": newick, 
            "source": old_path.name.replace('.nwk', '') + '.fasta'
        }
    except Exception as exc:
        return {"success": False, "error": str(exc)}


@app.get("/api/tree/content/{filename}")
async def get_tree_content(filename: str):
    try:
        path = Path("results/tree_workspace") / filename
        if path.exists():
            return {"content": path.read_text(encoding='utf-8', errors='ignore')}
        return {"content": ""}
    except Exception as exc:
        return {"content": "", "error": str(exc)}

class SaveSequencesRequest(BaseModel):
    content: str

@app.post("/api/tree/save_sequences")
async def save_tree_sequences(req: SaveSequencesRequest):
    try:
        workspace = (PROJECT_ROOT / "results" / "tree_workspace").resolve()
        workspace.mkdir(parents=True, exist_ok=True)

        first_header = "Station_Input"
        match = re.search(r'^>\s*(.+)', req.content, re.M)
        if match:
            header_line = match.group(1).strip()
            first_header = "".join(
                c if c.isalnum() or c in (' ', '.', '_', '-') else '_' for c in header_line
            ).strip()
            first_header = first_header.replace(' ', '_')[:40]

        timestamp = datetime.now().strftime("%y%m%d_%H%M")
        file_name = f"{first_header}_{timestamp}.fasta"
        file_path = workspace / file_name

        logger.info(f"[Tree] Saving sequence to: {file_path} (length: {len(req.content)})")
        with open(file_path, "w", encoding="utf-8") as fobj:
            fobj.write(req.content)
            
        # 验证写入
        if file_path.exists():
            logger.info(f"[Tree] Successfully verified file existence: {file_path}")
        else:
            logger.error(f"[Tree] FILE MISSING after write: {file_path}")
            
        return {"success": True, "file_name": file_name}
    except Exception as exc:
        logger.error(f"[Tree] Save sequences error: {exc}")
        return {"success": False, "error": str(exc)}

class RecallRequest(BaseModel):
    source_filename: str

@app.post("/api/tree/recall")
async def recall_tree_sequences(req: RecallRequest):
    import shutil
    try:
        results_dir = (PROJECT_ROOT / "results" / "tree_results").resolve()
        workspace_dir = (PROJECT_ROOT / "results" / "tree_workspace").resolve()
        workspace_dir.mkdir(parents=True, exist_ok=True)

        potential_file = results_dir / req.source_filename
        if not potential_file.exists():
            matches = list(results_dir.rglob(req.source_filename))
            if not matches:
                matches = list(results_dir.rglob(f"{req.source_filename}*"))
            
            if matches:
                potential_file = matches[0]
            else:
                return {"success": False, "error": "未找到原始文件"}

        pure_name = potential_file.name
        match = re.match(r'^Tree_\d{8}_\d{6}_(.+)$', pure_name)
        if match:
            pure_name = match.group(1)

        target_path = workspace_dir / pure_name
        shutil.copy2(potential_file, target_path)
        
        # 关键补丁：通过 WebSocket 广播召回结果
        broadcaster.broadcast_sync("recall_result", {
            "success": True, 
            "message": pure_name,
            "recalled_name": pure_name
        })
        return {"success": True, "recalled_name": pure_name}
    except Exception as exc:
        broadcaster.broadcast_sync("recall_result", {
            "success": False, 
            "message": str(exc)
        })
        return {"success": False, "error": str(exc)}

@app.delete("/api/tree/archive/{rel_path:path}")
async def delete_tree_archive(rel_path: str):
    import shutil
    try:
        target = Path("results/tree_results") / rel_path
        if target.exists():
            if target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink()
            return {"success": True}
        return {"success": False, "error": "目标不存在"}
    except Exception as exc:
        return {"success": False, "error": str(exc)}

class AddWorkspaceFilesRequest(BaseModel):
    paths: list[str]

@app.post("/api/tree/workspace/add")
async def add_tree_workspace_files(req: AddWorkspaceFilesRequest):
    try:
        workspace = Path("results/tree_workspace")
        workspace.mkdir(parents=True, exist_ok=True)
        
        valid_exts = {'.fasta', '.fas', '.fa', '.seq', '.txt', '.fna', '.ab1', '.abi', '.nwk', '.newick'}
        
        for p_str in req.paths:
            src_path = Path(p_str)
            if not src_path.exists():
                 continue
            
            # 如果是压缩包，解压有效序列到工作区
            if src_path.suffix.lower() == '.zip':
                try:
                    with zipfile.ZipFile(src_path, 'r') as zf:
                        for member_name in zf.namelist():
                            if member_name.endswith('/') or '__MACOSX' in member_name:
                                continue
                            m_path = Path(member_name)
                            if m_path.suffix.lower() in valid_exts:
                                target_name = m_path.name
                                if (workspace / target_name).exists():
                                    target_name = f"{src_path.stem}_{target_name}"
                                
                                with zf.open(member_name) as source, open(workspace / target_name, 'wb') as target:
                                    shutil.copyfileobj(source, target)
                                logger.info(f"[Tree] Extracted {member_name} from zip to workspace")
                except Exception as ze:
                    logger.error(f"Failed to extract zip {src_path}: {ze}")
            else:
                shutil.copy(src_path, workspace / src_path.name)
                
        return {"success": True}
    except Exception as exc:
        logger.error(f"Add workspace files error: {exc}")
        return {"success": False, "error": str(exc)}

class ProcessBlastFilesRequest(BaseModel):
    paths: list[str]

@app.post("/api/blast/process_files")
async def process_blast_files(req: ProcessBlastFilesRequest):
    """
    处理 BLAST 上传文件：
    1. 识别并解压 ZIP 压缩包
    2. 进行文件去重（相同 stem 保留最高优先级后缀）
    3. 返回最终可用于分析的文件路径清单
    """
    extracted_root = Path("results/extracted")
    extracted_root.mkdir(parents=True, exist_ok=True)
    
    session_dir = extracted_root / f"staged_{int(time.time())}_{os.getpid()}"
    session_dir.mkdir(parents=True, exist_ok=True)
    
    input_paths = []
    valid_exts = {'.fasta', '.fas', '.fa', '.seq', '.txt', '.fna', '.ab1', '.abi'}
    
    try:
        for p_str in req.paths:
            src_path = Path(p_str)
            if not src_path.exists(): continue
            
            if src_path.suffix.lower() == '.zip':
                try:
                    with zipfile.ZipFile(src_path, 'r') as zf:
                        # 先收集 ZIP 内所有有效成员
                        members_map = {} # stem -> (priority, member_name)
                        priority_config = {
                            '.fasta': 10, '.fas': 10, '.fa': 10, '.fna': 10,
                            '.seq': 8, '.txt': 5, '.ab1': 3, '.abi': 3
                        }
                        
                        for member_name in zf.namelist():
                            if member_name.endswith('/') or '__MACOSX' in member_name: continue
                            m_path = Path(member_name)
                            suffix = m_path.suffix.lower()
                            if suffix in valid_exts:
                                stem = m_path.stem.lower()
                                prio = priority_config.get(suffix, 0)
                                if stem not in members_map or prio > members_map[stem][0]:
                                    members_map[stem] = (prio, member_name)
                        
                        # 只解压每个 stem 下优先级最高的一个
                        for _, (prio, member_name) in members_map.items():
                            m_path = Path(member_name)
                            target_path = session_dir / m_path.name
                            counter = 1
                            while target_path.exists():
                                target_path = session_dir / f"{m_path.stem}_{counter}{m_path.suffix}"
                                counter += 1
                            
                            with zf.open(member_name) as source, open(target_path, 'wb') as target:
                                shutil.copyfileobj(source, target)
                            input_paths.append(str(target_path.resolve()))
                except Exception as ze:
                    logger.error(f"Blast zip extraction failed: {ze}")
            else:
                input_paths.append(str(src_path.resolve()))
        
        # 对最终列表再次进行全局去重（针对混合上传的情况）
        final_file_map = {} # stem -> (priority, path)
        priority_cfg = {
            '.fasta': 10, '.fas': 10, '.fa': 10, '.fna': 10,
            '.seq': 8, '.txt': 5, '.ab1': 3, '.abi': 3
        }
        for p in input_paths:
            path_obj = Path(p)
            stem = path_obj.stem.lower()
            suffix = path_obj.suffix.lower()
            prio = priority_cfg.get(suffix, 0)
            if stem not in final_file_map or prio > final_file_map[stem][0]:
                final_file_map[stem] = (prio, p)
                
        return {"success": True, "paths": [v[1] for v in final_file_map.values()]}
    except Exception as exc:
        return {"success": False, "error": str(exc)}

class DeleteFilesRequest(BaseModel):
    paths: list[str]

@app.post("/api/tree/analysis/delete")
async def delete_analysis_files(req: DeleteFilesRequest):
    try:
        workspace = (PROJECT_ROOT / "results" / "tree_workspace").resolve()
        for p_str in req.paths:
            # 优先尝试绝对路径，如果是文件名则基于工作区
            target = Path(p_str)
            if not target.is_absolute():
                target = workspace / p_str
                
            if target.exists() and target.is_file():
                target.unlink()
        return {"success": True}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


@app.get("/api/tree/sequences")
async def list_tree_sequences():
    try:
        workspace = (PROJECT_ROOT / "results" / "tree_workspace").resolve()
        workspace.mkdir(parents=True, exist_ok=True)
        files = []
        # 扩展工作区可见格式
        for ext in ("*.fasta", "*.seq", "*.fa", "*.fna", "*.nwk", "*.txt", "*.zip", "*.gz", "*.ab1", "*.abi"):
            files.extend([f.name for f in workspace.glob(ext)])
        
        # 去重：同名文件只保留优先级最高的一个 (seq > ab1)
        best_files = get_best_files(list(set(files)))
        
        # 使用自然排序返回文件列表
        return sorted(best_files, key=natural_sort_key)
    except Exception:
        return []

@app.delete("/api/tree/history/{group_id}")
async def delete_tree_history(group_id: str, physical: bool = False):
    """逻辑/物理删除进化树历史记录"""
    from ..backend.strain_db import StrainDBManager
    import shutil
    try:
        logger.info(f"Deletion Request: group_id={group_id}, physical={physical}")
        db = StrainDBManager()
        success = db.delete_tree_history_group(group_id)
        
        if physical:
            # 使用绝对路径定位目录，并在删除前后确认状态
            archive_dir = (PROJECT_ROOT / "results" / "tree_results" / group_id).resolve()
            logger.info(f"Physical delete target: {archive_dir}")
            
            if archive_dir.exists() and archive_dir.is_dir():
                try:
                    shutil.rmtree(archive_dir)
                    if not archive_dir.exists():
                        logger.info(f"SUCCESS: Physically deleted directory: {group_id}")
                    else:
                        logger.warning(f"FAILURE: Directory still exists after rmtree: {group_id}")
                except Exception as rmtree_err:
                    logger.error(f"RMTREE ERROR for {group_id}: {rmtree_err}")
            else:
                logger.warning(f"SKIP: Physical target not found or not a directory: {archive_dir}")
                
        return {"success": success}
    except Exception as exc:
        logger.error(f"Failed to delete tree history: {exc}")
        return {"success": False, "error": str(exc)}

class HashQueryRequest(BaseModel):
    hashes: list[str]

@app.post("/api/translate/hashes")
async def get_annotations_by_hashes(req: HashQueryRequest):
    """根据序列 MD5 哈希批量获取语义注释 (含 AI 翻译补偿)"""
    from ..utils.translation.biology_translator import get_global_biology_translator
    import re
    try:
        from ..workbench.models.annotation_manager import get_annotation_manager
        am = get_annotation_manager()
        mapping = am.get_annotations_by_hashes(req.hashes)
        
        # 收集唯一原料名称
        raw_names = []
        hash_to_raw = {}
        for h, identity in mapping.items():
            if identity:
                # 尽量提取物种名
                match = re.search(r'^([A-Z][a-z]+(?:\s+[a-z]+))', identity.strip())
                raw = match.group(1) if match else identity.split(';')[0].split(' strain')[0].split(' genome')[0].strip()
                raw_names.append(raw)
                hash_to_raw[h] = raw
            else:
                hash_to_raw[h] = None

        # 批量翻译
        unique_raw = list(set([n for n in raw_names if n]))
        translator = get_global_biology_translator()
        translated_map = translator.translate_batch(unique_raw, category='species')
        
        results = {}
        for h, raw in hash_to_raw.items():
            if not raw:
                results[h] = ""
                continue
            
            translated = translated_map.get(raw, raw)
            # 格式化
            if translated and translated != raw:
                if '(' in translated and ')' in translated:
                    results[h] = translated
                else:
                    results[h] = f"{translated}({raw})"
            else:
                results[h] = raw
                
        return results
    except Exception as exc:
        logger.error(f"Failed to get_annotations_by_hashes: {exc}")
        return {}
    except Exception as exc:
        logger.error(f"Failed to query annotations by hashes: {exc}")
        return {}


@app.delete("/api/tree/workspace")
async def clear_tree_workspace():
    try:
        workspace = (PROJECT_ROOT / "results" / "tree_workspace").resolve()
        if workspace.exists():
            import shutil
            for fobj in workspace.iterdir():
                try:
                    if fobj.is_file():
                        os.remove(fobj)
                    elif fobj.is_dir():
                        shutil.rmtree(fobj)
                except Exception as e:
                    logger.warning(f"Failed to delete {fobj}: {e}")
        return {"success": True}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


class TreeBatchBlastRequest(BaseModel):
    seq_ids: list[str]
    source_rel_path: str

@app.post("/api/blast/batch_from_tree")
async def batch_blast_from_tree(req: TreeBatchBlastRequest):
    """从进化树工作区发起批量比对"""
    from Bio import SeqIO
    from ..blast.manager import get_blast_manager
    try:
        results_dir = Path("results/tree_results")
        full_path = results_dir / req.source_rel_path

        if not full_path.exists():
            # 尝试在结果目录下递归搜索文件名部分
            file_name = req.source_rel_path.split('/')[-1].split('\\')[-1]
            matches = list(results_dir.rglob(file_name))
            if matches:
                 full_path = matches[0]
            else:
                 return {"status": "error", "error": f"找不到源文件: {req.source_rel_path}"}

        queries = []
        # 将请求的 ID 及其可能的变体（空格转下划线等）存入集合
        seq_id_set = set()
        for sid in req.seq_ids:
            seq_id_set.add(sid)
            seq_id_set.add(sid.replace(' ', '_'))
            seq_id_set.add(sid.replace('_', ' '))

        # 如果找到的 full_path 是个文件夹（IQ-TREE 会生成文件夹），在文件夹内搜索 FASTA 文件
        target_file = full_path
        if full_path.is_dir():
            fasta_files = list(full_path.rglob("*.fasta")) + list(full_path.rglob("*.fa")) + list(full_path.rglob("*.seq")) + list(full_path.rglob("*.txt"))
            # 过滤掉包含 'aligned' 或者是临时产物的文件，尽可能选取原始序列
            fasta_files = [f for f in fasta_files if "aligned" not in f.name.lower()]
            if fasta_files:
                target_file = fasta_files[0]
            else:
                return {"status": "error", "error": f"在文件夹 {full_path.name} 的所有子目录中均未找到原始 FASTA 文件"}

        for rec in SeqIO.parse(target_file, "fasta"):
            # 同样对序列文件中的 ID 进行变体匹配
            clean_rec_id = rec.id.strip()
            if clean_rec_id in seq_id_set or clean_rec_id.replace('_', ' ') in seq_id_set:
                queries.append(f">{rec.id}\n{str(rec.seq)}")

        if not queries:
            return {"status": "error", "error": f"在文件 {target_file.name} 中未找到匹配的待比对序列。请确认源数据是否包含: {', '.join(req.seq_ids[:3])}..."}

        params = {
            "query": "\n".join(queries),
            "program": "auto",
            "database": "nt",
            "task_name": f"Identify_{len(queries)}_Seqs_From_Tree"
        }
        task_id = get_blast_manager().create_task(params)
        return {"status": "started", "task_id": task_id}
    except Exception as exc:
        logger.error(f"Batch BLAST from tree failed: {str(exc)}")
        return {"status": "error", "error": str(exc)}


# ═══════════════════════════════════════════════════
# CSV 解析工具函数
# ═══════════════════════════════════════════════════
_result_cache = {}

def _parse_blast_csv(csv_path: str, limit: int = None) -> list:
    """带缓存的 BLAST CSV 解析器"""
    import csv
    import re
    csv_path_obj = Path(csv_path)
    if not csv_path_obj.exists():
        return []

    curr_mtime = None
    if limit is None:
        curr_mtime = csv_path_obj.stat().st_mtime
        if csv_path in _result_cache:
            old_mtime, cached_data = _result_cache[csv_path]
            if curr_mtime <= old_mtime:
                return cached_data

    data = []
    try:
        with open(csv_path, 'r', encoding='utf-8-sig') as fobj:
            reader = csv.DictReader(fobj)
            count = 0
            for row in reader:
                raw_title = row.get('标题', 'Unknown')
                if '>' in raw_title:
                    raw_title = raw_title.split('>')[0].strip()
                clean_title = raw_title
                gi_match = re.match(r'^gi\|\d+\|[a-z]+\|[A-Za-z0-9_.]+\|\s*', raw_title)
                if gi_match:
                    clean_title = raw_title[gi_match.end():].strip()

                species_raw = row.get('物种', 'N/A').strip()
                species_final = species_raw
                if len(species_raw) < 4 or species_raw.lower() in ['newman', 'strain', 'str.', 'subsp.', 'aureus']:
                    match = re.search(r'([A-Z][a-z]+(?:\s+[a-z]+)?)', clean_title)
                    if match:
                        species_final = match.group(1)

                data.append({
                    'title': clean_title,
                    'len': row.get('长度', '0'),
                    'acc': row.get('访问号', 'N/A'),
                    'species': species_final,
                    'genus': row.get('属名', ''),
                    'strain': row.get('菌株', ''),
                    'evalue': row.get('E值', 'N/A'),
                    'similarity': row.get('相似度', '0%'),
                    'align_len': row.get('比对长度', '0'),
                    'query_range': row.get('查询起始-结束', ''),
                    'hit_range': row.get('命中起始-结束', '')
                })
                count += 1
                if limit and count >= limit:
                    break
        if limit is None:
            _result_cache[csv_path] = (curr_mtime, data)
            if len(_result_cache) > 10:
                first_key = next(iter(_result_cache))
                del _result_cache[first_key]
    except Exception as exc:
        logger.error(f"CSV Parse Error: {exc}")
    return data


def _select_consensus_hit(hits: list) -> dict | None:
    """共识投票选择最佳命中"""
    from collections import Counter
    if not hits:
        return None

    high_identity_hits = []
    for hit in hits:
        sim_str = str(hit.get('similarity', '0%')).replace('%', '').strip()
        try:
            if float(sim_str) >= 98.0:
                high_identity_hits.append(hit)
        except (ValueError, TypeError):
            continue

    target_hits = high_identity_hits if high_identity_hits else hits
    if len(target_hits) == 1:
        return target_hits[0]

    generic_names = {'bacterium', 'uncultured bacterium', 'uncultured organism', 'unidentified', 'unknown', 'n/a', ''}
    species_counter = Counter()
    species_to_hit = {}
    for hit in target_hits:
        species = (hit.get('species') or '').strip()
        species_lower = species.lower()
        if species_lower and species_lower not in generic_names:
            species_counter[species] += 1
            if species not in species_to_hit:
                species_to_hit[species] = hit

    if not species_counter:
        return target_hits[0]

    total_valid = sum(species_counter.values())
    top_entries = species_counter.most_common(5)
    consensus_list = []
    prob_parts = []
    for name, count in top_entries:
        pct = (count / total_valid) * 100
        prob_parts.append(f"{name}({pct:.0f}%)")
        consensus_list.append({"name": name, "pct": round(pct)})

    consensus_species = top_entries[0][0]
    best_hit = dict(species_to_hit[consensus_species])
    best_hit['species'] = ", ".join(prob_parts)
    best_hit['consensusList'] = consensus_list
    return best_hit


# ─── 服务器启动入口 ────────────────────────────────
API_PORT = 8765

# ─── 进化树与分类学增强 (ETE4 Integration) ──────────

@app.get("/api/taxonomy/lineage")
async def get_taxonomy_lineage(query: str):
    """获取物种的完整谱系信息 (从界到种)"""
    from ..utils.taxonomy_provider import get_taxonomy_provider
    try:
        provider = get_taxonomy_provider()
        return provider.get_lineage_details(query)
    except Exception as exc:
        return {"error": str(exc)}

@app.get("/api/taxonomy/descendants")
async def get_taxonomy_descendants(name: str):
    """获取指定分类层级下的所有子物种名称"""
    from ..utils.taxonomy_provider import get_taxonomy_provider
    try:
        provider = get_taxonomy_provider()
        return provider.get_descendant_names(name)
    except Exception as exc:
        return {"error": str(exc)}

@app.get("/api/strains/search_by_category")
async def search_strains_by_category(category: str):
    """
    【跨模块统一检索】
    逻辑：给定一个大的分类范畴（如"Betacoronavirus"或"Coronaviridae"）
    1. 调用 ETE4 获取该分类下所有已知的成员物种名
    2. 在本地菌毒种管理数据库中筛选出属于这些物种的样本记录
    """
    from ..utils.taxonomy_provider import get_taxonomy_provider
    from ..backend.strain_db import StrainDBManager
    
    try:
        logger.info(f"Cross-module search initiated for category: {category}")
        provider = get_taxonomy_provider()
        # 1. 获取所有子物种
        target_names = provider.get_descendant_names(category)
        
        # 2. 到菌毒种库搜索
        db = StrainDBManager()
        records = db.search_by_species_list(target_names)
        
        return {
            "category": category,
            "descendant_count": len(target_names),
            "matched_strains_count": len(records),
            "results": records
        }
    except Exception as e:
        logger.error(f"Unified search error: {e}")
        return {"error": str(e)}

if __name__ == "__main__":
    import uvicorn
    # 为了支持在 Windows 环境下的多进程或重启，cwd 必须正确
    uvicorn.run(app, host="127.0.0.1", port=8765, log_level="info")
