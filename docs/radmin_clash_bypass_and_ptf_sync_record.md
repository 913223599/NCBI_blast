# Radmin VPN 排除 Clash Verge 代理与远程 PhageTailFinder 缺失文件同步留档

## 1. 背景与问题现象

- **日期**：2026-11-25
- **本机**：`WIN-7ASIN2F7AB4`（Radmin VPN IP：`26.93.8.7/8`，项目目录：`F:\NCBI blast`）
- **远程设备**：`CDDC-20261103OL`（Radmin VPN IP：`26.78.5.143/8`，项目目录：`D:\NCBI blast`）
- **问题现象**：
  1. 软件迁移到远程新设备后，界面显示 `PhageTailFinder 未就绪`（同时 `ai_classifier_ready` 为 `false`）。
  2. 本机开启 Clash Verge TUN 模式（`Mihomo`）后，直接访问远程 `26.78.5.143` 的请求被代理/劫持导致超时。

---

## 2. Clash Verge 排除 Radmin VPN 过程与变更清单

### 2.1 根因分析
- 本机 Clash Verge 开启了 `enable_tun_mode: true`（`verge-mihomo` 服务模式）。
- 全局配置 `config.yaml` 中存在显式 `tun.route-exclude-address: []`，覆盖清空了局部合并模板里的排除列表；且 `26.0.0.0/8` 网段和 Radmin VPN 进程未列入 `DIRECT` 规则，同时服务实际加载的运行配置位于 `C:\ProgramData\clash-verge-service\users\0f1f2edd1452b68aa47407624e5a60513595649bcaaaae5f9805e676e4d66002\runtime\config.yaml`。

### 2.2 备份位置
- `C:\Users\Administrator\AppData\Roaming\io.github.clash-verge-rev.clash-verge-rev\clash-verge-rev-backup\radmin_bypass_20261125\`
  - `config.yaml`
  - `clash-verge.yaml`
  - `profiles\mOYsccVdpiHg.yaml`
  - `profiles\rOF20XmGBJda.yaml`
  - `profiles\siGpJ0hVXvoi.js`
  - `runtime_config.yaml`

### 2.3 已生效排除策略
1. **TUN 路由层排除**（写入 `config.yaml`、`profiles\mOYsccVdpiHg.yaml`、`profiles\siGpJ0hVXvoi.js`、`clash-verge.yaml`、`runtime\config.yaml`）：
   - `route-exclude-address` 新增 `26.0.0.0/8`（保留 `192.168.0.0/16`、`10.0.0.0/8`、`172.16.0.0/12`、`127.0.0.0/8`、`224.0.0.0/4`、`100.64.0.0/10`）。
2. **规则头部直连**（写入 `profiles\rOF20XmGBJda.yaml`、`profiles\siGpJ0hVXvoi.js`、`clash-verge.yaml`、`runtime\config.yaml`）：
   - `PROCESS-NAME,RvControlSvc.exe,DIRECT`
   - `PROCESS-NAME,RvRvpnGui.exe,DIRECT`
   - `PROCESS-NAME,RvRvpnGui,DIRECT`
   - `PROCESS-NAME,RvGuiStarter.exe,DIRECT`
   - `PROCESS-NAME,RvFwHelper.exe,DIRECT`
   - `PROCESS-NAME,Radmin.exe,DIRECT`
   - `IP-CIDR,26.0.0.0/8,DIRECT,no-resolve`
   - `DOMAIN-SUFFIX,radmin-vpn.com,DIRECT`
   - `DOMAIN-SUFFIX,radmin.com,DIRECT`
   - `DOMAIN-SUFFIX,famatech.com,DIRECT`

### 2.4 校验与实测结果
- `verge-mihomo.exe -t` 语法校验通过。
- 通过命名管道 `PUT /configs?force=true` 热重载 `runtime\config.yaml` 返回 `HTTP/1.1 204 No Content`。
- `GET /configs` 确认 `tun.route-exclude-address` 包含 `26.0.0.0/8`；`GET /rules` 确认上述 10 条规则处于规则链最前方。
- `GET /connections` 实证 `RvControlSvc.exe` 对打洞/协调服务器（`148.113.190.78:17301`、`95.110.226.204:17313`）的连接命中 `ProcessName(RvControlSvc.exe) -> ['DIRECT']`。
- Windows 路由表确认 `26.0.0.0/8` 绑定在 `Radmin VPN` 网卡。

---

## 3. 远程 `PhageTailFinder 未就绪` 根因与通道排查

### 3.1 远程能力接口诊断
调用 `http://26.78.5.143:8765/api/analysis/phage_structure/capabilities`：
- `phagetailfinder_ready`: `false`
- `ai_classifier_ready`: `false`
- `wsl_pyhmmer_ready`: `true`
- `phold_ready`: `true`
- `unified_judge_ready`: `true`
- `structural_hmm_cached`: `true`
- `structural_hmm_path`: `D:\NCBI blast\database\phage_structure\structural_phrogs.h3m`
- `all_phrogs_available`: `true`

### 3.2 未就绪代码根因
依据 `src/analysis/phage_structure/tail_finder_adapter.py` 与 `.gitignore`：
1. `is_phagetailfinder_ready()` 要求 `third_party/PhageTailFinder/hmmmodel/` 下 4 个参数文件全部存在，且满足以下二选一：
   - `database/phage_tail_finder/ptf_pfams.h3m` 存在且大小大于 `50,000,000` 字节；或
   - WSL 中存在 `/opt/virsorter2_db/hmm/pfam/Pfam-A-*.hmm` 以供在线抽取重建。
