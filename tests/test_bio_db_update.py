# -*- coding: utf-8 -*-
"""
生物数据库流式下载、多线程 Range 分片、断点续传、NCBI 云端同步与路由编排离线回归测试。
"""
from __future__ import annotations

import asyncio
import io
import json
import tarfile
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import patch

import pytest
import requests

from src.backend.routes import database as db_routes
from src.backend.routes import taxonomy as tax_routes
from src.backend.utils.bio_db.cloud_sync import (
    NcbiCloudMirror,
    sync_ncbi_blast_db_from_cloud,
)
from src.backend.utils.bio_db.downloader import (
    DownloadCancelledError,
    stream_download_file,
    stream_download_with_mirrors,
)
from src.backend.utils.bio_db.providers import (
    BioDatabase,
    Ncbi16SDatabase,
    RdpDatabase,
    SilvaDatabase,
    create_database_provider,
)
from src.backend.utils.bio_db.subprocess_runner import resolve_makeblastdb
from src.backend.utils.bio_db_manager import bio_db_manager

pytestmark = pytest.mark.offline


class _FakeResponse:
    def __init__(
        self,
        payload: bytes = b"",
        status_code: int = 200,
        headers: Optional[Dict[str, str]] = None,
        chunks: Optional[List[bytes]] = None,
        cancel_after_first: Optional[threading.Event] = None,
        json_data: Any = None,
        text: str = "",
    ) -> None:
        self._payload = payload
        self.status_code = status_code
        self.headers = headers or {}
        self._chunks = chunks if chunks is not None else [payload]
        self._cancel_after_first = cancel_after_first
        self._json_data = json_data
        self.text = text
        self.raw = type("_Raw", (), {"decode_content": True})()

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *_args: object) -> bool:
        return False

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")

    def json(self) -> Any:
        return self._json_data

    def iter_content(self, chunk_size: int = 1024):
        for idx, ch in enumerate(self._chunks):
            yield ch
            if idx == 0 and self._cancel_after_first is not None:
                self._cancel_after_first.set()


class _StubRouteDb:
    def __init__(self, tmp_path: Path, mode: str) -> None:
        self.db_id = "stub_db"
        self.name = "Stub DB"
        self.last_error: Optional[str] = None
        self.mode = mode
        self.base_dir = tmp_path

    def get_status(self) -> Dict[str, Any]:
        return {
            "db_id": self.db_id,
            "name": self.name,
            "installed": False,
            "version": "1.0",
            "size_mb": 0.0,
            "last_modified": "未知",
            "category": "测试",
            "url": "https://example.org/stub",
        }

    async def update_database(self, progress_cb: Any = None, cancel_event: Any = None) -> bool:
        if progress_cb:
            progress_cb(42, "下载中 42%")
        if self.mode == "boom":
            raise RuntimeError("模拟未捕获崩溃")
        if self.mode == "cancel":
            while cancel_event is not None and not cancel_event.is_set():
                await asyncio.sleep(0.01)
            raise DownloadCancelledError("已取消")
        return True


def test_stream_download_file_normal_and_progress(tmp_path: Path) -> None:
    payload = b"ABCD" * 2048
    dest = tmp_path / "sample.tar.gz"
    seen_progress: List[tuple[int, int]] = []

    def _fake_get(_url: str, **_kwargs: Any) -> _FakeResponse:
        return _FakeResponse(
            payload,
            status_code=200,
            headers={"Content-Length": str(len(payload)), "ETag": '"v1"'},
            chunks=[payload[:4096], payload[4096:]],
        )

    with patch("requests.Session.get", side_effect=_fake_get):
        out = stream_download_file(
            "https://example.org/db.tar.gz",
            dest,
            progress_cb=lambda dl, tot, _spd: seen_progress.append((dl, tot)),
            num_threads=1,
        )

    assert out == dest
    assert dest.read_bytes() == payload
    assert not Path(f"{dest}.part").exists()
    assert not Path(f"{dest}.part.meta.json").exists()
    assert seen_progress[-1] == (len(payload), len(payload))


