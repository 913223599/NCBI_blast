# -*- coding: utf-8 -*-
"""自动回传端到端流水线（收件 → 注释 → 报告 → 打包 → SMTP 回传）。

用法示例：
  python -m src.mail_download.auto_pipeline --config mail_config.json
      # 完整链路：IMAP 收件（新附件才处理）→ 注释 → 报告 → 打包 → 回传
  python -m src.mail_download.auto_pipeline --config mail_config.json --test-input results/email_downloads/up_xxx/G2-1.fasta
      # 收件扫描后若没有新附件，用 --test-input 指定的 fasta 作为“新任务”跑完整链路
  python -m src.mail_download.auto_pipeline --config mail_config.json --no-send
      # 全链路但跳过邮件回传（调试用）
  python -m src.mail_download.auto_pipeline --config mail_config.json --annotate-only DIR
      # 只对已下载批次目录（含 fasta）做 注释→报告→打包，不回传

设计要点：
- 复用 mail_download 的 fetcher/downloader/packer/sender；
- 注释复用 src/analysis/annotation.pipeline.AnnotationPipeline（auto 调度，
  Pharokka/Prodigal 真实引擎可用时启用，产物 gbk/tsv/faa/ffn/features/summary/safety）；
- 报告复用 scripts/build_annotation_report.py（数据驱动 + 来源标注）；
- 收件幂等：processed_index.json 内容指纹跨次去重，重复附件自动跳过。
"""
import argparse
import asyncio
import json
import logging
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# 注释引擎（AnnotationPipeline 等）延迟导入：仅在有新附件需要处理时才加载，
# 避免“无新附件”的例行检查被引擎/WSL 探测拖慢（此前的瓶颈：顶层 import
# 触发 WSL 探测约 30s+）。轻量模块保持顶层导入。
from src.mail_download.config import DEFAULT_ATTACHMENT_EXTS, load_config
from src.mail_download.downloader import AttachmentSaver
from src.mail_download.fetcher import MailFetcher
from src.mail_download.packer import ResultPacker, DEFAULT_PRODUCT_GLOBS
from src.mail_download.sender import MailSender

logger = logging.getLogger("mail_download.auto_pipeline")

REPORT_SCRIPT = PROJECT_ROOT / "scripts" / "build_annotation_report.py"
CITATIONS_SPEC = PROJECT_ROOT / "scripts" / "citations_ops.json"
DOCX_CITATIONS = PROJECT_ROOT / "scripts" / "docx_citations.py"
ANNOTATIONS_DIR = PROJECT_ROOT / "results" / "annotations"
PIPELINE_LOG = PROJECT_ROOT / "results" / "email_downloads" / "pipeline.log"
ZIP_GLOBS = list(DEFAULT_PRODUCT_GLOBS) + ["*.docx"]


def _log(level, msg: str) -> None:
    getattr(logger, level)(msg)
    PIPELINE_LOG.parent.mkdir(parents=True, exist_ok=True)
    with PIPELINE_LOG.open("a", encoding="utf-8") as f:
        f.write(f"{datetime.now().isoformat(timespec='seconds')} [{level.upper()}] {msg}\n")


def _task_id_from_batch(batch_dir: Path, att_name: str) -> str:
    """任务编号：ANNO_<附件名>_<HHMMSS>，附件名取主名并清理非法字符。"""
    stem = Path(att_name).stem or "input"
    for ch in (' ', '(', ')', '[', ']', '&', '='):
        stem = stem.replace(ch, '_')
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"ANNO_{stem}_{stamp}"


