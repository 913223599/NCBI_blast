# -*- coding: utf-8 -*-
"""
生工 16S 测序结果官网自动登录与压缩包下载服务模块
职责：
1. 以单一浏览器会话登录 passport.sangon.com（遇可见人机验证立即中止报错，绝不绕过）；
2. 自动进入订单详情页全选样品、勾选服务条款、按需自动确认 KBSeq 费用弹窗；
3. 将压缩包写入临时文件并校验 Zip 完整性后原子落盘至 <订单目录>/原始压缩包/；
4. 批量执行前优先尝试从本机浏览器下载目录认领已有包，减少重复拉取。
"""
import logging
import re
import time
import zipfile
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional

from .sangon_ignore_rules import list_ignored_orders, normalize_order_key
from .sangon_mail_scanner import SangonMailIndex, create_sangon_subdirs
from .sangon_zip_importer import import_order_zips_from_downloads

logger = logging.getLogger("api.other_tools.sangon_downloader")

_INVALID_FILENAME_CHARS_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_SEQ_EXTS = (".fasta", ".fa", ".fas", ".fna", ".seq", ".ab1", ".abi")

_CAPTCHA_SELECTORS = (
    "#aliyunCaptcha-window-popup",
    "#aliyunCaptcha-mask",
    ".nc_wrapper",
    ".nc-container",
    "#nc_1_wrapper",
    "[class*='captcha'][style*='display: block']",
    "text=请完成安全验证",
    "text=请拖动滑块",
    "text=点击按钮进行验证",
    "text=人机验证",
)


class SangonCaptchaError(RuntimeError):
    """生工网页意外弹出可见安全/人机验证，需要人工介入。"""


class SangonLoginError(RuntimeError):
    """生工账号或密码登录失败。"""


class SangonOrderDownloadError(RuntimeError):
    """单个生工订单下载过程中发生业务或网络错误。"""


def build_sangon_order_url(cx_order_id: str = "", download_url: str = "") -> str:
    """规范化生工订单详情页 URL，优先使用稳定的 http://store.sangon.com 入口。"""
    cx = (cx_order_id or "").strip()
    if cx:
        return f"http://store.sangon.com/cxOrderDetail?cxOrderDetail.cxOrderID={cx}"
    url = (download_url or "").strip()
    if not url:
        return ""
    if url.startswith("https://store.sangon.com/"):
        return "http://" + url[len("https://"):]
    return url


def sanitize_zip_filename(raw_name: str, order_no: str) -> str:
    cleaned = _INVALID_FILENAME_CHARS_RE.sub("_", (raw_name or "").strip())
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if not cleaned:
        cleaned = f"{order_no}_测序结果.zip"
    if not cleaned.lower().endswith(".zip"):
        cleaned = f"{cleaned}.zip"
    return cleaned


def detect_visible_captcha(page: Any) -> str:
    """检测页面当前是否出现真正可见的人机/滑块验证浮层。"""
    for sel in _CAPTCHA_SELECTORS:
        try:
            loc = page.locator(sel)
            if loc.count() > 0 and loc.first.is_visible():
                return sel
        except Exception:
            continue
    return ""


def _validate_zip_file(zip_path: Path) -> int:
    """校验下载的压缩包非空且可完整读取 Zip 目录，返回内部文件条目数。"""
    if not zip_path.is_file() or zip_path.stat().st_size <= 0:
        raise SangonOrderDownloadError("下载到的文件为空")
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            names = zf.namelist()
            if not names:
                raise SangonOrderDownloadError("压缩包内不含任何文件")
            if "测序" not in zip_path.name and not any(n.lower().endswith(_SEQ_EXTS) for n in names):
                raise SangonOrderDownloadError("压缩包内未识别出测序序列或峰图文件")
            return len(names)
    except zipfile.BadZipFile as exc:
        raise SangonOrderDownloadError(f"压缩包损坏或未完整下载: {exc}") from exc


