# -*- coding: utf-8 -*-
"""
邮件发信草稿构造与安全投递服务模块
职责：
1. 统一解析收件人 / 抄送地址列表与默认本人兜底策略；
2. 为「生工 16S 结果发送」「注释回传压缩包发送」「SMTP 自检发信」提供预览与发送同源的默认草稿（发信标题、主题、正文、附件名）；
3. 兼容透传自定义发信标题 (from_name)、邮件主题 (subject)、邮件正文 (body)、抄送 (cc) 及附件压缩包文件名 (attachment_name)。
"""
import csv
import inspect
import json
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from ....mail_download.sender import sanitize_zip_filename


def parse_email_addresses(raw: Optional[Union[str, List[str]]]) -> List[str]:
    """拆分逗号/分号分隔的邮箱字符串或列表，保持顺序去重。"""
    if raw is None:
        return []
    tokens: List[str] = []
    if isinstance(raw, list):
        sources = raw
    else:
        sources = [raw]

    for src in sources:
        if not src:
            continue
        for piece in src.replace("；", ",").replace(";", ",").replace("，", ",").split(","):
            addr = piece.strip()
            if addr and addr not in tokens:
                tokens.append(addr)
    return tokens


def resolve_safe_send_target(cfg: Any, to_arg: Optional[str]) -> str:
    """解析目标收件人：留空或传入 self 时安全回退到自身发件/收件账号，绝不误发外部邮箱。"""
    val = (to_arg or "").strip()
    if not val or val.lower() == "self":
        smtp_acc = getattr(cfg, "smtp_account", "") or ""
        imap_acc = getattr(cfg, "account", "") or ""
        return (smtp_acc or imap_acc).strip()
    addresses = parse_email_addresses(val)
    return ", ".join(addresses) if addresses else val


def normalize_mail_body(body: Optional[str]) -> str:
    """规范化用户编辑后的正文文本，保留段落与缩进结构。"""
    if body is None:
        return ""
    return body.replace("\r\n", "\n").replace("\r", "\n").strip("\n")


def _default_from_name(cfg: Any) -> str:
    raw = getattr(cfg, "smtp_display_name", "")
    return raw.strip() if isinstance(raw, str) else ""


def _default_reply_to(cfg: Any) -> str:
    raw = getattr(cfg, "reply_to", "")
    return raw.strip() if isinstance(raw, str) else ""


def build_sangon_result_draft(
    clean_name: str,
    csv_path: Path,
    cfg: Any,
    extra_note: Optional[str] = None,
) -> Dict[str, Any]:
    """根据订单 16S 鉴定 CSV 构造默认邮件草稿，供前端弹窗预填与后端兜底发送共用。"""
    with open(csv_path, "r", encoding="utf-8-sig", errors="replace") as f:
        rows = list(csv.reader(f))
    data_rows = [r for r in rows[1:] if r] if len(rows) > 1 else []
    total = len(data_rows)
    no_hits = sum(
        1
        for r in data_rows
        if ("No Hits" in (r[3] if len(r) > 3 else "") or "未找到匹配项" in (r[3] if len(r) > 3 else ""))
    )
    with_hits = total - no_hits

    order_no = clean_name.split("_", 1)[1] if "_" in clean_name else clean_name
    subject = f"生工 16S 测序鉴定结果 - {clean_name}（共 {total} 样本）"

    preview_lines: List[str] = []
    for r in data_rows[:15]:
        qid = r[0] if len(r) > 0 else "-"
        sp_cn = r[1] if len(r) > 1 else ""
        sp_la = r[3] if len(r) > 3 else ""
        ident = r[7] if len(r) > 7 else ""
        acc = r[9] if len(r) > 9 else ""
        sp_disp = f"{sp_cn} ({sp_la})" if sp_cn and sp_la else (sp_cn or sp_la or "-")
        preview_lines.append(f"  - {qid}: {sp_disp} | Identity={ident} | Acc={acc}")
    if total > 15:
        preview_lines.append(f"  ...（其余 {total - 15} 条结果详见附件 CSV 表格）")

    body_lines = [
        "您好：",
        "",
        f"生工 16S 测序订单 {clean_name}（订单号 {order_no}）的自动 BLAST 鉴定与物种翻译已完成：",
        f"  样本总数：{total}",
        f"  成功命中：{with_hits}",
        f"  未命中：{no_hits}",
    ]
    if extra_note and extra_note.strip():
        body_lines.append(f"  备注信息：{extra_note.strip()}")
    if preview_lines:
        body_lines.append("")
        body_lines.append("鉴定结果预览（前 15 条）：")
        body_lines.extend(preview_lines)
    body_lines.extend(["", "完整 11 列鉴定结果请查收附件压缩包。", ""])

    return {
        "order_dir_name": clean_name,
        "order_no": order_no,
        "to": resolve_safe_send_target(cfg, None),
        "reply_to": _default_reply_to(cfg),
        "from_name": _default_from_name(cfg),
        "cc": "",
        "subject": subject,
        "body": "\n".join(body_lines),
        "attachment_name": f"16S鉴定结果_{clean_name}.zip",
        "inner_csv_name": f"16S鉴定结果_{order_no}.csv",
        "total_samples": total,
        "with_hits": with_hits,
        "no_hits": no_hits,
    }