def _register_test_batch(download_dir: Path, fasta_path: Path) -> Path:
    """把 --test-input 的 fasta 注册为一个“新任务批次”（模拟收到附件），返回批次目录。"""
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    batch = download_dir / f"up_{stamp}_TEST"
    batch.mkdir(parents=True, exist_ok=True)
    target = batch / fasta_path.name
    shutil.copy2(fasta_path, target)
    manifest = {
        "batch": batch.name,
        "download_time": datetime.now().isoformat(timespec="seconds"),
        "mail": {"seq": "TEST", "uid": "TEST", "date": datetime.now().strftime("%a, %d %b %Y %H:%M:%S %z"),
                 "sender": "local-test-input", "subject": "[TEST] 自动回传链路验证"},
        "attachments": [{"filename": target.name, "size_bytes": target.stat().st_size,
                         "sha256": "test-input", "path": str(target)}],
    }
    (batch / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    _log("info", f"已注册测试批次 {batch.name}（输入 {target.name}）")
    return batch


def _collect_batches(cfg, fasta_paths: list) -> list:
    """收集待处理批次：<批次目录, [fasta 路径列表]>。"""
    batches = []
    for fasta in fasta_paths:
        batch = fasta.parent
        batches.append((batch, [fasta]))
    return batches


async def _annotate(batch_dir: Path, fasta: Path) -> dict:
    """对单个 fasta 执行注释，返回 {task_id, out_dir, files}。"""
    # 延迟导入：仅在真正需要注释时加载引擎（避免无新附件时 WSL 探测开销）
    from src.analysis.annotation.pipeline import AnnotationPipeline
    from src.analysis.annotation.types import AnnotationRunRequest

    task_id = _task_id_from_batch(batch_dir, fasta.name)
    out_dir = ANNOTATIONS_DIR / task_id
    out_dir.mkdir(parents=True, exist_ok=True)
    _log("info", f"注释开始 {task_id}: {fasta}")
    req = AnnotationRunRequest(
        task_name=task_id,
        sample_type="PHAGE",
        engine="auto",          # Pharokka 可用则 Pharokka，否则自动降级
        fasta_path=str(fasta),
        prefix="ANNO",
        genetic_code=11,
        min_contig_len=200,
        enable_waterfall=True,
        enable_homology=True,
        enable_phold=True,
        enable_safety_audit=True,
    )
    pipe = AnnotationPipeline(task_id, out_dir)
    res = await pipe.execute(req)
    files = res.get("files", {})
    _log("info", f"注释完成 {task_id}: {res.get('feature_count', 0)} features, files={len(files)}")
    # 把 input fasta 也复制进产物目录，便于归档
    try:
        shutil.copy2(fasta, out_dir / "input_sequence.fasta")
    except OSError:
        pass
    return {"task_id": task_id, "out_dir": out_dir, "files": files}


def _build_report(out_dir: Path, task_id: str, sample_name: str, extra_notes: list) -> Path | None:
    """调用 build_annotation_report.py 生成 Word 报告到产物目录。"""
    if not REPORT_SCRIPT.exists():
        _log("warning", f"报告脚本不存在，跳过报告: {REPORT_SCRIPT}")
        return None
    report_path = out_dir / f"{task_id}_注释报告.docx"
    cmd = [
        sys.executable, "-X", "utf8", str(REPORT_SCRIPT),
        "--data", str(out_dir),
        "--out", str(report_path),
        "--task-id", task_id,
        "--sample-name", sample_name,
        "--report-no", "YSSW-ANNO-2026-XXX（待定）",
        "--company", "元昇生物（武汉）有限公司",
    ]
    for note in extra_notes:
        cmd += ["--extra-notes", note]
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                          timeout=1800, cwd=str(PROJECT_ROOT))
    if proc.returncode != 0:
        _log("error", f"报告生成失败: {proc.stderr[-800:]}")
        return None
    if not report_path.exists():
        _log("error", "报告脚本返回成功但产物缺失")
        return None
    _log("info", f"报告已生成: {report_path}（{report_path.stat().st_size} B）")

    # 注入参考文献编号（[1]–[8] REF 域），使终稿带引用
    if DOCX_CITATIONS.exists() and CITATIONS_SPEC.exists():
        try:
            apply_cmd = [sys.executable, "-X", "utf8", str(DOCX_CITATIONS), "apply",
                         str(report_path), "--spec", str(CITATIONS_SPEC), "--in-place"]
            r = subprocess.run(apply_cmd, capture_output=True, text=True, encoding="utf-8",
                               timeout=600, cwd=str(DOCX_CITATIONS.parent.parent))
            if r.returncode != 0:
                _log("error", f"引用注入失败: {r.stderr[-400:]}")
            else:
                val = subprocess.run([sys.executable, "-X", "utf8", str(DOCX_CITATIONS), "validate",
                                      str(report_path)], capture_output=True, text=True,
                                     encoding="utf-8", timeout=300, cwd=str(DOCX_CITATIONS.parent.parent))
                if val.returncode != 0:
                    _log("error", f"引用校验未通过: {val.stderr[-400:]}")
                else:
                    _log("info", "参考文献 [1]–[8] 编号已注入并校验通过")
        except Exception as e:
            _log("warning", f"引用注入步骤异常（不影响产物交付）: {e}")
    else:
        _log("warning", "引用操作文件或 docx_citations 工具缺失，跳过引用注入")
    return report_path


def _resolve_send_target(cfg, to_arg: str | None) -> tuple[str | None, bool]:
    """解析目标收件人；支持 --to self 安全指向本人邮箱。返回 (target_or_none, explicit_self_error)。"""
    if to_arg is None:
        return None, False
    val = str(to_arg).strip()
    if not val:
        return None, False
    if val.lower() == "self":
        self_addr = (getattr(cfg, "smtp_account", "") or getattr(cfg, "account", "") or "").strip()
        if not self_addr:
            return None, True
        return self_addr, False
    return val, False