class SangonBrowserSession:
    """复用单一 Chromium 上下文登录生工网站并顺序下载订单结果包。"""

    def __init__(
        self,
        account: str,
        password: str,
        *,
        headless: bool = True,
        timeout_ms: int = 90000,
    ):
        self.account = (account or "").strip()
        self.password = password or ""
        self.headless = headless
        self.timeout_ms = timeout_ms
        self._pw_cm: Any = None
        self._pw: Any = None
        self._browser: Any = None
        self._ctx: Any = None
        self._page: Any = None

    def __enter__(self) -> "SangonBrowserSession":
        if not self.account or not self.password:
            raise SangonLoginError("生工账号或登录密码未配置")
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise SangonOrderDownloadError(f"缺少 Playwright 运行环境，无法启动自动下载: {exc}") from exc

        self._pw_cm = sync_playwright()
        self._pw = self._pw_cm.__enter__()
        self._browser = self._pw.chromium.launch(headless=self.headless)
        self._ctx = self._browser.new_context(
            viewport={"width": 1366, "height": 900},
            accept_downloads=True,
        )
        self._page = self._ctx.new_page()
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        try:
            if self._ctx is not None:
                self._ctx.close()
        except Exception:
            pass
        try:
            if self._browser is not None:
                self._browser.close()
        except Exception:
            pass
        try:
            if self._pw_cm is not None:
                self._pw_cm.__exit__(exc_type, exc, tb)
        except Exception:
            pass
        return False

    def _wait_stable_order_page(self) -> None:
        page = self._page
        page.wait_for_url(
            lambda u: "store.sangon.com" in u and "cxOrderDetail" in u and "ticket=" not in u and "code=" not in u,
            timeout=25000,
        )
        last_url = page.url
        for _ in range(10):
            try:
                page.wait_for_load_state("networkidle", timeout=10000)
            except Exception:
                pass
            page.wait_for_timeout(350)
            try:
                if page.url == last_url and page.locator("#cxSelectAll").count() > 0:
                    break
            except Exception:
                pass
            last_url = page.url

    def _ensure_order_page_ready(
        self,
        url: str,
        log_cb: Optional[Callable[[str], None]] = None,
    ) -> None:
        page = self._page
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        try:
            page.wait_for_load_state("networkidle", timeout=10000)
        except Exception:
            pass

        if "passport.sangon.com" in page.url:
            gate = detect_visible_captcha(page)
            if gate:
                raise SangonCaptchaError(f"生工登录页出现人机验证 ({gate})，请改用「打开下载页」手动下载")

            if log_cb:
                log_cb("正在自动登录生工账号 (passport.sangon.com)...")

            user_input = page.locator("input[type='text'], input[placeholder*='手机'], input[placeholder*='账号']").first
            pwd_input = page.locator("input[type='password']").first
            login_btn = page.locator("button:has-text('登')").first

            user_input.wait_for(state="visible", timeout=15000)
            user_input.fill(self.account)
            pwd_input.fill(self.password)
            login_btn.click()

            # 等待跳回 store.sangon.com，若仍留在登录页则立刻排查验证码或账号密码报错
            deadline = time.monotonic() + 25.0
            while time.monotonic() < deadline:
                cur_url = page.url
                if "store.sangon.com" in cur_url and "cxOrderDetail" in cur_url and "passport.sangon.com" not in cur_url:
                    break
                gate_after = detect_visible_captcha(page)
                if gate_after:
                    raise SangonCaptchaError(
                        f"生工提交登录时触发安全验证 ({gate_after})，请点击「打开下载页」手动验证下载"
                    )
                try:
                    err_loc = page.locator(".error-msg, .el-form-item__error, .ant-message-error, [class*='errorTip']").first
                    if err_loc.count() > 0 and err_loc.is_visible():
                        err_txt = (err_loc.inner_text() or "").strip()
                        if err_txt:
                            raise SangonLoginError(f"生工账号登录被拒绝: {err_txt}")
                except SangonLoginError:
                    raise
                except Exception:
                    pass
                page.wait_for_timeout(300)

            if "passport.sangon.com" in page.url:
                raise SangonLoginError("登录生工超时，未跳转至订单详情页，请核对生工账号与密码")

        self._wait_stable_order_page()

    def download_order(
        self,
        order_meta: Dict[str, Any],
        *,
        auto_confirm_fee: bool = True,
        log_cb: Optional[Callable[[str], None]] = None,
    ) -> Dict[str, Any]:
        """在当前会话内打开指定订单页面并下载测序结果 zip 到 <order_dir>/原始压缩包/。"""
        page = self._page
        order_no = str(order_meta.get("order_no") or "").strip()
        dir_name = str(order_meta.get("dir_name") or "").strip()
        order_path = Path(order_meta["order_path"])
        url = build_sangon_order_url(
            cx_order_id=str(order_meta.get("cx_order_id") or ""),
            download_url=str(order_meta.get("download_url") or ""),
        )
        if not url:
            return {
                "order_no": order_no,
                "dir_name": dir_name,
                "status": "skipped_no_url",
                "message": "缺少 cxOrderID 与订单下载链接（请先执行一次检查新订单）",
            }

        self._ensure_order_page_ready(url, log_cb=log_cb)

        sel_all = page.locator("#cxSelectAll")
        if sel_all.count() == 0:
            return {
                "order_no": order_no,
                "dir_name": dir_name,
                "status": "skipped_unavailable",
                "message": "订单页未找到样品全选控件，可能尚未上传结果或页面改版",
            }
        sel_all.wait_for(state="visible", timeout=15000)

        if sel_all.is_disabled():
            return {
                "order_no": order_no,
                "dir_name": dir_name,
                "status": "skipped_unavailable",
                "message": "该订单全选框已禁用（全部样品可能测序失败或结果尚未上传完成）",
            }

        if not sel_all.is_checked():
            sel_all.click()
        checked_cnt = page.locator(".cxids:checked").count()
        if checked_cnt <= 0:
            return {
                "order_no": order_no,
                "dir_name": dir_name,
                "status": "skipped_unavailable",
                "message": "订单内没有可勾选的测序结果明细",
            }
        if log_cb:
            log_cb(f"订单 {dir_name} 已选中 {checked_cnt} 条测序明细，正在打开打包弹窗...")

        pack_btn = page.locator("a:has-text('测序结果打包下载'):visible").first
        if pack_btn.count() == 0:
            raise SangonOrderDownloadError("页面中未找到「测序结果打包下载」按钮")
        pack_btn.click()

        agreement = page.locator("#agreement")
        agreement.wait_for(state="visible", timeout=10000)
        if not agreement.is_checked():
            agreement.check()

        confirm_btn = page.locator(
            "xpath=//input[@id='agreement']/following::*[self::button or self::a or self::input]"
            "[normalize-space(.)='确定' or @value='确定'][1]"
        ).first
        if confirm_btn.count() == 0 or not confirm_btn.is_visible():
            confirm_btn = page.locator("#x_resultModel_Box button:has-text('确定'):visible, .shoppingModalFooter button.primaryBtn:visible").last

        captured_downloads: List[Any] = []
        blocking_alerts: List[str] = []
        notice_dialogs: List[str] = []

        def _on_download(dl: Any) -> None:
            captured_downloads.append(dl)

        def _on_dialog(dialog: Any) -> None:
            msg = str(dialog.message or "").strip()
            notice_dialogs.append(msg)
            # 生工 /isDownloadAttach 返回 msg=="500011" 时弹出 confirm("...峰图正在生成中，请确认是否现在下载?")
            if any(k in msg for k in ("是否现在下载", "正在生成中", "确认是否")):
                try:
                    dialog.accept()
                except Exception:
                    pass
                return
            blocking_alerts.append(msg)
            try:
                dialog.accept()
            except Exception:
                pass

        page.on("download", _on_download)
        page.on("dialog", _on_dialog)
        fee_confirmed = False
        tmp_zip: Optional[Path] = None

        try:
            confirm_btn.click()

            # 阶段 A：等待直接开始下载、报错提示或弹出 KBSeq 费用确认对话框 (#Sequencing_results_batch_box)
            modal_deadline = time.monotonic() + 18.0
            fee_box_handled = False
            while time.monotonic() < modal_deadline:
                if captured_downloads or blocking_alerts:
                    break
                fee_box = page.locator("#Sequencing_results_batch_box")
                if not fee_box_handled and fee_box.count() > 0 and fee_box.first.is_visible():
                    fee_box_handled = True
                    fee_rows = page.locator("#Sequencing_results_batch_box .seq_table tr.appendChild").count()
                    fee_amount = ""
                    try:
                        price_el = page.locator("#Sequencing_results_batch_box .foot_price").first
                        if price_el.count() > 0:
                            fee_amount = (price_el.inner_text() or "").strip()
                    except Exception:
                        pass

                    fee_desc = f"明细 {fee_rows} 条" + (f"，{fee_amount}" if fee_amount else "")
                    if not auto_confirm_fee:
                        close_btn = fee_box.locator("[onclick*='close'], button:has-text('取消'), a:has-text('取消')").first
                        if close_btn.count() > 0 and close_btn.is_visible():
                            close_btn.click()
                        return {
                            "order_no": order_no,
                            "dir_name": dir_name,
                            "status": "fee_confirm_required",
                            "fee_confirmed": False,
                            "message": f"检测到 KBSeq 费用确认弹窗 ({fee_desc})，已按设置暂停下载",
                        }

                    if log_cb:
                        log_cb(f"订单 {dir_name} 弹出 KBSeq 费用确认框 ({fee_desc})，已按设定自动确认下载")
                    fee_ok_btn = fee_box.locator("[onclick*='determine'], button:has-text('确定'), a:has-text('确定')").first
                    fee_ok_btn.click()
                    fee_confirmed = True
                    break
                page.wait_for_timeout(200)

            # 阶段 B：等待下载事件到达
            dl_wait_deadline = time.monotonic() + max(15.0, self.timeout_ms / 1000.0)
            while time.monotonic() < dl_wait_deadline:
                if captured_downloads or blocking_alerts:
                    break
                page.wait_for_timeout(250)

            if blocking_alerts and not captured_downloads:
                return {
                    "order_no": order_no,
                    "dir_name": dir_name,
                    "status": "skipped_unavailable",
                    "fee_confirmed": fee_confirmed,
                    "message": f"生工提示暂不可下载: {' | '.join(blocking_alerts)}",
                }

            if not captured_downloads:
                raise SangonOrderDownloadError(
                    f"点击确认后 {int(self.timeout_ms / 1000)}s 内未收到浏览器下载流"
                )

            dl = captured_downloads[0]
            suggested = sanitize_zip_filename(getattr(dl, "suggested_filename", ""), order_no)
            zip_dir = order_path / "原始压缩包"
            zip_dir.mkdir(parents=True, exist_ok=True)
            tmp_zip = zip_dir / f".downloading_{order_no}_{int(time.time())}.tmp"
            final_zip = zip_dir / suggested

            # 等待下载完成并流式保存至临时文件，校验完整后再原子替换正式目录文件
            dl.save_as(str(tmp_zip))
            entry_count = _validate_zip_file(tmp_zip)
            tmp_zip.replace(final_zip)
            tmp_zip = None

            size_bytes = final_zip.stat().st_size
            return {
                "order_no": order_no,
                "dir_name": dir_name,
                "status": "downloaded",
                "zip_name": final_zip.name,
                "dest_path": str(final_zip),
                "size_bytes": size_bytes,
                "entry_count": entry_count,
                "fee_confirmed": fee_confirmed,
                "dialogs": notice_dialogs,
                "message": f"下载并校验完成 ({final_zip.name}, {size_bytes / (1024 * 1024):.2f} MB, {entry_count} 项)",
            }
        finally:
            if tmp_zip is not None and tmp_zip.exists():
                try:
                    tmp_zip.unlink()
                except OSError:
                    pass
            try:
                page.remove_listener("download", _on_download)
            except Exception:
                pass
            try:
                page.remove_listener("dialog", _on_dialog)
            except Exception:
                pass