def test_stream_download_file_resumes_with_range_206(tmp_path: Path) -> None:
    full_payload = b"0123456789ABCDEF" * 64
    split_pos = 256
    dest = tmp_path / "resume.tar.gz"
    url = "https://example.org/resume.tar.gz"

    Path(f"{dest}.part").write_bytes(full_payload[:split_pos])
    Path(f"{dest}.part.meta.json").write_text(
        json.dumps({"url": url, "total_bytes": len(full_payload), "etag": '"r1"'}),
        encoding="utf-8",
    )

    seen_headers: List[Dict[str, str]] = []

    def _fake_get(_url: str, headers: Dict[str, str], **_kwargs: Any) -> _FakeResponse:
        seen_headers.append(dict(headers))
        return _FakeResponse(
            full_payload[split_pos:],
            status_code=206,
            headers={
                "Content-Range": f"bytes {split_pos}-{len(full_payload) - 1}/{len(full_payload)}",
                "ETag": '"r1"',
            },
        )

    with patch("requests.Session.get", side_effect=_fake_get):
        stream_download_file(url, dest, num_threads=1)

    assert seen_headers[0].get("Range") == f"bytes={split_pos}-"
    assert dest.read_bytes() == full_payload


def test_stream_download_file_falls_back_to_full_on_200_and_retries_truncated(tmp_path: Path) -> None:
    full_payload = b"XYZ" * 100
    dest = tmp_path / "fallback.gz"
    Path(f"{dest}.part").write_bytes(b"STALE")

    calls = 0

    def _fake_get(_url: str, **_kwargs: Any) -> _FakeResponse:
        nonlocal calls
        calls += 1
        if calls == 1:
            return _FakeResponse(
                full_payload[:50],
                status_code=200,
                headers={"Content-Length": str(len(full_payload))},
            )
        return _FakeResponse(
            full_payload[50:],
            status_code=206,
            headers={"Content-Range": f"bytes 50-{len(full_payload) - 1}/{len(full_payload)}"},
        )

    with (
        patch("requests.Session.get", side_effect=_fake_get),
        patch("src.core.download.downloader.wait_backoff_with_cancel"),
    ):
        stream_download_file("https://example.org/fallback.gz", dest, max_retries=2, num_threads=1)

    assert calls == 2
    assert dest.read_bytes() == full_payload


def test_stream_download_file_cancel_preserves_part_and_rejects_bad_scheme(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="不允许的 URL 协议"):
        stream_download_file("file:///etc/passwd", tmp_path / "bad.bin", num_threads=1)

    dest = tmp_path / "cancel.tar.gz"
    cancel_ev = threading.Event()
    payload = b"A" * 2048

    def _fake_get(_url: str, **_kwargs: Any) -> _FakeResponse:
        return _FakeResponse(
            payload,
            status_code=200,
            headers={"Content-Length": str(len(payload))},
            chunks=[payload[:1024], payload[1024:]],
            cancel_after_first=cancel_ev,
        )

    with (
        patch("requests.Session.get", side_effect=_fake_get),
        pytest.raises(DownloadCancelledError),
    ):
        stream_download_file("https://example.org/cancel.tar.gz", dest, cancel_event=cancel_ev, num_threads=1)

    assert not dest.exists()
    assert Path(f"{dest}.part").exists()


