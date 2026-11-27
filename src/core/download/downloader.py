# -*- coding: utf-8 -*-
"""
通用 HTTP/HTTPS 安全流式下载与单连接断点续传模块 (core.download.downloader)

提供基于 requests 的分片流式下载能力：
1. 强制经 http_guard 校验 http/https 协议白名单；
2. 遵循系统/环境变量代理与 certifi CA 证书链，避开全局 urllib opener 污染；
3. 支持单连接 .part 断点续传与退避重试，大文件自动委托 parallel_downloader 并发拉取；
4. 支持多镜像 URL 自动故障转移 (stream_download_with_mirrors)。
"""
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Protocol, Sequence, Tuple

import requests

from ..http_guard import validate_http_url

logger = logging.getLogger("core.download")

DownloadProgressCallback = Callable[[int, int, float], None]
DEFAULT_USER_AGENT = "Mozilla/5.0 (compatible; NCBI-Bio-Station/2.1)"


class CancelSignal(Protocol):
    """抽象取消信号接口，兼容 threading.Event 与组合取消信号。"""

    def is_set(self) -> bool:
        ...


class DownloadCancelledError(RuntimeError):
    """当用户或同组并发任务触发取消时抛出。"""


@dataclass(frozen=True)
class DownloadConfig:
    """不可变下载参数载体，消除多层透传的长参数列表。"""

    connect_timeout: float = 15.0
    read_timeout: float = 30.0
    max_retries: int = 3
    chunk_size: int = 262144
    log_label: str = ""
    num_threads: int = 4
    min_parallel_size: int = 5 * 1024 * 1024
    bypass_proxy: bool = False


def format_bytes(num_bytes: int) -> str:
    """将字节数格式化为人类可读的 KB / MB / GB 字符串。"""
    if num_bytes < 0:
        return "0 B"
    if num_bytes < 1024:
        return f"{num_bytes} B"
    if num_bytes < 1024 * 1024:
        return f"{num_bytes / 1024:.1f} KB"
    if num_bytes < 1024 * 1024 * 1024:
        return f"{num_bytes / (1024 * 1024):.1f} MB"
    return f"{num_bytes / (1024 * 1024 * 1024):.2f} GB"


def format_download_progress(downloaded: int, total: int, speed_bps: float) -> str:
    """格式化包含已下载体积、总体积与实时速率的状态文本。"""
    speed_text = f"{format_bytes(int(max(0.0, speed_bps)))}/s"
    if total > 0:
        return f"已下载 {format_bytes(downloaded)} / {format_bytes(total)} ({speed_text})"
    return f"已下载 {format_bytes(downloaded)} ({speed_text})"


def create_http_session(bypass_proxy: bool = False) -> requests.Session:
    """构造统一配置的 requests 会话。"""
    session = requests.Session()
    if bypass_proxy:
        session.trust_env = False
        session.proxies = {}
    return session


def load_json_dict(path: Path) -> Dict[str, Any]:
    """安全读取 JSON 字典文件，缺失或损坏返回空字典。"""
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except (OSError, json.JSONDecodeError) as exc:
        logger.debug("读取下载元数据失败，忽略旧断点 (%s): %s", path.name, exc)
        return {}


def save_json_dict(path: Path, payload: Dict[str, Any]) -> None:
    """持久化下载元数据。"""
    try:
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError as exc:
        logger.debug("写入下载元数据失败 (%s): %s", path.name, exc)


def safe_unlink(path: Path) -> None:
    """安全删除临时文件并记录上下文调试日志。"""
    try:
        if path.exists():
            path.unlink()
    except OSError as exc:
        logger.debug("清理临时文件失败 (%s): %s", path.name, exc)


def parse_content_length(header_val: Optional[str]) -> int:
    """解析 Content-Length 字符串为非负整数，缺失或非法返回 -1。"""
    if header_val and str(header_val).strip().isdigit():
        return int(str(header_val).strip())
    return -1


def parse_content_range_total(header_val: Optional[str]) -> int:
    """从 HTTP Content-Range 头中解析文件总字节数，无法解析返回 -1。"""
    if not header_val or "/" not in header_val:
        return -1
    total_part = header_val.rsplit("/", 1)[-1].strip()
    return int(total_part) if total_part.isdigit() else -1


