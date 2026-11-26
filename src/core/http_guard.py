# -*- coding: utf-8 -*-
"""
安全 HTTP/HTTPS 请求守卫 (http_guard)

统一校验远端 URL 协议白名单（默认仅放行 http/https），杜绝 file:// 等非预期协议注入，
收口全仓 urllib 请求构造、打开与流式下载入口。
"""
from __future__ import annotations

import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Sequence, Union

DEFAULT_ALLOWED_SCHEMES: tuple[str, ...] = ("http", "https")


def validate_http_url(
    url: str,
    *,
    allowed_schemes: Sequence[str] = DEFAULT_ALLOWED_SCHEMES,
) -> str:
    """校验 URL 必须使用白名单协议且包含合法主机名。"""
    cleaned = str(url or "").strip()
    parsed = urllib.parse.urlparse(cleaned)
    scheme = (parsed.scheme or "").lower()
    allowed = {s.lower() for s in allowed_schemes}
    if scheme not in allowed or not parsed.netloc:
        raise ValueError(f"不允许的 URL 协议或非法地址: {cleaned!r} (允许协议: {sorted(allowed)})")
    return cleaned


def build_safe_request(
    url: str,
    *,
    data: Optional[bytes] = None,
    headers: Optional[Dict[str, str]] = None,
    method: Optional[str] = None,
    allowed_schemes: Sequence[str] = DEFAULT_ALLOWED_SCHEMES,
) -> urllib.request.Request:
    """构造经协议白名单校验的 urllib Request 对象。"""
    safe_url = validate_http_url(url, allowed_schemes=allowed_schemes)
    return urllib.request.Request(  # noqa: S310
        safe_url,
        data=data,
        headers=headers or {},
        method=method,
    )


def safe_urlopen(
    url_or_req: Union[str, urllib.request.Request],
    *,
    timeout: float = 20.0,
    allowed_schemes: Sequence[str] = DEFAULT_ALLOWED_SCHEMES,
    opener: Optional[urllib.request.OpenerDirector] = None,
) -> Any:
    """校验目标 URL 协议后安全打开连接，支持自定义 OpenerDirector。"""
    if isinstance(url_or_req, urllib.request.Request):
        validate_http_url(url_or_req.full_url, allowed_schemes=allowed_schemes)
        target: Union[str, urllib.request.Request] = url_or_req
    else:
        target = validate_http_url(url_or_req, allowed_schemes=allowed_schemes)
    if opener is not None:
        return opener.open(target, timeout=timeout)
    return urllib.request.urlopen(target, timeout=timeout)  # noqa: S310


def safe_urlretrieve(
    url: str,
    dest_path: Union[str, Path],
    reporthook: Optional[Callable[[int, int, int], None]] = None,
    *,
    timeout: float = 120.0,
    chunk_size: int = 65536,
    headers: Optional[Dict[str, str]] = None,
    allowed_schemes: Sequence[str] = DEFAULT_ALLOWED_SCHEMES,
) -> Path:
    """经协议校验的流式文件下载，兼容 urlretrieve 进度回调签名。"""
    req = build_safe_request(url, headers=headers, allowed_schemes=allowed_schemes)
    out_path = Path(dest_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with safe_urlopen(req, timeout=timeout, allowed_schemes=allowed_schemes) as resp, open(
        out_path, "wb"
    ) as fh:
        total_raw = resp.headers.get("Content-Length") if hasattr(resp, "headers") else None
        total_size = int(total_raw) if total_raw and str(total_raw).isdigit() else -1
        block_num = 0
        while True:
            chunk = resp.read(chunk_size)
            if not chunk:
                break
            fh.write(chunk)
            block_num += 1
            if reporthook is not None and total_size > 0:
                reporthook(block_num, chunk_size, total_size)
    return out_path