def test_stream_download_parallel_range_and_merge(tmp_path: Path) -> None:
    payload = bytes((i % 251 for i in range(4096)))
    dest = tmp_path / "parallel.bin"
    seen_ranges: List[str] = []
    seen_progress: List[tuple[int, int]] = []

    def _fake_head(_self: Any, _url: str, **_kwargs: Any) -> _FakeResponse:
        return _FakeResponse(
            status_code=200,
            headers={"Content-Length": str(len(payload)), "Accept-Ranges": "bytes", "ETag": '"p1"'},
        )

    def _fake_get(_self: Any, _url: str, headers: Dict[str, str], **_kwargs: Any) -> _FakeResponse:
        rng = headers.get("Range", "")
        seen_ranges.append(rng)
        s_str, e_str = rng.replace("bytes=", "").split("-")
        start, end = int(s_str), int(e_str)
        return _FakeResponse(
            payload[start : end + 1],
            status_code=206,
            headers={"Content-Range": f"bytes {start}-{end}/{len(payload)}"},
        )

    with (
        patch("requests.Session.head", _fake_head),
        patch("requests.Session.get", _fake_get),
    ):
        out = stream_download_file(
            "https://example.org/parallel.bin",
            dest,
            progress_cb=lambda dl, tot, _spd: seen_progress.append((dl, tot)),
            num_threads=4,
            min_parallel_size=1024,
        )

    assert out == dest
    assert dest.read_bytes() == payload
    assert len(seen_ranges) == 4
    assert not list(tmp_path.glob("parallel.bin.seg.*"))
    assert not Path(f"{dest}.segs.meta.json").exists()
    assert seen_progress[-1] == (len(payload), len(payload))


def test_stream_download_parallel_segment_resume(tmp_path: Path) -> None:
    payload = b"0123456789" * 100
    url = "https://example.org/seg_resume.bin"
    dest = tmp_path / "seg_resume.bin"

    Path(f"{dest}.seg.0").write_bytes(payload[:200])
    Path(f"{dest}.segs.meta.json").write_text(
        json.dumps({"url": url, "total_bytes": len(payload), "workers": 2, "etag": '"sr1"'}),
        encoding="utf-8",
    )
    seen_ranges: List[str] = []

    def _fake_head(_self: Any, _url: str, **_kwargs: Any) -> _FakeResponse:
        return _FakeResponse(
            status_code=200,
            headers={"Content-Length": str(len(payload)), "Accept-Ranges": "bytes", "ETag": '"sr1"'},
        )

    def _fake_get(_self: Any, _url: str, headers: Dict[str, str], **_kwargs: Any) -> _FakeResponse:
        rng = headers.get("Range", "")
        seen_ranges.append(rng)
        s_str, e_str = rng.replace("bytes=", "").split("-")
        start, end = int(s_str), int(e_str)
        return _FakeResponse(
            payload[start : end + 1],
            status_code=206,
            headers={"Content-Range": f"bytes {start}-{end}/{len(payload)}"},
        )

    with (
        patch("requests.Session.head", _fake_head),
        patch("requests.Session.get", _fake_get),
    ):
        stream_download_file(url, dest, num_threads=2, min_parallel_size=500)

    assert sorted(seen_ranges) == ["bytes=200-499", "bytes=500-999"]
    assert dest.read_bytes() == payload


def test_stream_download_parallel_fallback_to_single_stream(tmp_path: Path) -> None:
    payload = b"FALLBACK" * 200
    dest = tmp_path / "fallback_single.bin"

    def _fake_head(_self: Any, _url: str, **_kwargs: Any) -> _FakeResponse:
        return _FakeResponse(
            status_code=200,
            headers={"Content-Length": str(len(payload)), "Accept-Ranges": "bytes"},
        )

    def _fake_get(_self: Any, _url: str, headers: Dict[str, str], **_kwargs: Any) -> _FakeResponse:
        if "Range" in headers:
            return _FakeResponse(status_code=503)
        return _FakeResponse(payload, status_code=200, headers={"Content-Length": str(len(payload))})

    with (
        patch("requests.Session.head", _fake_head),
        patch("requests.Session.get", _fake_get),
        patch("src.core.download.downloader.wait_backoff_with_cancel"),
    ):
        stream_download_file("https://example.org/fb.bin", dest, num_threads=2, min_parallel_size=500, max_retries=1)

    assert dest.read_bytes() == payload