def wait_backoff_with_cancel(seconds: float, cancel_event: Optional[CancelSignal]) -> None:
    """支持及时响应取消信号的重试退避等待。"""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if cancel_event is not None and cancel_event.is_set():
            raise DownloadCancelledError("用户已取消下载")
        time.sleep(min(0.2, max(0.01, deadline - time.monotonic())))


def _resolve_resume_offset(part_path: Path, meta_path: Path, url: str) -> Tuple[int, Dict[str, Any]]:
    """检查本地单流分片与元数据是否匹配当前 URL，返回可用的断点偏移量。"""
    if not part_path.is_file():
        return 0, {}
    size = part_path.stat().st_size
    if size <= 0:
        return 0, {}
    meta = load_json_dict(meta_path)
    if meta and str(meta.get("url") or "") != url:
        safe_unlink(part_path)
        safe_unlink(meta_path)
        return 0, {}
    return size, meta


def _prepare_response_stream(
    resp: requests.Response,
    resume_offset: int,
    meta: Dict[str, Any],
    meta_path: Path,
    url: str,
) -> Tuple[int, int, str]:
    """校验 HTTP 响应状态并决定写入模式 ('ab' 或 'wb')。"""
    etag = str(resp.headers.get("ETag") or "").strip()
    last_modified = str(resp.headers.get("Last-Modified") or "").strip()

    if resp.status_code == 206 and resume_offset > 0:
        cr_total = parse_content_range_total(resp.headers.get("Content-Range"))
        raw_meta_total = meta.get("total_bytes")
        meta_total = raw_meta_total if isinstance(raw_meta_total, int) else -1
        meta_etag = str(meta.get("etag") or "").strip()
        if not (meta_etag and etag and meta_etag != etag) and not (
            meta_total > 0 and cr_total > 0 and meta_total != cr_total
        ):
            total_bytes = cr_total if cr_total > 0 else meta_total
            save_json_dict(
                meta_path,
                {"url": url, "total_bytes": total_bytes, "etag": etag, "last_modified": last_modified},
            )
            return resume_offset, total_bytes, "ab"
        logger.info("远端资源已变更，放弃旧分片并从头下载: %s", url)

    content_len = parse_content_length(resp.headers.get("Content-Length"))
    save_json_dict(
        meta_path,
        {"url": url, "total_bytes": content_len, "etag": etag, "last_modified": last_modified},
    )
    return 0, content_len, "wb"


def _handle_416_range(
    resp: requests.Response,
    resume_offset: int,
    part_path: Path,
    meta_path: Path,
    dest_path: Path,
) -> bool:
    """处理 HTTP 416 Range Not Satisfiable，已完整则落盘并返回 True。"""
    cr_total = parse_content_range_total(resp.headers.get("Content-Range"))
    if cr_total > 0 and resume_offset == cr_total:
        os.replace(part_path, dest_path)
        safe_unlink(meta_path)
        return True
    safe_unlink(part_path)
    safe_unlink(meta_path)
    return False


def _consume_response_chunks(
    resp: requests.Response,
    part_path: Path,
    file_mode: str,
    initial_downloaded: int,
    total_bytes: int,
    cfg: DownloadConfig,
    progress_cb: Optional[DownloadProgressCallback],
    cancel_event: Optional[CancelSignal],
) -> int:
    """流式分块写入单流分片文件，执行取消检测、节流进度回调与心跳日志。"""
    downloaded = initial_downloaded
    start_ts = time.monotonic()
    last_cb_ts = 0.0
    last_cb_pct = -1
    last_log_ts = start_ts

    if progress_cb is not None:
        progress_cb(downloaded, total_bytes, 0.0)

    with (open(part_path, "ab") if file_mode == "ab" else open(part_path, "wb")) as fh:
        for chunk in resp.iter_content(chunk_size=cfg.chunk_size):
            if cancel_event is not None and cancel_event.is_set():
                raise DownloadCancelledError("用户已取消下载")
            if not chunk:
                continue
            fh.write(chunk)
            downloaded += len(chunk)

            now = time.monotonic()
            speed_bps = max(0.0, (downloaded - initial_downloaded) / max(0.05, now - start_ts))
            pct = int(downloaded * 100 / total_bytes) if total_bytes > 0 else -1

            if progress_cb is not None and ((now - last_cb_ts) >= 0.5 or (pct >= 0 and pct > last_cb_pct)):
                progress_cb(downloaded, total_bytes, speed_bps)
                last_cb_ts = now
                last_cb_pct = pct

            if (now - last_log_ts) >= 5.0:
                logger.info(
                    "[%s] %s",
                    cfg.log_label or part_path.name,
                    format_download_progress(downloaded, total_bytes, speed_bps),
                )
                last_log_ts = now

    final_speed = max(0.0, (downloaded - initial_downloaded) / max(0.05, time.monotonic() - start_ts))
    if progress_cb is not None:
        progress_cb(downloaded, total_bytes, final_speed)
    return downloaded


