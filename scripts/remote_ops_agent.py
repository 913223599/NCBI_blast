# -*- coding: utf-8 -*-
"""
受控白名单远程执行 Agent 服务端入口（默认绑定本机回环，远程运维需显式指定网卡 IP 与允许来源 IP）。

示例：
    python scripts/remote_ops_agent.py --host 26.78.5.143 --port 18766 --allow-ip 26.93.8.7 --generate-token
"""
from __future__ import annotations

import argparse
import os
import secrets
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.ops.remote_executor import ALLOWED_ACTIONS, create_agent_server  # noqa: E402


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="启动受控白名单远程诊断/运维 Agent 服务")
    parser.add_argument("--host", default="127.0.0.1", help="监听 IP 地址（默认 127.0.0.1）")
    parser.add_argument("--port", type=int, default=18766, help="监听 TCP 端口（默认 18766）")
    parser.add_argument("--token", default="", help="Bearer 鉴权 Token（也可通过 REMOTE_OPS_TOKEN 环境变量传入）")
    parser.add_argument("--generate-token", action="store_true", help="自动生成高强度一次性随机 Token")
    parser.add_argument(
        "--allow-ip",
        action="append",
        dest="allowed_ips",
        default=[],
        help="允许访问的来源 IP 白名单（可多次指定，例如 --allow-ip 26.93.8.7）",
    )
    return parser


def main() -> int:
    args = build_arg_parser().parse_args()
    token = (args.token or os.environ.get("REMOTE_OPS_TOKEN", "")).strip()
    if args.generate_token and not token:
        token = secrets.token_urlsafe(24)
        print(f"已生成本次运行临时 Token (请仅在受信任控制端使用): {token}", flush=True)

    if not token:
        print("错误: 必须通过 --token、环境变量 REMOTE_OPS_TOKEN 或 --generate-token 提供鉴权 Token", file=sys.stderr)
        return 2

    server = create_agent_server(
        host=args.host,
        port=args.port,
        token=token,
        project_root=PROJECT_ROOT,
        allowed_ips=args.allowed_ips or None,
    )
    allow_desc = ", ".join(args.allowed_ips) if args.allowed_ips else "<any (protected by Bearer Token)>"
    print(f"受控远程执行 Agent 已启动: http://{args.host}:{args.port}", flush=True)
    print(f"项目根目录: {PROJECT_ROOT}", flush=True)
    print(f"IP 白名单 : {allow_desc}", flush=True)
    print(f"允许动作  : {', '.join(ALLOWED_ACTIONS)}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
