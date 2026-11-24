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


def test_second_task_dispatched_after_ghost_cancel_and_reorder(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    """复现幽灵取消 + 重排后队列引用必须保持同一对象且继续派发第 2 个任务。"""
    db = _init_temp_db(monkeypatch, tmp_path)
    executed: list[str] = []
    done_first = asyncio.Event()
    done_second = asyncio.Event()

    async def _fake_processor(payload: Dict[str, Any]) -> None:
        tid = str(payload["task_id"])
        executed.append(tid)
        if tid == "probe_1":
            done_first.set()
        elif tid == "probe_2":
            done_second.set()

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
        await q.start_workers(_fake_processor)
        initial_queue_ref = q._queue
        try:
            db.create_task("probe_1", "P1", "S1", "BACTERIA", "ILLUMINA", {})
            await q.add_task({"task_id": "probe_1", "name": "P1"})
            await asyncio.wait_for(done_first.wait(), timeout=2.0)

            # 取消不存在的幽灵任务并重排空队列，_queue 对象引用不得发生更换
            assert q.remove_task_from_queue("non_existent_ghost") is False
            q.reorder_queue(["ghost_only"])
            assert q._queue is initial_queue_ref

            db.create_task("probe_2", "P2", "S2", "BACTERIA", "ILLUMINA", {})
            await q.add_task({"task_id": "probe_2", "name": "P2"})
            await asyncio.wait_for(done_second.wait(), timeout=2.0)
        finally:
            if q._worker_task is not None:
                q._worker_task.cancel()
                try:
                    await q._worker_task
                except asyncio.CancelledError:
                    pass

    asyncio.run(_run())
    assert executed == ["probe_1", "probe_2"]


def test_queue_positions_consistent_across_run_status_and_queue_endpoints(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    _init_temp_db(monkeypatch, tmp_path)
    monkeypatch.setattr(assembly_route.AssemblyStorage, "get_task_dir", lambda tid: tmp_path / tid)

    started_t1 = asyncio.Event()
    release_t1 = asyncio.Event()

    async def _fake_processor(payload: Dict[str, Any]) -> None:
        if payload.get("task_id") == "T1":
            started_t1.set()
            await release_t1.wait()

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
            await assembly_route.run_assembly_job({"task_id": "T1", "name": "T1"})
            await started_t1.wait()

            await assembly_route.run_assembly_job({"task_id": "T2", "name": "T2"})
            await assembly_route.run_assembly_job({"task_id": "T3", "name": "T3"})

            # 将 T3 提前到 T2 前面，校验 /status 与 /queue 完全一致
            q.reorder_queue(["T3", "T2"])

            st1 = await assembly_route.get_assembly_status("T1")
            st2 = await assembly_route.get_assembly_status("T2")
            st3 = await assembly_route.get_assembly_status("T3")
            q_res = await assembly_route.get_assembly_queue_status()

            assert st1["queue_position"] == 0
            assert st3["queue_position"] == 1
            assert st2["queue_position"] == 2
            assert q_res["running_task"]["id"] == "T1"
            assert q_res["waiting_count"] == 2
            assert [(w["id"], w["position"]) for w in q_res["waiting_tasks"]] == [
                ("T3", 1),
                ("T2", 2),
            ]
        finally:
            release_t1.set()
            if q._worker_task is not None:
                q._worker_task.cancel()
                try:
                    await q._worker_task
                except asyncio.CancelledError:
                    pass

    asyncio.run(_run())


def test_worker_loop_handles_rapid_enqueue_without_lost_wakeup(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    db = _init_temp_db(monkeypatch, tmp_path)
    executed: list[str] = []
    all_done = asyncio.Event()

    async def _fake_processor(payload: Dict[str, Any]) -> None:
        executed.append(str(payload["task_id"]))
        if len(executed) == 5:
            all_done.set()

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
        await q.start_workers(_fake_processor)
        try:
            for idx in range(1, 6):
                tid = f"Rapid_{idx}"
                db.create_task(tid, tid, tid, "BACTERIA", "ILLUMINA", {})
                await q.add_task({"task_id": tid, "name": tid})
            await asyncio.wait_for(all_done.wait(), timeout=2.0)
        finally:
            if q._worker_task is not None:
                q._worker_task.cancel()
                try:
                    await q._worker_task
                except asyncio.CancelledError:
                    pass

    asyncio.run(_run())
    assert executed == ["Rapid_1", "Rapid_2", "Rapid_3", "Rapid_4", "Rapid_5"]
