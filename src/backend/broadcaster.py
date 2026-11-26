# -*- coding: utf-8 -*-
"""向后兼容门面：实际实现已下沉至 src/core/broadcaster.py，消除跨层循环依赖。"""
from ..core.broadcaster import EventBroadcaster, broadcaster

__all__ = ["EventBroadcaster", "broadcaster"]