def test_stream_download_with_mirrors_failover_and_cancel(tmp_path: Path) -> None:
    dest = tmp_path / "mirror.bin"
    payload = b"MIRROR_OK"

    def _fake_dl(url: str, dest_path: Path, **_kwargs: Any) -> Path:
        if "bad-mirror" in url:
            raise RuntimeError("连接超时")
        Path(dest_path).write_bytes(payload)
        return Path(dest_path)

    with patch("src.core.download.downloader.stream_download_file", side_effect=_fake_dl):
        out = stream_download_with_mirrors(["https://bad-mirror.org/a.gz", "https://good-mirror.org/a.gz"], dest)
    assert out == dest
    assert dest.read_bytes() == payload

    called_urls: List[str] = []

    def _cancel_dl(url: str, _dest_path: Path, **_kwargs: Any) -> Path:
        called_urls.append(url)
        raise DownloadCancelledError("已取消")

    with (
        patch("src.core.download.downloader.stream_download_file", side_effect=_cancel_dl),
        pytest.raises(DownloadCancelledError),
    ):
        stream_download_with_mirrors(["https://m1.org/a.gz", "https://m2.org/a.gz"], dest)
    assert called_urls == ["https://m1.org/a.gz"]


def test_ncbi_cloud_sync_gcp_success_and_skip_existing_taxdb(tmp_path: Path) -> None:
    (tmp_path / "taxdb.btd").write_bytes(b"local-btd")
    (tmp_path / "taxdb.bti").write_bytes(b"local-bti")

    mirror = NcbiCloudMirror("GCP 测试源", "https://storage.googleapis.com/blast-db")
    meta_json = {
        "dbname": "16S_ribosomal_RNA",
        "last-updated": "2026-10-22T00:00:00",
        "bytes-total": 200,
        "files": [
            "gs://blast-db/2026-10-22-01-05-01/16S_ribosomal_RNA.nsq",
            "gs://blast-db/2026-10-22-01-05-01/16S_ribosomal_RNA.nhr",
        ],
    }
    downloaded_urls: List[str] = []

    def _fake_get(_self: Any, url: str, **_kwargs: Any) -> _FakeResponse:
        if url.endswith("/latest-dir"):
            return _FakeResponse(status_code=200, text="2026-10-22-01-05-01\n")
        return _FakeResponse(status_code=200, json_data=meta_json)

    def _fake_stream(url: str, dest_path: Path, progress_cb: Any = None, **_kwargs: Any) -> Path:
        downloaded_urls.append(url)
        content = f"content-of-{Path(dest_path).name}".encode("utf-8")
        if progress_cb:
            progress_cb(len(content), len(content), 10000.0)
        Path(dest_path).write_bytes(content)
        return Path(dest_path)

    reported: List[tuple[int, str]] = []
    with (
        patch("requests.Session.get", _fake_get),
        patch("src.backend.utils.bio_db.cloud_sync.stream_download_file", side_effect=_fake_stream),
    ):
        info = sync_ncbi_blast_db_from_cloud(
            "16S_ribosomal_RNA",
            tmp_path,
            require_taxdb=True,
            progress_cb=lambda p, m: reported.append((p, m)),
            mirrors=[mirror],
        )

    assert info["source"] == "GCP 测试源"
    assert info["last_updated"] == "2026-10-22T00:00:00"
    assert (tmp_path / "16S_ribosomal_RNA.nsq").is_file()
    assert (tmp_path / "16S_ribosomal_RNA-nucl-metadata.json").is_file()
    assert not any("taxdb" in u for u in downloaded_urls)
    assert not (tmp_path / ".cloud_staging").exists()
    assert any(p >= 90 for p, _ in reported)


