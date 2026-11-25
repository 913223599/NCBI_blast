# -*- coding: utf-8 -*-
"""
阶段二测试：PhyloCore REST API (/api/phylo/*) 全链路集成测试
"""
import time
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.backend.routes import phylo as phylo_route
from src.phylo.pipeline.executor import get_phylo_executor
from src.phylo.storage.archive_store import PhyloArchiveStore


def test_phylo_api_full_lifecycle(tmp_path: Path, monkeypatch):
    store = PhyloArchiveStore(base_dir=tmp_path / "api_phylo_store")
    executor = get_phylo_executor()
    orig_store = executor.store
    executor.store = store
    monkeypatch.setattr(phylo_route, "get_phylo_store", lambda: store)

    app = FastAPI()
    app.include_router(phylo_route.router)
    client = TestClient(app)

    try:
        # 1. 能力探测
        cap_res = client.get("/api/phylo/capabilities")
        assert cap_res.status_code == 200
        caps = cap_res.json()
        assert caps["cpu_safe_max"] >= 1
        assert "bionj" in caps["engines"]

        # 2. 粘贴序列导入工作区
        fasta_text = (
            ">Seq_A\n" + "ATGCGTACGTAGCTAGCTAG" * 10 + "\n"
            ">Seq_B\n" + "ATGCGTACGTAGCTAGCTGG" * 10 + "\n"
            ">Seq_C\n" + "ATGCGTACGTAGTTAGCTAG" * 10 + "\n"
            ">Seq_D\n" + "TTACGTGCATAGCTCGCTAG" * 10 + "\n"
        )
        paste_res = client.post(
            "/api/phylo/workspace/paste",
            json={"content": fasta_text, "filename": "test_panel.fasta"},
        )
        assert paste_res.status_code == 200
        ws_data = paste_res.json()
        assert len(ws_data["files"]) == 1
        assert ws_data["profile"]["sequence_count"] == 4
        assert ws_data["profile"]["is_aligned"] is True

        # 3. 提交任务（使用已对齐 + BioNJ 快速测试）
        job_res = client.post(
            "/api/phylo/jobs",
            json={
                "title": "API_Test_Tree",
                "track": "gene",
                "msa": "none",
                "engine": "bionj",
                "model": "jc69",
                "bootstrap": 10,
                "threads": 2,
                "use_gpu": False,
            },
        )
        assert job_res.status_code == 200, job_res.text
        job_id = job_res.json()["job_id"]

        # 4. 轮询直到任务完成
        final_job = None
        for _ in range(60):
            st_res = client.get(f"/api/phylo/jobs/{job_id}")
            assert st_res.status_code == 200
            final_job = st_res.json()
            if final_job["status"] in ("completed", "failed", "cancelled"):
                break
            time.sleep(0.15)

        assert final_job is not None
        assert final_job["status"] == "completed", final_job.get("error")
        assert final_job["metrics"]["leaf_count"] == 4
        assert "Seq_A" in final_job["newick"]

        # 5. 日志、重定根、导出与删除
        log_res = client.get(f"/api/phylo/jobs/{job_id}/logs")
        assert log_res.status_code == 200
        assert len(log_res.json()["lines"]) > 0

        reroot_res = client.post(
            f"/api/phylo/jobs/{job_id}/reroot",
            json={"mode": "outgroup", "node_name": "Seq_D"},
        )
        assert reroot_res.status_code == 200
        assert "Seq_D" in reroot_res.json()["newick"]

        exp_nwk = client.get(f"/api/phylo/jobs/{job_id}/export/newick")
        assert exp_nwk.status_code == 200
        assert "Seq_A" in exp_nwk.text

        exp_csv = client.get(f"/api/phylo/jobs/{job_id}/export/distance_csv")
        assert exp_csv.status_code == 200
        assert "Seq_A" in exp_csv.text

        exp_json = client.get(f"/api/phylo/jobs/{job_id}/export/report_json")
        assert exp_json.status_code == 200

        del_res = client.delete(f"/api/phylo/jobs/{job_id}")
        assert del_res.status_code == 200
        assert client.get(f"/api/phylo/jobs/{job_id}").status_code == 404

        clear_res = client.delete("/api/phylo/workspace")
        assert clear_res.status_code == 200
        assert clear_res.json()["files"] == []

        # 6. 验证只读文件导入后支持单文件删除与整区清空（回归 Windows WinError 5 修复）
        import os
        import stat

        ro_dir = tmp_path / "readonly_src"
        ro_dir.mkdir(parents=True, exist_ok=True)
        ro_files = []
        for idx, name in enumerate(["Sample_A_contig1.fasta", "Sample_B_contig1.fasta", "Sample_C_contig1.fasta"], start=1):
            p = ro_dir / name
            p.write_text(f">contig1\n{'ATGCGTACGT' * (10 + idx)}\n", encoding="utf-8")
            os.chmod(p, stat.S_IREAD)
            ro_files.append(str(p))

        try:
            add_res = client.post("/api/phylo/workspace/add", json={"paths": ro_files})
            assert add_res.status_code == 200
            add_data = add_res.json()
            assert len(add_data["files"]) == 3
            assert add_data["profile"]["duplicate_id_count"] == 0

            # 即使工作区文件被外部标记为只读，也必须能成功单删和清空
            for fitem in add_data["files"]:
                os.chmod(store.workspace_dir / fitem["name"], stat.S_IREAD)

            del_one = client.delete("/api/phylo/workspace/Sample_A_contig1.fasta")
            assert del_one.status_code == 200
            assert len(del_one.json()["files"]) == 2

            clear_ro = client.delete("/api/phylo/workspace")
            assert clear_ro.status_code == 200
            assert clear_ro.json()["files"] == []
        finally:
            for rp in ro_files:
                try:
                    os.chmod(rp, stat.S_IWRITE | stat.S_IREAD)
                except OSError:
                    pass
    finally:
        executor.store = orig_store


