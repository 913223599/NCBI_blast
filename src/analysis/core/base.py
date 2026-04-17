"""
Base classes and interfaces for analysis components.
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, List
from pathlib import Path


class BaseEngine(ABC):
    """基础引擎接口"""
    
    @abstractmethod
    def is_available(self) -> bool:
        """检查引擎是否可用"""
        pass
    
    @abstractmethod
    def execute(self, **kwargs) -> Dict[str, Any]:
        """执行引擎任务"""
        pass


class BaseParser(ABC):
    """基础解析器接口"""
    
    @abstractmethod
    def parse(self, data: Any) -> Dict[str, Any]:
        """解析数据"""
        pass


class BaseService(ABC):
    """基础服务接口"""
    
    @abstractmethod
    def execute(self, **kwargs) -> Dict[str, Any]:
        """执行服务"""
        pass