def _collect_pending_download_targets(
    root_dir: Path,
    *,
    order_names: Optional[List[str]] = None,
    ignored_orders: Optional[Iterable[str]] = None,
) -> Dict[str, Any]:
    """筛选待下载订单目录及附加的 cxOrderID/download_url 元数据。"""
    resolved_ignored = (
        {normalize_order_key(k) for k in ignored_orders if normalize_order_key(k)}
        if ignored_orders is not None
        else set(list_ignored_orders().keys())
    )
    index = SangonMailIndex(root_dir)
    index.load()

    candidate_dirs: List[Path] = []
    if order_names:
        for name in order_names:
            p = root_dir / name
            if p.exists() and p.is_dir():
                candidate_dirs.append(p)
    elif root_dir.exists():
        for child in sorted(root_dir.iterdir(), key=lambda p: p.name, reverse=True):
            if child.is_dir() and re.match(r"^\d{8}_\d+", child.name):
                candidate_dirs.append(child)

    targets: List[Dict[str, Any]] = []
    skipped_items: List[Dict[str, Any]] = []

    for order_dir in candidate_dirs:
        order_no = order_dir.name.split("_", 1)[1] if "_" in order_dir.name else order_dir.name
        if normalize_order_key(order_no) in resolved_ignored:
            skipped_items.append({
                "order_no": order_no,
                "dir_name": order_dir.name,
                "status": "skipped_ignored",
                "message": "订单处于全局忽略名单，已跳过",
            })
            continue

        zip_dir = order_dir / "原始压缩包"
        existing_zips = list(zip_dir.glob("*.zip")) if zip_dir.exists() else []
        if existing_zips:
            skipped_items.append({
                "order_no": order_no,
                "dir_name": order_dir.name,
                "status": "skipped_existing",
                "zip_name": existing_zips[0].name,
                "message": f"订单已有压缩包 {existing_zips[0].name}",
            })
            continue

        create_sangon_subdirs(order_dir)
        meta = index.get_order(order_no)
        cx_order_id = str(meta.get("cx_order_id") or "").strip()
        download_url = str(meta.get("download_url") or "").strip()
        targets.append({
            "order_no": order_no,
            "dir_name": order_dir.name,
            "order_path": str(order_dir),
            "cx_order_id": cx_order_id,
            "download_url": download_url,
        })

    return {"targets": targets, "skipped": skipped_items}


