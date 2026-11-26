# -*- coding: utf-8 -*-
"""通用 Bio-Station JSON 编码器，支持 Path 与 numpy/tolist 对象序列化。"""
from __future__ import annotations

import json
from pathlib import Path


class BioJsonEncoder(json.JSONEncoder):
    """通用 Bio-Station JSON 编码器。"""

    def default(self, o):
        if isinstance(o, Path):
            return str(o)
        if hasattr(o, "tolist"):
            return o.tolist()
        return super().default(o)
