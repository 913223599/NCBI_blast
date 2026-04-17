
"""
api_server.py — NCBI Bio-Station 入口 (V2.0 模块化版本)
--------------------------------------------------
所有业务 REST 路由已迁移至 src/backend/routes/ 目录。
底层解析工具迁移至 src/backend/utils/blast_utils.py (含解析缓存)。
 WebSocket 广播已由 src/backend/broadcaster.py 统一管理。
"""
import asyncio
import json
import logging
import os
import sys
import re
import psutil
import time
import platform
import logging.handlers
from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

# ─── 1. 项目根目录初始化 (必须保留) ────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# ─── 2. 核心环境初始化 ───────────────────────────────
from ..workbench.models.tool_config import ToolConfig
ToolConfig.initialize_env()

# 环境变量重定向：强制将 ETE4 数据库重定向到自定义目录
os.environ["XDG_DATA_HOME"] = str(PROJECT_ROOT / "database" / "taxonomy")
os.environ["XDG_CONFIG_HOME"] = str(PROJECT_ROOT / "database" / "taxonomy")
os.environ["XDG_CACHE_HOME"] = str(PROJECT_ROOT / "database" / "taxonomy")

from .broadcaster import broadcaster
from .utils.blast_utils import parse_blast_csv, select_consensus_hit

# ─── 3. 日志配置 ────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%H:%M:%S',
    stream=sys.stdout
)
logger = logging.getLogger("api_server")

# ─── Windows asyncio 稳定性补丁 ────────────────────────
if platform.system() == "Windows":
    # 抑制 proactor_events.py 中的已知断言错误
    # 该错误是 asyncio 内部 Bug，通常不影响业务逻辑但会产生大量冗余日志
    class AsyncioAssertionFilter(logging.Filter):
        def filter(self, record):
            return "assert f is self._write_fut" not in record.getMessage()
    
    logging.getLogger("asyncio").addFilter(AsyncioAssertionFilter())
    logger.info("🔧 已应用 Windows asyncio 稳定性补丁 (日志过滤)")
    
    # ─── 信号处理加速退出 (针对 Electron 生命周期优化) ───
    import signal
    def handle_exit(sig, frame):
        logger.info(f"接收到信号 {sig}，正在强制清理 WSL 环境...")
        try:
            from src.assembly.env.wsl_manager import WSLManager
            WSLManager.shutdown_distro()
        except: pass
        sys.exit(0)
        
    signal.signal(signal.SIGTERM, handle_exit)
    signal.signal(signal.SIGINT, handle_exit)

print(">>> Python API Server Process Started", flush=True)

# ─── 资源监控 ─────────────────────────────────────────
process = psutil.Process(os.getpid())
_last_resource_log = 0
_RESOURCE_LOG_INTERVAL = 5  # 每5秒记录一次

def log_resources(force=False):
    """记录全系统的 CPU 和内存使用情况 (反映整机真实压力)"""
    global _last_resource_log
    now = time.time()
    
    if not force and (now - _last_resource_log) < _RESOURCE_LOG_INTERVAL:
        return
    
    _last_resource_log = now
    
    try:
        # 获取全系统 CPU 利用率
        sys_cpu = psutil.cpu_percent(interval=None)
        
        # 获取全系统内存状态
        vm = psutil.virtual_memory()
        used_gb = vm.used / (1024 ** 3)
        total_gb = vm.total / (1024 ** 3)
        
        # 按照用户截图格式输出
        logger.info(f"📊 硬件监控 | CPU利用率: {sys_cpu:.1f}% | 内存利用率: {used_gb:.2f} GB / {total_gb:.2f} GB")
    except Exception as e:
        logger.debug(f"资源监控失败: {e}")