def build_package_send_draft(
    zip_path: Path,
    send_dir: Path,
    cfg: Any,
    extra_note: Optional[str] = None,
) -> Dict[str, Any]:
    """读取回传压缩包清单及内容，构造默认邮件草稿。"""
    task_id = zip_path.stem
    pack_time = ""
    file_names: List[str] = []
    manifest_path = send_dir / f"{zip_path.stem}.manifest.json"
    if manifest_path.is_file():
        try:
            mdata = json.loads(manifest_path.read_text(encoding="utf-8"))
            if isinstance(mdata, dict):
                raw_tid = mdata.get("task_id")
                if raw_tid:
                    task_id = str(raw_tid)
                raw_pt = mdata.get("pack_time")
                if raw_pt:
                    pack_time = str(raw_pt)
                for entry in mdata.get("files") or []:
                    if isinstance(entry, dict) and entry.get("name"):
                        file_names.append(str(entry["name"]))
                    elif isinstance(entry, str):
                        file_names.append(entry)
        except Exception:
            pass
    if not file_names:
        try:
            with zipfile.ZipFile(zip_path, "r") as zf:
                file_names = list(zf.namelist())
        except Exception:
            pass

    docx_names = [n for n in file_names if n.lower().endswith(".docx")]
    subject = f"噬菌体注释结果回传 - {task_id}"
    preview = file_names[:20]
    if len(file_names) > 20:
        preview.append(f"...（其余 {len(file_names) - 20} 个文件）")

    size_kb = round(zip_path.stat().st_size / 1024, 1)
    body_lines = [
        "您好：",
        "",
        f"现发送噬菌体基因组注释任务 {task_id} 的结果压缩包：",
        f"  附件文件名：{zip_path.name}",
        f"  文件大小：{size_kb:.1f} KB",
        f"  内含产物数：{len(file_names)} 个",
    ]
    if pack_time:
        body_lines.append(f"  打包时间：{pack_time}")
    if docx_names:
        body_lines.append(f"  包含 Word 报告：{', '.join(docx_names)}")
    if extra_note and extra_note.strip():
        body_lines.append(f"  附加备注：{extra_note.strip()}")
    if preview:
        body_lines.append("")
        body_lines.append("压缩包内文件清单：")
        body_lines.extend(f"  - {name}" for name in preview)
    body_lines.extend(["", "如需进一步分析或调整，请回复本邮件。", ""])

    return {
        "zip_name": zip_path.name,
        "task_id": task_id,
        "pack_time": pack_time,
        "file_count": len(file_names),
        "size_kb": size_kb,
        "to": resolve_safe_send_target(cfg, None),
        "reply_to": _default_reply_to(cfg),
        "from_name": _default_from_name(cfg),
        "cc": "",
        "subject": subject,
        "body": "\n".join(body_lines),
        "attachment_name": zip_path.name,
        "docx_names": docx_names,
        "file_names": file_names,
    }