2. `.gitignore` 第 37 行忽略了 `database/`、第 72 行忽略了 `*.h3m`、第 99 行忽略了 `/models/`。因此新设备从 GitHub 拉取仓库时不会携带 `database/phage_tail_finder/ptf_pfams.h3m`（144,142,379 字节）以及 `models/phage_structure/*.joblib`（双轨 AI 形态分类模型），导致两项同时未就绪。

### 3.3 传输通道排查
- 远程 `445/SMB` 在使用所提供凭据时返回 `System error 1272`（未认证来宾访问受组织策略阻止）；提供的 `Yssw / Yssw123` 为 Radmin Server（`4899` 端口）凭据。
- `Radmin VPN`（`26.93.8.7 <-> 26.78.5.143`）L3 TCP/UDP 通道已完全打通。

---

## 4. 白名单只读同步服务与待分发文件清单

为安全快速地通过 Radmin VPN 通道补齐缺失文件，在本机 Radmin 网卡 `26.93.8.7:18765` 启动白名单只读 HTTP 服务（仅放行来源 IP `26.78.5.143` 的入站防火墙规则 `Antigravity-Radmin-PTF-Sync-18765`）：

| 相对路径 | 大小 (Bytes) | SHA256 |
| :--- | ---: | :--- |
| `database/phage_tail_finder/ptf_pfams.h3m` | 144142379 | `53ea9e23babfd0c2edf67d83ccb60a2d6384fe02f6ec497cfb76045c07944407` |
| `third_party/PhageTailFinder/hmmmodel/start_prob` | 37 | `50060b3f01cae47942b772b9157d7ff25c15137ae67776ef66bf5778b36ed94a` |
| `third_party/PhageTailFinder/hmmmodel/transition_prob` | 76 | `5d1571ef01821a0291387717e0a7b348519fdeeddf0014385fd2d0bfe611aeed` |
| `third_party/PhageTailFinder/hmmmodel/emission_prob` | 142846 | `6d48b23316bae7cdb60508847b8de934e3e99f6e9af0bd662cc1021174157719` |
| `third_party/PhageTailFinder/hmmmodel/pfam_DICT` | 58474 | `09106ca37254823a66c0e3c6ce6c65e1f46b93c6954cea3fd266f28c8a1020ed` |
| `models/phage_structure/morphotype_ai_v2.joblib` | 2747949 | `873e65b8173f126e2220b42f88050b7e6987dd937b83219c5cbed5f842768045` |
| `models/phage_structure/morphotype_ai_v2_meta.json` | 3403 | `1bf8b338c7e9a470f0d443a79e8aa47a5ff43ecd506f709a315f66b32f6aa169` |
| `models/phage_structure/morphotype_ai_v1.joblib` | 1173390 | `bfa2e048e62fb0d3c2dc8979200259b00ea5b2928e0d22faa99992ee42bc16c6` |
| `models/phage_structure/morphotype_ai_v1_meta.json` | 1901 | `f3689688b3fcb22222fa30c3b408d30ba313f000f43cbb083c28ef5b5f05e756` |

### 4.1 同步完成后清理步骤
1. 停止后台只读同步服务进程；
2. 移除临时防火墙规则：
   ```powershell
   Remove-NetFirewallRule -DisplayName "Antigravity-Radmin-PTF-Sync-18765"
   ```
3. 复测 `http://26.78.5.143:8765/api/analysis/phage_structure/capabilities` 确认 `phagetailfinder_ready` 与 `ai_classifier_ready` 均为 `true`。

---

## 5. 最终同步验证与清理收尾记录

### 5.1 远程同步执行结果（`CDDC-20261103OL` / `26.78.5.143` -> `D:\NCBI blast`）
- `third_party/PhageTailFinder/hmmmodel/*`（4 个参数文件）：`SKIP`（远端已存在且 SHA256 与本机完全一致）。
- `database/phage_tail_finder/ptf_pfams.h3m`（144,142,379 B）：下载并校验 SHA256 一致（`53ea9e23babfd0c2edf67d83ccb60a2d6384fe02f6ec497cfb76045c07944407`）。
- `models/phage_structure/morphotype_ai_v2.joblib`（2,747,949 B）：下载并校验 SHA256 一致（`873e65b8173f126e2220b42f88050b7e6987dd937b83219c5cbed5f842768045`）。
- `models/phage_structure/morphotype_ai_v2_meta.json`（3,403 B）：下载并校验 SHA256 一致（`1bf8b338c7e9a470f0d443a79e8aa47a5ff43ecd506f709a315f66b32f6aa169`）。
- `models/phage_structure/morphotype_ai_v1.joblib`（1,173,390 B）：下载并校验 SHA256 一致（`bfa2e048e62fb0d3c2dc8979200259b00ea5b2928e0d22faa99992ee42bc16c6`）。
- `models/phage_structure/morphotype_ai_v1_meta.json`（1,901 B）：下载并校验 SHA256 一致（`f3689688b3fcb22222fa30c3b408d30ba313f000f43cbb083c28ef5b5f05e756`）。

### 5.2 清理与复测结果
- 后台白名单同步服务（`26.93.8.7:18765`）已停止并确认端口不再监听。
- 临时入站防火墙规则 `Antigravity-Radmin-PTF-Sync-18765` 已删除。
- 本机跨 Radmin VPN 复测 `http://26.78.5.143:8765/api/analysis/phage_structure/capabilities` 验证 `phagetailfinder_ready: true`、`ai_classifier_ready: true`、`unified_judge_ready: true`、`phold_ready: true`、`wsl_pyhmmer_ready: true`。
