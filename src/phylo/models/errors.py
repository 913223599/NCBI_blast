# -*- coding: utf-8 -*-
"""
PhyloCore 统一异常层级
"""
from typing import Optional


class PhyloError(Exception):
    """系统发育分析引擎基础异常。"""

    def __init__(self, message: str, code: str = "PHYLO_ERROR", detail: Optional[str] = None):
        super().__init__(message)
        self.message = message
        self.code = code
        self.detail = detail


class PhyloCancelledError(PhyloError):
    """任务被用户或系统强制取消时抛出。"""

    def __init__(self, message: str = "分析任务已取消", detail: Optional[str] = None):
        super().__init__(message=message, code="PHYLO_CANCELLED", detail=detail)


class ToolUnavailableError(PhyloError):
    """所需外部计算引擎或运行时不可用时抛出。"""

    def __init__(self, tool_name: str, message: Optional[str] = None, detail: Optional[str] = None):
        msg = message or f"计算工具不可用: {tool_name}"
        super().__init__(message=msg, code="TOOL_UNAVAILABLE", detail=detail)
        self.tool_name = tool_name


class InvalidInputError(PhyloError):
    """输入序列文件缺失、格式错误或数量不足以构树时抛出。"""

    def __init__(self, message: str, detail: Optional[str] = None):
        super().__init__(message=message, code="INVALID_INPUT", detail=detail)
