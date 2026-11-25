# `DELETE /api/phylo/jobs/{job_id}` 500 异常及未捕获异常丢失 CORS 头修复留档

## 1. 现象与双重根因定位

### 1.1 现场现象
在远程主机（`26.78.5.143`，前端 `http://localhost:5173/#/tree`）历史面板删除失败任务 `phylo_261125_200946_940705` 时，浏览器控制台同时报错：
- `Access to fetch at 'http://127.0.0.1:8765/api/phylo/jobs/phylo_261125_200946_940705' from origin 'http://localhost:5173' has been blocked by CORS policy: No 'Access-Control-Allow-Origin' header is present on the requested resource.`
- `DELETE http://127.0.0.1:8765/api/phylo/jobs/phylo_261125_200946_940705 net::ERR_FAILED 500 (Internal Server Error)`

### 1.2 实测验证与根因拆解
1. **CORS 预检本身已正确放行**：对远程 `OPTIONS /api/phylo/jobs/...` 发送预检返回 `200 OK`，响应头包含 `Access-Control-Allow-Methods: GET, POST, PUT, PATCH, DELETE, OPTIONS` 与 `Access-Control-Allow-Origin: http://localhost:5173`。
2. **真正触发 500 崩溃的根因（跨 Python 版本兼容性 + Windows 文件锁）**：
   - [archive_store.py](../src/phylo/storage/archive_store.py) 的 `_rmtree_readonly()` 原先硬编码调用 `shutil.rmtree(path, onexc=_on_exc)`。`onexc` 为 Python 3.12+ 新增关键字参数；若运行时为 Python 3.11 及以下，删除包含目录的作业时在清理 SQLite 记录之后立刻因 `TypeError: rmtree() got an unexpected keyword argument 'onexc'` 崩溃返回 500（实测远程查询该任务 `GET /api/phylo/jobs/phylo_261125_200946_940705` 已为 404，印证 SQLite 记录已删、异常正发生在目录清理阶段）。
   - 此外，在任务刚执行取消后若后台线程/子进程句柄尚未完全释放，Windows 上无重试容错也会触发 `PermissionError` 导致 500。
3. **本机与远程共性的 CORS 丢失根因**：
   - 即使配置了 `CORSMiddleware`，在 Starlette/FastAPI 栈中，最外层 `ServerErrorMiddleware`（含通过 `@app.exception_handler(Exception)` 注册的处理器）位于 `CORSMiddleware` **外层**；当接口抛出未捕获异常（如 `TypeError`、`RuntimeError`）时，响应绕过 `CORSMiddleware` 直接返回裸 500，导致浏览器先报跨域拦截并吞掉原始 500 报错详情。

---

## 2. 本次修复内容

1. **兼容 Python <3.12 与 >=3.12 并增加只读/占用容错重试**（[src/phylo/storage/archive_store.py](../src/phylo/storage/archive_store.py)）：
   - 新增 `_rmtree_supports_onexc()` 通过 `inspect.signature(shutil.rmtree).parameters` 动态判断传 `onexc=` 或 `onerror=`；
   - `_rmtree_readonly()` 升级为支持 `retries=3, retry_delay=0.15` 退避重试并在最终仍被外部进程占锁时记录 warning 返回 `False`，防止目录清理残留导致 `DELETE` 接口报 500。
2. **取消等待与删除路由保护**（[src/phylo/pipeline/executor.py](../src/phylo/pipeline/executor.py)、[src/backend/routes/phylo.py](../src/backend/routes/phylo.py)）：
   - `PhyloJobExecutor.cancel_job()` 新增可选 `wait_timeout: float = 0.0`（默认不变），`delete_phylo_job` 调用时传 `wait_timeout=1.5` 并用 `try/except` 保护，使刚停止的任务线程有机会释放日志/文件句柄。
3. **在 `CORSMiddleware` 内层捕获未处理异常**（[src/backend/api_server.py](../src/backend/api_server.py)）：
   - 新增纯 ASGI 中间件 `UnhandledExceptionJsonMiddleware` 并注册于 `CORSMiddleware` 内层（先于 `CORSMiddleware` 调用 `add_middleware`），确保任何未捕获异常统一返回 JSON `500` 且必定经过 `CORSMiddleware` 附带 `Access-Control-Allow-Origin` 头。
4. **前端 `apiDelete` 错误体解析**（[src/web-next/src/bridge/electron-bridge.ts](../src/web-next/src/bridge/electron-bridge.ts)）：
   - 非 `2xx` 时读取 JSON `detail`/`error`/`message` 或文本错误信息返回 `{ success: false, error, status }`，向 UI 透传真实后端报错。

---

## 3. 回归测试与校验结果

1. 新增 3 项定向测试（[tests/phylo/test_phylo_api.py](../tests/phylo/test_phylo_api.py)）：
   - `test_rmtree_readonly_compatible_with_python311_onerror`：模拟 Python 3.11 仅支持 `onerror=` 的 `shutil.rmtree`，验证含只读文件任务删除返回 `200 OK`；
   - `test_delete_job_tolerates_locked_directory_without_500`：模拟目录持续 `PermissionError` 占用，验证不返回 500 且清理元数据；
   - `test_unhandled_500_preserves_cors_header`：对真实 `api_server.app` 注入模拟 500 路由，带 `Origin: http://localhost:5173` 请求验证返回 `500` 且响应头携带 `access-control-allow-origin: http://localhost:5173`。
2. 实测验证结果：
   - `.venv\Scripts\python.exe -m pytest tests/phylo/test_phylo_api.py -q`：**5 passed in 6.48s**
   - `python -m ruff check src/phylo/storage/archive_store.py src/phylo/pipeline/executor.py src/backend/routes/phylo.py tests/phylo/test_phylo_api.py` 与 `--select F,E9 src/backend/api_server.py`：**All checks passed!**
   - `npx vue-tsc --noEmit`：**0 errors**
   - `npx vitest run`：**13 test files, 59 tests passed**

---

## 4. 远程计算机生效步骤

在本地执行 `git push` 后，在远程计算机 `D:\NCBI blast` 拉取最新代码并重启 API 服务即可生效（同时附注此前已知的另一项远程缺失：若远程需要使用 Pharokka/TerL 提取，请确认 `D:\NCBI blast\database\pharokka_db\all_phrogs.h3m` 及 `phrog_annot_v4.tsv` 是否已补齐）：

```powershell
git pull
# 重启运行中的 Python API 后端（或重启 Electron 客户端）以加载新版 archive_store.py 与 api_server.py
```
