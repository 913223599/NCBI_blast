# -*- coding: utf-8 -*-
"""手动运行入口：

  python -m src.mail_download.cli                    # 用 mail_config.json 拉取
  python -m src.mail_download.cli --dry-run          # 只列出命中邮件，不下载
  python -m src.mail_download.cli --since-days 14    # 覆盖时间窗口
  python -m src.mail_download.cli --sender a@b.com   # 覆盖发件人白名单
  python -m src.mail_download.cli --example          # 生成配置模板
"""
import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from src.mail_download.config import PROJECT_ROOT, load_config, dump_example
from src.mail_download.downloader import AttachmentSaver
from src.mail_download.fetcher import MailFetcher


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="mail_download", description="从邮箱下载需求附件（拼接 fasta）")
    parser.add_argument("--config", default=None, help="mail_config.json 路径（默认项目根目录）")
    parser.add_argument("--since-days", type=int, default=None, help="覆盖时间窗口（天）")
    parser.add_argument("--sender", default=None, help="覆盖发件人白名单（逗号分隔）")
    parser.add_argument("--dry-run", action="store_true", help="只扫描并打印命中邮件，不落地附件")
    parser.add_argument("--example", action="store_true", help="生成 mail_config.example.json 后退出")
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
        cfg = load_config(args.config)
    except RuntimeError as e:
        print(f"[错误] {e}")
        return 1
    if args.sender:
        cfg.sender_whitelist = [s.strip() for s in args.sender.split(",") if s.strip()]

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
