
import logging
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, List, Dict
from ..broadcaster import broadcaster

logger = logging.getLogger("api_server")
router = APIRouter(tags=["Settings"])

# ─── 模型定义 ─────────────────────────────────────────

class ApiKeyRequest(BaseModel):
    key: str

class ModelRequest(BaseModel):
    model_key: str

class AddModelRequest(BaseModel):
    key: str
    name: str

class LanShareRequest(BaseModel):
    enabled: bool

# ─── API Key 管理 ─────────────────────────────────────

@router.get("/api/settings/api_key/{service}")
async def get_api_key(service: str):
    from ...utils.config_manager import get_config_manager
    return {"key": get_config_manager().get_api_key(service)}

@router.post("/api/settings/api_key/{service}")
async def save_api_key(service: str, req: ApiKeyRequest):
    from ...utils.config_manager import get_config_manager
    try:
        get_config_manager().set_api_key(service, req.key)
        await broadcaster.broadcast("data_updated", {"module": "config"})
        return {"success": True}
    except Exception as exc:
        return {"success": False, "error": str(exc)}

# ─── AI 模型配置 ──────────────────────────────────────

@router.get("/api/settings/ai_model")
async def get_ai_model():
    from ...utils.config_manager import get_config_manager
    settings = get_config_manager().get_advanced_settings()
    return {"model": settings.get("ai_model", "deepseek-r1")}

@router.post("/api/settings/ai_model")
async def save_ai_model(req: ModelRequest):
    from ...utils.config_manager import get_config_manager
    try:
        config = get_config_manager()
        config.set_advanced_settings({'ai_model': req.model_key})
        # 清除全局翻译器缓存以强制应用新模型
        import src.utils.translation.biology_translator as bt
        bt._global_translator = None
        await broadcaster.broadcast("data_updated", {"module": "config"})
        return {"success": True}
    except Exception as exc:
        return {"success": False, "error": str(exc)}

@router.get("/api/settings/ai_models")
async def get_ai_models():
    from ...utils.config_manager import get_config_manager
    models = get_config_manager().get_supported_models()
    if isinstance(models, dict):
        return [{"key": k, "name": v} for k, v in models.items()]
    return models

@router.post("/api/settings/ai_models")
async def add_ai_model(req: AddModelRequest):
    from ...utils.config_manager import get_config_manager
    try:
        get_config_manager().add_supported_model(req.key, req.name)
        await broadcaster.broadcast("data_updated", {"module": "config"})
        return {"success": True}
    except Exception as exc:
        return {"success": False, "error": str(exc)}

@router.delete("/api/settings/ai_models/{key}")
async def delete_ai_model(key: str):
    from ...utils.config_manager import get_config_manager
    try:
        get_config_manager().remove_supported_model(key)
        await broadcaster.broadcast("data_updated", {"module": "config"})
        return {"success": True}
    except Exception as exc:
        return {"success": False, "error": str(exc)}

# ─── UI 与语言 ────────────────────────────────────────

@router.get("/api/settings/ui_language")
async def get_ui_language():
    from ...utils.ui_translation_manager import get_ui_translator
    return {"language": get_ui_translator().get_language()}

@router.get("/api/settings/ui_translations")
async def get_ui_translations():
    from ...utils.ui_translation_manager import get_ui_translator
    translator = get_ui_translator()
    logger.info(f"UI 翻译请求: 语种={translator.get_language()}, 路径={translator.locales_path}")
    translator.load_all_translations()
    data = translator.get_all_translations_for_current_lang()
    return data

# ─── 局域网共享模式 ────────────────────────────────────

@router.get("/api/settings/lan_share")
async def get_lan_share():
    from ...utils.config_manager import get_config_manager
    return {"enabled": get_config_manager().get_config_value("lan_share", False)}

@router.get("/api/settings/lan_info")
async def get_lan_info():
    """获取本机局域网共享的详细连接信息"""
    from ...utils.config_manager import get_config_manager
    from ..lan_share import LanShareManager
    
    # 临时创建一个 manager 实例来调用其获取 IP 的逻辑
    # 这里的 app=None 因为我们只需要调用其工具方法
    mgr = LanShareManager(None) 
    ips = mgr.get_local_ips()
    primary_ip = ips[0] if ips else "127.0.0.1"
    
    return {
        "enabled": get_config_manager().get_config_value("lan_share", False),
        "ip": primary_ip,
        "all_ips": ips,
        "port": 8765
    }

@router.post("/api/settings/lan_share")
async def save_lan_share(req: LanShareRequest):
    from ...utils.config_manager import get_config_manager
    try:
        get_config_manager().set_config_value("lan_share", req.enabled)
        await broadcaster.broadcast("data_updated", {"module": "network"})
        return {"success": True}
    except Exception as exc:
        return {"success": False, "error": str(exc)}
