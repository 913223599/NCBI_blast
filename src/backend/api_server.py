# -*- coding: utf-8 -*-
"""
api_server.py — NCBI Bio-Station 入口 (V2.0 模块化版本)
--------------------------------------------------
所有业务 REST 路由已迁移至 src/backend/routes/ 目录。
底层解析工具迁移至 src/backend/utils/blast_utils.py (含解析缓存)。
 WebSocket 广播已由 src/backend/broadcaster.py 统一管理。
"""
import asyncio
import collections
import json
import logging
import logging.handlers
import os
import platform
import re
import signal
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

_platform_patched = False
_asyncio_filters_installed = False
_runtime_hooks_installed = False


def _apply_windows_platform_patch() -> None:
    """幂等补丁：修复 Windows WMI/CMD 卡死导致的 platform 模块挂起。"""
    global _platform_patched
    if _platform_patched or not sys.platform.startswith("win"):
        return
    platform.system = lambda: "Windows"
    platform.machine = lambda: "AMD64"
    platform.release = lambda: "10"
    platform.version = lambda: "10.0.19041"
    uname_result = collections.namedtuple(
        "uname_result", ["system", "node", "release", "version", "machine", "processor"]
    )
    platform.uname = lambda: uname_result("Windows", "Node", "10", "10.0.19041", "AMD64", "AMD64")  # type: ignore
    _platform_patched = True


_apply_windows_platform_patch()

# ─── 1. 项目根目录初始化 (必须保留) ────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# ─── 2. 核心环境初始化 ───────────────────────────────
from ..workbench.models.tool_config import ToolConfig  # noqa: E402
ToolConfig.initialize_env()

# 环境变量重定向：强制将 ETE4 数据库重定向到自定义目录
os.environ["XDG_DATA_HOME"] = str(PROJECT_ROOT / "database" / "taxonomy")
os.environ["XDG_CONFIG_HOME"] = str(PROJECT_ROOT / "database" / "taxonomy")
os.environ["XDG_CACHE_HOME"] = str(PROJECT_ROOT / "database" / "taxonomy")

from .broadcaster import broadcaster  # noqa: E402
from .utils.access_log_filter import (  # noqa: E402
    install_uvicorn_access_filter,
    silence_noisy_third_party_loggers,
)
from .utils.blast_utils import parse_blast_csv, select_consensus_hit  # noqa: E402

# ─── 3. 日志配置 ────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%H:%M:%S',
    stream=sys.stdout
)
logger = logging.getLogger("api_server")
install_uvicorn_access_filter()
silence_noisy_third_party_loggers()


def _install_windows_asyncio_log_filters() -> None:
    """幂等安装 Windows asyncio/websockets 已知噪音日志过滤器。"""
    global _asyncio_filters_installed
    if _asyncio_filters_installed or not sys.platform.startswith("win"):
        return

    class AsyncioAssertionFilter(logging.Filter):
        def filter(self, record):
            return "assert f is self._write_fut" not in record.getMessage()

    class WebsocketsTransferFilter(logging.Filter):
        def filter(self, record):
            if record.exc_info:
                _, exc_value, _ = record.exc_info
                if isinstance(exc_value, OSError) and getattr(exc_value, 'winerror', None) == 121:
                    return False
            return True

    logging.getLogger("asyncio").addFilter(AsyncioAssertionFilter())
    logging.getLogger("websockets.server").addFilter(WebsocketsTransferFilter())
    logging.getLogger("websockets.protocol").addFilter(WebsocketsTransferFilter())
    _asyncio_filters_installed = True


def install_process_runtime_hooks() -> None:
    """
    显式安装服务端运行时钩子（信号处理、Windows asyncio 过滤器与进程启动标记）。
    仅在真正启动服务时调用，避免单纯 import api_server 时污染 stdout 或劫持调用方信号。
    """
    global _runtime_hooks_installed
    _apply_windows_platform_patch()
    _install_windows_asyncio_log_filters()
    if _runtime_hooks_installed:
        return
    if sys.platform.startswith("win"):
        def handle_exit(sig, _frame):
            logger.info(f"接收到信号 {sig}，正在强制清理 WSL 环境...")
            try:
                from src.assembly.env.wsl_manager import WSLManager
                WSLManager.shutdown_distro()
            except Exception as _exc:
                logger.debug("handle_exit 忽略非致命异常: %s", _exc)
            sys.exit(0)

        signal.signal(signal.SIGTERM, handle_exit)
        signal.signal(signal.SIGINT, handle_exit)
        logger.info("[Config] 已应用 Windows asyncio 稳定性补丁与退出信号钩子")

    logger.info(">>> Python API Server Process Ready")
    _runtime_hooks_installed = True