def find_latest_docx_report(send_dir: Path, annotations_dir: Path) -> Optional[Path]:
    """定位最新的 Word 注释报告，优先读取回传目录，其次回退注释产物目录。"""
    docx_list: List[Path] = []
    if send_dir.exists():
        docx_list = sorted(send_dir.glob("*.docx"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not docx_list and annotations_dir.exists():
        docx_list = sorted(annotations_dir.rglob("*.docx"), key=lambda p: p.stat().st_mtime, reverse=True)
    return docx_list[0] if docx_list else None


def build_test_send_draft(
    cfg: Any,
    send_dir: Path,
    annotations_dir: Path,
    note: Optional[str] = None,
    attach_latest_report: bool = False,
    stamp: Optional[str] = None,
) -> Dict[str, Any]:
    """构造 SMTP 自检测试邮件默认草稿。"""
    now = datetime.now()
    now_str = now.strftime("%Y-%m-%d %H:%M:%S")
    use_stamp = stamp or now.strftime("%Y%m%d_%H%M%S")
    default_zip = f"SMTP_自检验证包_{use_stamp}.zip"
    target_to = resolve_safe_send_target(cfg, None)

    attached_files = ["smtp_self_test.txt"]
    latest_docx: Optional[Path] = None
    if attach_latest_report:
        latest_docx = find_latest_docx_report(send_dir, annotations_dir)
        if latest_docx is not None:
            attached_files.append(latest_docx.name)

    smtp_acc = (getattr(cfg, "smtp_account", "") or "").strip()
    body_lines = [
        "您好：",
        "",
        "本邮件为 NCBI Pro 邮件自动回传流水线的 SMTP 发信自检测试邮件。",
        f"发件账号：{smtp_acc}",
        f"目标收件人：{target_to}",
        f"验证时间：{now_str}",
        f"测试附件：{default_zip}（包含 {', '.join(attached_files)}）",
    ]
    if note and note.strip():
        body_lines.append(f"备注信息：{note.strip()}")
    body_lines.append("")
    body_lines.append("若您顺利收到本邮件且附件中文名称显示正常，即表示 SMTP 链路畅通。")

    return {
        "to": target_to,
        "reply_to": _default_reply_to(cfg),
        "from_name": _default_from_name(cfg),
        "cc": "",
        "subject": f"【自检验证】邮件自动回传 SMTP 测试 ({use_stamp})",
        "body": "\n".join(body_lines),
        "attachment_name": default_zip,
        "attached_files": attached_files,
        "latest_docx_path": latest_docx,
        "now_str": now_str,
        "stamp": use_stamp,
    }


def resolve_final_mail_params(
    *,
    cfg: Any,
    draft: Dict[str, Any],
    req_from_name: Optional[str],
    req_subject: Optional[str],
    req_body: Optional[str],
    req_attachment_name: Optional[str],
    req_cc: Optional[Union[str, List[str]]],
) -> Dict[str, Any]:
    """合并用户修改字段与草稿默认值，返回校验后可直接用于发送的参数字典。"""
    from_name = (req_from_name or "").strip() or draft["from_name"]
    subject = (req_subject or "").strip() or draft["subject"]
    edited_body = normalize_mail_body(req_body)
    body = edited_body if edited_body.strip() else draft["body"]
    attachment_name = sanitize_zip_filename(req_attachment_name, draft["attachment_name"])
    cc_list = parse_email_addresses(req_cc)
    return {
        "from_name": from_name,
        "subject": subject,
        "body": body,
        "attachment_name": attachment_name,
        "cc_list": cc_list,
    }


def send_mail_compat(
    sender: Any,
    attachment: Path,
    *,
    to: str,
    subject: str,
    body: str,
    cc: Optional[List[str]] = None,
    from_name: Optional[str] = None,
    attachment_name: Optional[str] = None,
) -> Any:
    """兼容调用 MailSender.send 及只实现旧签名的测试 Mock 对象。"""
    kwargs: Dict[str, Any] = {
        "to": to,
        "subject": subject,
        "body": body,
        "cc": cc or None,
    }
    try:
        sig = inspect.signature(sender.send)
        accepts_kw = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values())
        params = sig.parameters
        if accepts_kw or "from_name" in params:
            kwargs["from_name"] = from_name
        if accepts_kw or "attachment_name" in params:
            kwargs["attachment_name"] = attachment_name
    except (TypeError, ValueError):
        pass

    orig_display: Optional[str] = None
    sender_cfg = getattr(sender, "cfg", None)
    patched_display = False
    if "from_name" not in kwargs and from_name and sender_cfg is not None and hasattr(sender_cfg, "smtp_display_name"):
        orig_display = sender_cfg.smtp_display_name
        sender_cfg.smtp_display_name = from_name
        patched_display = True

    try:
        return sender.send(attachment, **kwargs)
    finally:
        if patched_display and sender_cfg is not None and orig_display is not None:
            sender_cfg.smtp_display_name = orig_display

