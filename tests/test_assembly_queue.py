# -*- coding: utf-8 -*-
"""
基因组组装排队与严格串行调度行为测试
"""
import asyncio
from pathlib import Path
from typing import Any, Dict, List

from src.backend.routes import assembly as assembly_route
from src.backend.utils.assembly_db import assembly_db
from src.backend.utils.persistent_queue import PersistentAssemblyQueue


def test_assembly_run_returns_queued_when_engine_busy(tmp_path: Path, monkeypatch):
    """当已有组装任务正在运行时，提交第二个任务必须返回 status='queued' 与 is_busy=True，严禁返回 running 误导前端直接运行。"""
    test_db_path = tmp_path / "test_assembly.db"
    monkeypatch.setattr(assembly_db, "DB_PATH", test_db_path)
    assembly_db._init_db()
    monkeypatch.setattr(
        assembly_route.AssemblyStorage,
        "get_task_dir",
        staticmethod(lambda tid: tmp_path / "results" / tid),
    )

    async def _scenario() -> None:
        q = PersistentAssemblyQueue.__new__(PersistentAssemblyQueue)
        q._is_running = False
        q._paused = False
        q._queue = []
        q._queued_ids = set()
        q._worker_task = None
        q._processor = None
        q._current_task_id = None
        q._new_task_event = asyncio.Event()
        q._resume_event = asyncio.Event()
        q._resume_event.set()
        monkeypatch.setattr(assembly_route, "assembly_queue", q)

        first_entered = asyncio.Event()
        release_first = asyncio.Event()
        executed: List[str] = []
        active_count = 0
        max_active = 0

        async def _fake_pipeline(payload: Dict[str, Any]) -> None:
            nonlocal active_count, max_active
            tid = payload["task_id"]
            active_count += 1
            max_active = max(max_active, active_count)
            executed.append(tid)
            if tid == "asm_1":
                first_entered.set()
                await release_first.wait()
            assembly_db.update_task_progress(tid, "COMPLETED", 100, "completed")
            active_count -= 1

        await q.start_workers(_fake_pipeline)

        res1 = await assembly_route.run_assembly_job(
            {"task_id": "asm_1", "name": "AsmOne", "sample_id": "S1"}
        )
        await asyncio.wait_for(first_entered.wait(), timeout=2.0)

        # 第 2 个任务在第 1 个任务运行期间加入，等待队列长度是 1，但引擎正忙，必须告知前端处于排队状态
        res2 = await assembly_route.run_assembly_job(
            {"task_id": "asm_2", "name": "AsmTwo", "sample_id": "S2"}
        )
        assert res1["success"] is True
        assert res2["success"] is True
        assert res2["queue_position"] == 1
        assert res2["status"] == "queued"
        assert res2["is_busy"] is True

        q_status = await assembly_route.get_assembly_queue_status()
        assert q_status["is_busy"] is True
        assert q_status["waiting_count"] == 1
        assert q_status["waiting_tasks"][0]["id"] == "asm_2"
        assert max_active == 1

        release_first.set()
        deadline = asyncio.get_running_loop().time() + 2.0
        while asyncio.get_running_loop().time() < deadline:
            if q.current_task_id is None and q.get_queue_size() == 0:
                break
            await asyncio.sleep(0.02)

        assert max_active == 1
        assert executed == ["asm_1", "asm_2"]

        if q._worker_task is not None:
            q._worker_task.cancel()
            await asyncio.gather(q._worker_task, return_exceptions=True)

    asyncio.run(_scenario())
