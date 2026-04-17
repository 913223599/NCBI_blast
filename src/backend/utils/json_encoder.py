import json
from pathlib import Path

class BioJsonEncoder(json.JSONEncoder):
    """
    通用 Bio-Station JSON 编码器
    能够处理 Path 对象、numpy 类型等非标准 JSON 类型
    """
    def default(self, obj):
        if isinstance(obj, Path):
            return str(obj)
        # 兼容 numpy 等（如果后续引用）
        if hasattr(obj, "tolist"):
            return obj.tolist()
        return super().default(obj)
