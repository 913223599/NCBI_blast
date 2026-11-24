# -*- coding: utf-8 -*-
"""
基因组拼接任务队列与接口状态契约回归测试（使用临时 SQLite，绝不触碰生产库）。
"""
import asyncio
import sqlite3
from pathlib import Path
from typing import Any, Dict

import pytest

from src.backend.routes import assembly as assembly_route
from src.backend.utils import persistent_queue as pq_mod
from src.backend.utils.assembly_db import AssemblyDB
from src.backend.utils.persistent_queue import PersistentAssemblyQueue


def _init_temp_db(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> AssemblyDB:
    db_file = tmp_path / "assembly_test.db"
    monkeypatch.setattr(AssemblyDB, "DB_PATH", db_file)
    db = AssemblyDB()
    monkeypatch.setattr(assembly_route, "assembly_db", db)
    monkeypatch.setattr(pq_mod, "assembly_db", db)
    return db


def test_start_workers_cleans_pending_and_queued_zombies(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    db = _init_temp_db(monkeypatch, tmp_path)
    db.create_task("T_RUN", "Run", "S1", "BACTERIA", "ILLUMINA", {})
    db.update_task_progress("T_RUN", "NGCS", 20.0, "running")
    db.create_task("T_PEND", "Pend", "S2", "BACTERIA", "ILLUMINA", {})
    db.create_task("T_QUEUE", "Queue", "S3", "BACTERIA", "ILLUMINA", {})
    db.update_task_progress("T_QUEUE", "QUEUED", 0.0, "queued")

    async def _noop_processor(payload: Dict[str, Any]) -> None:
        return None

    async def _fake_broadcast(*args: Any, **kwargs: Any) -> None:
        return None

    monkeypatch.setattr(pq_mod.broadcaster, "broadcast", _fake_broadcast)

    q = PersistentAssemblyQueue.__new__(PersistentAssemblyQueue)
    q._queue = None
    q._worker_task = None
    q._processor = None
    q._is_running = False
    q._queued_ids = set()
    q._paused = False
    q._resume_event = None
    q._new_task_event = None
    q._current_task_id = None

    async def _run() -> None:
        await q.start_workers(_noop_processor)
        assert q._worker_task is not None
        q._worker_task.cancel()
        try:
            await q._worker_task
        except asyncio.CancelledError:
            pass

    asyncio.run(_run())

    with sqlite3.connect(db.DB_PATH) as conn:
        rows = dict(conn.execute("SELECT id, status FROM assembly_tasks").fetchall())
    assert rows["T_RUN"] == "aborted"
    assert rows["T_PEND"] == "aborted"
    assert rows["T_QUEUE"] == "aborted"
    assert db.get_queued_tasks() == []


def test_run_assembly_job_reports_running_for_single_idle_task(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    _init_temp_db(monkeypatch, tmp_path)
    monkeypatch.setattr(assembly_route.AssemblyStorage, "get_task_dir", lambda tid: tmp_path / tid)

    started_event = asyncio.Event()
    release_event = asyncio.Event()

    async def _fake_processor(payload: Dict[str, Any]) -> None:
        started_event.set()
        await release_event.wait()

    async def _fake_broadcast(*args: Any, **kwargs: Any) -> None:
        return None

    monkeypatch.setattr(pq_mod.broadcaster, "broadcast", _fake_broadcast)

    q = PersistentAssemblyQueue.__new__(PersistentAssemblyQueue)
    q._queue = None
    q._worker_task = None
    q._processor = None
    q._is_running = False
    q._queued_ids = set()
    q._paused = False
    q._resume_event = None
    q._new_task_event = None
    q._current_task_id = None
    monkeypatch.setattr(assembly_route, "assembly_queue", q)

    async def _run() -> None:
        await q.start_workers(_fake_processor)
        try:
            # 1. 空闲时提交第 1 个任务，不应被错误标记为 queued
            res1 = await assembly_route.run_assembly_job(
                {"task_id": "Asm_First_Only", "name": "Single", "sample_type": "BACTERIA"}
            )
            data1 = res1["data"] if isinstance(res1, dict) and "data" in res1 else res1
            assert data1["status"] == "running"
            assert data1["is_busy"] is False
            assert data1["queue_position"] == 0

            await started_event.wait()

            # 2. 第 1 个任务正在执行时提交第 2 个任务，必须正确返回 queued 与 queue_position >= 1
            res2 = await assembly_route.run_assembly_job(
                {"task_id": "Asm_Second_Wait", "name": "Second", "sample_type": "BACTERIA"}
            )
            data2 = res2["data"] if isinstance(res2, dict) and "data" in res2 else res2
            assert data2["status"] == "queued"
            assert data2["is_busy"] is True
            assert data2["queue_position"] >= 1
        finally:
            release_event.set()
            if q._worker_task is not None:
                q._worker_task.cancel()
                try:
                    await q._worker_task
                except asyncio.CancelledError:
                    pass

    asyncio.run(_run())
