# -*- coding: utf-8 -*-
"""受控白名单远程执行器数据模型与动作白名单定义。"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Tuple

ALLOWED_ACTIONS: Tuple[str, ...] = (
    "git_status",
    "git_diff_summary",
    "git_recover_and_pull",
    "phold_gpu_check",
    "service_health",
)

SSH_READONLY_ACTIONS: Tuple[str, ...] = (
    "git_status",
    "git_diff_summary",
    "service_health",
)


@dataclass(frozen=True)
class RemoteTarget:
    """远程主机连接目标配置（禁止硬编码凭据，Token 从环境变量或参数传入）。"""

    mode: str
    host: str
    port: int = 8765
    token: str = ""
    user: str = ""
    remote_dir: str = ""
    timeout: float = 15.0


@dataclass
class ActionResult:
    """远程执行器统一结构化返回。"""

    ok: bool
    action: str
    host: str
    elapsed_ms: float
    data: Dict[str, Any] = field(default_factory=dict)
    error: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