def test_ncbi_cloud_sync_failover_to_aws_and_reject_path_traversal(tmp_path: Path) -> None:
    m_bad = NcbiCloudMirror("坏 GCP 源", "https://storage.googleapis.com/blast-db")
    m_aws = NcbiCloudMirror("AWS S3 源", "https://ncbi-blast-databases.s3.amazonaws.com", bypass_proxy=True)

    def _fake_get(_self: Any, url: str, **_kwargs: Any) -> _FakeResponse:
        if "googleapis" in url:
            raise requests.ConnectionError("GCP unreachable")
        if url.endswith("/latest-dir"):
            return _FakeResponse(status_code=200, text="2026-10-22-01-05-01")
        return _FakeResponse(
            status_code=200,
            json_data={
                "last-updated": "2026-10-22T00:00:00",
                "bytes-total": 64,
                "files": ["s3://ncbi-blast-databases/2026-10-22-01-05-01/16S_ribosomal_RNA.nsq"],
            },
        )

    def _fake_stream(url: str, dest_path: Path, **_kwargs: Any) -> Path:
        assert "amazonaws.com" in url
        Path(dest_path).write_bytes(b"aws-ok")
        return Path(dest_path)

    with (
        patch("requests.Session.get", _fake_get),
        patch("src.backend.utils.bio_db.cloud_sync.stream_download_file", side_effect=_fake_stream),
    ):
        info = sync_ncbi_blast_db_from_cloud("16S_ribosomal_RNA", tmp_path, require_taxdb=False, mirrors=[m_bad, m_aws])
    assert info["source"] == "AWS S3 源"
    assert (tmp_path / "16S_ribosomal_RNA.nsq").read_bytes() == b"aws-ok"

    def _evil_get(_self: Any, url: str, **_kwargs: Any) -> _FakeResponse:
        if url.endswith("/latest-dir"):
            return _FakeResponse(status_code=200, text="2026-10-22")
        return _FakeResponse(status_code=200, json_data={"files": ["../../etc/passwd"]})

    with (
        patch("requests.Session.get", _evil_get),
        pytest.raises(RuntimeError, match="非法路径穿越"),
    ):
        sync_ncbi_blast_db_from_cloud("16S_ribosomal_RNA", tmp_path, require_taxdb=False, mirrors=[m_aws])


def test_ncbi_cloud_sync_aborts_sibling_workers_on_failure(tmp_path: Path) -> None:
    mirror = NcbiCloudMirror("并发联动源", "https://storage.googleapis.com/blast-db")
    sibling_aborted = threading.Event()

    def _fake_get(_self: Any, url: str, **_kwargs: Any) -> _FakeResponse:
        if url.endswith("/latest-dir"):
            return _FakeResponse(status_code=200, text="2026-10-22")
        return _FakeResponse(
            status_code=200,
            json_data={
                "bytes-total": 100,
                "files": ["gs://blast-db/2026-10-22/a.nsq", "gs://blast-db/2026-10-22/b.nhr"],
            },
        )

    def _fake_stream(url: str, dest_path: Path, cancel_event: Any = None, **_kwargs: Any) -> Path:
        if url.endswith("a.nsq"):
            raise RuntimeError("首个文件失败")
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            if cancel_event is not None and cancel_event.is_set():
                sibling_aborted.set()
                raise DownloadCancelledError("联动中止")
            time.sleep(0.01)
        Path(dest_path).write_bytes(b"slow")
        return Path(dest_path)

    with (
        patch("requests.Session.get", _fake_get),
        patch("src.backend.utils.bio_db.cloud_sync.stream_download_file", side_effect=_fake_stream),
        pytest.raises(RuntimeError, match="首个文件失败"),
    ):
        sync_ncbi_blast_db_from_cloud(
            "16S_ribosomal_RNA",
            tmp_path,
            require_taxdb=False,
            mirrors=[mirror],
            max_workers=2,
        )

    assert sibling_aborted.is_set() is True


def test_rdp_instantiated_as_rdp_database_and_makeblastdb_resolution(tmp_path: Path) -> None:
    rdp_inst = create_database_provider(
        "rdp",
        {"name": "RDP", "url": "https://example.org/rdp.fa.gz", "version": "18", "local_folder": "16S/rdp"},
    )
    silva_inst = create_database_provider(
        "silva",
        {"name": "SILVA", "url": "https://example.org/silva.fa.gz", "version": "138.1", "local_folder": "16S/silva"},
    )
    assert isinstance(rdp_inst, RdpDatabase)
    assert isinstance(silva_inst, SilvaDatabase)

    fake_bin = tmp_path / "makeblastdb.exe"
    fake_bin.write_text("stub", encoding="utf-8")
    with patch("src.workbench.models.tool_config.ToolConfig.resolve_bio_tool", return_value=fake_bin) as mock_res:
        resolved = resolve_makeblastdb()
        mock_res.assert_called_once_with("makeblastdb")
        assert Path(resolved).exists()
        assert Path(resolved).suffix.lower() == ".exe"


