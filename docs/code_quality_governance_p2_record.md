# 代码质量专项治理（P2）过程留档

## 1. 治理背景与目标

在完成上一轮仓库卫生与基础质量门禁建设后，针对项目“局部热点仍偏重、前端 `any` 与部分边角脚本尚未收口、Electron 主进程缺少静态扫描、CI 未接入后端渐进式类型检查”四个高收益改进项，实施五阶段系统性治理与门禁升级。

## 2. 分阶段实施明细与前后指标对比

### 阶段 1：清理历史边角目录与重复配置
1. 移除零引用历史一次性修复脚本（7 个）：`tools/1.py`、`tools/fix_imports_batch.py`、`tools/fix_init_files.py`、`tools/fix_json_comments.py`、`tools/fix_ncbi_component.py`、`tools/project_fixer.py`、`tools/quick_fix_component.py`。
2. 移除重复/冗余目录与配置：`src/pyrightconfig.json`、`third_party/PhageTailFinder/scripts/`（及本地残留 `__pycache__`）。
3. 完善根 `pyrightconfig.json` 排除列表，补充 `archive`、`data`、`database`、`dist`、`models`、`quast`、`results`、`scratch`、`test_data`、`third_party`、`tools`、`vendor`。
4. 同步更新 `docs/project_structure.md` 目录说明与 `tests/test_repo_hygiene.py` 僵尸清理断言。

### 阶段 2：后端圈复杂度压降（C901 上限 35 降为 25）
1. 将 `ruff.toml` 中 `[lint.mccabe]` 的 `max-complexity` 从 `35` 收紧至 `25`。
2. 对全仓超标（`C901 > 25`）的全部 27 个函数进行单一职责拆解，覆盖范围如下：
   - `src/analysis/annotation/`：`builtin_annotator.py`（`export_features_to_files`）、`functional_assigner.py`（`run_blastp_annotation`）、`fuser.py`（`integrate_safety_audit`）。
   - `src/analysis/phage_structure/`：`sequence_annotator.py`（`parse_input_contigs`）、`tmp_analyzer.py`（`_inspect_operon_context`）。
   - `src/backend/`：`api_server.py`（`lifespan`）、`routes/blast.py`（`get_visualization_data`）、`services/diversity_excel_exporter.py`（`build_rich_diversity_excel`）、`services/other_tools/history_cleaner.py`（`cleanup_mail_history`）、`services/other_tools/sangon_downloader.py`（`download_order`）、`services/other_tools/sangon_mail_scanner.py`（`scan_sangon_mails`）、`strain_db.py`（`_reconstruct_from_fs`）。
   - `src/phage_discovery/`：`data/phrog_teacher.py`（`enrich_semantic_targets_with_phrog`）、`data/v4_semantic_prep.py`（`_build_hard_v4_records`、`annotate_train_semantics_with_diamond`）、`inference/judge_boundary_refiner.py`（`refine_region_boundaries_with_judge`）、`inference/judge_rescue_filter.py`（`rescue_and_filter_regions_with_judge`）、`inference/unified_model.py`（`scan_fasta_streaming`）。
   - `src/phylo/`：`delivery/subtree_extractor.py`（`extract_query_focus_subtree`）、`engines/ani/inphared_index.py`（`sample_macro_background`）、`engines/reference/ref_curator.py`（`curate_candidates`）、`pipeline/executor.py`（`_run_job_worker`）。
   - `src/utils/`：`phage_dataset/expansion_downloader.py`（`_run_expansion_pool`）、`translation/biology_translator.py`（`translate_text`、`translate_batch`）、`translation/term_extractor.py`（`normalize_term`、`_determine_category`）。
3. 治理后全仓 `src/`、`tests/` 及 tracked `scripts/**/*.py` 均在 `max-complexity = 25` 下零告警通过。

### 阶段 3：前端千行热点拆解与生产代码 `any` 清零
1. 拆分三个超千行 TypeScript 模块（拆分后全部控制在 631 行以内）：
   - 生工 16S 流水线：拆分为 `useSangonPipeline.ts`（628 行）、`useSangonMailActions.ts`（345 行）、`useSangonOrderActions.ts`（458 行）、`useSangonPipelineShared.ts` 与 `sangonHelpers.ts`。
   - 系统发育树核心画布：拆分为 `TreeCanvas.ts`（404 行）、`TreeSvgRenderer.ts`（631 行）与 `TreeExportBuilder.ts`（156 行）。
   - 泛基因组全景图导出：拆分为 `exportLandscapeFigure.ts`（476 行）、`exportLandscapeSvg.ts`（216 行）与 `exportLandscapeTree.ts`（273 行）。
