# -*- coding: utf-8 -*-
"""
WebBridge Mixin: AI 模型配置 + 系统设置
职责：API Key 管理、AI 模型增删切换、UI 语言、工作区拓扑持久化
"""
import os
import json
from pathlib import Path
from PyQt6.QtCore import pyqtSlot


class SettingsBridgeMixin:
    """系统设置桥接 Mixin"""

    @pyqtSlot(str, result=str)
    def get_api_key(self, service):
        """Get API key from config"""
        from src.utils.config_manager import get_config_manager
        return get_config_manager().get_api_key(service)

    @pyqtSlot(str, str, result=bool)
    def save_api_key(self, service, key):
        """Save API key to config"""
        try:
            from src.utils.config_manager import get_config_manager
            get_config_manager().set_api_key(service, key)
            self.logger.info(f"API key for {service} saved via bridge")
            return True
        except Exception as exc:
            self.logger.error(f"Failed to save API key for {service}: {exc}")
            return False

    # --- UI Translation Slots ---
    @pyqtSlot(result=str)
    def get_ui_translations(self):
        """Return full translation dictionary for current language"""
        from src.utils.ui_translation_manager import get_ui_translator
        translator = get_ui_translator()
        translator.load_all_translations()
        data = translator.get_all_translations_for_current_lang()
        return json.dumps(data, ensure_ascii=False)

    @pyqtSlot(result=str)
    def get_ui_language(self):
        """Get current UI language code"""
        from src.utils.ui_translation_manager import get_ui_translator
        return get_ui_translator().get_language()

    @pyqtSlot(str, result=bool)
    def save_ui_language(self, lang_code):
        """Save UI language and return True if successful"""
        try:
            from src.utils.ui_translation_manager import get_ui_translator
            get_ui_translator().set_language(lang_code)
            self.logger.info(f"UI Language switched to: {lang_code}")
            return True
        except Exception as exc:
            self.logger.error(f"Failed to save UI language: {exc}")
            return False

    @pyqtSlot(result=str)
    def get_tools_metadata(self):
        """Return the tools_metadata.json content"""
        try:
            path = os.path.join(os.path.dirname(__file__), "../../resources/tools_metadata.json")
            if os.path.exists(path):
                with open(path, 'r', encoding='utf-8') as fobj:
                    return fobj.read()
            return "{}"
        except Exception as exc:
            self.logger.error(f"Failed to load tools metadata: {exc}")
            return "{}"

    # --- AI Model Config ---
    @pyqtSlot(str, result=bool)
    def save_selected_model(self, model_key):
        """Save the selected AI model and force-recreate the global translator"""
        try:
            from src.utils.config_manager import get_config_manager
            config = get_config_manager()
            config.set_advanced_settings({'ai_model': model_key})
            self.logger.info(f"Selected AI model saved: {model_key}")

            import src.utils.translation.biology_translator as bt
            bt._global_translator = None
            self.logger.info("Global translator reset. Next translation will use new model.")
            return True
        except Exception as exc:
            self.logger.error(f"Failed to save selected model: {exc}")
            return False

    @pyqtSlot(result=str)
    def get_selected_model(self):
        """Get the currently saved AI model selection"""
        try:
            from src.utils.config_manager import get_config_manager
            advanced = get_config_manager().get_advanced_settings()
            return advanced.get('ai_model', '')
        except Exception as exc:
            self.logger.error(f"Failed to get selected model: {exc}")
            return ""

    @pyqtSlot(result=str)
    def get_supported_ai_models(self):
        """Get list of supported AI models from config"""
        try:
            from src.utils.config_manager import get_config_manager
            models = get_config_manager().get_supported_models()
            return json.dumps(models)
        except Exception as exc:
            self.logger.error(f"Failed to get supported models: {exc}")
            return "{}"

    @pyqtSlot(result=str)
    def get_current_ai_model(self):
        """Get currently selected AI model"""
        try:
            from src.utils.config_manager import get_config_manager
            settings = get_config_manager().get_advanced_settings()
            current = settings.get("ai_model", "deepseek-r1")
            return current
        except Exception as exc:
            self.logger.error(f"Failed to get current model: {exc}")
            return "deepseek-r1"

    @pyqtSlot(str, result=bool)
    def save_ai_model(self, model_key):
        """Save selected AI model"""
        try:
            from src.utils.config_manager import get_config_manager
            config_mgr = get_config_manager()
            settings = config_mgr.get_advanced_settings()
            settings["ai_model"] = model_key
            config_mgr.set_advanced_settings(settings)
            self.logger.info(f"AI Model switched to: {model_key}")
            return True
        except Exception as exc:
            self.logger.error(f"Failed to save AI model: {exc}")
            return False

    @pyqtSlot(str, result=str)
    def test_ai_model(self, model_key):
        """测试新增模型是否可用"""
        try:
            from src.utils.translation.qwen_translator import QwenTranslator
            self.logger.info(f"Bridge testing model: {model_key}")
            translator = QwenTranslator(model=model_key)
            success, message = translator.validate_model()
            self.logger.info(f"Model test result: {success}, {message}")
            return json.dumps({"success": success, "message": message})
        except Exception as exc:
            self.logger.error(f"Bridge testing model exception: {exc}")
            return json.dumps({"success": False, "message": str(exc)})

    @pyqtSlot(result=str)
    def get_ai_models(self):
        """Get all AI models configured on backend"""
        try:
            from src.utils.config_manager import get_config_manager
            models = get_config_manager().get_supported_models()
            if isinstance(models, dict):
                models = [{"key": k, "name": v} for k, v in models.items()]
            return json.dumps(models)
        except Exception as exc:
            self.logger.error(f"Failed to get AI models: {exc}")
            return "[]"

    @pyqtSlot(str, str, result=bool)
    def add_ai_model(self, model_key, model_name):
        """Add a new AI model to the supported list"""
        try:
            from src.utils.config_manager import get_config_manager
            get_config_manager().add_supported_model(model_key, model_name)
            self.logger.info(f"AI Model added: {model_key} ({model_name})")
            return True
        except Exception as exc:
            self.logger.error(f"Failed to add AI model: {exc}")
            return False

    @pyqtSlot(str, result=bool)
    def delete_ai_model(self, model_key):
        """Remove an AI model from the supported list"""
        try:
            from src.utils.config_manager import get_config_manager
            get_config_manager().remove_supported_model(model_key)
            self.logger.info(f"AI Model removed: {model_key}")
            return True
        except Exception as exc:
            self.logger.error(f"Failed to remove AI model: {exc}")
            return False

    # --- Workspace Topology ---
    @pyqtSlot(str)
    def save_topology(self, topology_json):
        """Save the current canvas topology to a local file for persistence"""
        try:
            path = Path(self.blast_manager.results_dir) / "workspace_topology.json"
            with open(path, 'w', encoding='utf-8') as fobj:
                fobj.write(topology_json)
            self.logger.info(f"Workspace topology saved to: {path}")
        except Exception as exc:
            self.logger.error(f"Failed to save workspace topology: {exc}")

    @pyqtSlot(result=str)
    def load_topology(self):
        """Load the last saved workspace topology from local file"""
        try:
            path = Path(self.blast_manager.results_dir) / "workspace_topology.json"
            if path.exists():
                with open(path, 'r', encoding='utf-8') as fobj:
                    return fobj.read()
            return ""
        except Exception as exc:
            self.logger.error(f"Failed to load workspace topology: {exc}")
            return ""
