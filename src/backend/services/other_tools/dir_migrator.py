# -*- coding: utf-8 -*-
"""目录迁移工具

职责：输入/输出目录变更时，将旧目录内容整体迁移到新目录，并修正 JSON 清单中残留的旧绝对路径。
策略：
- 新目录不存在或为空：逐项 shutil.move；
- 同名子目录：递归合并；
- 同名文件冲突：保留新目录文件，旧文件原地保留并记录为冲突，不做覆盖；
- 迁移完成后旧目录若已为空则删除。
"""
import json
import os
import shutil
from pathlib import Path
from typing import Any, Dict, List


def _is_subpath(child: Path, parent: Path) -> bool:
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


def _merge_move(src: Path, dst: Path, moved: List[str], conflicts: List[str]) -> None:
    dst.mkdir(parents=True, exist_ok=True)
    for item in list(src.iterdir()):
        target = dst / item.name
        if not target.exists():
            shutil.move(str(item), str(target))
            moved.append(item.name)
        elif item.is_dir() and target.is_dir():
            _merge_move(item, target, moved, conflicts)
            try:
                item.rmdir()
            except OSError:
                pass
        else:
            conflicts.append(str(item))


def _replace_prefix(value: Any, old_prefix: str, new_prefix: str) -> Any:
    """递归替换 JSON 结构中以旧目录开头的字符串路径（Windows 下大小写不敏感）。"""
    if isinstance(value, str):
        if os.path.normcase(value).startswith(os.path.normcase(old_prefix)):
            return new_prefix + value[len(old_prefix):]
        return value
    if isinstance(value, list):
        return [_replace_prefix(v, old_prefix, new_prefix) for v in value]
    if isinstance(value, dict):
        return {k: _replace_prefix(v, old_prefix, new_prefix) for k, v in value.items()}
    return value


def rewrite_json_paths(root: Path, old_dir: Path, new_dir: Path) -> int:
    """修正 root 下所有 *.json 文件中的旧绝对路径，返回被修改的文件数。"""
    if not root.exists():
        return 0
    old_prefix = str(old_dir)
    new_prefix = str(new_dir)
    changed = 0
    for jf in root.rglob("*.json"):
        try:
            raw = jf.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if os.path.normcase(old_prefix) not in os.path.normcase(raw).replace("\\\\", "\\"):
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        new_data = _replace_prefix(data, old_prefix, new_prefix)
        if new_data != data:
            jf.write_text(json.dumps(new_data, ensure_ascii=False, indent=2), encoding="utf-8")
            changed += 1
    return changed


def migrate_directory(old_dir: Path, new_dir: Path) -> Dict[str, Any]:
    """将 old_dir 内容迁移到 new_dir，返回迁移统计。"""
    old_dir = old_dir.resolve()
    new_dir = new_dir.resolve()
    result: Dict[str, Any] = {
        "old": str(old_dir),
        "new": str(new_dir),
        "migrated": False,
        "moved_count": 0,
        "conflicts": [],
        "json_rewritten": 0,
        "message": "",
    }
    if os.path.normcase(str(old_dir)) == os.path.normcase(str(new_dir)):
        result["message"] = "路径未变化"
        return result
    if _is_subpath(new_dir, old_dir) or _is_subpath(old_dir, new_dir):
        raise ValueError(f"新旧目录不能互相嵌套: {old_dir} <-> {new_dir}")
    if not old_dir.exists() or not any(old_dir.iterdir()):
        new_dir.mkdir(parents=True, exist_ok=True)
        result["message"] = "旧目录不存在或为空，已直接切换到新目录"
        return result

    moved: List[str] = []
    conflicts: List[str] = []
    _merge_move(old_dir, new_dir, moved, conflicts)
    result["moved_count"] = len(moved)
    result["conflicts"] = conflicts
    result["json_rewritten"] = rewrite_json_paths(new_dir, old_dir, new_dir)
    result["migrated"] = True
    try:
        if not any(old_dir.iterdir()):
            old_dir.rmdir()
    except OSError:
        pass
    result["message"] = f"已迁移 {len(moved)} 项" + (f"，{len(conflicts)} 项同名冲突保留在旧目录" if conflicts else "")
    return result

