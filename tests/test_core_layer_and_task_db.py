# -*- coding: utf-8 -*-
"""Batch P1A 架构守护与核心基础设施测试：验证零跨层反向导入及 BaseTaskDB 共享基类行为。"""
from __future__ import annotations

import ast
from pathlib import Path

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
        if "__pycache__" in py_file.parts:
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