# ─── 资源监控 (已模块化抽离至 src/utils/system_monitor.py) ──
from ..utils.system_monitor import log_resources  # noqa: E402, F401

# ─── 4. 生命周期管理 ────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用启动与清理钩子"""
    install_uvicorn_access_filter()
    silence_noisy_third_party_loggers()
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
        logger.info("[INIT] BLAST 引擎与事件总线已全速激活")
    except Exception as eb:
        logger.error(f"BLAST 引擎启动失败: {eb}")

    # 托管后台异步任务引用，防止被 GC 静默回收并在退出时优雅取消
    bg_tasks: set[asyncio.Task] = set()

    def _spawn_bg_task(coro, label: str):
        task = asyncio.create_task(coro)
        bg_tasks.add(task)
        task.add_done_callback(bg_tasks.discard)
        logger.debug(f"[INIT] 已托管后台任务: {label}")
        return task

    app.state.bg_tasks = bg_tasks

    # B2. 初始化组装任务队列工作线程 (持久化串行队列)
    from .routes.assembly import execute_assembly_pipeline
    from .utils.persistent_queue import persistent_queue
    _spawn_bg_task(persistent_queue.start_workers(execute_assembly_pipeline), "assembly_queue")
    logger.info("Assembly 持久化串行队列引擎已启动 (max_workers=1)")

    # B3. 初始化功能注释任务队列调度工作者
    try:
        from src.analysis.annotation.manager import get_annotation_manager
        _spawn_bg_task(get_annotation_manager().initialize_queue_worker(), "annotation_queue")
        logger.info("[INIT] Annotation 持久化任务队列引擎已启动 (max_workers=1)")
    except Exception as ea:
        logger.error(f"Annotation 队列引擎启动失败: {ea}")

    # B4. 初始化前噬菌体发现 (V4.2) 队列调度工作者
    try:
        from src.analysis.phage_finder.manager import get_phage_discovery_manager
        _spawn_bg_task(get_phage_discovery_manager().initialize_queue_worker(), "phage_discovery_queue")
        logger.info("[INIT] PhageDiscovery (V4.2) 队列引擎已启动 (max_workers=1)")
    except Exception as ep:
        logger.error(f"PhageDiscovery 队列引擎启动失败: {ep}")

    # B5. 初始化噬菌体结构与尾部形态预测队列调度工作者
    try:
        from src.analysis.phage_structure.manager import get_phage_structure_manager
        _spawn_bg_task(get_phage_structure_manager().initialize_queue_worker(), "phage_structure_queue")
        logger.info("[INIT] PhageStructure 结构预测队列引擎已启动 (max_workers=1)")
    except Exception as eps:
        logger.error(f"PhageStructure 队列引擎启动失败: {eps}")

    # D. 打印局域网共享地址与初始化 WSL 环境
    try:
        from .lan_share import LanShareManager
        from ..utils.config_manager import get_config_manager
        lan_mgr = LanShareManager(app)
        if get_config_manager().get_config_value("lan_share", False):
            lan_mgr.print_share_info(port=8765)
            
        # 核心增强：预热 WSL 软链接 (解决 Windows 目录带空格导致的分析失败)
        from src.assembly.env.wsl_manager import WSLManager
        if WSLManager.is_available():
            WSLManager.ensure_project_link()
            logger.info("WSL 项目软链接已准备就绪")
    except Exception as e:
        logger.error(f"WSL/局域网共享初始化失败: {e}")

    # E. 无头浏览器配置启动检查与非阻塞自修复
    try:
        from starlette.concurrency import run_in_threadpool
        from src.utils.headless_browser_manager import (
            heal_headless_browser_config,
            inspect_headless_browser,
            repair_headless_browser,
        )

        hb_cfg_res = heal_headless_browser_config(project_root=PROJECT_ROOT)
        for act in hb_cfg_res.get("actions", []):
            logger.info(f"[HeadlessBrowser] 配置自愈: {act}")
        for warn in hb_cfg_res.get("warnings", []):
            logger.warning(f"[HeadlessBrowser] 配置警告: {warn}")

        hb_state = inspect_headless_browser(project_root=PROJECT_ROOT, probe_launch=False)
        eff_dir = str(hb_state.get("effective_browsers_path") or "")
        if eff_dir and Path(eff_dir).is_dir():
            os.environ["PLAYWRIGHT_BROWSERS_PATH"] = eff_dir

        if hb_state.get("ready"):
            logger.info(
                "[HeadlessBrowser] 无头浏览器启动检查通过 (模式: %s, 版本: %s)",
                hb_state.get("mode"),
                hb_state.get("expected_version") or hb_state.get("playwright_version") or "-",
            )
        elif hb_state.get("enabled", True):
            logger.warning(
                "[HeadlessBrowser] 检测到无头浏览器未就绪，已调度后台非阻塞自修复..."
            )

            async def _bg_heal_browser():
                try:
                    rep = await run_in_threadpool(
                        repair_headless_browser,
                        PROJECT_ROOT,
                        None,
                        auto_install=None,
                        probe_launch=True,
                    )
                    if rep.get("ready"):
                        logger.info(
                            "[HeadlessBrowser] 后台自修复完成 (模式: %s)",
                            rep.get("mode"),
                        )
                    else:
                        logger.warning(
                            "[HeadlessBrowser] 后台自修复未完全就绪: %s",
                            rep.get("warnings") or rep.get("issues"),
                        )
                    await broadcaster.broadcast("data_updated", {"module": "browser_env"})
                except Exception as exc_bg:
                    logger.error(f"[HeadlessBrowser] 后台自修复异常: {exc_bg}")

            _spawn_bg_task(_bg_heal_browser(), "headless_browser_heal")
    except Exception as hb_exc:
        logger.warning(f"[HeadlessBrowser] 启动检查异常（不影响主服务启动）: {hb_exc}")

    yield

    # 取消仍在运行的后台协程，防止进程挂起
    for task in list(bg_tasks):
        if not task.done():
            task.cancel()
    if bg_tasks:
        await asyncio.gather(*bg_tasks, return_exceptions=True)
        bg_tasks.clear()

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

