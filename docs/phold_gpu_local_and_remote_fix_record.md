# Phold GPU 本机排查与跨机诊断修复留档

## 1. 本机与远程环境对比排查结果

| 检查项 | 本机 (`WIN-7ASIN2F7AB4`) | 远程主机 (`CDDC-20261103OL`, `26.78.5.143`) |
| --- | --- | --- |
| GPU 与架构 | NVIDIA GeForce RTX 4070 Laptop GPU (8 GB, `sm_89`) | NVIDIA GeForce RTX 5060 (8 GB, Blackwell `sm_120`) |
| WSL 发行版 | `Ubuntu` | `NCBIUbuntu` |
| `phold` 实际路径与解释器 | `root`: `/usr/local/bin/phold` -> `/usr/bin/python3` (`phold 1.2.4`)；默认用户额外存在 `/home/administrator/.local/bin/phold` (`1.2.6`) | 历史部署由旧版 `scripts/setup_phold.sh` 安装 |
| WSL PyTorch 与 CUDA 状态 | `torch 2.11.0+cu130`, `cuda_available=True`, `kernel_ok=True`, 无 `~/.local` 阴影包 | 旧任务 `ANNO_1CF9C571` 在 16:46-17:47 执行 `Predicting 3Di` 时 GPU 显存 `0.0 GB`、CPU 约 `75%`、速度约 `2.02 s/it` |
| 本机 `phold proteins-predict` 实测 | 3 条测试蛋白真实走 `Using device: cuda:0` + `half-precision`，速率 `3.81 it/s`，显存占用约 `1.6 GB` | 需在远程运行 `cu128` 修复与 `Using device: cuda:0` 冒烟核验 |

结论：**本机 WSL 不存在装成 CPU 版 PyTorch 的问题**，但暴露了三项跨机代码隐患：
1. [sequence_annotator.py](../src/analysis/phage_structure/sequence_annotator.py) 中 `check_phold_ready` 与 `enhance_with_phold_3d` 调用 `wsl` 时缺少 `-u root`，与 [phold_engine.py](../src/analysis/annotation/engines/phold_engine.py) 所用 `CommandRunner(is_wsl=True)`（使用 `-u root`）上下文不一致；当默认用户与 `root` 的 `~/.local` 存在不同版本 `phold` 或残留 CPU 版 `torch` 时，会导致行为分叉。
2. [phold_engine.py](../src/analysis/annotation/engines/phold_engine.py) 调用 `phold run` 前未先清理显存，也未预检 WSL 内 `phold` shebang 实际解释器的 CUDA kernel 可用性及明确捕获 `Using device:` / `CPU only` 日志。
3. [setup_phold.sh](../scripts/setup_phold.sh) 未自动追踪 `phold` 的 shebang 解释器及排查 `~/.local` 阴影 `torch`，且此前 PowerShell 直接向 `wsl bash -lc` 传嵌套双引号易出现语法截断错误。

---

## 2. 远程同步收尾与历史接口核验

1. **Radmin 白名单 HTTP 同步收尾**：
   - `task-497.log` 第 68-73 行显示 `26.78.5.143` 已完成 `database/pharokka_db/9Aug2025_genomes.fa.msh`、`database/pharokka_db/9Aug2025_data.tsv`、`models/phage_structure/morphotype_ai_v{1,2}.portable.{npz,json}` 共 6 个文件的 `HTTP 200` 拉取。
   - 已终止守护任务 `task-497`，并删除临时入站防火墙规则 `Antigravity-Radmin-PTF-Sync-18765`。
2. **远程接口核验**：
   - `GET http://26.78.5.143:8765/api/analysis/phage_structure/capabilities` 返回 `phagetailfinder_ready=true`、`ai_classifier_ready=true`、`unified_judge_ready=true`、`phold_ready=true`。
   - `POST http://26.78.5.143:8765/api/phylo/phage/ani-screen`（使用动态日期 `9Aug2025_genomes.fa.msh`）实测 `200 OK` 返回 `engine_used="viridic_blastn"` 及完整 `top_hits` / `ani_matrix` / `af_matrix`。

---

## 3. 本次代码与脚本修复清单

