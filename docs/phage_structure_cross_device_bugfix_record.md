# PhageStructure 跨端双缺陷排查与修复留档

## 1. 远程异常诊断与本地核对结论

针对远程主机（`CDDC-20261103OL` / `26.78.5.143`）同步完 `PhageTailFinder` 与 `AI` 权重后运行时日志报出的两处错误，经逐行核对本地代码与环境，确认情况如下：

### 问题 1：`FileNotFoundError: 前噬菌体扫描任务未导出区段序列: ...\prophages.fasta`
- **受影响范围**：**本地与远程 100% 均受影响**。
- **根因**：
  - 前噬菌体扫描导出器 `src/analysis/phage_finder/exporter.py` 第 811 行实际写入的文件名为 `{task_id}_prophages.fasta`，并在 `phage_discovery_db` 的 `files["fasta"]` 中记录相对路径（同时单区段 GenBank 导出至 `regions/region_{idx}.gbk`）。
  - 结构预测管理器 `src/analysis/phage_structure/manager.py` 原 `_load_contigs_from_phage_discovery()` 硬编码拼接 `pd_dir / "prophages.fasta"`，导致前端在「前噬菌体导入」页签预检（`/inspect` 返回 `404 Not Found`）及提交运行（`/run` 抛出 `FileNotFoundError`）全部失败。

### 问题 2：`ModuleNotFoundError: No module named '_loss'`
- **受影响范围**：**远程环境（`scikit-learn 1.9.1`）必现**；本地 `.venv`（`scikit-learn 1.7.2`）暂不触发，但同样在全局 Python 或未来升级 `scikit-learn` 时必现（且测试中已证实本地系统 Python 直接 `joblib.load()` 也会因导入顺序复现 `No module named '_loss'`）。
- **根因**：
  - `models/phage_structure/morphotype_ai_v2.joblib` 与 `morphotype_ai_v1.joblib` 均包含在 `scikit-learn 1.7.2` 下序列化的 `HistGradientBoostingClassifier`，其 `_loss.closs` 被 pickle 为顶层模块 `_loss.CyHalfMultinomialLoss`，在 `scikit-learn 1.9.1` 环境下反序列化失败。
  - 同时 `src/analysis/phage_structure/manager.py` 的 `_attach_ai_predictions()` 将 `load_ai_predictor_bundle()` 放在 `try/except` 保护块之外，使可选双轨 AI 加载异常直接击穿整个主结构预测流水线。

---

## 2. 本机已实施修复清单

1. **新增零 `scikit-learn` / 零 `pickle` 依赖便携推理运行时**：
   - 文件：`src/analysis/phage_structure/portable_ai_runtime.py`
   - 实现纯 NumPy 确定性推理组件（`PortableStandardScaler`、`PortablePCA`、`PortableColumnTransformer`、`PortableLogisticRegression`、`PortableHistGBClassifier`、`PortableVotingClassifier`、`PortablePipeline`），使用 `JSON` + `np.savez_compressed(..., allow_pickle=False)` 加载，彻底消除跨 `scikit-learn` 版本反序列化风险。
   - 同时实现上下文安全的 `safe_joblib_load()`，为历史 `.joblib` 提供 `_loss -> sklearn._loss._loss` 临时兼容别名并自动转为便携推理对象。
2. **导出 V1 / V2 便携推理包**：
   - `models/phage_structure/morphotype_ai_v2.portable.npz`（2,231,438 B）与 `morphotype_ai_v2.portable.json`（5,847 B）
   - `models/phage_structure/morphotype_ai_v1.portable.npz`（843,334 B）与 `morphotype_ai_v1.portable.json`（4,032 B）
   - 数值等价性校验（200 条随机测试样本 + 5% `NaN` 注入）：V1/V2 `deep_only_pipeline` 与 `HistGB` 含 `NaN` 推理最大绝对误差 `0.000e+00`，`fusion_pipeline` 最大绝对误差 `<= 3.177e-07`。
3. **升级 AI 模型加载器**：
   - 文件：`src/analysis/phage_structure/ai_morphotype_model.py`
   - 优先加载 `.portable.npz` + `.portable.json`，缺失时回退 `safe_joblib_load()`；`auto` 模式下如 V2 加载失败可自动平滑回退 V1。
4. **修复前噬菌体区段导入并加固流水线容错**：
   - 文件：`src/analysis/phage_structure/manager.py`
   - 新增 `_resolve_phage_discovery_sequence_source()`，按 `phage_discovery_db` 的 `files["fasta"]`（含跨盘符文件名兜底） -> `{task_id}_prophages.fasta` -> `prophages.fasta` -> `*prophages.fasta` -> `regions/region_{idx}.gbk` / `*prophages.gbk` 顺序定位序列源。
   - 将 `_attach_ai_predictions()` 中的 `load_ai_predictor_bundle()` 移入 `try/except` 块，避免可选 AI 模块异常阻断主规则引擎与 PHROG/TMP/PTF 结果输出。

---

## 3. 验证结果（2026-11-25）

- 回归测试：`tests/test_phage_structure.py` 新增 4 项专项测试，共 **26 / 26 全部 PASSED**（耗时 159.19s）。
- 本地真实前噬菌体任务实测：`inspect_input(source_mode="phage_discovery", source_task_id="phage_20261118_174533_8aa180")` 成功返回 5 个区段（总长 184,758 bp），不再报 `404 Not Found`。
