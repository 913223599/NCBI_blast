# Phold AI GPU 启用排查与 Radmin VPN 双向排除 Clash Verge 留档

## 1. 远程 Phold 不调用 GPU 的根因与修复

### 1.1 现场现象与根因
- 远程主机（`CDDC-20261103OL` / `26.78.5.143`）配备 **NVIDIA GeForce RTX 5060**（8 GB 显存，Blackwell 架构 `sm_120`），但在执行 `phold run`（阶段 4/5 3D 结构感知 `Predicting 3Di`）时，任务管理器显示 RTX 5060 专用显存占用 `0.0 GB`、CPU 占用约 `75%`、单蛋白耗时约 `2.02 s/it`。
- **代码根因**：[scripts/setup_phold.sh](../scripts/setup_phold.sh) 原先硬编码安装 **CPU-only PyTorch**（`--index-url https://download.pytorch.org/whl/cpu`），导致 WSL（`NCBIUbuntu`）内的 `phold` 检测到 `torch.cuda.is_available() == False` 而完全退化到 CPU 推理。
- **架构适配要求**：RTX 5060（`sm_120`）需要 **PyTorch `cu128`** 及以上版本（旧版 `cu118`/`cu121`/`cu124` 无法在 Blackwell 上运行 CUDA kernel）。

### 1.2 脚本修复
- 更新 `scripts/setup_phold.sh`（UTF-8 无 BOM、LF 换行、去除 Emoji）：
  1. 在安装阶段自动探测 WSL GPU（`/dev/dxg` 或 `nvidia-smi`）以及现有 PyTorch 是否能够执行 CUDA kernel；
  2. 存在 GPU 且未启用兼容 CUDA 时，优先安装 `torch --index-url https://download.pytorch.org/whl/cu128`（依次回退 `cu124`、`cpu`）；
  3. 在自检阶段输出 `torch` 版本、`cuda_available`、`kernel_ok` 与设备名称。

---

## 2. Clash Verge 彻底双向排除 Radmin VPN（上行 + 下行）

### 2.1 原因排查
- 此前发现 Clash Verge GUI 内存中缓存的旧配置覆盖了 `runtime/config.yaml` 的 `tun.route-exclude-address`，且原配置仅排除了下行目标网段 `26.0.0.0/8`，未排除 Radmin VPN 虚拟网卡接口、`SRC-IP-CIDR,26.0.0.0/8` 源地址回包，以及 `RvControlSvc.exe` 对外打洞/中继服务器的真实公网 IP（`95.110.226.204/32`、`148.113.190.78/32`）。

### 2.2 备份与生效配置
- 备份目录：`C:\Users\Administrator\AppData\Roaming\io.github.clash-verge-rev.clash-verge-rev\clash-verge-rev-backup\radmin_bypass_v2_20261125\`
- **TUN 层**（同步写入 `config.yaml`、`profiles\mOYsccVdpiHg.yaml`、`profiles\siGpJ0hVXvoi.js`、`clash-verge.yaml`、`runtime\config.yaml`）：
  - `exclude-interface: ['Radmin VPN']`
  - `route-exclude-address` 包含：`26.0.0.0/8`、`95.110.226.204/32`、`148.113.190.78/32` 及本地保留网段。
- **规则层**（同步写入 `profiles\rOF20XmGBJda.yaml`、`profiles\siGpJ0hVXvoi.js`、`clash-verge.yaml`、`runtime\config.yaml` 规则最前方，并清理重复规则）：
  - `IP-CIDR,26.0.0.0/8,DIRECT,no-resolve`
  - `SRC-IP-CIDR,26.0.0.0/8,DIRECT`
  - `IP-CIDR,95.110.226.204/32,DIRECT,no-resolve`
  - `IP-CIDR,148.113.190.78/32,DIRECT,no-resolve`
  - Radmin 进程（`RvControlSvc.exe`、`RvRvpnGui.exe`、`RvRvpnGui`、`RvGuiStarter.exe`、`RvFwHelper.exe`、`Radmin.exe`）及官方域名（`radmin-vpn.com`、`radmin.com`、`famatech.com`）。
- **校验与重载**：`verge-mihomo.exe -t` 通过，`PUT /configs?force=true` 返回 `HTTP/1.1 204 No Content`。