def download_sangon_orders(
    root_dir: Path,
    downloads_dir: Path,
    *,
    order_names: Optional[List[str]] = None,
    account: str = "",
    password: str = "",
    auto_confirm_fee: bool = True,
    headless: bool = True,
    timeout_ms: int = 90000,
    ignored_orders: Optional[Iterable[str]] = None,
    progress_cb: Optional[Callable[[int, int, str], None]] = None,
    log_cb: Optional[Callable[[str], None]] = None,
    session_factory: Optional[Callable[..., Any]] = None,
) -> Dict[str, Any]:
    """
    批量自动获取生工订单测序压缩包（优先认领本机 Downloads 既有包，其余登录生工单会话顺序下载落盘）。
    单订单原子校验落盘，具备天然断点续传保护；若触发人机验证立刻中止并返回明确标记。
    """
    r_dir = Path(root_dir)
    d_dir = Path(downloads_dir)
    r_dir.mkdir(parents=True, exist_ok=True)

    collected = _collect_pending_download_targets(
        r_dir, order_names=order_names, ignored_orders=ignored_orders
    )
    targets: List[Dict[str, Any]] = collected["targets"]
    items: List[Dict[str, Any]] = list(collected["skipped"])

    if not targets:
        return {
            "total": len(items),
            "claimed_count": 0,
            "downloaded_count": 0,
            "skipped_count": len(items),
            "failed_count": 0,
            "captcha_blocked": False,
            "items": items,
            "processed_dir_names": [],
        }

    # 第一步：优先从浏览器下载目录认领已下好的有效压缩包，避免重复下载
    claimed_by_dir: Dict[str, Dict[str, Any]] = {}
    if d_dir.exists() and d_dir.is_dir():
        imp = import_order_zips_from_downloads(
            r_dir,
            d_dir,
            order_names=[t["dir_name"] for t in targets],
            auto_create_order=False,
            ignored_orders=ignored_orders,
        )
        for rec in imp.get("imported") or []:
            claimed_by_dir[rec["dir_name"]] = rec
            items.append({
                "order_no": rec["order_no"],
                "dir_name": rec["dir_name"],
                "status": "claimed",
                "zip_name": rec["zip_name"],
                "dest_path": rec["dest_path"],
                "message": f"已在下载目录找到并认领 {rec['zip_name']}",
            })
            if log_cb:
                log_cb(f"优先从下载目录认领完成: {rec['dir_name']} <- {rec['zip_name']}")

    remaining = [t for t in targets if t["dir_name"] not in claimed_by_dir]
    web_targets: List[Dict[str, Any]] = []
    for t in remaining:
        if not build_sangon_order_url(t.get("cx_order_id", ""), t.get("download_url", "")):
            msg = "缺少 cxOrderID 与下载链接，请先运行「检查新订单」或确认是否为非测序通知"
            items.append({
                "order_no": t["order_no"],
                "dir_name": t["dir_name"],
                "status": "skipped_no_url",
                "message": msg,
            })
            if log_cb:
                log_cb(f"[跳过] {t['dir_name']}: {msg}")
        else:
            web_targets.append(t)

    downloaded_count = 0
    failed_count = 0
    captcha_blocked = False
    processed_dir_names: List[str] = list(claimed_by_dir.keys())

    if web_targets:
        if not (account or "").strip() or not (password or ""):
            raise SangonLoginError("需要网页自动下载但尚未配置生工账号或密码")

        factory = session_factory or SangonBrowserSession
        total_web = len(web_targets)
        with factory(
            account,
            password,
            headless=headless,
            timeout_ms=timeout_ms,
        ) as session:
            for idx, target in enumerate(web_targets, start=1):
                if progress_cb:
                    progress_cb(idx, total_web, target["dir_name"])
                try:
                    res = session.download_order(
                        target,
                        auto_confirm_fee=auto_confirm_fee,
                        log_cb=log_cb,
                    )
                    items.append(res)
                    st = res.get("status")
                    if st == "downloaded":
                        downloaded_count += 1
                        processed_dir_names.append(target["dir_name"])
                    elif st in ("failed",):
                        failed_count += 1
                    if log_cb:
                        log_cb(f"({idx}/{total_web}) {target['dir_name']}: {res.get('message', st)}")
                except SangonCaptchaError as exc:
                    captcha_blocked = True
                    failed_count += 1
                    msg = str(exc)
                    items.append({
                        "order_no": target["order_no"],
                        "dir_name": target["dir_name"],
                        "status": "failed",
                        "message": msg,
                    })
                    if log_cb:
                        log_cb(f"[中止] {msg}")
                    break
                except SangonLoginError as exc:
                    failed_count += 1
                    msg = str(exc)
                    items.append({
                        "order_no": target["order_no"],
                        "dir_name": target["dir_name"],
                        "status": "failed",
                        "message": msg,
                    })
                    if log_cb:
                        log_cb(f"[登录失败] {msg}")
                    break
                except Exception as exc:
                    failed_count += 1
                    msg = f"自动下载异常: {exc}"
                    items.append({
                        "order_no": target["order_no"],
                        "dir_name": target["dir_name"],
                        "status": "failed",
                        "message": msg,
                    })
                    if log_cb:
                        log_cb(f"[失败] {target['dir_name']}: {msg}")

    claimed_count = len(claimed_by_dir)
    skipped_count = sum(
        1 for it in items if str(it.get("status", "")).startswith("skipped") or it.get("status") == "fee_confirm_required"
    )
    return {
        "total": len(targets),
        "claimed_count": claimed_count,
        "downloaded_count": downloaded_count,
        "skipped_count": skipped_count,
        "failed_count": failed_count,
        "captcha_blocked": captcha_blocked,
        "items": items,
        "processed_dir_names": processed_dir_names,
    }

