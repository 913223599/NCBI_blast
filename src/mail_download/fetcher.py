# -*- coding: utf-8 -*-
"""IMAP 收件核心（标准库 imaplib + email，零第三方依赖）。

设计要点：
- 连接对象可注入（_connect 为可重写钩子），自动化测试用 FakeIMAP 替换，
  不触碰真实邮箱账号。
- 两阶段拉取（应对大邮箱）：
  ① 服务端按发件人白名单 FROM 搜索（QQ 邮箱对 SINCE 支持不可靠）；
  ② 分批抓取"头部"做客户端初筛（发件人/主题/时间窗口），只对命中的
     少量邮件抓取全文并做附件级匹配。
"""
import email
import email.header
import email.utils
import logging
import imaplib
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from email.message import Message
from typing import Any, Callable, Iterable, List, Optional, Tuple

logger = logging.getLogger("mail_download.fetcher")

_HEADER_FIELDS = "(FROM SUBJECT DATE MESSAGE-ID)"


@dataclass
class MessageSummary:
    """一封符合筛选条件的邮件（原始邮件保留供附件提取）。"""
    seq: int
    uid: str
    date: Optional[datetime]
    sender: str
    subject: str
    has_attachment: bool
    raw: Message

    @property
    def date_text(self) -> str:
        return self.date.isoformat() if self.date else ""


@dataclass
class FetchResult:
    matched: List[MessageSummary] = field(default_factory=list)
    scanned: int = 0
    skipped_dup_mails: int = 0
    connection_error: Optional[str] = None


def sanitize_filename(name: str) -> str:
    """清洗附件文件名，去掉路径分隔符与非法字符。"""
    name = name.replace("\\", "_").replace("/", "_")
    name = "".join(c if c not in '<>:"|?*' else "_" for c in name).strip()
    return name or "attachment"


def _fmt_imap_date(dt: datetime) -> str:
    return dt.strftime("%d-%b-%Y")


def _to_str(value) -> str:
    """把可能为 str/bytes/email.header.Header 的头值归一为 str。"""
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _parse_date(value) -> Optional[datetime]:
    """解析 Date 头（兼容 Header 实例/bytes/str），失败返回 None；无时区时补本地时区。"""
    text = _to_str(value)
    if not text:
        return None
    try:
        dt = email.utils.parsedate_to_datetime(text)
    except (TypeError, ValueError, OverflowError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.now().astimezone().tzinfo)
    return dt


def _parse_address(raw) -> str:
    """从 From 头提取纯邮箱地址（小写）。"""
    raw = _to_str(raw)
    addr = email.utils.parseaddr(raw)[1]
    return addr.lower() if addr else raw.strip().lower()


def _decode_header(value) -> str:
    value = _to_str(value)
    if not value:
        return ""
    parts = email.header.decode_header(value)
    out = []
    for data, charset in parts:
        if isinstance(data, bytes):
            try:
                out.append(data.decode(charset or "utf-8", errors="replace"))
            except LookupError:
                out.append(data.decode("utf-8", errors="replace"))
        else:
            out.append(data)
    return "".join(out)


def _attachment_parts(msg: Message) -> List[Tuple[str, bytes]]:
    """返回 [(文件名, 字节内容)]；非附件正文部分忽略。"""
    result: List[Tuple[str, bytes]] = []
    for part in msg.walk():
        fn = part.get_filename()
        if not fn:
            continue
        payload = part.get_payload(decode=True)
        if not isinstance(payload, bytes):
            continue
        result.append((sanitize_filename(_decode_header(fn)), payload))
    return result


def _sender_allowed(sender: str, whitelist: Iterable[str]) -> bool:
    wl = [s.strip().lower() for s in whitelist if s and s.strip() and not s.startswith("填写")]
    if not wl:
        return True
    return (sender or "").strip().lower() in wl


def _subject_matches(subject: str, keywords: Iterable[str]) -> bool:
    kws = [k.strip() for k in keywords if k and k.strip() and not k.startswith("填写")]
    if not kws:
        return True
    subj = subject.lower()
    return any(k.lower() in subj for k in kws)


def _extension_ok(name: str, exts: Iterable[str]) -> bool:
    ex = [e.lower() for e in exts if e and e.strip()]
    if not ex:
        return True
    low = name.lower()
    return any(low.endswith(e) for e in ex)


