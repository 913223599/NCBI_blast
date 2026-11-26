# -*- coding: utf-8 -*-
"""
其他功能工作台系统辅助路由子模块
职责：无头浏览器健康检查/自动自修复、宿主机本地文件资源管理器定位。
"""
import asyncio
import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, HTTPException

from ...services.other_tools.schemas import BrowserEnvRepairRequest, OpenPathRequest

system_router = APIRouter()


def _ot():
    from .. import other_tools as ot
    return ot


@system_router.get("/browser_env")
async def get_browser_env_status(probe: bool = False):
    """查询无头浏览器（Playwright Chromium / 系统浏览器兜底）健康状态与配置"""
    ot = _ot()
    report = await asyncio.to_thread(
        ot.inspect_headless_browser,
        ot.PROJECT_ROOT,
        ot.CONFIG_JSON_PATH,
        probe,
    )
    return {"status": "success", **report}


@system_router.post("/browser_env/repair")
async def repair_browser_env(req: Optional[BrowserEnvRepairRequest] = Body(default=None)):
    """更新无头浏览器配置并执行完整检查与自动自修复"""
    ot = _ot()
    params = req or BrowserEnvRepairRequest()
    patch_cfg: Dict[str, Any] = {}
    if params.enabled is not None:
        patch_cfg["enabled"] = params.enabled
    if params.headless is not None:
        patch_cfg["headless"] = params.headless
    if params.use_system_browser_fallback is not None:
        patch_cfg["use_system_browser_fallback"] = params.use_system_browser_fallback
    if params.executable_path is not None:
        patch_cfg["executable_path"] = params.executable_path
    if params.browsers_path is not None:
        patch_cfg["browsers_path"] = params.browsers_path

    def _do_repair() -> Dict[str, Any]:
        return ot.repair_headless_browser(
            project_root=ot.PROJECT_ROOT,
            config_path=ot.CONFIG_JSON_PATH,
            auto_install=params.auto_install,
            probe_launch=params.probe_launch,
            patch_config=patch_cfg or None,
        )

    report = await asyncio.to_thread(_do_repair)
    return {"status": "success", **report}


@system_router.post("/open_path")
async def open_local_path(req: OpenPathRequest):
    """在宿主机 Windows 资源管理器中打开指定目录或选中文件"""
    ot = _ot()
    target = Path(req.path)
    if not target.is_absolute():
        target = ot.PROJECT_ROOT / target
    if not target.exists():
        raise HTTPException(status_code=404, detail=f"路径不存在: {target}")

    try:
        if sys.platform.startswith("win"):
            if target.is_file():
                ot.subprocess.Popen(["explorer.exe", f"/select,{target}"])
            else:
                os.startfile(str(target))
        return {"status": "success", "path": str(target)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