def test_ncbi_16s_cloud_first_and_ftp_fallback(tmp_path: Path) -> None:
    db = Ncbi16SDatabase.__new__(Ncbi16SDatabase)
    db.db_id = "ncbi_16s_test"
    db.name = "NCBI 16S Test"
    db.last_error = None
    db.base_dir = tmp_path / "16S_ncbi"
    db.base_dir.mkdir(parents=True, exist_ok=True)
    db.config = {
        "name": "NCBI 16S Test",
        "url": "https://example.org/16S.tar.gz",
        "version": "2026-01",
        "local_folder": "16S/ncbi",
    }

    BioDatabase.clear_dir_info_cache()
    with (
        patch(
            "src.backend.utils.bio_db.providers.sync_ncbi_blast_db_from_cloud",
            return_value={"source": "GCP", "last_updated": "2026-10-22T00:00:00"},
        ),
        patch.object(db, "_update_registry_version") as mock_ver_cloud,
    ):
        ok_cloud = asyncio.run(db.update_database(progress_cb=lambda _p, _m: None))
    assert ok_cloud is True
    mock_ver_cloud.assert_called_once_with("2026-10")

    tar_buf = io.BytesIO()
    with tarfile.open(fileobj=tar_buf, mode="w:gz") as tf:
        data = b"fake-nsq-content"
        ti = tarfile.TarInfo("16S_ribosomal_RNA.nsq")
        ti.size = len(data)
        tf.addfile(ti, io.BytesIO(data))
    tar_bytes = tar_buf.getvalue()

    def _fake_mirrors(_urls: Any, dest_path: Path, progress_cb: Any = None, _cancel_event: Any = None, **_kwargs: Any) -> Path:
        if progress_cb:
            progress_cb(len(tar_bytes), len(tar_bytes), 102400.0)
        Path(dest_path).write_bytes(tar_bytes)
        return Path(dest_path)

    reported: List[tuple[int, str]] = []
    with (
        patch("src.backend.utils.bio_db.providers.sync_ncbi_blast_db_from_cloud", side_effect=RuntimeError("cloud down")),
        patch("src.backend.utils.bio_db.providers.stream_download_with_mirrors", side_effect=_fake_mirrors),
        patch.object(db, "_update_registry_version") as mock_ver_ftp,
    ):
        ok_ftp = asyncio.run(db.update_database(progress_cb=lambda p, m: reported.append((p, m))))

    assert ok_ftp is True
    assert (db.base_dir / "16S_ribosomal_RNA.nsq").exists()
    mock_ver_ftp.assert_called_once()
    assert any(p >= 45 for p, _ in reported)