# ─── 5. 应用实例化与安全中间件 / 路由挂载 ────────────────
from ..utils.app_metadata import get_app_metadata as _get_app_metadata  # noqa: E402

_APP_META = _get_app_metadata()
app = FastAPI(
    title=f"{_APP_META['name']} API",
    version=_APP_META["version"],
    description=_APP_META["description"],
    lifespan=lifespan,
)

_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost", "testclient", "::ffff:127.0.0.1"})

_ALLOWED_LOCAL_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:8765",
    "http://127.0.0.1:8765",
    "null",  # Electron 生产模式 file:// 加载时的 Origin
]

# 仅放行本机回环及标准 RFC1918 私有局域网来源，拒绝公网恶意站点跨域访问
_PRIVATE_LAN_ORIGIN_REGEX = (
    r"^https?://("
    r"localhost|127\.0\.0\.1"
    r"|10\.\d{1,3}\.\d{1,3}\.\d{1,3}"
    r"|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}"
    r"|192\.168\.\d{1,3}\.\d{1,3}"
    r")(:\d+)?$"
)


def _is_lan_share_enabled() -> bool:
    try:
        from ..utils.config_manager import get_config_manager
        return bool(get_config_manager().get_config_value("lan_share", False))
    except Exception:
        return False


def _extract_client_host(scope: dict) -> str:
    client = scope.get("client")
    if isinstance(client, (tuple, list)) and client:
        return str(client[0] or "").strip().lower()
    return ""


def is_client_ip_allowed(client_host: str, lan_share_enabled: bool) -> bool:
    """当 lan_share 关闭时，仅允许本机回环地址访问 API 与静态资源。"""
    if lan_share_enabled:
        return True
    normalized = (client_host or "").strip().lower()
    if normalized in _LOOPBACK_HOSTS:
        return True
    return normalized.startswith("127.")


class LanAccessGuardMiddleware:
    """纯 ASGI 局域网访问隔离守卫（保持 0.0.0.0 动态切换，不重启服务即可生效）。"""

    def __init__(self, asgi_app):
        self.app = asgi_app

    async def __call__(self, scope, receive, send):
        scope_type = scope.get("type")
        if scope_type in {"http", "websocket"}:
            client_host = _extract_client_host(scope)
            if not is_client_ip_allowed(client_host, _is_lan_share_enabled()):
                if scope_type == "http":
                    body = json.dumps(
                        {"detail": "LAN Share is disabled. Remote access denied."},
                        ensure_ascii=False,
                    ).encode("utf-8")
                    await send({
                        "type": "http.response.start",
                        "status": 403,
                        "headers": [
                            (b"content-type", b"application/json; charset=utf-8"),
                            (b"content-length", str(len(body)).encode("ascii")),
                        ],
                    })
                    await send({"type": "http.response.body", "body": body})
                    return
                await send({"type": "websocket.close", "code": 1008})
                return
        await self.app(scope, receive, send)


