# 远程主机运行日志诊断与系统性问题修复留档

## 1. 远程日志诊断背景

依据远程主机 `2026-11-25 21:30 - 21:32` 完整启动与业务运行日志，共识别出 **5 项实际代码缺陷** 与 **2 项远程部署/目录环境提示**。

---

## 2. 发现的 5 项代码问题与修复方案

### 2.1 `api_server.py` 在首次 `/api/strain/load` 时被二次完整导入执行
- **日志现象**：服务已启动就绪后，前端首次请求 `GET /api/strain/load` 时控制台突然再次输出 `[Config] 已应用 Windows asyncio 稳定性补丁`、`>>> Python API Server Process Started`、`局域网共享路由已挂载`。
- **根因**：Electron 以 `python -m src.backend.api_server` 启动进程，入口模块名为 `__main__`；`src/backend/routes/strains.py` 在 `strain_load_all()` 中执行 `from ..api_server import log_resources`，导致 Python 重新以模块名 `src.backend.api_server` 二次导入并执行顶层初始化与第二个 `FastAPI` 实例构建。
- **修复**：
  - 将线程安全且带 5 秒节流的 `log_resources()` 抽离至独立公共模块 [src/utils/system_monitor.py](../src/utils/system_monitor.py)；
  - 修改 [src/backend/routes/strains.py](../src/backend/routes/strains.py) 改为从 `...utils.system_monitor` 导入 `log_resources`；
  - 清理 [src/backend/api_server.py](../src/backend/api_server.py) 中冗余的 `psutil` / `time` 导入与本地 `log_resources` 实现（保留向后兼容重导出）。

### 2.2 Figure Studio 导出中文样本名时缺字告警与方块乱码
- **日志现象**：渲染 VIRIDIC 图表时 `src/figure_studio/palette.py:174` 报 14 条 `UserWarning: Glyph ... missing from font(s) Arial.`（样本含中文“附件 霍氏肠杆菌噬菌体基因组序列”）。
- **根因**：部分渲染器（如 `viridic_renderer.py`、`host_matrix_renderer.py`）通过 `set_xticklabels` / `set_yticklabels` / `fig.suptitle` / `legend` 直接设置中文文本，未走 `draw_text` 字体路由，导致字体回退至 `Arial` 出现缺字告警及 PDF/PNG 方块乱码。
- **修复**：
  - 在 [src/figure_studio/palette.py](../src/figure_studio/palette.py) 新增 `ensure_figure_text_fonts(fig)`，在 `save_publication_figure()` 导出前自动扫描整张图形中全部 `matplotlib.text.Text` 对象，将包含 CJK 字符的刻度、标题与图例统一切换至 `resolve_cjk_font()`；
  - 同步将 [src/figure_studio/renderers/host_matrix_renderer.py](../src/figure_studio/renderers/host_matrix_renderer.py) 中的 `fig.suptitle(...)` 统一为 `draw_suptitle(...)`。

### 2.3 `fontTools.subset` 导出矢量 PDF 时数百行 INFO 刷屏
- **日志现象**：每次渲染 VIRIDIC / Genome Map / Synteny 图表导出 PDF 时，控制台输出数百行 `fontTools.subset: maxp pruned / Glyph names / Retaining glyphs`。
- **根因**：根日志级别为 `INFO`，未调高 `fontTools` 子集化库日志阈值。
- **修复**：
  - 在 [src/backend/utils/access_log_filter.py](../src/backend/utils/access_log_filter.py) 新增 `NOISY_THIRD_PARTY_LOGGERS` 与 `silence_noisy_third_party_loggers()`，将 `fontTools`、`fontTools.subset`、`fontTools.ttLib`、`matplotlib.font_manager` 日志级别提升至 `WARNING`；
  - 同时在 [src/backend/api_server.py](../src/backend/api_server.py)（日志配置及 `lifespan`）与 [src/figure_studio/palette.py](../src/figure_studio/palette.py)（`apply_journal_rcparams()`）生效。

### 2.4 `/api/settings/ui_translations` 每次请求重复全量读盘两次
- **日志现象**：`GET /api/settings/ui_translations?lang=zh_CN` 单次请求触发两次 `UI Translations loaded: en_US: 11 fragments, zh_CN: 11 fragments`。
- **根因**：`UITranslationManager` 初始化时已加载全部翻译文件，但 [src/backend/routes/settings.py](../src/backend/routes/settings.py) 每次请求仍无条件调用 `translator.load_all_translations()`。
- **修复**：仅在缓存为空或显式传入 `?reload=true` 时才重新读盘加载，并将例行请求日志降为 `debug`。

### 2.5 Electron 转发 Uvicorn 正常 `INFO:` 日志误标 `[Python:ERR]`
- **日志现象**：`INFO: Started server process`、`INFO: Application startup complete.`、`INFO: Uvicorn running on ...`、`INFO: connection open` 因走 stderr 管道，在运行窗口显示为 `[Python:ERR]`。
- **修复**：修改 [electron-shell/main.js](../electron-shell/main.js)，按行解析 `proc.stderr` 输出，对以 `INFO:` 开头的行按 `[Python]` 正常日志转发，仅将警告、错误与堆栈保留 `[Python:ERR]` 标识。

---

## 3. 远程环境同步与目录说明

1. **代码同步说明**：远程本次运行时间（`21:30`）早于或未同步本机最新本地提交（包含轮询 200 访问日志过滤及本次修复），因此日志中仍可见 `GET /api/core/system_metrics HTTP/1.1" 200 OK` 轮询输出；后续代码推拉同步至远程即可一并消除。
2. **`database/database` 嵌套目录提示**：启动日志 `[WARNING] api_server: 检测到历史遗留的 database/database 布局，以下库已自动回退到该目录: ['card', 'cdd_pfam', 'defense_finder', 'phagescope', 'phold', 'swissprot', 'vfdb']` 属于兼容回退安全机制，数据库读写功能不受影响；如后续需规范远程目录结构，可在停服后将该 7 个库目录移动至外层 `D:\NCBI blast\database\`。

---

## 4. 回归测试与验证结果

- 新增回归测试：[tests/test_remote_log_diagnostics_fixes.py](../tests/test_remote_log_diagnostics_fixes.py)。
- `.venv\Scripts\python.exe -m pytest tests/test_remote_log_diagnostics_fixes.py tests/test_system_monitor.py tests/figure_studio/test_figure_studio_renderers.py tests/test_repo_hygiene.py tests/test_security_and_lan_guard.py tests/test_resource_guard_and_hygiene_p2.py -q`：**42 passed in 16.30s**。
- `uvx --from ruff==0.17.6 ruff check src tests/test_remote_log_diagnostics_fixes.py tests/test_system_monitor.py`：**All checks passed!**。
- `node --check electron-shell/main.js`：语法检查通过（exit code 0）。