def test_database_routes_error_reentry_and_cancel(tmp_path: Path) -> None:
    events: List[tuple[str, Dict[str, Any]]] = []

    async def _fake_broadcast(ev_type: str, data: Optional[Dict[str, Any]] = None, **_kw: Any) -> None:
        events.append((ev_type, dict(data or {})))

    def _fake_broadcast_sync(ev_type: str, data: Optional[Dict[str, Any]] = None, **_kw: Any) -> None:
        events.append((ev_type, dict(data or {})))

    original_dbs = dict(bio_db_manager.dbs)
    try:
        bio_db_manager.dbs["stub_db"] = _StubRouteDb(tmp_path, "boom")  # type: ignore[assignment]
        bio_db_manager.clear_update_state("stub_db")

        async def _run_boom() -> None:
            with (
                patch.object(db_routes.broadcaster, "broadcast", side_effect=_fake_broadcast),
                patch.object(db_routes.broadcaster, "broadcast_sync", side_effect=_fake_broadcast_sync),
            ):
                res = await db_routes.trigger_db_update("stub_db")
                assert res["success"] is True
                res2 = await db_routes.trigger_db_update("stub_db")
                assert res2["already_running"] is True
                st = await db_routes.get_all_db_status()
                stub_row = next(x for x in st["data"] if x["db_id"] == "stub_db")
                assert stub_row["update_state"]["status"] == "updating"
                await bio_db_manager.wait_active_updates()

        asyncio.run(_run_boom())
        assert bio_db_manager.is_updating("stub_db") is False
        assert events[-1][1]["status"] == "error"
        assert "模拟未捕获崩溃" in events[-1][1]["message"]

        events.clear()
        bio_db_manager.dbs["stub_db"] = _StubRouteDb(tmp_path, "cancel")  # type: ignore[assignment]
        bio_db_manager.clear_update_state("stub_db")

        async def _run_cancel() -> None:
            with (
                patch.object(db_routes.broadcaster, "broadcast", side_effect=_fake_broadcast),
                patch.object(db_routes.broadcaster, "broadcast_sync", side_effect=_fake_broadcast_sync),
            ):
                res = await db_routes.trigger_db_update("stub_db")
                assert res["success"] is True
                await asyncio.sleep(0.03)
                c_res = await db_routes.cancel_db_update("stub_db")
                assert c_res["success"] is True
                await bio_db_manager.wait_active_updates()

        asyncio.run(_run_cancel())
        assert bio_db_manager.is_updating("stub_db") is False
        assert events[-1][1]["status"] == "cancelled"
    finally:
        bio_db_manager.dbs = original_dbs  # type: ignore[assignment]
        bio_db_manager.clear_update_state("stub_db")


def test_taxonomy_provider_multi_source_download_and_cancel(tmp_path: Path) -> None:
    from src.utils.taxonomy_provider import TaxonomyProvider

    prov = TaxonomyProvider.__new__(TaxonomyProvider)
    prov._local = threading.local()
    prov._is_building = False
    prov._build_progress = ""
    prov._status_code = "idle"
    prov._cancel_event = threading.Event()

    dest = tmp_path / "taxdump.tar.gz"
    seen_urls: List[str] = []

    def _fake_stream(
        url: str,
        dest_path: Path,
        progress_cb: Any = None,
        cancel_event: Any = None,
        **_kwargs: Any,
    ) -> Path:
        seen_urls.append(url)
        if url.startswith("https://ftp.ncbi.nih.gov/"):
            raise RuntimeError("直连失败测试切换")
        if progress_cb:
            progress_cb(50, 100, 138 * 1024.0)
        Path(dest_path).write_bytes(b"ddbj-taxdump")
        return Path(dest_path)

    with patch("src.core.download.stream_download_file", side_effect=_fake_stream):
        prov._download_taxdump(dest)

    assert dest.read_bytes() == b"ddbj-taxdump"
    assert len(seen_urls) == 2 and "ddbj.nig.ac.jp" in seen_urls[1]
    assert "DDBJ 日本官方镜像" in prov.build_progress and "50.0%" in prov.build_progress

    # 验证取消流程与路由契约
    prov._is_building = True
    prov._status_code = "building"
    prov._cancel_event = threading.Event()
    with patch("src.backend.routes.taxonomy.get_taxonomy_provider", return_value=prov):
        res = asyncio.run(tax_routes.cancel_taxonomy_update())
    assert res["success"] is True
    assert prov._cancel_event.is_set() is True

    def _fake_cancel_stream(*_args: Any, cancel_event: Any = None, **_kwargs: Any) -> Path:
        assert cancel_event is not None and cancel_event.is_set()
        raise DownloadCancelledError("已取消")

    with (
        patch.object(prov, "_ensure_ete4_path"),
        patch("src.core.download.stream_download_file", side_effect=_fake_cancel_stream),
    ):
        prov._build_worker(force_download=True, skip_if_same=False)

    st = prov.get_status()
    assert st["building"] is False
    assert st["status"] == "cancelled"
    assert "已取消" in st["progress"]

