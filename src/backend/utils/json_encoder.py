import json
from pathlib import Path

class BioJsonEncoder(json.JSONEncoder):
    """
    通用 Bio-Station JSON 编码器
    能够处理 Path 对象、numpy 类型等非标准 JSON 类型
    """
    def default(self, o):
        if isinstance(o, Path):
            return str(o)
        # 兼容 numpy 等（如果后续引用）
        if hasattr(o, "tolist"):
            return o.tolist()
        return super().default(o)