# ─── 4. 生命周期管理 ────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用启动与清理钩子"""
    logger.info("Bio-Station API 启动中...")
    
    # A. 预热翻译词库 (Sqlite 缓存)
    try:
        from ..utils.translation.translation_data_manager import get_translation_data_manager
        get_translation_data_manager().preload()
    except Exception as exc:
        logger.warning(f"翻译库加载警告: {exc}")

    # B. 注册 BLAST 监听回调 (连接 Sidecar 进程)
    from ..blast.manager import get_blast_manager
    get_blast_manager().result_listeners.append(_on_blast_result)
    logger.info("BLAST 事件总线已连接")

    # B2. 初始化组装任务队列工作线程
    from .routes.assembly import execute_assembly_pipeline
    from .utils.assembly_queue import assembly_queue
    asyncio.create_task(assembly_queue.start_workers(execute_assembly_pipeline))
    logger.info("Assembly 任务队列工作线程已启动")

    # D. 初始化局域网共享功能 (始终挂载路由以支持实时开关)
    try:
        from .lan_share import LanShareManager
        from ..utils.config_manager import get_config_manager
        lan_mgr = LanShareManager(app)
        lan_mgr.setup()
        
        if get_config_manager().get_config_value("lan_share", False):
            lan_mgr.print_share_info(port=8765)
    except Exception as e:
        logger.error(f"局域网共享模块加载失败: {e}")

    yield

    # C. 退出清理
    try:
        from ..utils.translation.translation_data_manager import get_translation_data_manager
        get_translation_data_manager().prepare_shutdown()
        logger.info("资源已安全回收")
    except: pass
    
    # D. 清理数据库连接池
    try:
        from .strain_db import get_strain_db_manager
        get_strain_db_manager().cleanup()
        logger.info("StrainDB 连接池已清理")
    except: pass

    # E. 清理 WSL 运行环境 (释放内存与后台进程)
    try:
        from ..assembly.env.wsl_manager import WSLManager
        if WSLManager.is_available():
            logger.info("正在关闭 WSL (Ubuntu) 分发版以释放内存...")
            WSLManager.shutdown_distro()
    except: pass

def _on_blast_result(task_id: str, data: dict):
    """处理 BLAST 实时任务结果的回调钩子"""
    best_hit = None
    if 'csv_file' in data and os.path.exists(data['csv_file']):
        # 这里引用的是带 _result_cache 优化的全局解析器
        top_hits = parse_blast_csv(data['csv_file'], limit=50)
        best_hit = select_consensus_hit(top_hits)
        data['data'] = [best_hit] if best_hit else []

    # 全网广播数据更新消息，通知前端刷新 UI
    broadcaster.broadcast_sync("single_result_update", {"task_id": task_id, "result": data})

    # 注释自动映射逻辑
    if best_hit:
        try:
            from ..workbench.models.annotation_manager import get_annotation_manager
            identity = best_hit.get('speciesName') or best_hit.get('species') or best_hit.get('title')
            if identity:
                # 物种名学名规范化
                match = re.search(r'^([A-Z][a-z]+(?:\s+[a-z]+)?)', identity.strip())
                name = match.group(1) if match else identity.split(';')[0].strip()
                get_annotation_manager().update_annotation(
                    sequence_hash=data.get('sequence_id'),
                    last_known_id=data.get('sequence_id'),
                    blast_identity=name
                )
        except: pass

# ─── 5. 应用实例化与路由挂载 ────────────────────────────
app = FastAPI(title="NCBI Bio-Station API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 动态载入分散在各路由模块的接口
from .routes import blast, strains, dictionary, tree, settings, core, common, taxonomy, assembly

app.include_router(common.router)
app.include_router(blast.router)
app.include_router(strains.router)
app.include_router(dictionary.router)
app.include_router(tree.router)
app.include_router(settings.router)
app.include_router(taxonomy.router)
app.include_router(core.router)

# 注册基因组拼接与数据库管理路由
from .routes import assembly, database, analysis
app.include_router(assembly.router, prefix="/api")
app.include_router(database.router, prefix="/api")
app.include_router(analysis.router, prefix="/api")

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """由 broadcaster 托管的长连接通道，支持 client_id 识别"""
    client_id = websocket.query_params.get("client_id", "unknown")
    await broadcaster.connect(websocket, client_id)
    try:
        while True:
            msg = await websocket.receive_text()
            if msg == "ping":
                await websocket.send_text(json.dumps({"type": "pong"}))
    except WebSocketDisconnect:
        broadcaster.disconnect(websocket)

if __name__ == "__main__":
    import uvicorn
    # 监听 0.0.0.0 以支持局域网共享访问
    uvicorn.run(app, host="0.0.0.0", port=8765, log_level="info")
