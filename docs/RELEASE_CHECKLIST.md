# NCBI Bio-Station 发布与打包校验清单

本文档规范桌面端（Electron 35 + Python Sidecar）发版前的自动化门禁、安全核验与构建流程。

---

## 1. 版本号单一事实源同步

1. 修改根目录 [version.json](../version.json) 中的 `version`。
2. 执行版本一致性校验或同步：
   ```powershell
   node scripts/sync_version.mjs --write
   node scripts/sync_version.mjs --check
   ```
3. 确认以下三处 `package.json` 与 `version.json` 完全一致：
   - 根目录 `package.json`
   - `electron-shell/package.json`
   - `src/web-next/package.json`

---

## 2. 发版前 6 项全栈质量门禁

在根目录运行一键门禁（要求 6/6 全部退出码 0）：

```powershell
npm run verify
```

门禁涵盖：
1. Electron 主进程 / 预加载 / 开发启动脚本语法检查（`node --check`）；
2. Python `ruff check src`（含 `E4`, `E7`, `E9`, `F`, `B023`, `S202` 零告警）；
3. 后端 9 大核心离线回归套件（仓库卫生、安全与 LAN 隔离、资源守卫、压缩包穿越防线、单向分层与 `BaseTaskDB`、路由、进化树渲染、噬菌体拆解、3D 结构与 Word 引文）；
4. 前端 Vitest 全量单测（0 失败、0 Pinia 告警）；
5. 前端 `vue-tsc -b && vite build`（确认 `dist/` 最新产物生成，首屏包无异常膨胀）；
6. `modern-web-guidance legacy-scan`（0 findings）。

---

## 3. 安全与隐私配置核验

- 确认私有配置未被跟踪：`git ls-files config.json mail_config.json .idea` 必须输出为空；
- 确认默认配置模板存在且不含个人邮箱或密钥：`config.default.json`、`mail_config.default.json`；
- 确认局域网共享默认关闭时非回环 IP 访问 `/api/*` 返回 `403`；
- 确认所有压缩包解压均经由 `src/utils/archive_guard.py`（无裸 `.extractall()`）。

---

## 4. 桌面端构建与打包

```powershell
# 1. 构建前端生产静态包
npm run build

# 2. 使用 electron-builder（自动读取 version.json）打包 Windows 安装包与便携版
cd electron-shell
npx electron-builder --config electron-builder.config.js --dir   # 仅验证目录装配
npx electron-builder --config electron-builder.config.js         # 生成 NSIS 安装包与 Portable 版
```

> **提示（大体积二进制历史瘦身建议）**：若计划将 `tools/` 中历史遗留的大体积二进制从 `.git` 对象库中彻底剥离以缩小克隆体积，请在团队统一停机窗口使用 `git filter-repo` 配合 GitHub Releases 资产分发脚本（`scripts/download_externals.ps1`）执行，避免在日常开发分支直接改写远端共享历史。
