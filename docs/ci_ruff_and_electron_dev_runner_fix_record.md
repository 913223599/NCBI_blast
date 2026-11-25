# GitHub CI `Ruff` 门禁失败修复与 `electron-shell/dev-runner.js` 日志转发纳管留档

## 1. 问题与根因复现

### 1.1 GitHub Actions `Backend Lint & Hygiene Guard` 失败根因
1. **Ruff 版本与默认规则集漂移**：
   - 本地开发机安装的是 `ruff 0.14.10`，仓库此前未提供 `ruff.toml` 或 `pyproject.toml`，默认仅启用 `E4/E7/E9/F`。
   - GitHub Actions [.github/workflows/ci.yml](../.github/workflows/ci.yml) 中 `pip install ruff` 拉取最新 `ruff 0.17.6` 后，启用了 `I001`、`UP`、`BLE`、`RUF` 等新默认规则，在本地通过 `uvx --from ruff==0.17.6 ruff check src` 成功复现出与云端完全一致的失败（`7574 errors`）。
2. **CI `pytest` 下一步隐藏阻断（隔离环境实测复现）**：
   - 云端未设置 `PYTHONPATH: "."` 且直接运行 `pytest`，导致导入 `from src...` 抛出 `ModuleNotFoundError: No module named 'src'`；
   - 云端最小依赖清单缺少 `biopython` 与 `python-multipart`（[blast.py](../src/backend/routes/blast.py) 等路由在应用初始化时导入）。

### 1.2 远程主机 `electron-shell/dev-runner.js` 日志转发问题
- Windows 下 `electron.exe` 为 GUI 子系统进程，直接运行 `electron . --dev` 时控制台窗口往往收不到主进程与 Python Sidecar 的实时 `stdout/stderr` 日志；此前仅远程工作区遗留未追踪的 `electron-shell/dev-runner.js`，未纳入仓库统一版本管理。

---

## 2. 本次修复清单

1. **固定 Ruff 目标版本与规则集**（[ruff.toml](../ruff.toml)）：
   - 声明 `target-version = "py311"` 与 `[lint] select = ["E4", "E7", "E9", "F"]`，统一本地与 CI 检查口径。
2. **修复 GitHub Actions CI 工作流**（[.github/workflows/ci.yml](../.github/workflows/ci.yml)）：
   - 补齐 `biopython`、`python-multipart` 依赖；
   - `Core hygiene & security guard tests` 增加 `PYTHONPATH: "."` 并改为 `python -m pytest ...`；
   - 前端任务补充 `node --check electron-shell/dev-runner.js`。
3. **正式纳管 Electron 开发日志转发器**：
   - 新增 [electron-shell/dev-runner.js](../electron-shell/dev-runner.js)：清除 `ELECTRON_RUN_AS_NODE` / `ELECTRON_NO_ATTACH_CONSOLE`，强制开启 `ELECTRON_ENABLE_LOGGING=1` 与 `PYTHONUTF8=1`，通过 `pipe` 实时无缓冲将 `stdout` 与 `stderr` 透传到启动终端窗口，并透传 `SIGINT`/`SIGTERM` 与真实退出码；支持 `ELECTRON_DEV_RUNNER_BINARY` 用于测试替身验证。
   - 更新 [electron-shell/package.json](../electron-shell/package.json)：将 `"dev"` 脚本改为 `"node dev-runner.js --dev"`。
   - 更新 [scripts/verify_all.ps1](../scripts/verify_all.ps1)：在 `[1/6]` 增加 `preload.js` 与 `dev-runner.js` 语法检查。
4. **补充集成测试**（[tests/test_security_and_lan_guard.py](../tests/test_security_and_lan_guard.py)）：
   - 新增 `test_electron_dev_runner_forwards_stdout_stderr_and_exit_code()`，实测验证 `dev-runner.js` 对标准输出、标准错误及非零退出码（`7`）的透传行为。

---

## 3. 验证结果（全量通过）

- `node --check electron-shell/main.js electron-shell/preload.js electron-shell/dev-runner.js`：全部通过。
- `uvx --from ruff==0.17.6 ruff check src`：**All checks passed!**（与 GitHub Actions 同版本实测通过）。
- `python -m ruff check src tests/test_security_and_lan_guard.py`：**All checks passed!**。
- 干净隔离 CI 环境（`PYTHONPATH="."`, `PYTHONUTF8="1"`, `uv run --no-project --with pytest --with fastapi --with httpx --with pydantic --with psutil --with biopython --with python-multipart`）：**25 passed in 13.31s**。
- 本地 `.venv\Scripts\python.exe -m pytest tests/test_repo_hygiene.py tests/test_security_and_lan_guard.py tests/test_resource_guard_and_hygiene_p2.py -q`：**25 passed in 9.01s**。

---

## 4. 远程计算机同步提示

本机推送（`git push`）后，远程主机若因工作区此前自带未追踪 `electron-shell/dev-runner.js` 在 `git pull` 时提示 untracked file would be overwritten，可在远程执行：

```powershell
cd "D:\NCBI blast"
# 先备份或重命名旧的 dev-runner.js，再拉取新版纳管脚本并重启应用
Move-Item -Path "electron-shell\dev-runner.js" -Destination "electron-shell\dev-runner.js.bak" -Force
git pull --rebase origin master
```