def _load_batch_mail_info(batch: Path) -> dict:
    """读取批次目录 manifest.json 中的原邮件上下文信息。"""
    manifest = batch / "manifest.json"
    if not manifest.exists():
        return {}
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
        mail_info = dict(data.get("mail") or {})
        atts = data.get("attachments") or []
        mail_info["attachments"] = [
            a.get("filename", a.get("path", "")) if isinstance(a, dict) else str(a)
            for a in atts
        ]
        return mail_info
    except Exception as e:
        _log("warning", f"读取批次 manifest 失败（不影响处理）: {e}")
        return {}


def _collect_batch_fastas(batch: Path, cfg) -> list[Path]:
    """收集批次目录下所有匹配配置扩展名的序列文件。"""
    if not batch.exists() or not batch.is_dir():
        return []
    raw_exts = getattr(cfg, "attachment_exts", None) or DEFAULT_ATTACHMENT_EXTS
    allowed = {
        (e.lower() if e.startswith(".") else f".{e.lower()}")
        for e in raw_exts
        if isinstance(e, str) and e.strip()
    }
    found: list[Path] = []
    for p in sorted(batch.iterdir(), key=lambda x: x.name.lower()):
        if not p.is_file():
            continue
        if p.name in ("manifest.json", "pipeline.log", "run_errors.log"):
            continue
        if p.suffix.lower() in allowed:
            found.append(p)
    return found


def _sync_docx_to_send_dir(out_dir: Path, send_dir: Path) -> None:
    """把产物目录中的 Word 报告同步复制到回传目录，便于工作台展示与测试发信选择。"""
    try:
        send_dir.mkdir(parents=True, exist_ok=True)
        resolved_send = send_dir.resolve()
        for docx_file in sorted(out_dir.glob("*.docx")):
            if not docx_file.is_file():
                continue
            target = send_dir / docx_file.name
            if docx_file.resolve().parent != resolved_send:
                shutil.copy2(docx_file, target)
    except OSError as e:
        _log("warning", f"同步 Word 报告至回传目录失败: {e}")


def _pack_and_send(cfg, out_dir: Path, task_id: str, do_send: bool,
                   to: str | None, subject_prefix: str,
                   mail_info: dict | None = None) -> bool:
    packer = ResultPacker(cfg.resolved_send_dir, product_globs=ZIP_GLOBS)
    packed = packer.pack(out_dir, task_id=task_id)
    _sync_docx_to_send_dir(out_dir, cfg.resolved_send_dir)
    zip_path = Path(str(packed["zip"]))
    size_kb = int(packed.get("size_bytes", 0)) / 1024
    _log("info", f"已打包 {packed['file_count']} 文件 → {zip_path}（{size_kb:.1f} KB）")
    if not do_send:
        _log("info", "已跳过回传（--no-send 或未开启回传）")
        return True
    resolved_to, self_err = _resolve_send_target(cfg, to)
    if self_err:
        _log("error", "回传失败：指定 --to self 但未配置 smtp_account 或 account")
        return False
    sender = MailSender(cfg)
    subject = f"{subject_prefix}噬菌体注释结果回传 - {task_id}"
    body = _build_reply_body(task_id, zip_path, mail_info or {})
    result = sender.send(zip_path, to=resolved_to, subject=subject, body=body)
    if not result.ok:
        _log("error", f"回传失败（{result.stage}）: {result.error}")
        return False
    _log("info", f"回传成功 → {result.to}，主题：{result.subject}")
    return True


