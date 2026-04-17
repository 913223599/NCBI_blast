import socket
import logging
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

logger = logging.getLogger("lan_share")

class LanShareManager:
    """
    局域网共享管理模块
    单一职责：负责将前端静态资源挂载到 FastAPI，并在局域网暴露服务入口以支持其它设备访问。
    """
    def __init__(self, app: FastAPI):
        self.app = app
        # 解析项目根目录 (src/backend/lan_share.py -> src/backend -> src -> root)
        self.project_root = Path(__file__).resolve().parent.parent.parent
        self.dist_path = self.project_root / 'src' / 'web-next' / 'dist'

    def setup(self):
        """挂载前端静态文件，实现局域网共享访问"""
        if not self.dist_path.exists():
            logger.warning(f"前端构建目录不存在，无法启用局域网共享服务: {self.dist_path}")
            return
            
        from ..utils.config_manager import get_config_manager
        
        # 1. 定义检查函数
        def is_shared():
            return get_config_manager().get_config_value("lan_share", False)

        # 2. 根请求下发 index.html 首页
        @self.app.get("/")
        async def serve_root():
            if not is_shared():
                raise HTTPException(status_code=403, detail="LAN Share is disabled")
            
            index_path = self.dist_path / "index.html"
            if index_path.exists():
                return FileResponse(
                    str(index_path), 
                    headers={"Cache-Control": "no-cache, no-store, must-revalidate"}
                )
            return {"status": "lan_share_active_but_ui_missing"}
        
        # 3. 拦截 SPA 路由
        @self.app.get("/{full_path:path}")
        async def serve_spa(full_path: str):
            if not is_shared():
                raise HTTPException(status_code=403, detail="LAN Share is disabled")
                
            if full_path.startswith("api/") or full_path.startswith("ws"):
                raise HTTPException(status_code=404, detail="API or WS Not Found")
            
            file_path = self.dist_path / full_path
            if file_path.exists() and file_path.is_file():
                return FileResponse(str(file_path))
            
            index_path = self.dist_path / "index.html"
            if index_path.exists():
                return FileResponse(str(index_path))
            raise HTTPException(status_code=404, detail="Resource Not Found")
        
        # 4. 挂载已编译静态资源 (注意：StaticFiles 挂载是底层的，通常不建议在里面做动态鉴权，但可以通过 Middleware 处理。
        # 此处我们让主路由拦截掉大部分访问即可)
        assets_path = self.dist_path / "assets"
        if assets_path.exists():
            self.app.mount("/assets", StaticFiles(directory=str(assets_path)), name="assets")

    def get_local_ips(self) -> list[str]:
        """动态探测并获取本机所有物理局域网 IP 地址"""
        ips = []
        try:
            # 获取所有网络接口信息
            hostname = socket.gethostname()
            addr_infos = socket.getaddrinfo(hostname, None)
            for info in addr_infos:
                ip = info[4][0]
                # 过滤 IPv6 和 回环地址
                if ":" not in ip and not ip.startswith("127."):
                    # 过滤常见的虚拟网段 (如 Clash 的 198.18.x.x)
                    if not ip.startswith("198.18."):
                        ips.append(ip)
            
            # 兜底方案：通过 UDP 连接尝试解析主要出口 IP
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect(("8.8.8.8", 80))
                primary_ip = s.getsockname()[0]
                if primary_ip not in ips and not primary_ip.startswith("198.18."):
                    ips.insert(0, primary_ip)
        except Exception:
            pass
        
        return list(set(ips)) if ips else ["127.0.0.1"]

    def print_share_info(self, port: int):
        """将局域网访问地址格式化打印在终端控制台上供用户获取"""
        all_ips = self.get_local_ips()
        
        logger.info("\n" + "═"*60)
        logger.info("  [LAN] 局域网共享已就绪！ (LAN Share Ready)")
        logger.info("  同网络的外部设备可通过以下地址访问此工作台：")
        for ip in all_ips:
            logger.info(f"  ->  http://{ip}:{port}")
        
        # 检查 dist 目录是否存在，给用户提醒
        if not self.dist_path.exists():
            logger.warning("  [!] 警告：检测到项目未进行 Build，局域网用户可能无法加载界面。")
            logger.warning("  请运行 `npm run build` 生成生产环境静态资源。")
            
        logger.info("═"*60 + "\n")
