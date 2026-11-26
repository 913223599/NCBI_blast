# -*- coding: utf-8 -*-
"""
CheckpointManager & StageCache - 分阶段断点保护与内容寻址缓存
"""
import hashlib
import json
import os
import shutil
import time
from pathlib import Path
from typing import Any, Dict, List

from ..models.schemas import StageState
import logging
_s110_logger = logging.getLogger(__name__)


def _atomic_write_text(target: Path, content: str) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    tmp_path.write_text(content, encoding="utf-8")
    os.replace(tmp_path, target)


class CheckpointManager:
    """持久化单任务阶段状态与产物路径，防止中断丢失状态。"""

    def __init__(self, job_dir: Path) -> None:
        self.job_dir = job_dir
        self.checkpoint_file = job_dir / "checkpoint.json"
        self.data: Dict[str, Any] = {
            "updated_at": time.time(),
            "stages": {},
            "artifacts": {},
        }
        if self.checkpoint_file.exists():
            try:
                loaded = json.loads(self.checkpoint_file.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    self.data = loaded
            except Exception as _exc:
                _s110_logger.debug("CheckpointManager.__init__ 忽略非致命异常: %s", _exc)

    def update_stage(self, stage: StageState) -> None:
        self.data.setdefault("stages", {})[stage.name] = stage.model_dump()
        self.data["updated_at"] = time.time()
        _atomic_write_text(
            self.checkpoint_file,
            json.dumps(self.data, ensure_ascii=False, indent=2),
        )

    def set_artifact(self, key: str, value: Any) -> None:
        self.data.setdefault("artifacts", {})[key] = value
        self.data["updated_at"] = time.time()
        _atomic_write_text(
            self.checkpoint_file,
            json.dumps(self.data, ensure_ascii=False, indent=2),
        )


class StageCache:
    """
    内容寻址阶段缓存（MSA 对齐、Mash 距离矩阵等）。
    同一批序列切换下游建树引擎时可直接复用对齐结果。
    """

    def __init__(self, cache_root: Path) -> None:
        self.cache_root = cache_root
        self.cache_root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def make_key(content_hash: str, stage: str, params: Dict[str, Any]) -> str:
        payload = json.dumps(
            {"content_hash": content_hash, "stage": stage, "params": params},
            sort_keys=True,
            ensure_ascii=False,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]

    def get_dir(self, stage: str, key: str) -> Path:
        return self.cache_root / stage / key

    def has_files(self, stage: str, key: str, required_files: List[str]) -> bool:
        cdir = self.get_dir(stage, key)
        if not cdir.is_dir():
            return False
        return all((cdir / fname).is_file() and (cdir / fname).stat().st_size > 0 for fname in required_files)

    def restore_files(self, stage: str, key: str, mapping: Dict[str, Path]) -> bool:
        cdir = self.get_dir(stage, key)
        if not self.has_files(stage, key, list(mapping.keys())):
            return False
        for fname, dst in mapping.items():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(cdir / fname, dst)
        return True

    def store_files(self, stage: str, key: str, mapping: Dict[str, Path]) -> None:
        cdir = self.get_dir(stage, key)
        tmp_dir = cdir.with_name(f".{key}.{os.getpid()}.tmp")
        if tmp_dir.exists():
            shutil.rmtree(tmp_dir, ignore_errors=True)
        tmp_dir.mkdir(parents=True, exist_ok=True)
        try:
            for fname, src in mapping.items():
                if src.is_file():
                    shutil.copy2(src, tmp_dir / fname)
            if cdir.exists():
                shutil.rmtree(cdir, ignore_errors=True)
            cdir.parent.mkdir(parents=True, exist_ok=True)
            os.replace(tmp_dir, cdir)
        finally:
            if tmp_dir.exists():
                shutil.rmtree(tmp_dir, ignore_errors=True)
