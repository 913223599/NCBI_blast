"""
Base classes and interfaces for analysis components.
"""

from abc import ABC, abstractmethod


class BaseEngine(ABC):
    """基础引擎接口（具体子类定义各自的 execute 参数签名）"""
    
    @abstractmethod
    def is_available(self) -> bool:
        """检查引擎是否可用"""
        pass


class BaseParser(ABC):
    """基础解析器接口（具体子类实现 parse 方法）"""
    pass


class BaseService(ABC):
    """基础服务接口（具体子类实现 execute 方法）"""
    pass
