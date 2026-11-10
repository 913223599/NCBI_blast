# -*- coding: utf-8 -*-
"""手动运行入口：

  python -m src.mail_download.cli                    # 用 mail_config.json 拉取
  python -m src.mail_download.cli --dry-run          # 只列出命中邮件，不下载
  python -m src.mail_download.cli --since-days 14    # 覆盖时间窗口
  python -m src.mail_download.cli --sender a@b.com   # 覆盖发件人白名单
  python -m src.mail_download.cli --example          # 生成配置模板
  python -m src.mail_download.cli --pack-results <产物目录> [--task-id xxx]
                                                     # 打包注释产物为 zip（不发送）
  python -m src.mail_download.cli --send-results <产物目录> [--to a@b.com]
                                                     # 打包并 SMTP 发回
"""
import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from src.mail_download.config import PROJECT_ROOT, load_config, dump_example
from src.mail_download.downloader import AttachmentSaver
from src.mail_download.fetcher import MailFetcher
from src.mail_download.packer import ResultPacker
from src.mail_download.sender import MailSender


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="mail_download", description="从邮箱下载需求附件（拼接 fasta）")
    parser.add_argument("--config", default=None, help="mail_config.json 路径（默认项目根目录）")
    parser.add_argument("--since-days", type=int, default=None, help="覆盖时间窗口（天）")
    parser.add_argument("--sender", default=None, help="覆盖发件人白名单（逗号分隔）")
    parser.add_argument("--dry-run", action="store_true", help="只扫描并打印命中邮件，不落地附件")
    parser.add_argument("--example", action="store_true", help="生成 mail_config.example.json 后退出")
    parser.add_argument("--pack-results", default=None, metavar="DIR",
                        help="打包注释产物目录为 zip（不发送）")
    parser.add_argument("--send-results", default=None, metavar="DIR",
                        help="打包注释产物并 SMTP 发回（需授权码）")
    parser.add_argument("--task-id", default=None, help="打包任务的 task_id（默认用目录名）")
    parser.add_argument("--to", default=None, help="回传收件人（默认 mail_config.reply_to）")
    parser.add_argument("--subject", default=None, help="回传邮件主题（默认固定主题）")
    parser.add_argument("--verbose", action="store_true", help="打印详细日志")
    args = parser.parse_args(argv)

    if args.verbose:
        logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    else:
        logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")

    if args.example:
        p = dump_example()
        print(f"已生成配置模板: {p}")
        return 0

    try:
        cfg = load_config(args.config, require_imap_auth=False)
    except RuntimeError as e:
        print(f"[错误] {e}")
        return 1
    if args.sender:
        cfg.sender_whitelist = [s.strip() for s in args.sender.split(",") if s.strip()]

    # ---- 回传分支：打包（+发送） ----
    target = args.pack_results or args.send_results
    if target:
        packer = ResultPacker(cfg.resolved_send_dir)
        try:
            packed = packer.pack(target, task_id=args.task_id)
        except (FileNotFoundError, ValueError) as e:
            print(f"[错误] 打包失败: {e}")
            return 1
        print(
            f"已打包 {packed['file_count']} 个文件 → {packed['zip']}\n"
            f"  SHA256: {packed['sha256']}\n"
            f"  大小: {packed['size_bytes'] / 1024:.1f} KB"
        )
        if args.pack_results:
            return 0
        # --send-results：继续发送
        sender = MailSender(cfg)
        result = sender.send(packed["zip"], to=args.to, subject=args.subject)
        if not result.ok:
            print(f"[错误] 回传失败（{result.stage}）: {result.error}")
            return 1
        print(f"已回传给 {result.to}，主题：{result.subject}")
        return 0

    # ---- 收件分支 ----
    fetcher = MailFetcher(cfg)
    result = fetcher.fetch(since_days=args.since_days)

    if result.connection_error:
        print(f"[错误] 邮箱连接/读取失败: {result.connection_error}")
        return 1

    print(f"扫描邮件 {result.scanned} 封，命中 {len(result.matched)} 封：")
    for m in result.matched:
        print(f"  [{m.date_text}] 来自 {m.sender}: {m.subject}")

    if args.dry_run:
        print("[dry-run] 未下载附件。")
        return 0

    if not result.matched:
        print("没有需要下载的新附件。")
        return 0

    saver = AttachmentSaver(cfg.resolved_download_dir)
    stats = saver.save(result.matched)
    print(
        f"已保存 {stats['count']} 个附件（共 {stats['total_bytes']/1024:.1f} KB，"
        f"同批跳过 {stats['skipped_duplicates']}，已处理跳过 {stats['skipped_processed']}）"
        f"到: {stats['download_dir']}"
    )
    if cfg.on_download_cmd:
        print(f"提示: 已配置下载后回调 {cfg.on_download_cmd}（当前版本不自动执行，由外部调度负责）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
