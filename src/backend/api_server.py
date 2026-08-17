
"""
api_server.py — NCBI Bio-Station 入口 (V2.0 模块化版本)
--------------------------------------------------
所有业务 REST 路由已迁移至 src/backend/routes/ 目录。
底层解析工具迁移至 src/backend/utils/blast_utils.py (含解析缓存)。
 WebSocket 广播已由 src/backend/broadcaster.py 统一管理。
"""
import sys
import platform
import collections

# ─── 紧急补丁：修复 Windows WMI/CMD 卡死导致的 platform 模块挂起 ───
if sys.platform.startswith("win"):
    platform.system = lambda: "Windows"
    platform.machine = lambda: "AMD64"
    platform.release = lambda: "10"
    platform.version = lambda: "10.0.19041"
    uname_result = collections.namedtuple("uname_result", ["system", "node", "release", "version", "machine", "processor"])
    platform.uname = lambda: uname_result("Windows", "Node", "10", "10.0.19041", "AMD64", "AMD64")

import asyncio
import json
import logging
import os
import re
import psutil
import time
import logging.handlers
from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

# ─── 0. Windows 控制台 UTF‑8 支持 ───────────────────────
# import sys, io
# if sys.platform.startswith("win"):
#     sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
#     sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")

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
if sys.platform.startswith("win"):
    # 抑制 proactor_events.py 中的已知断言错误
    # 该错误是 asyncio 内部 Bug，通常不影响业务逻辑但会产生大量冗余日志
    class AsyncioAssertionFilter(logging.Filter):
        def filter(self, record):
            return "assert f is self._write_fut" not in record.getMessage()
            
    class WebsocketsTransferFilter(logging.Filter):
        def filter(self, record):
            if record.exc_info:
                exc_type, exc_value, exc_tb = record.exc_info
                if isinstance(exc_value, OSError) and getattr(exc_value, 'winerror', None) == 121:
                    return False
            return True
    
    logging.getLogger("asyncio").addFilter(AsyncioAssertionFilter())
    logging.getLogger("websockets.server").addFilter(WebsocketsTransferFilter())
    logging.getLogger("websockets.protocol").addFilter(WebsocketsTransferFilter())
    logger.info("[Config] 已应用 Windows asyncio 稳定性补丁 (日志过滤)")
    
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

    # B. 强制启动 BLAST 引擎 (防止冷启动导致的鉴定任务无响应)
    try:
        from ..blast.manager import get_blast_manager
        mgr = get_blast_manager()
        mgr.result_listeners.append(_on_blast_result)
        logger.info("🚀 BLAST 引擎与事件总线已全速激活")
    except Exception as eb:
        logger.error(f"BLAST 引擎启动失败: {eb}")

    # B2. 初始化组装任务队列工作线程 (持久化串行队列)
    from .routes.assembly import execute_assembly_pipeline
    from .utils.persistent_queue import persistent_queue
    asyncio.create_task(persistent_queue.start_workers(execute_assembly_pipeline))
    logger.info("🚀 Assembly 持久化串行队列引擎已启动 (max_workers=1)")

    # D. 打印局域网共享地址与初始化 WSL 环境
    try:
        from .lan_share import LanShareManager
        from ..utils.config_manager import get_config_manager
        lan_mgr = LanShareManager(app)
        if get_config_manager().get_config_value("lan_share", False):
            lan_mgr.print_share_info(port=8765)
            
        # 🔗 核心增强：预热 WSL 软链接 (解决 Windows 目录带空格导致的分析失败)
        from src.assembly.env.wsl_manager import WSLManager
        if WSLManager.is_available():
            WSLManager.ensure_project_link()
            logger.info("WSL 项目软链接已准备就绪")
    except Exception as e:
        logger.error(f"WSL/局域网共享初始化失败: {e}")

    yield

    # C. 退出清理
    try:
        from ..utils.translation.translation_data_manager import get_translation_data_manager
        get_translation_data_manager().prepare_shutdown()
        logger.info("资源已安全回收")
    except Exception as e:
        logger.warning(f"翻译库关闭失败: {e}")
    
    # D. 清理数据库连接池
    try:
        from .strain_db import get_strain_db_manager
        get_strain_db_manager().cleanup()
        logger.info("StrainDB 连接池已清理")
    except Exception as e:
        logger.warning(f"StrainDB 清理失败: {e}")

    # E. 清理 WSL 运行环境 (释放内存与后台进程)
    try:
        from ..assembly.env.wsl_manager import WSLManager
        if WSLManager.is_available():
            logger.info("正在关闭 WSL (Ubuntu) 分发版以释放内存...")
            WSLManager.shutdown_distro()
    except Exception as e:
        logger.warning(f"WSL 关闭失败: {e}")

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
                seq_id = data.get('sequence_id', '')
                get_annotation_manager().update_annotation(
                    sequence_hash=str(seq_id),
                    last_known_id=str(seq_id),
                    blast_identity=name
                )
        except Exception as cb_e:
            logger.debug(f"标注回调失败 (skip): {cb_e}")

# ─── 5. 应用实例化与路由挂载 ────────────────────────────
app = FastAPI(title="NCBI Bio-Station API", lifespan=lifespan)

# 初始化局域网共享管理 (暂不 setup，等待业务路由注册完成)
lan_mgr = None
try:
    from .lan_share import LanShareManager
    lan_mgr = LanShareManager(app)
except Exception as e:
    logger.error(f"局域网共享模块初始化失败: {e}")

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
from .routes import assembly, database, analysis, annotation, protein_compare
app.include_router(assembly.router, prefix="/api")
app.include_router(database.router, prefix="/api")
app.include_router(analysis.router, prefix="/api")
app.include_router(annotation.router, prefix="/api")
app.include_router(protein_compare.router)


# 最后：启动局域网共享路由 (确保通配符路由 /{full_path} 不会屏蔽业务 API)
try:
    if lan_mgr is not None:
        lan_mgr.setup()
        logger.info("局域网共享路由已挂载 (位于业务路由之后)")
except Exception as e:
    logger.error(f"局域网共享路由延迟加载失败: {e}")

# 🎉 开放组装与报告产物的静态资源展示
from fastapi.staticfiles import StaticFiles
results_dir = PROJECT_ROOT / "results"
results_dir.mkdir(parents=True, exist_ok=True)
app.mount("/static_results", StaticFiles(directory=str(results_dir)), name="results")

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
    except Exception as e:
        logger.debug(f"WebSocket 异常断开 (ID={client_id}): {e}")
        broadcaster.disconnect(websocket)

def start_server(host="0.0.0.0", port=8765):
    """启动 FastAPI 后端服务"""
    import uvicorn
    # 监听 host 以支持局域网共享访问
    logger.info(f"🚀 正在启动 API 服务器: http://{host}:{port}")
    uvicorn.run(app, host=host, port=port, log_level="info")

if __name__ == "__main__":
    start_server()