def _build_reply_body(task_id: str, zip_path: Path, mail_info: dict) -> str:
    """构造回传邮件正文：引用原邮件信息，避免收件人不知道对应哪封邮件。"""
    lines = ["您好：", ""]
    if mail_info:
        lines.append(f"本结果为对您发送的原邮件（如下）中附件的注释产物，任务编号：{task_id}：")
        if mail_info.get("subject"):
            lines.append(f"  原邮件主题：{mail_info['subject']}")
        if mail_info.get("date"):
            lines.append(f"  原邮件时间：{mail_info['date']}")
        attachments = mail_info.get("attachments") or []
        if attachments:
            names = [a if isinstance(a, str) else a.get("filename", "") for a in attachments]
            lines.append(f"  原邮件附件：{'、'.join(n for n in names if n)}")
        lines.append("")
    lines.append(f"结果包见附件：{zip_path.name}")
    lines.append(f"文件大小：{zip_path.stat().st_size / 1024:.1f} KB")
    lines.append("")
    lines.append("如需调整请回复本邮件。")
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="auto_pipeline", description="收件→注释→报告→打包→回传 端到端")
    parser.add_argument("--config", default=None, help="mail_config.json 路径")
    parser.add_argument("--since-days", type=int, default=None, help="收件时间窗（天）")
    parser.add_argument("--test-input", default=None, metavar="FASTA",
                        help="当收件无新附件时，用该 fasta 作为测试任务跑完整链路")
    parser.add_argument("--annotate-only", default=None, metavar="DIR",
                        help="对指定批次目录（含序列文件）执行 注释→报告→打包；传入 --to 或 --send 时可同时回传")
    parser.add_argument("--send", action="store_true", help="配合 --annotate-only 使用，允许将重跑结果邮件回传")
    parser.add_argument("--no-send", action="store_true", help="跳过邮件回传（仅测试注释/报告/打包）")
    parser.add_argument("--to", default=None, help="回传收件人（默认 reply_to；传入 self 时发往自身账号）")
    parser.add_argument("--subject-prefix", default="【自动】", help="回传主题前缀")
    parser.add_argument("--extra-note", action="append", default=[], help="报告额外备注（可多次）")
    parser.add_argument("--verbose", action="store_true", help="详细日志")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s %(message)s")

    cfg = load_config(args.config, require_imap_auth=False)

    # 流水线日志跟随配置中的下载目录（目录迁移后日志同步落到新位置）
    global PIPELINE_LOG
    PIPELINE_LOG = cfg.resolved_download_dir / "pipeline.log"
    # ---- 模式 A：处理指定批次（annotate-only，支持可选回传） ----
    if args.annotate_only:
        batch = Path(args.annotate_only)
        fastas = _collect_batch_fastas(batch, cfg)
        if not fastas:
            print(f"[错误] 批次目录中没有匹配序列文件: {batch}")
            return 1
        mail_info = _load_batch_mail_info(batch)
        do_send = (not args.no_send) and (args.send or bool((args.to or "").strip()))
        ok_all = True
        for f in fastas:
            info = asyncio.run(_annotate(batch, f))
            report = _build_report(info["out_dir"], info["task_id"], f.stem, args.extra_note)
            if report is None:
                ok_all = False
            if not _pack_and_send(cfg, info["out_dir"], info["task_id"],
                                  do_send=do_send, to=args.to,
                                  subject_prefix=args.subject_prefix, mail_info=mail_info):
                ok_all = False
        print("批次重跑结束：全部环节成功" if ok_all else "批次重跑结束：存在失败环节（见日志）")
        return 0 if ok_all else 1

    # ---- 模式 B：完整链路（收件 → 处理） ----
    fetcher = MailFetcher(cfg)
    result = fetcher.fetch(since_days=args.since_days)
    if result.connection_error:
        print(f"[错误] 邮箱连接/读取失败: {result.connection_error}")
        return 1
    print(f"扫描邮件 {result.scanned} 封，命中 {len(result.matched)} 封")

    batches: list = []
    if result.matched:
        saver = AttachmentSaver(cfg.resolved_download_dir)
        stats = saver.save(result.matched)
        print(f"已保存 {stats['count']} 个附件（跳过重复 {stats['skipped_duplicates']}，"
              f"已处理 {stats['skipped_processed']}）")
        saved_list: list[dict] = stats.get("saved_files") or []
        for sf in saved_list:
            sf_path = Path(str(sf["path"]))
            batches.append((sf_path.parent, [sf_path]))
        _log("info", f"收件下载完成: {stats['count']} 个新附件")

    # 无新附件但有 --test-input：注册测试批次
    if not batches and args.test_input:
        tp = Path(args.test_input)
        if not tp.exists():
            print(f"[错误] 测试输入不存在: {tp}")
            return 1
        batch = _register_test_batch(cfg.resolved_download_dir, tp)
        batches.append((batch, [batch / tp.name]))

    if not batches:
        print("没有需要处理的新任务。")
        return 0

    ok_all = True
    for batch, fastas in batches:
        mail_info = _load_batch_mail_info(batch)
        for f in fastas:
            info = asyncio.run(_annotate(batch, f))
            report = _build_report(info["out_dir"], info["task_id"], f.stem, args.extra_note)
            if report is None:
                ok_all = False
            if not _pack_and_send(cfg, info["out_dir"], info["task_id"],
                                  do_send=not args.no_send, to=args.to,
                                  subject_prefix=args.subject_prefix, mail_info=mail_info):
                ok_all = False
    print("流水线结束：全部环节成功" if ok_all else "流水线结束：存在失败环节（见日志）")
    return 0 if ok_all else 1


if __name__ == "__main__":
    raise SystemExit(main())