def _attempt_single_download(
    session: requests.Session,
    safe_url: str,
    dest_path: Path,
    cfg: DownloadConfig,
    progress_cb: Optional[DownloadProgressCallback],
    cancel_event: Optional[CancelSignal],
) -> None:
    """执行单次带 Range 断点续传探测的单连接流式下载尝试。"""
    if cancel_event is not None and cancel_event.is_set():
        raise DownloadCancelledError("用户已取消下载")

    part_path = Path(f"{dest_path}.part")
    meta_path = Path(f"{dest_path}.part.meta.json")
    resume_offset, meta = _resolve_resume_offset(part_path, meta_path, safe_url)
    headers: Dict[str, str] = {"User-Agent": DEFAULT_USER_AGENT, "Accept-Encoding": "identity"}
    if resume_offset > 0:
        headers["Range"] = f"bytes={resume_offset}-"
        logger.info("[%s] 尝试断点续传，本地已缓存 %s", cfg.log_label or dest_path.name, format_bytes(resume_offset))

    with session.get(
        safe_url,
        headers=headers,
        stream=True,
        timeout=(cfg.connect_timeout, cfg.read_timeout),
        allow_redirects=True,
    ) as resp:
        if resp.status_code == 416 and resume_offset > 0:
            if _handle_416_range(resp, resume_offset, part_path, meta_path, dest_path):
                return
            raise IOError("本地分片偏移越界，已重置分片准备重新下载")

        resp.raise_for_status()
        if hasattr(resp.raw, "decode_content"):
            resp.raw.decode_content = False

        initial_downloaded, total_bytes, file_mode = _prepare_response_stream(
            resp, resume_offset, meta, meta_path, safe_url
        )
        downloaded = _consume_response_chunks(
            resp=resp,
            part_path=part_path,
            file_mode=file_mode,
            initial_downloaded=initial_downloaded,
            total_bytes=total_bytes,
            cfg=cfg,
            progress_cb=progress_cb,
            cancel_event=cancel_event,
        )

    if total_bytes > 0 and downloaded < total_bytes:
        raise IOError(
            f"下载未完成 ({format_bytes(downloaded)} / {format_bytes(total_bytes)})，将在重试时从断点续传"
        )

    os.replace(part_path, dest_path)
    safe_unlink(meta_path)
    safe_unlink(Path(f"{dest_path}.tmp"))


def _single_stream_download(
    safe_url: str,
    target: Path,
    cfg: DownloadConfig,
    progress_cb: Optional[DownloadProgressCallback],
    cancel_event: Optional[CancelSignal],
) -> Path:
    """单连接流式下载（支持断点续传与退避重试）。"""
    label = cfg.log_label or target.name
    last_exc: Optional[Exception] = None
    attempts = max(1, int(cfg.max_retries))

    with create_http_session(bypass_proxy=cfg.bypass_proxy) as session:
        for attempt in range(1, attempts + 1):
            try:
                _attempt_single_download(session, safe_url, target, cfg, progress_cb, cancel_event)
                return target
            except DownloadCancelledError:
                raise
            except (requests.RequestException, OSError) as exc:
                last_exc = exc
                if attempt >= attempts:
                    break
                backoff = min(8.0, float(2 ** (attempt - 1)))
                logger.warning("[%s] 第 %s/%s 次下载中断 (%s)，%.1fs 后尝试断点续传...", label, attempt, attempts, exc, backoff)
                wait_backoff_with_cancel(backoff, cancel_event)

    raise RuntimeError(f"下载失败（已重试 {attempts} 次）: {last_exc}") from last_exc