def test_recover_interrupted_jobs(tmp_path: Path):
    from src.phylo.models.schemas import PhyloJobConfig, PhyloJobRecord

    store = PhyloArchiveStore(base_dir=tmp_path / "recover_store")
    stale = PhyloJobRecord(
        job_id="stale_running_001",
        title="StaleJob",
        status="running",
        resolved_track="gene",
        config=PhyloJobConfig(),
        created_at=time.time(),
        job_dir=str(tmp_path / "recover_store" / "jobs" / "stale_running_001"),
    )
    store.save_job(stale)
    count = store.recover_interrupted_jobs()
    assert count == 1
    reloaded = store.get_job("stale_running_001")
    assert reloaded is not None
    assert reloaded.status == "failed"
    assert "重启" in (reloaded.error or "")


def test_rmtree_readonly_compatible_with_python311_onerror(tmp_path: Path, monkeypatch):
    import os
    import shutil
    import stat

    from src.phylo.models.schemas import PhyloJobConfig, PhyloJobRecord
    from src.phylo.storage import archive_store

    real_rmtree = shutil.rmtree

    def py311_rmtree(path, ignore_errors=False, onerror=None):
        return real_rmtree(path, ignore_errors=ignore_errors, onerror=onerror)

    monkeypatch.setattr(archive_store.shutil, "rmtree", py311_rmtree)

    store = PhyloArchiveStore(base_dir=tmp_path / "py311_store")
    job_id = "phylo_261125_200946_940705"
    job_dir = store.jobs_dir / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    ro_file = job_dir / "readonly.txt"
    ro_file.write_text("locked", encoding="utf-8")
    os.chmod(ro_file, stat.S_IREAD)

    store.save_job(
        PhyloJobRecord(
            job_id=job_id,
            title="Py311CompatJob",
            status="failed",
            resolved_track="gene",
            config=PhyloJobConfig(),
            created_at=time.time(),
            job_dir=str(job_dir),
        )
    )

    executor = get_phylo_executor()
    orig_store = executor.store
    executor.store = store
    monkeypatch.setattr(phylo_route, "get_phylo_store", lambda: store)
    app = FastAPI()
    app.include_router(phylo_route.router)
    client = TestClient(app)

    try:
        res = client.delete(f"/api/phylo/jobs/{job_id}")
        assert res.status_code == 200
        assert res.json() == {"success": True, "job_id": job_id}
        assert not job_dir.exists()
        assert store.get_job(job_id) is None
    finally:
        executor.store = orig_store
        if ro_file.exists():
            os.chmod(ro_file, stat.S_IWRITE | stat.S_IREAD)


def test_delete_job_tolerates_locked_directory_without_500(tmp_path: Path, monkeypatch):
    from src.phylo.models.schemas import PhyloJobConfig, PhyloJobRecord
    from src.phylo.storage import archive_store

    def always_locked_rmtree(path, **kwargs):
        raise PermissionError(32, "simulated file handle busy", str(path))

    monkeypatch.setattr(archive_store.shutil, "rmtree", always_locked_rmtree)
    monkeypatch.setattr(archive_store.time, "sleep", lambda _sec: None)

    store = PhyloArchiveStore(base_dir=tmp_path / "locked_store")
    job_id = "phylo_locked_001"
    job_dir = store.jobs_dir / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    (job_dir / "job.log").write_text("busy", encoding="utf-8")
    store.save_job(
        PhyloJobRecord(
            job_id=job_id,
            title="LockedJob",
            status="failed",
            resolved_track="gene",
            config=PhyloJobConfig(),
            created_at=time.time(),
            job_dir=str(job_dir),
        )
    )

    executor = get_phylo_executor()
    orig_store = executor.store
    executor.store = store
    monkeypatch.setattr(phylo_route, "get_phylo_store", lambda: store)
    app = FastAPI()
    app.include_router(phylo_route.router)
    client = TestClient(app)

    try:
        res = client.delete(f"/api/phylo/jobs/{job_id}")
        assert res.status_code == 200
        assert res.json()["success"] is True
        assert store.get_job(job_id) is None
    finally:
        executor.store = orig_store


def test_unhandled_500_preserves_cors_header():
    from src.backend import api_server

    route_path = "/api/_test/force-unhandled-500"

    async def boom():
        raise RuntimeError("simulated unhandled crash")

    api_server.app.add_api_route(route_path, boom, methods=["DELETE"])
    added_route = api_server.app.router.routes[-1]
    client = TestClient(api_server.app, raise_server_exceptions=False)
    try:
        res = client.delete(route_path, headers={"Origin": "http://localhost:5173"})
        assert res.status_code == 500
        assert res.headers.get("access-control-allow-origin") == "http://localhost:5173"
        body = res.json()
        assert "detail" in body and "simulated unhandled crash" in body["detail"]
    finally:
        api_server.app.router.routes.remove(added_route)