2. 收口 `src/web-next/src/` 全部生产文件中的显式 `any`：
   - 为请求封装 `OtherTools/api.ts`、`useMailPipeline.ts`、`stores/blast.ts`、`stores/strain/*`、`phage_discovery/types.ts`、`viewer/utils/*`、`Assembly/*`、`pan_genomics/*` 及各 Vue 业务组件补齐精准类型定义，同步抽出 `stores/strain/freezerStats.ts` 与 `components/strain/forms/formTypes.ts` 消除重复计算及表单 `any`。
   - 补强 `vue-tsc` 暴露的多处空值访问与类型窄化问题（包括 `BlastInputPanel.vue`、`StrainDetailPanel.vue`、`useBatchImport.ts`、`useTaxonomySync.ts`、`actions-records.ts` 等）。
3. 在 `src/web-next/eslint.config.js` 中将生产代码 `@typescript-eslint/no-explicit-any` 从 `'warn'` 正式升级为 `'error'`（保留测试文件覆盖规则），实现 `eslint src` 0 error / 0 warning。

### 阶段 4：Electron ESLint 门禁、Pyright CI 接入与脚本同频
1. 新增无外部依赖的 `electron-shell/eslint.config.mjs` 与 `scripts/lint_electron.mjs`，并在 `src/web-next/package.json` 注册 `lint:electron` 脚本，强制约束 `no-empty`（禁止空 `catch`）、`no-undef`、`no-unused-vars`、`no-debugger`、`no-redeclare` 与 `no-unreachable`。
2. 全面治理 `electron-shell/main.js` 与 `electron-shell/dev-runner.js` 中的静默/空 `catch` 块（日志轮转与写入异常直接输出至 `process.stderr`，避免调用封装后的 `console.*` 引起递归；其余生命周期及 IPC 异常补齐带上下文的告警/调试日志）。
3. 在 `.venv` 验证 `pyright 1.1.414` 可用并新增 `pyrightconfig.ci.json` 覆盖 `src/backend/routes` 与 `src/backend/services`，同时修复 `routes/analysis.py`、`services/diversity_engine.py`、`services/other_tools/sangon_mail_scanner.py` 共 12 处空值/字典类型诊断至 `0 errors, 0 warnings, 0 informations`。
4. 同步 `.github/workflows/ci.yml` 与 `scripts/verify_all.ps1`：CI 与本地脚本统一覆盖 Electron 语法/版本同步/`lint:electron`、Ruff、Pyright 渐进式检查、`pytest -m offline -q`、前端 ESLint/Vitest/`vue-tsc -b && vite build`。

## 3. 核心指标前后对比

| 治理维度 | 治理前状态 | 治理后状态 |
| --- | --- | --- |
| 历史边角脚本与冗余目录 | `tools/` 含 7 个零引用脚本，存在重复 `pyrightconfig` 与 `PhageTailFinder/scripts` | 全部清理完毕，卫生测试断言固化 |
| Python 圈复杂度红线（C901） | `max-complexity = 35`，27 个函数高于 25 | `max-complexity = 25`，0 超标告警 |
| 前端千行 TS 热点 | 3 个文件超过 1000 行 | 均拆分为单一职责模块，单文件上限 631 行 |
| 前端生产代码 `any` 数量 | 近百条 `@typescript-eslint/no-explicit-any` 警告，规则为 `'warn'` | 0 条警告，规则升级为 `'error'` |
| Electron 静态检查与空 `catch` | 仅做 `node --check` 语法检查，存在多处空 `catch` | 独立 ESLint 门禁 `lint:electron`（0 error / 0 warning），空 `catch` 清零 |
| 后端渐进式类型检查 | CI 未启用 Pyright | `pyright -p pyrightconfig.ci.json`（`routes` & `services` 0 errors）已入 CI 与本地脚本 |

## 4. 最终回归验证记录

- Ruff 静态检查：`ruff check src tests` 与 tracked `scripts/**/*.py` 检查均通过（`All checks passed!`）。
- Pyright 类型检查：`pyright -p pyrightconfig.ci.json` 通过（`0 errors, 0 warnings, 0 informations`）。
- 后端离线与核心回归：`python -m pytest -m offline -q` 全量通过（245 passed）。
- Electron 门禁：`node --check`（4 个 JS 文件）与 `npm run lint:electron` 均通过（0 error / 0 warning）。
- 前端门禁：`npm run lint`（0 error / 0 warning）、`npm run test -- --run`（22 个测试文件，82 个测试全部通过）、`npm run build`（`vue-tsc -b && vite build` 零错误完成）。
