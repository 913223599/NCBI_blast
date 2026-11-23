# -*- coding: utf-8 -*-
"""
IdCodec - 安全短 ID 双向编解码器
确保外部工具不会因特殊字符、空格或长 ID 截断导致报错或拓扑错位。
"""
import json
import re
from pathlib import Path
from typing import Dict, Iterable, List


class IdCodec:
    """管理 `short_id (T000001)` 与 `display_id` 的唯一双向映射。"""

    def __init__(self, mapping: Dict[str, str] | None = None) -> None:
        self.short_to_orig: Dict[str, str] = dict(mapping or {})

    @staticmethod
    def deduplicate_ids(raw_ids: Iterable[str]) -> List[str]:
        """对重复的原始序列 ID 附加 _2, _3 后缀，保证叶节点名称唯一。"""
        seen: Dict[str, int] = {}
        result: List[str] = []
        for raw in raw_ids:
            clean = (raw or "seq").strip() or "seq"
            count = seen.get(clean, 0) + 1
            seen[clean] = count
            if count == 1:
                result.append(clean)
            else:
                result.append(f"{clean}_{count}")
        return result

    def build_mapping(self, unique_ids: List[str]) -> Dict[str, str]:
        """生成 T000001 风格的短 ID 映射字典。"""
        self.short_to_orig = {}
        for idx, orig in enumerate(unique_ids, start=1):
            short_id = f"T{idx:06d}"
            self.short_to_orig[short_id] = orig
        return dict(self.short_to_orig)

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(self.short_to_orig, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    @classmethod
    def load(cls, path: Path) -> "IdCodec":
        if not path.exists():
            return cls()
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(data if isinstance(data, dict) else {})

    @staticmethod
    def format_newick_label(label: str) -> str:
        """若标签含 Newick 保留字符或空白，自动使用单引号转义。"""
        if re.search(r"[():,;\[\]'\s]", label):
            escaped = label.replace("'", "''")
            return f"'{escaped}'"
        return label

    @classmethod
    def restore_newick(cls, newick: str, short_to_orig: Dict[str, str]) -> str:
        """
        将 Newick 字符串中的安全短 ID 无损还原为原始序列 ID。
        使用词边界匹配与键长降序，避免前缀误替换。
        """
        if not newick or not short_to_orig:
            return newick

        sorted_keys = sorted(short_to_orig.keys(), key=len, reverse=True)
        pattern = re.compile(r"\b(" + "|".join(re.escape(k) for k in sorted_keys) + r")\b")

        def _replace(match: re.Match[str]) -> str:
            key = match.group(1)
            orig = short_to_orig.get(key, key)
            return cls.format_newick_label(orig)

        return pattern.sub(_replace, newick)
