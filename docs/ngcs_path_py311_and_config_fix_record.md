# Python 3.11 下 NGCS 跨盘符自动探测失败与 `config.json` 配置支持留档

## 1. 现象与根因分析

### 1.1 远程现场报错
远程主机（`CDDC-20261103OL`，项目路径 `D:\NCBI blast`）清理本地未提交修改并拉取最新代码重启后，提交基因组组装任务 `Assembly_1795612657741` 时立即报错：
- `[ERROR] Assembly.AssemblerStep: 未找到 NGCS 引擎入口文件: D:\NGCS\ngcs\cli.py`

### 1.2 为什么本地（`F:\NCBI blast`）正常而远程失败
1. **Python 3.12+ 专属 API `os.listdrives()` 兼容性缺失**：
   - [path_resolver.py](../src/assembly/utils/path_resolver.py) 原先在 `_list_system_drives()` 中使用 `hasattr(os, "listdrives")` 枚举本地所有逻辑盘符。
   - 本机（Python `3.13.5`）具备 `os.listdrives()`，因而能从 `F:` 跨盘探测到 `E:\NGCS\ngcs\cli.py`。
   - 远程计算机运行在 **Python 3.11** 环境下，不存在 `os.listdrives()`，导致 `_list_system_drives()` 只返回项目所在单盘符 `["D:"]`；当远程 NGCS 放在 `C:\NGCS`、`E:\NGCS` 或其他盘符时无法跨盘发现，只能回退到 `D:\NGCS\ngcs\cli.py` 并报错（且此前远程之所以能跑，可能是本地未提交硬编码或旧版本，清理后彻底暴露此 3.11 兼容性 bug）。
2. **缺少本地 `config.json` 路径配置支持**：
   - 此前 [path_resolver.py](../src/assembly/utils/path_resolver.py) 仅支持函数入参、环境变量与自动探测，不支持从 `.gitignore` 忽略的 `config.json` 读取 `ngcs_root` / `ngcs_cli_path` / `tool_paths.ngcs_root`，也不检查 `PROJECT_ROOT/tools/NGCS` 与 `PROJECT_ROOT/NGCS`。

---

## 2. 本次修复内容

1. **修复 Python <3.12 跨盘符枚举**（[src/assembly/utils/path_resolver.py](../src/assembly/utils/path_resolver.py)）：
   - 新增 `_list_windows_drives_win32()`：在 Windows 且缺失 `os.listdrives` 时，通过 `ctypes.windll.kernel32.GetLogicalDrives()` 读取逻辑盘符位掩码，用 `string.ascii_uppercase` 动态生成盘符列表（完全避免硬编码盘符字面量，保持合规）。
2. **支持 `config.json` 与更多项目相对路径**（[src/assembly/utils/path_resolver.py](../src/assembly/utils/path_resolver.py)）：
   - 新增 `_load_ngcs_config_entries()` 读取 `config.json` 中的 `ngcs_root`、`ngcs_cli_path`、`tool_paths.ngcs_root`、`tool_paths.ngcs_cli_path`；
   - 扩展相对路径探测：`vendor/NGCS`、`tools/NGCS`、`NGCS` 及同级 `../NGCS`，再按全盘符枚举兜底。
3. **优化缺失提示信息**（[src/assembly/steps/assembler.py](../src/assembly/steps/assembler.py)）：
   - 保留 `未找到 NGCS 引擎入口文件: {ngcs_cli}` 核心信息，补充 `config.json` / `NGCS_ROOT` 指引。
4. **补充单元测试**（[tests/test_engineering_optimizations.py](../tests/test_engineering_optimizations.py)）：
   - 新增 `test_assembly_path_resolver_py311_drive_fallback_and_config_json()` 验证模拟 Python 3.11（移除 `os.listdrives`）与 `config.json` 精确解析。

---

## 3. 验证结果

- `.venv\Scripts\python.exe -m pytest tests/test_engineering_optimizations.py tests/test_repo_hygiene.py -q`：**16 passed in 6.03s**。
- `uvx --from ruff==0.17.6 ruff check src`：**All checks passed!**。
- `python -m ruff check src/assembly/utils/path_resolver.py src/assembly/steps/assembler.py tests/test_engineering_optimizations.py`：**All checks passed!**。
- 实测删除 `os.listdrives` 后在本机调用 `resolve_ngcs_cli()`：`_list_system_drives()` 返回 `['F:', 'C:', 'D:', 'E:', 'G:']`，准确找到 `E:\NGCS\ngcs\cli.py`（`exists=True`）。

---

## 4. 远程计算机生效与确认方式

1. 本机推送后，在远程软件更新界面点击更新并重启应用后：
   - 若 NGCS 位于任意盘符根目录（如 `C:\NGCS`、`E:\NGCS`、`F:\NGCS`）或 `D:\NCBI blast\tools\NGCS` / `vendor\NGCS`，Python 3.11 现已能**直接自动发现**，无需任何手工配置。
   - 若远程把 NGCS 放在非根目录的自定义路径（如 `E:\BioTools\NGCS`）或此前曾在 `D:\NCBI blast\results\git_update_backups\20261125_205815` 里有相关配置备份，可在远程 `D:\NCBI blast\config.json` 中加上一行即可永久生效（不会引起 Git 冲突）：
     ```json
     "ngcs_root": "你的NGCS实际目录路径"
     ```
