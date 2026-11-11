# -*- coding: utf-8 -*-
"""定时轮询入口（常驻模式）：

  python -m src.mail_download.scheduler --every 300        # 每 5 分钟轮询一次（常驻）
  python -m src.mail_download.scheduler --every 300 --once # 只执行一次后退出（配合 Windows 计划任务）

与 Windows 计划任务配合（推荐常驻方式）：
  scripts\\install_mail_poll_task.ps1 -IntervalMinutes 5     # 注册 schtasks 计划任务
"""
import argparse
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from src.mail_download.cli import main as cli_main


def run_poll(args) -> int:
    """执行一次轮询（复用 CLI 逻辑）。"""
    argv = ["--since-days", str(args.since_days)]
    if getattr(args, "config", None):
        argv += ["--config", args.config]
    if getattr(args, "verbose", False):
        argv.append("--verbose")
    return cli_main(argv)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="mail_download.scheduler", description="邮箱附件定时轮询")
    parser.add_argument("--every", type=int, default=300, help="轮询间隔（秒），默认 300")
    parser.add_argument("--once", action="store_true", help="只执行一次后退出（供计划任务调用）")
    parser.add_argument("--config", default=None, help="mail_config.json 路径")
    parser.add_argument("--since-days", type=int, default=7, help="时间窗口（天）")
    parser.add_argument("--verbose", action="store_true", help="详细日志")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING,
                        format="%(asctime)s %(levelname)s %(message)s")

    if args.once:
        return run_poll(args)

    logging.getLogger("mail_download.scheduler").info(
        "轮询已启动，每 %s 秒检查一次", args.every
    )
    while True:
        try:
            run_poll(args)
        except Exception as e:  # 轮询失败不退出，下轮重试
            logging.getLogger("mail_download.scheduler").exception("轮询异常: %s", e)
        time.sleep(args.every)


if __name__ == "__main__":
    raise SystemExit(main())
