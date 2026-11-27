# -*- coding: utf-8 -*-
"""Batch P1A 架构守护与核心基础设施测试：验证零跨层反向导入及 BaseTaskDB 共享基类行为。"""
from __future__ import annotations

import ast
from pathlib import Path
import pytest

pytestmark = pytest.mark.offline

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_no_reverse_imports_from_core_assembly_blast_to_backend():
    """核心内核层 (core) 与领域引擎层 (assembly/blast) 严禁反向导入 src.backend。"""
    violations = []
    for layer in ("core", "assembly", "blast"):
        layer_dir = PROJECT_ROOT / "src" / layer
        if not layer_dir.exists():
            continue
        for py_file in sorted(layer_dir.rglob("*.py")):
            if "__pycache__" in py_file.parts:
                continue
            tree = ast.parse(py_file.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if "backend" in alias.name.split("."):
                            violations.append(f"{py_file.relative_to(PROJECT_ROOT)}:{node.lineno} import {alias.name}")
                elif isinstance(node, ast.ImportFrom):
                    mod = node.module or ""
                    if "backend" in mod.split("."):
                        violations.append(f"{py_file.relative_to(PROJECT_ROOT)}:{node.lineno} from {mod}")
    assert not violations, "检测到破坏单向分层原则的反向导入:\n" + "\n".join(violations)


def test_core_and_backend_facade_identity():
    """验证向后兼容门面与 src/core 实现保持严格同源。"""
    from src.backend import broadcaster as backend_bc
    from src.backend.utils import assembly_db as backend_adb
    from src.backend.utils import assembly_storage as backend_as
    from src.backend.utils import compat as backend_compat
    from src.backend.utils import json_encoder as backend_je
    from src.core import assembly_db as core_adb
    from src.core import assembly_storage as core_as
    from src.core import broadcaster as core_bc
    from src.core import compat as core_compat
    from src.core import json_encoder as core_je

    assert backend_bc.broadcaster is core_bc.broadcaster
    assert backend_compat.get_short_path_name is core_compat.get_short_path_name
    assert backend_je.BioJsonEncoder is core_je.BioJsonEncoder
    assert backend_adb.assembly_db is core_adb.assembly_db
    assert backend_as.AssemblyStorage is core_as.AssemblyStorage


def test_shared_base_task_db_lifecycle(tmp_path: Path):
    """验证继承自 BaseTaskDB 的 3 套分析任务 DB 均具备完整的创建/更新/自愈/删除能力。"""
    from src.analysis.annotation.db import AnnotationDB
    from src.analysis.phage_finder.db import PhageDiscoveryDB
    from src.analysis.phage_structure.db import PhageStructureDB
    from src.core.task_db import BaseTaskDB

    anno_db = AnnotationDB(str(tmp_path / "anno.db"))
    finder_db = PhageDiscoveryDB(tmp_path / "finder.db")
    struct_db = PhageStructureDB(tmp_path / "struct.db")

    for db in (anno_db, finder_db, struct_db):
        assert isinstance(db, BaseTaskDB)

    anno_db.create_task("A1", "sample_a", "PHAGE", "auto")
    anno_db.update_progress("A1", 40, "running_step", "running")
    assert anno_db.get_task("A1")["progress"] == 40
    anno_db.reset_interrupted_tasks()
    assert anno_db.get_task("A1")["status"] == "cancelled"
    anno_db.delete_task("A1")
    assert anno_db.get_task("A1") is None

    finder_db.create_task("F1", "sample_f", "v4", "4.2", "cpu", True)
    finder_db.update_progress("F1", 55, "scanning", "running")
    finder_db.mark_failed("F1", "boom")
    assert finder_db.get_task("F1")["status"] == "failed"

    struct_db.create_task("S1", "sample_s", "file")
    struct_db.update_progress("S1", 70, "hmm", "running")
    assert struct_db.reset_interrupted_tasks() == 1
    assert struct_db.get_task("S1")["status"] == "cancelled"


def test_resource_guard_facade_identity():
    """验证 src.utils.resource_guard 与 src.core.resource_guard 保持严格同源。"""
    from src.core.resource_guard import GpuGuard as CoreGpuGuard
    from src.core.resource_guard import get_safe_cpu_budget as core_budget
    from src.utils.resource_guard import GpuGuard as UtilsGpuGuard
    from src.utils.resource_guard import get_safe_cpu_budget as utils_budget

    assert utils_budget is core_budget
    assert UtilsGpuGuard is CoreGpuGuard


def test_zero_bidirectional_package_cycles_in_src():
    """全仓 src/ 顶层包间严禁存在双向循环依赖，且 src.core 不得依赖上层业务包。"""
    import collections

    src_root = PROJECT_ROOT / "src"
    top_pkgs = {
        p.name
        for p in src_root.iterdir()
        if p.is_dir() and p.name not in {"__pycache__", "web-next"}
    }
    edges: dict[tuple[str, str], list[str]] = collections.defaultdict(list)

    for py_file in sorted(src_root.rglob("*.py")):
        if any(part in {"__pycache__", "node_modules", "dist"} for part in py_file.parts):
            continue
        rel = py_file.relative_to(PROJECT_ROOT)
        if len(rel.parts) <= 2:
            continue
        src_pkg = rel.parts[1]
        mod_parts = list(rel.with_suffix("").parts)
        if mod_parts[-1] == "__init__":
            mod_parts = mod_parts[:-1]
        pkg_parts = mod_parts[:-1]

        tree = ast.parse(py_file.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            tgt_pkg = None
            tgt_mod = ""
            if isinstance(node, ast.ImportFrom):
                if node.level > 0:
                    base = pkg_parts[: len(pkg_parts) - (node.level - 1)]
                    full = base + node.module.split(".") if node.module else base
                    if len(full) >= 2 and full[0] == "src":
                        tgt_pkg = full[1]
                        tgt_mod = ".".join(full)
                elif node.module:
                    parts = node.module.split(".")
                    if parts[0] == "src" and len(parts) >= 2:
                        tgt_pkg = parts[1]
                        tgt_mod = node.module
                    elif parts[0] in top_pkgs:
                        tgt_pkg = parts[0]
                        tgt_mod = node.module
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    parts = alias.name.split(".")
                    if parts[0] == "src" and len(parts) >= 2:
                        tgt_pkg = parts[1]
                        tgt_mod = alias.name
            if tgt_pkg and tgt_pkg in top_pkgs and tgt_pkg != src_pkg:
                edges[(src_pkg, tgt_pkg)].append(f"{rel}:{node.lineno} -> {tgt_mod}")

    bidir = sorted({tuple(sorted((a, b))) for (a, b) in edges if (b, a) in edges})
    assert not bidir, "检测到包级双向循环依赖:\n" + "\n".join(
        f"  {a} <-> {b}: {edges[(a, b)][:2]} | {edges[(b, a)][:2]}" for a, b in bidir
    )

    forbidden_core_deps = sorted(
        f"{tgt}: {edges[('core', tgt)][:2]}"
        for (src_p, tgt) in edges
        if src_p == "core" and tgt in {"utils", "backend", "analysis", "assembly", "blast", "phylo", "workbench"}
    )
    assert not forbidden_core_deps, "src/core 违规依赖上层包:\n" + "\n".join(forbidden_core_deps)


def test_serial_queue_base_classes_lifecycle():
    """验证共享串行队列基座 BaseAsyncTaskQueue 与 BasePausableSerialQueue 的核心契约与继承关系。"""
    import asyncio

    from src.analysis.annotation.queue import AnnotationQueue, annotation_queue
    from src.analysis.phage_finder.queue import PhageDiscoveryQueue, phage_discovery_queue
    from src.analysis.phage_structure.queue import PhageStructureQueue, phage_structure_queue
    from src.backend.utils.persistent_queue import PersistentAssemblyQueue, persistent_queue
    from src.core.serial_queue import BaseAsyncTaskQueue, BasePausableSerialQueue

    assert issubclass(PhageDiscoveryQueue, BaseAsyncTaskQueue)
    assert issubclass(PhageStructureQueue, BaseAsyncTaskQueue)
    assert issubclass(AnnotationQueue, BasePausableSerialQueue)
    assert issubclass(PersistentAssemblyQueue, BasePausableSerialQueue)
    assert isinstance(phage_discovery_queue, BaseAsyncTaskQueue)
    assert isinstance(phage_structure_queue, BaseAsyncTaskQueue)
    assert isinstance(annotation_queue, BasePausableSerialQueue)
    assert isinstance(persistent_queue, BasePausableSerialQueue)

    class _DummyAsyncQueue(BaseAsyncTaskQueue):
        async def _broadcast_snapshot(self) -> None:
            return None

    class _DummyPausableQueue(BasePausableSerialQueue):
        def __init__(self) -> None:
            self._init_base_state()
            self.executed: list[str] = []

        async def _broadcast_status(self) -> None:
            return None

    async def _scenario() -> None:
        aq = _DummyAsyncQueue(max_workers=1)
        async_seen: list[str] = []
        done_evt = asyncio.Event()

        async def _exec(tid: str, req, ctx) -> None:
            async_seen.append(tid)
            if tid == "a3":
                done_evt.set()

        aq.set_executor(_exec)
        await aq.start()
        await aq.enqueue("a1", None, {})
        await aq.enqueue("a2", None, {})
        await aq.enqueue("a3", None, {})
        assert (await aq.cancel_task("a2"))["status"] == "cancelled"
        await asyncio.wait_for(done_evt.wait(), timeout=2.0)
        assert async_seen == ["a1", "a3"]
        for w in aq._workers:
            w.cancel()
        await asyncio.gather(*aq._workers, return_exceptions=True)

        pq = _DummyPausableQueue()
        pq.pause()
        assert pq.is_paused is True
        q_ref = pq._queue
        pq._queue.extend([{"task_id": "p1"}, {"task_id": "p2"}, {"task_id": "p3"}])
        pq._queued_ids.update({"p1", "p2", "p3"})
        pq.reorder_queue(["p3", "p1", "p2"])
        assert pq._remove_task_inplace("p1")
        assert pq._queue is q_ref
        assert pq.get_waiting_ids() == ["p3", "p2"]
        assert pq.get_queue_position("p3") == 1
        assert pq.get_queue_position("p2") == 2

        p_done = asyncio.Event()

        async def _proc(payload) -> None:
            pq.executed.append(str(payload["task_id"]))
            if len(pq.executed) == 2:
                p_done.set()

        pq._processor = _proc
        pq._worker_task = asyncio.create_task(pq._worker_loop())
        pq.resume()
        await asyncio.wait_for(p_done.wait(), timeout=2.0)
        assert pq.executed == ["p3", "p2"]
        pq._worker_task.cancel()
        await asyncio.gather(pq._worker_task, return_exceptions=True)

    asyncio.run(_scenario())
