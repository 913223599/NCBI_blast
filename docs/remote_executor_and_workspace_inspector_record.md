# 受控白名单远程执行器与 Git 工作区明细诊断留档

## 1. 设计背景与安全边界

- 实测远程主机 `26.78.5.143` 仅开放项目 API 端口 `8765`，SSH (`22`) 与 WinRM (`5985`) 均关闭；且远程当前代码处于 `e73e7b2`，`/api/settings/update/status` 仅返回 `has_uncommitted_changes: true`，尚未提供逐文件未提交/冲突清单。
- 严格遵循安全底线：**不绕过未开启的系统访问控制，不暴露任意 shell 命令执行接口（RCE）**，而是构建基于 **Bearer Token 强鉴权 + 来源 IP 白名单 + 预定义动作白名单** 的受控远程执行器，并在业务后端同步补充只读明细接口 `GET /api/settings/update/workspace-details`。

---

## 2. 模块与接口清单

1. **Git 工作区只读明细诊断**
   - [src/backend/utils/git_updater.py](../src/backend/utils/git_updater.py)：新增 `_parse_porcelain_status()`（保留首位空格准确区分 `unmerged` / `staged` / `modified` / `untracked`）与 `get_git_workspace_details()`（统计分类计数、文件清单、`git diff --stat`、`git diff --cached --stat` 与 `git stash list`）。
   - [src/backend/routes/settings.py](../src/backend/routes/settings.py)：新增只读接口 `GET /api/settings/update/workspace-details`。
2. **受控远程执行器核心包 `src/ops/remote_executor/`**
   - [models.py](../src/ops/remote_executor/models.py)：定义白名单动作 `ALLOWED_ACTIONS = ("git_status", "git_diff_summary", "git_recover_and_pull", "phold_gpu_check", "service_health")`、只读 SSH 动作集与返回模型。
   - [actions.py](../src/ops/remote_executor/actions.py)：按白名单调度 Git 明细、冲突片段截取、冲突备份并拉取恢复、`phold_gpu_check` 与服务健康检查；任何非白名单动作直接抛出 `PermissionError`。
   - [agent_server.py](../src/ops/remote_executor/agent_server.py)：实现受控 HTTP 服务端，强制 Token >= 16 位、`hmac.compare_digest` 鉴权、来源 IP 白名单过滤、`64 KiB` 请求体上限及审计日志打印。
   - [client.py](../src/ops/remote_executor/client.py)：实现 `RemoteOpsClient`（统一禁用代理直连 Radmin VPN），支持 `api`（含对 `e73e7b2` 旧后端 404 自动降级提示）、`agent` 与 `ssh` 三种模式。
3. **CLI 入口**
   - [scripts/remote_ops_agent.py](../scripts/remote_ops_agent.py)：远程 Agent 启动脚本（支持 `--generate-token` 与 `--allow-ip`）。
   - [scripts/remote_ops_client.py](../scripts/remote_ops_client.py)：本机查询/控制脚本（输出结构化摘要或 `--json`）。

---

## 3. 验证与实测输出

- `.venv\Scripts\python.exe -m pytest tests/test_remote_executor.py tests/test_git_updater.py -q`：**9 passed in 22.25s**（覆盖全分类解析、FastAPI 明细路由、弱 Token 拒绝、401/403 鉴权与 IP/动作白名单拦截、Agent 调用及旧版 API 404 降级）。
- `python -m ruff check src/backend/utils/git_updater.py src/backend/routes/settings.py src/ops scripts/remote_ops_agent.py scripts/remote_ops_client.py tests/test_remote_executor.py`：**All checks passed!**
- `.venv\Scripts\python.exe -m py_compile ...`：全部通过。
- 对远程主机实测 `.venv\Scripts\python.exe scripts/remote_ops_client.py --mode api --host 26.78.5.143 --action git_status`：
  - 返回 `master @ e73e7b2`、`存在未提交改动 : True`，并准确识别远程为尚未升级的旧后端，提示启动 Agent 或拉取新版后即可直出文件级未提交/冲突明细。

---

## 4. 查看远程具体未提交明细的操作指引

### 方式 A：直接升级远程后端后免额外进程查看（推荐）
1. 在本机推送当前最新提交（`git push`）后，在远程按上一份说明清理冲突并 `git pull --rebase origin master` 后重启应用；
2. 此后在本机随时运行免鉴权只读查看：
   ```powershell
   .\.venv\Scripts\python.exe scripts\remote_ops_client.py --mode api --host 26.78.5.143 --action git_status
   ```

### 方式 B：在远程未更新前立刻通过受控 Agent 查看并远程修复
1. 在远程主机 `D:\NCBI blast` 拉取本提交（或更新）后启动临时受控 Agent（仅放行本机 Radmin IP `26.93.8.7`）：
   ```powershell
   .\.venv\Scripts\python.exe scripts\remote_ops_agent.py --host 26.78.5.143 --port 18766 --allow-ip 26.93.8.7 --generate-token
   ```
   （需放行远程防火墙 TCP `18766` 仅来自 `26.93.8.7`。）
2. 在本机使用控制台打印出的临时 Token 立即查看远程逐文件未提交/冲突明细，或一键执行备份清理拉取：
   ```powershell
   .\.venv\Scripts\python.exe scripts\remote_ops_client.py --mode agent --host 26.78.5.143 --port 18766 --token "<一次性Token>" --action git_status
   .\.venv\Scripts\python.exe scripts\remote_ops_client.py --mode agent --host 26.78.5.143 --port 18766 --token "<一次性Token>" --action git_diff_summary
   ```
