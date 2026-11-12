# 工程问题修复与架构加固过程留档

## 1. 背景与目标
针对全项目巡检中发现的 IDE 插件异常、硬编码盘符路径、编码与 Emoji 规范偏差、SQLite 批量写入与内存驻留瓶颈、GPU 3-mer 滑窗局部性缺陷与显存红线控制，以及超大单文件职责耦合问题，按照“先测试后执行、每步留档”的原则完成全面修复与验证。

---

## 2. 分步实施记录

### 步骤一：IDE R Language Server 报错修复与基线测试
- **问题根因**：项目 `.venv`（`scipy` 测试脚本）及 `tools/miniconda` 下包含 `.R` 后缀文件，唤醒了 IDE 的 `reditorsupport.r` 扩展；因宿主机未安装 R 解释器，扩展以空字符串 `''` 调用 `child_process.spawn('')` 抛出 `TypeError: The argument 'file' cannot be empty`。
- **修复措施**：在 [.vscode/settings.json](file:///f:/NCBI%20blast/.vscode/settings.json) 中显式设置 `"r.lsp.enabled": false`。

### 步骤二：消除硬编码路径与跨盘符容错重构
- **新增模块**：创建 [path_resolver.py](file:///f:/NCBI%20blast/src/assembly/utils/path_resolver.py)，提供：
  - `resolve_ngcs_root()` / `resolve_ngcs_cli()`：按入参、`NGCS_ROOT` / `NGCS_CLI_PATH` 环境变量、项目相对路径 `vendor/NGCS`、`../NGCS` 及多盘符顺序动态探测。
  - `resolve_safe_work_dir()` / `get_candidate_safe_work_dirs()`：动态分配纯 ASCII 无空格工作目录，消除对 `E:\NGCS` 与 `E:/NGCS_Work` 的硬编码依赖。
- **关联改造**：
  - [assembler.py](file:///f:/NCBI%20blast/src/assembly/steps/assembler.py)：改用 `path_resolver` 动态解析 CLI 与安全隔离目录。
  - [assembly.py](file:///f:/NCBI%20blast/src/backend/routes/assembly.py)：改用 `get_candidate_safe_work_dirs(task_id)` 检索组装报告与产物。
  - [protein_compare.py](file:///f:/NCBI%20blast/src/backend/routes/protein_compare.py)：将两处 `Path(r"f:\NCBI blast\results\annotations")` 替换为基于 `PROJECT_ROOT` 的相对路径常量 `ANNOTATIONS_DIR`。
  - [main.js](file:///f:/NCBI%20blast/electron-shell/main.js)：`stopPythonSidecar()` 改为通过 `wsl --list --running --quiet` 动态终止运行中的 WSL 发行版，不再硬编码 `Ubuntu`。
  - [test_ngcs_defects_evaluation.py](file:///f:/NCBI%20blast/tests/test_ngcs_defects_evaluation.py) 与 [test_ngcs_defects_solution_prototype.py](file:///f:/NCBI%20blast/tests/test_ngcs_defects_solution_prototype.py)：移除硬编码 `E:\NGCS` 并修复命名空间包遮蔽问题。

### 步骤三：强制 UTF-8 编码合规与全库 Emoji 清理
- **编码合规**：
  - [universal_parser.py](file:///f:/NCBI%20blast/src/utils/universal_parser.py)：移除 `TEXT_ENCODINGS` 中的 `'gbk'`，统一使用 `['utf-8', 'utf-8-sig', 'latin-1']`。
  - [hash_checker.py](file:///f:/NCBI%20blast/src/utils/hash_checker.py) 与 [taxonomy_provider.py](file:///f:/NCBI%20blast/src/utils/taxonomy_provider.py)：为全部文本 `open()` 补齐 `encoding="utf-8"`。
- **Emoji 清理**：
  - 清理 `src/` 下 13 个 Python 文件中的全部 Emoji 符号，经 AST 与正则扫描验证 `src/` 下所有 `.py` 文件 `py_emojis=0, no_enc=0`。

### 步骤四：批量内存保护、SQLite WAL 优化与 GPU 显存红线控制
- **GPU 张量加速器重构**（[gpu_accelerator.py](file:///f:/NCBI%20blast/src/analysis/pan_genomics/gpu_accelerator.py)）：
  - 修复原滚动哈希未减去滑出字符导致单点突变污染整条序列下游特征的缺陷，改用 NumPy 向量化 3-mer 滑窗 `(arr[:-2] * 441 + arr[1:-1] * 21 + arr[2:]) % num_features` 与 `np.bincount`。
  - 引入 `torch.cuda.mem_get_info()` 显存水位检测，预留至少 512MB 物理显存并将单批工作集控制在可用空闲显存的 35% 以内，采用行列二维 Tile 分块矩阵乘法并在前后强制执行 `torch.cuda.empty_cache()`。
- **BLAST 存储与内存封顶优化**（[manager.py](file:///f:/NCBI%20blast/src/blast/manager.py)）：
  - 启用 `PRAGMA journal_mode=WAL;`、`PRAGMA synchronous=NORMAL;`，建立 `idx_results_task_seq ON results(task_id, sequence_id)` 复合索引。
  - 使用 `contextlib.closing` 确保每次数据库操作后立即释放 Windows 文件句柄。
  - 新增 `save_results_batch` 单事务批量写入接口；将 `on_result` 中的序列查找由 $O(N)$ 线性扫描优化为 $O(1)$ 字典查找，并对内存驻留的 `raw_sequence` 实施 500 条封顶保护。

### 步骤五：超大单文件模块化拆分（单一职责原则）
- **蛋白比对引擎拆分**：
  - [categories.py](file:///f:/NCBI%20blast/src/analysis/protein_compare/categories.py)：承载 11 大功能分类正则词典与结构域生物学命名映射。
  - [models.py](file:///f:/NCBI%20blast/src/analysis/protein_compare/models.py)：承载 `ProteinItem`、`MutationSite`、`RegionDomainItem`、`ProteinComparisonRow`、`ProteinComparisonResult` 数据模型。
  - [engine.py](file:///f:/NCBI%20blast/src/analysis/protein_compare/engine.py)：专注序列解析、多线程安全对齐（`threading.local` 独立 `PairwiseAligner`）与 GPU 候选集预筛。
- **其他功能工作台拆分**：
  - [schemas.py](file:///f:/NCBI%20blast/src/backend/services/other_tools/schemas.py)：承载 23 个 Pydantic 请求参数模型与 CSV 表头常量。
  - [sangon_order_inspector.py](file:///f:/NCBI%20blast/src/backend/services/other_tools/sangon_order_inspector.py)：承载生工 16S 订单目录状态巡检与 11 列鉴定结果 CSV 翻译导出逻辑。
  - [other_tools.py](file:///f:/NCBI%20blast/src/backend/routes/other_tools.py)：收敛为纯粹的 FastAPI 路由编排层（由 2189 行精简至 1785 行）。

---

## 3. 验证测试结果
新增专项验证测试 [test_engineering_optimizations.py](file:///f:/NCBI%20blast/tests/test_engineering_optimizations.py)，连同既有单元测试套件全部通过。