# 初始化局域网共享管理 (暂不 setup，等待业务路由注册完成)
lan_mgr = None
try:
    from .lan_share import LanShareManager
    lan_mgr = LanShareManager(app)
except Exception as e:
    logger.error(f"局域网共享模块初始化失败: {e}")

class UnhandledExceptionJsonMiddleware:
    """将未捕获异常在 CORSMiddleware 内层转为标准 500 JSON，防止裸 500 丢失 CORS 响应头。"""

    def __init__(self, asgi_app):
        self.app = asgi_app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        response_started = False

        async def _guarded_send(message):
            nonlocal response_started
            if message.get("type") == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, receive, _guarded_send)
        except Exception as exc:
            if response_started:
                raise
            method = scope.get("method", "")
            path = scope.get("path", "")
            logger.exception(f"未捕获接口异常 [{method} {path}]: {exc}")
            resp = JSONResponse(
                status_code=500,
                content={"detail": f"服务器内部错误: {exc}"},
            )
            await resp(scope, receive, send)


# 遵循 FastAPI CORS 安全规范：显式白名单 + 私有网段正则，且不开启通配 credentials
app.add_middleware(UnhandledExceptionJsonMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_ALLOWED_LOCAL_ORIGINS,
    allow_origin_regex=_PRIVATE_LAN_ORIGIN_REGEX,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "X-Client-ID", "Authorization", "Accept"],
)
app.add_middleware(LanAccessGuardMiddleware)


@app.get("/api/health", tags=["Core"])
async def api_health():
    """轻量级健康检查端点，供 Electron Sidecar 快速探活。"""
    return {"status": "ok", "service": "ncbi-bio-station"}

# 动态载入分散在各路由模块的接口
from .routes import blast, strains, dictionary, phylo, figure_studio, settings, core, common, taxonomy  # noqa: E402

app.include_router(common.router)
app.include_router(blast.router)
app.include_router(strains.router)
app.include_router(dictionary.router)
app.include_router(phylo.router)
app.include_router(figure_studio.router)
app.include_router(settings.router)
app.include_router(taxonomy.router)
app.include_router(core.router)

# 注册基因组拼接与数据库管理路由
from .routes import assembly, database, analysis, annotation, phage_discovery, phage_structure, pan_genomics, sanger_trace, diversity, other_tools  # noqa: E402
app.include_router(assembly.router, prefix="/api")
app.include_router(database.router, prefix="/api")
app.include_router(analysis.router, prefix="/api")
app.include_router(annotation.router, prefix="/api")
app.include_router(phage_discovery.router, prefix="/api")
app.include_router(phage_structure.router, prefix="/api")
app.include_router(pan_genomics.router, prefix="/api")
app.include_router(sanger_trace.router)
app.include_router(diversity.router, prefix="/api")
app.include_router(other_tools.router, prefix="/api")

# 静默吸收外部第三方工具 (如 QingchiAI / 外部插件) 的轮询探测，消除控制台刷屏
@app.api_route("/api/ai/bridge/{full_path:path}", methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"])
@app.api_route("/api/ai/{full_path:path}", methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"])
@app.api_route("/api/projects", methods=["GET", "POST", "OPTIONS"])
@app.api_route("/api/prompt", methods=["GET", "POST", "OPTIONS"])
async def _silent_external_sink(full_path: str = ""):
    return {"status": "ok", "bridged": False}


# 最后：启动局域网共享路由 (确保通配符路由 /{full_path} 不会屏蔽业务 API)
try:
    if lan_mgr is not None:
        lan_mgr.setup()
        logger.info("局域网共享路由已挂载 (位于业务路由之后)")
except Exception as e:
    logger.error(f"局域网共享路由延迟加载失败: {e}")

# 开放组装与报告产物的静态资源展示
from fastapi.staticfiles import StaticFiles  # noqa: E402
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
    install_process_runtime_hooks()
    # 监听 host 以支持局域网共享访问
    logger.info(f"[START] 正在启动 API 服务器: http://{host}:{port}")
    uvicorn.run(app, host=host, port=port, log_level="info")

if __name__ == "__main__":
    start_server()
