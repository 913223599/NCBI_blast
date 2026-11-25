# 顶栏性能监控插件 CPU 失真滞后与 GPU 数值缺失修复留档

## 1. 异常现象与根因定位

### 1.1 现场异常对比（远程主机 `26.78.5.143`）
在远程主机并行运行 NGCS 组装任务期间：
- 任务管理器实测：**CPU 25%**、**内存 10.0/31.8 GB (31%)**、**GPU 0 (RTX 5060) 7% (44°C)**；
- 应用顶栏监控胶囊仅显示：**`CPU 9% · RAM 31% · GPU`**（CPU 严重偏低滞后，GPU 无任何算力/显存/温度百分比）。

### 1.2 三项代码根因
1. **CPU 长期均值失真与基准污染**（[core.py](../src/backend/routes/core.py)、[AppHeader.vue](../src/web-next/src/components/layout/AppHeader.vue)）：
   - `/api/core/system_metrics` 原先调用 `psutil.cpu_percent(interval=None)`（非阻塞读自“上一次全局调用以来”的平均利用率），前端每 `15 秒` 才轮询一次，拉取的是过去 15 秒的陈旧历史均值，且与后台监控定时器互相干扰基准点。
2. **GPU 无算力利用率与温度，且主进程白占显存**（[resource_guard.py](../src/utils/resource_guard.py)、[AppHeader.vue](../src/web-next/src/components/layout/AppHeader.vue)）：
   - `AppHeader.vue` 对可用 GPU 仅硬编码显示 `"GPU"`；
   - `GpuGuard.probe()` 通过 `torch.cuda.mem_get_info()` 探测显存，无法返回 GPU 核心算力利用率与温度，还会在主 FastAPI 进程初始化 CUDA 上下文额外消耗显存。
3. **事件循环阻塞**：
   - `get_system_metrics()` 直接在 `async def` 路由中执行同步探测，未使用 `run_in_threadpool`。

---

## 2. 本次修复内容

1. **新增统一实时硬件采集器**（[src/utils/system_monitor.py](../src/utils/system_monitor.py)）：
   - `collect_system_metrics(force=False, cpu_sample_interval=0.25, ttl_sec=1.5)`：使用 `psutil.cpu_percent(interval=0.25)` 采集短时真实瞬时 CPU 利用率，并配合线程锁与 1.5s TTL 缓存防多端并发抖动。
   - `probe_gpu_metrics()`：优先通过 `nvidia-smi` 无窗短超时查询（`name,utilization.gpu,memory.used,memory.total,temperature.gpu`，Windows 下传入 `CREATE_NO_WINDOW` 不弹黑窗）获取算力百分比、已用/空闲/总量显存与温度；不可用时平滑回退 `GpuGuard.probe()` 并计算显存占比。
2. **后端路由非阻塞改造**（[src/backend/routes/core.py](../src/backend/routes/core.py)）：
   - `/api/core/system_metrics` 新增 `?force=bool` 参数并通过 `await run_in_threadpool(collect_system_metrics, force=force)` 执行。
3. **前端监控胶囊与双语词典升级**（[AppHeader.vue](../src/web-next/src/components/layout/AppHeader.vue)、[zh_CN/shell.json](../src/resources/locales/zh_CN/shell.json)、[en_US/shell.json](../src/resources/locales/en_US/shell.json)）：
   - 胶囊格式升级为 `CPU XX% · RAM XX% · GPU XX%`（无核心算力传感器时降级显示 `VRAM XX%`），并增加高负载警示配色（`>=65%` 琥珀色、`>=85%` 红色）；
   - Tooltip 展示 CPU 核心与并发预算、内存占用及 GPU 型号/算力/显存/温度；
   - 轮询间隔缩短至 `3 秒`，增加并发防重入与 `visibilitychange` 节能暂停/切回立即刷新。

---

## 3. 测试与实测验证

- 新增后端测试 [tests/test_system_monitor.py](../tests/test_system_monitor.py) 与前端测试 [appHeaderMetrics.test.ts](../src/web-next/src/components/__tests__/appHeaderMetrics.test.ts)。
- `.venv\Scripts\python.exe -m pytest tests/test_system_monitor.py tests/test_repo_hygiene.py tests/test_security_and_lan_guard.py tests/test_resource_guard_and_hygiene_p2.py -q`：**29 passed in 9.48s**。
- `uvx --from ruff==0.17.6 ruff check src` 与本地 `ruff check`：**All checks passed!**。
- 本机实测 `collect_system_metrics(force=True)`：`RTX 4070 Laptop GPU`、`utilization_percent: 5.0`、`used_vram_mb: 1495`、`total_vram_mb: 8188`、`temperature_c: 61`、`source: "nvidia-smi"`。
- 前端 `npx vue-tsc --noEmit`：**0 errors**；`npx vitest run`：**14 test files / 62 tests passed**。