def _resolve_download_config(config: Optional[DownloadConfig], kwargs: Dict[str, Any]) -> DownloadConfig:
    """将显式 config 或兼容关键字参数归一化为 DownloadConfig。"""
    if config is not None:
        return config
    defaults = DownloadConfig()
    return DownloadConfig(
        connect_timeout=float(kwargs.get("connect_timeout", defaults.connect_timeout)),
        read_timeout=float(kwargs.get("read_timeout", defaults.read_timeout)),
        max_retries=int(kwargs.get("max_retries", defaults.max_retries)),
        chunk_size=int(kwargs.get("chunk_size", defaults.chunk_size)),
        log_label=str(kwargs.get("log_label", defaults.log_label)),
        num_threads=int(kwargs.get("num_threads", defaults.num_threads)),
        min_parallel_size=int(kwargs.get("min_parallel_size", defaults.min_parallel_size)),
        bypass_proxy=bool(kwargs.get("bypass_proxy", defaults.bypass_proxy)),
    )


def stream_download_file(
    url: str,
    dest_path: Path,
    progress_cb: Optional[DownloadProgressCallback] = None,
    cancel_event: Optional[CancelSignal] = None,
    *,
    config: Optional[DownloadConfig] = None,
    **kwargs: Any,
) -> Path:
    """
    从远端 HTTP/HTTPS 地址流式下载文件至 dest_path。
    自动探测 Range 并发能力：满足阈值时启用多线程分片下载，遇阻自动降级为单连接断点续传。
    """
    from .parallel_downloader import (
        cleanup_parallel_segments,
        parallel_range_download,
        probe_parallel_support,
    )

    cfg = _resolve_download_config(config, kwargs)
    safe_url = validate_http_url(url)
    target = Path(dest_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    label = cfg.log_label or target.name
    single_part_path = Path(f"{target}.part")

    if cfg.num_threads > 1 and not single_part_path.is_file():
        file_meta, supports_range = probe_parallel_support(safe_url, cfg)
        if supports_range and file_meta.total_bytes >= cfg.min_parallel_size:
            workers = min(8, max(2, int(cfg.num_threads)))
            try:
                return parallel_range_download(
                    safe_url=safe_url,
                    target=target,
                    file_meta=file_meta,
                    cfg=cfg,
                    progress_cb=progress_cb,
                    cancel_event=cancel_event,
                )
            except DownloadCancelledError:
                raise
            except Exception as exc:
                logger.warning("[%s] 多线程分片下载受阻 (%s)，自动降级为单连接断点续传模式", label, exc)
                cleanup_parallel_segments(target, workers)

    return _single_stream_download(safe_url, target, cfg, progress_cb, cancel_event)


def stream_download_with_mirrors(
    urls: Sequence[str],
    dest_path: Path,
    progress_cb: Optional[DownloadProgressCallback] = None,
    cancel_event: Optional[CancelSignal] = None,
    *,
    config: Optional[DownloadConfig] = None,
    **kwargs: Any,
) -> Path:
    """依次尝试多个镜像地址下载目标文件，遇到取消信号立即停止绝不切换。"""
    cfg = _resolve_download_config(config, kwargs)
    cleaned: List[str] = []
    seen = set()
    for raw in urls:
        u = str(raw or "").strip()
        if u and u not in seen:
            seen.add(u)
            cleaned.append(u)
    if not cleaned:
        raise ValueError("未提供任何有效的下载镜像地址")

    errors: List[str] = []
    for idx, mirror_url in enumerate(cleaned, 1):
        try:
            return stream_download_file(
                mirror_url,
                dest_path,
                progress_cb=progress_cb,
                cancel_event=cancel_event,
                config=cfg,
            )
        except DownloadCancelledError:
            raise
        except Exception as exc:
            errors.append(f"源#{idx} ({mirror_url}): {exc}")
            if idx < len(cleaned):
                logger.warning("镜像下载失败，切换备用源 (%s/%s): %s", idx, len(cleaned), exc)

    raise RuntimeError("全部下载源均失败: " + " | ".join(errors))