class MailFetcher:
    """IMAP 收件器。conn_factory 可注入（测试用 FakeIMAP）。"""

    def __init__(self, cfg, conn_factory: Optional[Callable[[], Any]] = None):
        self.cfg = cfg
        self._conn_factory = conn_factory

    def _connect(self) -> Any:
        if self._conn_factory is not None:
            return self._conn_factory()
        auth = self.cfg.auth_code
        if not auth:
            raise RuntimeError(
                f"缺少授权码：请设置环境变量 {self.cfg.auth_code_env} 后重试"
            )
        timeout = getattr(self.cfg, "socket_timeout", 60)
        conn = imaplib.IMAP4_SSL(self.cfg.imap_server, self.cfg.imap_port, timeout=timeout)
        conn.login(self.cfg.account, auth)
        return conn

    # ---- 主流程 ----

    def fetch(self, since_days: Optional[int] = None) -> FetchResult:
        """两阶段拉取：FROM 搜索 → 头部初筛 → 命中邮件全文匹配。"""
        since_days = since_days if since_days is not None else self.cfg.since_days
        since_dt = datetime.now().astimezone() - timedelta(days=since_days)
        conn = None
        try:
            conn = self._connect()
            typ, _ = conn.select("INBOX")
            if typ != "OK":
                return FetchResult(connection_error=f"select INBOX 失败: {typ}")

            criteria = self._build_search_criteria(since_dt)
            typ, data = conn.search(None, criteria)
            if typ != "OK" and criteria != "ALL":
                # 部分服务器对 SINCE/FROM 等搜索条件支持不稳定：失败时降级全量
                # 搜索，保证功能不丢（客户端过滤仍生效）。
                logger.warning("服务端搜索 %r 失败(%s)，降级全量搜索", criteria, typ)
                typ, data = conn.search(None, "ALL")
            if typ != "OK":
                return FetchResult(connection_error=f"search 失败: {typ}")

            seq_ids = data[0].split() if data and data[0] else []
            result = FetchResult(scanned=len(seq_ids))
            if not seq_ids:
                return result

            # 阶段①：分批抓头部做初筛（附带同批 Message-ID 去重，保留最新一封）
            candidates, skipped_dup_mails = self._scan_headers(conn, seq_ids, since_dt)
            result.skipped_dup_mails = skipped_dup_mails
            # 阶段②：命中者抓全文，附件级匹配
            for seq in candidates:
                full = self._fetch_full(conn, seq)
                if full is None:
                    continue
                try:
                    summary = self._match(seq, full)
                except Exception as e:
                    logger.warning("解析邮件 %s 失败: %s", seq, e)
                    continue
                if summary is not None:
                    result.matched.append(summary)

            return result
        except Exception as e:
            logger.error("IMAP 会话异常: %s", e)
            return FetchResult(connection_error=str(e))
        finally:
            if conn is not None:
                try:
                    conn.logout()
                except Exception:
                    pass

    def _build_search_criteria(self, since_dt: datetime) -> str:
        """服务端搜索条件构造（通用化）：
        - cfg.imap_search_mode == "all"（或旧配置未显式开启服务端搜索）→ "ALL"；
        - 默认 "since_from"：SINCE 时间窗 + 白名单发件人 FROM，把服务端返回集合
          从全量邮箱压缩到近期+白名单范围，大幅减少头部抓取耗时；
        - 服务端不支持时由 fetch() 自动降级 ALL，客户端过滤始终兜底。"""
        mode = getattr(self.cfg, "imap_search_mode", "since_from")
        if mode == "all":
            return "ALL"
        since = _fmt_imap_date(since_dt)
        senders = [s.strip() for s in self.cfg.sender_whitelist
                   if s and s.strip() and not s.startswith("填写")]
        if not senders:
            return f"SINCE {since}"
        if len(senders) == 1:
            return f'SINCE {since} FROM "{senders[0]}"'
        # 多白名单发件人：RFC3501 OR 两两嵌套
        expr = f'FROM "{senders[0]}"'
        for s in senders[1:]:
            expr = f'(OR {expr} FROM "{s}")'
        return f"SINCE {since} {expr}"

    def _scan_headers(self, conn, seq_ids: List[bytes], since_dt: datetime) -> Tuple[List[int], int]:
        """分批抓取头部，返回 (通过初筛的序号列表, 同批同 Message-ID 去重跳过数)。
        使用序号范围语法（如 1:200），避免长 UID/序号列表被服务器拒绝。"""
        batch = getattr(self.cfg, "batch_size", 200)
        candidates: List[int] = []
        mid_latest: dict[str, int] = {}
        skipped_dup = 0
        for rng in self._chunk_ranges(seq_ids, batch):
            typ, msg_data = conn.fetch(rng, f"(BODY.PEEK[HEADER.FIELDS {_HEADER_FIELDS}])")
            if typ != "OK":
                continue
            for seq, head in self._iter_messages(msg_data):
                sender = _parse_address(_decode_header(head.get("From")))
                subject = _decode_header(head.get("Subject"))
                date = _parse_date(head.get("Date"))
                if date is not None and date < since_dt:
                    continue
                if not _sender_allowed(sender, self.cfg.sender_whitelist):
                    continue
                if not _subject_matches(subject, self.cfg.subject_keywords):
                    continue
                mid = _to_str(head.get("Message-ID")).strip()
                if mid:
                    if mid in mid_latest:
                        skipped_dup += 1
                        prev_seq = mid_latest[mid]
                        if seq > prev_seq:
                            candidates = [s for s in candidates if s != prev_seq]
                            mid_latest[mid] = seq
                            candidates.append(seq)
                        continue
                    mid_latest[mid] = seq
                candidates.append(seq)
        return candidates, skipped_dup

    @staticmethod
    def _chunk_ranges(seq_ids: List[bytes], batch: int) -> List[bytes]:
        """把序号折叠为紧凑 seqset 批：
        - 连续的序号合并为范围（1:200）；
        - 不连续的序号用逗号分隔（2147,3450），避免把稀疏目标之间的
          大量无关邮件一起抓取（此前的范围折叠会拉取中间全部邮件头部）。
        - 超过 batch 时按段分片，防止单条 seqset 过长。
        示例：[2147, 3450] → [b'2147,3450']；1..205 → [b'1:200', b'201:205']。"""
        nums = sorted({int(s) for s in seq_ids if s.strip()})
        if not nums:
            return []
        chunks = []
        for start in range(0, len(nums), batch):
            chunk = nums[start:start + batch]
            seg = []
            seg_lo = prev = chunk[0]
            for n in chunk[1:]:
                if n == prev + 1:
                    prev = n
                    continue
                seg.append(f"{seg_lo}:{prev}" if seg_lo != prev else str(seg_lo))
                seg_lo = prev = n
            seg.append(f"{seg_lo}:{prev}" if seg_lo != prev else str(seg_lo))
            chunks.append(",".join(seg).encode())
        return chunks

    def _fetch_full(self, conn, seq: int) -> Optional[Message]:
        """抓取单封全文。"""
        typ, msg_data = conn.fetch(str(seq).encode(), "(BODY.PEEK[])")
        if typ != "OK" or not msg_data:
            return None
        for _seq, full in self._iter_messages(msg_data):
            return full
        return None

    # ---- 内部 ----

    @staticmethod
    def _flatten_bytes(block) -> bytes:
        out: List[bytes] = []

        def walk(x):
            if isinstance(x, bytes):
                out.append(x)
            elif isinstance(x, (tuple, list)):
                for item in x:
                    walk(item)

        walk(block)
        return b"".join(out)

    def _iter_messages(self, msg_data) -> Iterable[Tuple[int, Message]]:
        """从 fetch 返回块中提取 (序号, 邮件)。内容取块中最长的 bytes 片段
        （IMAP 响应的 seq 前缀很短，头部/全文内容必然最长）。"""
        for block in msg_data:
            if not isinstance(block, tuple):
                continue
            seq = self._extract_seq(block)
            content = self._longest_bytes(block)
            if content:
                raw_msg = email.message_from_bytes(content)
                yield seq, raw_msg

    @staticmethod
    def _extract_seq(block) -> int:
        """递归寻找块内第一个以数字开头的 bytes 前缀作为邮件序号。
        兼容两种真实响应结构：
          全文:  (b'1 (UID 10000)', raw, b')')
          头部:  ((b'1 (BODY[HEADER...', header), b')')"""

        def walk(x):
            if isinstance(x, bytes):
                try:
                    return int(x.split(b" ")[0])
                except (ValueError, IndexError):
                    return None
            if isinstance(x, (tuple, list)):
                for item in x:
                    r = walk(item)
                    if r is not None:
                        return r
            return None

        r = walk(block)
        return r if r is not None else 0

    @staticmethod
    def _longest_bytes(block) -> bytes:
        best = b""
        def walk(x):
            nonlocal best
            if isinstance(x, bytes):
                if len(x) > len(best):
                    best = x
            elif isinstance(x, (tuple, list)):
                for item in x:
                    walk(item)
        walk(block)
        return best

    def _match(self, seq: int, msg: Message) -> Optional[MessageSummary]:
        sender = _parse_address(_decode_header(msg.get("From")))
        subject = _decode_header(msg.get("Subject"))
        date = _parse_date(msg.get("Date"))

        attachments = _attachment_parts(msg)
        matched_att = [
            (name, payload) for name, payload in attachments
            if _extension_ok(name, self.cfg.attachment_exts)
            and len(payload) <= self.cfg.max_attach_size_mb * 1024 * 1024
        ]
        if not matched_att:
            return None

        summary = MessageSummary(
            seq=seq,
            uid=str(seq),
            date=date,
            sender=sender,
            subject=subject,
            has_attachment=True,
            raw=msg,
        )
        summary._matched_attachments = matched_att  # type: ignore[attr-defined]
        return summary
