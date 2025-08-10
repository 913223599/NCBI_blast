"""
配置管理模块
用于管理API密钥等配置信息
"""

import json
import os
from pathlib import Path


class ConfigManager:
    """
    配置管理器
    负责管理API密钥等配置信息的存储和读取
    """
    
    def __init__(self, config_file: str = None):
        """
        初始化配置管理器
        
        Args:
            config_file (str, optional): 配置文件路径，默认为项目根目录下的config.json
        """
        if config_file is None:
            # 默认配置文件路径为项目根目录下的config.json
            project_root = Path(__file__).parent.parent.parent
            self.config_file = project_root / "config.json"
        else:
            self.config_file = Path(config_file)
        
        self.config_data = {}
        self._load_config()
    
    def _load_config(self):
        """
        从配置文件加载配置数据
        """
        if self.config_file.exists():
            try:
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    self.config_data = json.load(f)
            except Exception as e:
                print(f"警告: 加载配置文件时出错: {e}")
                self.config_data = {}
        else:
            # 如果配置文件不存在，创建默认配置
            self.config_data = {
                "api_keys": {
                    "dashscope": ""
                }
            }
            self._save_config()
    
    def _save_config(self):
        """
        保存配置数据到文件
        """
        try:
            # 确保配置文件的目录存在
            self.config_file.parent.mkdir(parents=True, exist_ok=True)
            
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(self.config_data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"错误: 保存配置文件时出错: {e}")
    
    def get_api_key(self, service: str) -> str:
        """
        获取指定服务的API密钥
        
        Args:
            service (str): 服务名称，如 "dashscope"
            
        Returns:
            str: API密钥，如果找不到则返回空字符串
        """
        return self.config_data.get("api_keys", {}).get(service, "")
    
    def set_api_key(self, service: str, api_key: str):
        """
        设置指定服务的API密钥
        
        Args:
            service (str): 服务名称，如 "dashscope"
            api_key (str): API密钥
        """
        if "api_keys" not in self.config_data:
            self.config_data["api_keys"] = {}
        
        self.config_data["api_keys"][service] = api_key
        self._save_config()
    
    def get_config_file_path(self) -> str:
        """
        获取配置文件路径
        
        Returns:
            str: 配置文件路径
        """
        return str(self.config_file)


def get_config_manager(config_file: str = None) -> ConfigManager:
    """
    获取配置管理器实例
    
    Args:
        config_file (str, optional): 配置文件路径
        
    Returns:
        ConfigManager: 配置管理器实例
    """
    return ConfigManager(config_file)


# 示例和测试
if __name__ == "__main__":
    # 测试配置管理器
    config_manager = get_config_manager()
    
    print(f"配置文件路径: {config_manager.get_config_file_path()}")
    print(f"当前DashScope API密钥: {config_manager.get_api_key('dashscope')}")
    
    # 设置API密钥示例（请替换为实际的API密钥）
    # config_manager.set_api_key("dashscope", "your_actual_api_key_here")