1. [src/analysis/annotation/engines/phold_engine.py](../src/analysis/annotation/engines/phold_engine.py)
   - 新增 `_parse_gpu_probe_output`、`_format_gpu_probe_notice` 与异步 `_probe_wsl_gpu_runtime`：在执行 `phold run` 前通过 `base64` 管道无引号风险探测 `phold` shebang 实际解释器的 `/dev/dxg`、`torch` 版本与 `(torch.zeros(1).cuda() + 1).item()` 内核实测。
   - `complement_from_gbk` 执行前先调用 `_cleanup_gpu_memory()`（显存红线保护），上报 GPU/CPU 运行态，并在 `on_phold_output` 中高亮捕获 `Using device:`、`ProstT5 will be run with CPU only` 与 `CUDA out of memory`。
2. [src/analysis/phage_structure/sequence_annotator.py](../src/analysis/phage_structure/sequence_annotator.py)
   - 统一 `check_phold_ready` 与 `enhance_with_phold_3d` 的 WSL 调用为 `wsl -d <distro> -u root`，与 `CommandRunner(is_wsl=True)` 保持一致；顺手清理两处未使用的旧导入（`time`、`METAGENOMIC_BINS_4`）。
3. [scripts/setup_phold.sh](../scripts/setup_phold.sh)（UTF-8 无 BOM、LF 换行）
   - 新增 `resolve_phold_python()` 自动对齐 `$(command -v phold)` 的 shebang 解释器；部署 `cu128`（回退 `cu124`/`cpu`）前检测并清理冲突 `torch` 阴影包。
4. [scripts/fix_phold_gpu_wsl.ps1](../scripts/fix_phold_gpu_wsl.ps1)（新增，UTF-8 无 BOM）
   - 支持 `-Distro`（留空自动通过 `Unicode` 编码解析 `wsl --list --quiet`）、`-CheckOnly`、`-RunSmokeTest`、`-CudaIndex`。
   - 通过 `System.Diagnostics.Process` 向 WSL `bash -s` 发送无 BOM UTF-8 LF 脚本（且规避 `wsl.exe` `-d` 参数不兼容多余双引号问题），自动检查 `root` 与默认用户上下文的 `phold` shebang、阴影包及真实 CUDA kernel；在 `-RunSmokeTest` 模式下用相对路径 `database/phold_db` 验证输出 `Using device: cuda:0`。
5. [tests/test_phold_gpu_diagnostics.py](../tests/test_phold_gpu_diagnostics.py)（新增）
   - 覆盖探测 JSON 解析、4 种 GPU/CPU 告警文案、执行前后显存清理、`Using device` 日志识别及 `sequence_annotator` `-u root` 上下文测试。

---

## 4. 本机验证结果

- `pwsh -NoProfile -File scripts\fix_phold_gpu_wsl.ps1 -CheckOnly`：`Ubuntu` 上 `root` 与 `administrator` 均返回 `KERNEL_OK=True`（`torch 2.11.0+cu130`、`NVIDIA GeForce RTX 4070 Laptop GPU`、`shadow_paths=[]`），退出码 `0`。
- `wsl -d Ubuntu -u root bash -n "/mnt/f/NCBI blast/scripts/setup_phold.sh"`：退出码 `0`（LF、无 BOM）。
- `python -m ruff check src/analysis/annotation/engines/phold_engine.py src/analysis/phage_structure/sequence_annotator.py tests/test_phold_gpu_diagnostics.py`：`All checks passed!`。
- `.venv\Scripts\python.exe -m py_compile ...`：通过。
- `.venv\Scripts\python.exe -m pytest tests/test_phold_gpu_diagnostics.py tests/test_annotation_fixes.py tests/test_phage_structure.py -q`：**35 passed in 141.85s**。

---

## 5. 远程主机 (`26.78.5.143` / `NCBIUbuntu`) 后续执行指引

在远程主机项目目录 `D:\NCBI blast` 拉取本次更新后，执行一键诊断、修复（如 `kernel_ok=False` 自动重装 `cu128` 并清阴影包）与 `Using device: cuda:0` 冒烟验证：

```powershell
git pull
pwsh -NoProfile -File scripts\fix_phold_gpu_wsl.ps1 -Distro NCBIUbuntu -RunSmokeTest
```

若暂未拉取最新仓库代码，也可直接使用两条无引号嵌套转义的兼容命令先检查 `phold` 实际解释器并安装 `cu128`：

```powershell
wsl -d NCBIUbuntu -u root python3 -m pip install --break-system-packages --upgrade --force-reinstall torch --index-url https://download.pytorch.org/whl/cu128
wsl -d NCBIUbuntu -u root python3 -c "import torch; print(torch.__version__, torch.cuda.is_available(), torch.cuda.get_device_name(0), (torch.zeros(1).cuda() + 1).item())"
```
