# -*- coding: utf-8 -*-
"""
受控白名单远程执行客户端 CLI（支持 api / agent / ssh 三种模式）。

示例：
    python scripts/remote_ops_client.py --mode api --host 26.78.5.143 --action git_status
    python scripts/remote_ops_client.py --mode agent --host 26.78.5.143 --token <TOKEN> --action git_status
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.ops.remote_executor import ALLOWED_ACTIONS, RemoteOpsClient, RemoteTarget  # noqa: E402


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="调用受控白名单远程执行器查询远端状态与修复更新")
    parser.add_argument("--mode", choices=("api", "agent", "ssh"), default="api", help="通信模式")
    parser.add_argument("--host", required=True, help="远程主机 IP 或主机名")
    parser.add_argument("--port", type=int, default=0, help="目标端口（默认 api=8765, agent=18766, ssh=22）")
    parser.add_argument("--token", default="", help="agent 模式 Bearer Token（或读 REMOTE_OPS_TOKEN）")
    parser.add_argument("--user", default="", help="ssh 模式用户名")
    parser.add_argument("--remote-dir", default="", help="ssh 模式远程项目目录")
    parser.add_argument("--timeout", type=float, default=20.0, help="请求超时（秒）")
    parser.add_argument("--action", choices=ALLOWED_ACTIONS, default="git_status", help="白名单动作名称")
    parser.add_argument("--json", action="store_true", help="以完整 JSON 格式输出结果")
    return parser


def _print_summary(result_dict: dict) -> None:
    data = result_dict.get("data") or {}
    print(f"目标主机 : {result_dict.get('host')} | 动作: {result_dict.get('action')} | 耗时: {result_dict.get('elapsed_ms')} ms")
    print(f"执行状态 : {'OK' if result_dict.get('ok') else 'FAILED'}")
    if result_dict.get("error"):
        print(f"错误信息 : {result_dict['error']}")

    if data.get("legacy_server"):
        print(f"当前分支 : {data.get('branch')} @ {data.get('commit_hash')} ({data.get('commit_date')})")
        print(f"最新提交 : {data.get('commit_message')}")
        print(f"存在未提交改动 : {data.get('has_uncommitted_changes')}")
        if data.get("notice"):
            print(f"提示     : {data['notice']}")
        return

    if "entries" in data:
        counts = data.get("counts") or {}
        print(
            f"仓库状态 : {data.get('branch')} @ {data.get('commit_hash')} | "
            f"unmerged={counts.get('unmerged', 0)} staged={counts.get('staged', 0)} "
            f"modified={counts.get('modified', 0)} untracked={counts.get('untracked', 0)}"
        )
        if data.get("in_progress_op"):
            print(f"进行中操作 : {data['in_progress_op']}")
        entries = data.get("entries") or []
        if entries:
            print("未提交 / 冲突文件明细:")
            for item in entries:
                print(f"  [{item.get('code'):>2}] ({item.get('category')}) {item.get('path')}")
        else:
            print("工作区干净无未提交文件。")
        stash_list = data.get("stash_list") or []
        if stash_list:
            print("Stash 栈:")
            for s in stash_list:
                print(f"  {s}")
        return

    if data:
        print(json.dumps(data, ensure_ascii=False, indent=2))


def main() -> int:
    args = build_arg_parser().parse_args()
    default_ports = {"api": 8765, "agent": 18766, "ssh": 22}
    port = args.port if args.port > 0 else default_ports[args.mode]
    token = (args.token or os.environ.get("REMOTE_OPS_TOKEN", "")).strip()

    target = RemoteTarget(
        mode=args.mode,
        host=args.host,
        port=port,
        token=token,
        user=args.user,
        remote_dir=args.remote_dir,
        timeout=args.timeout,
    )
    client = RemoteOpsClient(target)
    res = client.run_action(args.action)
    res_dict = res.to_dict()

    if args.json:
        print(json.dumps(res_dict, ensure_ascii=False, indent=2))
    else:
        _print_summary(res_dict)
    return 0 if res.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
