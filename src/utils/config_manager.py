"""
配置管理模块
用于管理API密钥等配置信息 - 优化版 (单例模式+线程安全)
"""

import json
import threading
import logging
from pathlib import Path


class ConfigManager:
    """
    配置管理器
    负责管理API密钥等配置信息的存储和读取
    采用单例模式，确保全局配置一致性
    """

    _instance = None
    _lock = threading.RLock()  # 使用可重入锁防止死锁
    _initialized = False

    # 定义默认配置常量
    DEFAULT_API_KEYS = {
        "dashscope": ""
    }

    DEFAULT_ADVANCED_SETTINGS = {
        "hitlist_size": 20,
        "word_size": None,
        "evalue": None,
        "matrix_name": None,
        "filter": None,
        "alignments": None,
        "descriptions": None,
        "local_num_threads": None,
        "nucleotide_database": "nt",
        "protein_database": "nr",
        "prefer_local": True,
        "fallback_to_remote": True,
        "use_cache": True,
        "use_ai_translation": True,
        "ai_translation_model": "deepseek-r1",
        "thread_count": 3  # 默认处理线程数
    }

    def __new__(cls, *args, **kwargs):
        """实现单例模式的核心方法"""
        if not cls._instance:
            with cls._lock:
                if not cls._instance:
                    cls._instance = super(ConfigManager, cls).__new__(cls)
        return cls._instance

    def __init__(self, config_file: str = None):
        """
        初始化配置管理器
        Args:
            config_file (str, optional): 配置文件路径
        """
        # 防止重复初始化
        if self._initialized:
            return

        with self._lock:
            if self._initialized:
                return

            if config_file is None:
                # 优化路径获取：src/utils/config_manager.py -> Project Root
                # parents[2] 指向项目根目录
                project_root = Path(__file__).resolve().parents[2]
                self.config_file = project_root / "config.json"
            else:
                self.config_file = Path(config_file)

            self.config_data = {}
            self._load_config()
            self._initialized = True

    def _load_config(self):
        """从配置文件加载配置数据"""
        modified = False

        # 1. 加载现有文件
        if self.config_file.exists():
            try:
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    self.config_data = json.load(f)
            except Exception as e:
                logging.warning(f"加载配置文件时出错: {e}，将使用默认配置")
                self.config_data = {}
                modified = True
        else:
            self.config_data = {}
            modified = True

        # 2. 验证并修复 'api_keys'
        if "api_keys" not in self.config_data:
            self.config_data["api_keys"] = self.DEFAULT_API_KEYS.copy()
            modified = True
        else:
            for key, default_val in self.DEFAULT_API_KEYS.items():
                if key not in self.config_data["api_keys"]:
                    self.config_data["api_keys"][key] = default_val
                    modified = True

        # 3. 验证并修复 'advanced_settings'
        if "advanced_settings" not in self.config_data:
            self.config_data["advanced_settings"] = self.DEFAULT_ADVANCED_SETTINGS.copy()
            modified = True
        else:
            current_settings = self.config_data["advanced_settings"]
            for key, default_val in self.DEFAULT_ADVANCED_SETTINGS.items():
                if key not in current_settings:
                    current_settings[key] = default_val
                    modified = True

        # 4. 仅在必要时保存
        if modified:
            self._save_config()

    def _save_config(self):
        """保存配置数据到文件 (线程安全)"""
        try:
            with self._lock: # 写入时加锁
                self.config_file.parent.mkdir(parents=True, exist_ok=True)
                with open(self.config_file, 'w', encoding='utf-8') as f:
                    json.dump(self.config_data, f, indent=2, ensure_ascii=False)
                # print(f"配置已保存至: {self.config_file}") # 调试用
        except Exception as e:
            logging.error(f"保存配置文件时出错: {e}")

    def get_api_key(self, service: str) -> str:
        return self.config_data.get("api_keys", {}).get(service, "")

    def set_api_key(self, service: str, api_key: str):
        if "api_keys" not in self.config_data:
            self.config_data["api_keys"] = {}

        # 仅当值发生变化时才保存
        if self.config_data["api_keys"].get(service) != api_key:
            self.config_data["api_keys"][service] = api_key
            self._save_config()

    def get_advanced_settings(self) -> dict:
        """获取高级设置的副本，防止外部直接修改内部字典"""
        return self.config_data.get("advanced_settings", {}).copy()

    def set_advanced_settings(self, settings: dict):
        """设置高级设置"""
        if "advanced_settings" not in self.config_data:
            self.config_data["advanced_settings"] = {}

        current_settings = self.config_data["advanced_settings"]

        # 检查是否有实际更改
        has_changes = False
        for k, v in settings.items():
            if current_settings.get(k) != v:
                current_settings[k] = v
                has_changes = True

        if has_changes:
            self.config_data["advanced_settings"] = current_settings
            self._save_config()

    def get_config_file_path(self) -> str:
        return str(self.config_file)

    def get_supported_models(self) -> dict:
        """获取支持的AI模型列表，返回 {key: name} 格式的字典"""
        # 从配置文件中获取支持的模型
        supported_models = self.config_data.get("supported_models", [])
        
        # 转换为字典格式 {key: name}
        models_dict = {}
        for model in supported_models:
            if isinstance(model, dict) and "key" in model and "name" in model:
                models_dict[model["key"]] = model["name"]
        
        # 如果配置文件中没有定义，返回默认值
        if not models_dict:
            return {
                'qwen-plus': '通义千问-Plus',
                'qwen-mt-plus': '通义千问-MT-Plus',
                'qwen-mt-turbo': '通义千问-MT-Turbo',
                'qwen-turbo': '通义千问-Turbo',
                'deepseek-r1': 'DeepSeek'
            }
        
        return models_dict
    
    def get_supported_model_keys(self) -> list:
        """获取支持的AI模型键列表，用于界面显示"""
        return list(self.get_supported_models().keys())


def get_config_manager(config_file: str = None) -> ConfigManager:
    """获取配置管理器单例"""
    return ConfigManager(config_file)