[CmdletBinding()]
param(
    [string]$Distro = "",
    [switch]$CheckOnly,
    [switch]$RunSmokeTest,
    [string]$CudaIndex = "https://download.pytorch.org/whl/cu128"
)

$ErrorActionPreference = "Stop"
$Utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[Console]::OutputEncoding = $Utf8NoBom
$OutputEncoding = $Utf8NoBom

function Resolve-BestWslDistro {
    param([string]$Requested)
    if ($Requested -and $Requested.Trim()) {
        return $Requested.Trim()
    }
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = "wsl.exe"
    $psi.Arguments = "--list --quiet"
    $psi.UseShellExecute = $false
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.StandardOutputEncoding = [System.Text.Encoding]::Unicode
    $proc = [System.Diagnostics.Process]::Start($psi)
    $rawText = $proc.StandardOutput.ReadToEnd()
    $proc.WaitForExit()
    if ($proc.ExitCode -ne 0 -or -not $rawText) {
        throw "未检测到可用的 WSL 发行版，请确认 WSL 已安装。"
    }
    $lines = @()
    foreach ($line in ($rawText -split "`r?`n")) {
        $clean = ($line.Trim([char]0xFEFF) -replace "`0", "").Trim()
        if ($clean) {
            $lines += $clean
        }
    }
    $ubuntu = $lines | Where-Object { $_ -match "ubuntu" } | Select-Object -First 1
    if ($ubuntu) { return $ubuntu }
    $debian = $lines | Where-Object { $_ -match "debian" } | Select-Object -First 1
    if ($debian) { return $debian }
    return ($lines | Select-Object -First 1)
}

function Invoke-WslBash {
    param(
        [string]$TargetDistro,
        [string]$User,
        [string]$ScriptBody
    )
    $lf = ($ScriptBody -replace "`r`n", "`n").TrimEnd("`n") + "`n"
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = "wsl.exe"
    $psi.UseShellExecute = $false
    $psi.RedirectStandardInput = $true
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.StandardOutputEncoding = $Utf8NoBom
    $psi.StandardErrorEncoding = $Utf8NoBom
    if ($User) {
        $psi.Arguments = "-d $TargetDistro -u $User bash -s"
    } else {
        $psi.Arguments = "-d $TargetDistro bash -s"
    }

    $proc = New-Object System.Diagnostics.Process
    $proc.StartInfo = $psi
    [void]$proc.Start()

    $bytes = $Utf8NoBom.GetBytes($lf)
    $proc.StandardInput.BaseStream.Write($bytes, 0, $bytes.Length)
    $proc.StandardInput.BaseStream.Flush()
    $proc.StandardInput.Close()

    $stdoutTask = $proc.StandardOutput.ReadToEndAsync()
    $stderrTask = $proc.StandardError.ReadToEndAsync()
    $proc.WaitForExit()

    $combined = ($stdoutTask.Result + "`n" + $stderrTask.Result).Trim()
    return [pscustomobject]@{
        ExitCode = $proc.ExitCode
        Output   = $combined
    }
}

$targetDistro = Resolve-BestWslDistro -Requested $Distro
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Write-Host "=== WSL Phold GPU 环境诊断与修复 ==="
Write-Host "目标 WSL 发行版 : $targetDistro"
Write-Host "项目根目录      : $projectRoot"

$diagScript = @'
set -u
export PATH="$PATH:/usr/local/bin:/root/.local/bin"
echo "USER=$(whoami)"
echo "HAS_DXG=$([ -e /dev/dxg ] && echo True || echo False)"
PHOLD_BIN="$(command -v phold 2>/dev/null || true)"
echo "PHOLD_BIN=${PHOLD_BIN:-NONE}"
PY_BIN=""
if [ -n "$PHOLD_BIN" ] && [ -r "$PHOLD_BIN" ]; then
  SHEBANG="$(head -n 1 "$PHOLD_BIN" | sed -n 's/^#![[:space:]]*//p')"
  case "$SHEBANG" in
    */env\ *) PY_BIN="$(echo "$SHEBANG" | awk '{print $2}')" ;;
    *) PY_BIN="$(echo "$SHEBANG" | awk '{print $1}')" ;;
  esac
fi
if [ -z "$PY_BIN" ] || [ ! -x "$PY_BIN" ]; then
  PY_BIN="$(command -v python3 || true)"
fi
echo "PY_BIN=${PY_BIN:-NONE}"
if [ -n "$PY_BIN" ]; then
  "$PY_BIN" - << 'PY'
import json, os, sys
info = {
    "python": sys.executable,
    "torch_version": "",
    "torch_file": "",
    "cuda_version": "",
    "cuda_available": False,
    "kernel_ok": False,
    "device_name": "",
    "shadow_paths": [],
    "error": "",
}
for sp in sys.path:
    if ".local" in sp and os.path.isdir(os.path.join(sp, "torch")):
        info["shadow_paths"].append(os.path.join(sp, "torch"))
try:
    import torch
    info["torch_version"] = getattr(torch, "__version__", "")
    info["torch_file"] = getattr(torch, "__file__", "")
    info["cuda_version"] = str(getattr(getattr(torch, "version", None), "cuda", "") or "")
    info["cuda_available"] = bool(torch.cuda.is_available())
    if info["cuda_available"]:
        info["device_name"] = torch.cuda.get_device_name(0)
        val = (torch.zeros(1).cuda() + 1).item()
        info["kernel_ok"] = (abs(val - 1.0) < 1e-6)
        torch.cuda.empty_cache()
except Exception as exc:
    info["error"] = str(exc)
print("DIAG_JSON=" + json.dumps(info, ensure_ascii=False))
print("KERNEL_OK=" + ("True" if info["kernel_ok"] else "False"))
PY
fi
'@

Write-Host "`n--- [1/3] 检查 root 上下文 (后端 PholdEngine / SequenceAnnotator 实际运行上下文) ---"
$rootDiag = Invoke-WslBash -TargetDistro $targetDistro -User "root" -ScriptBody $diagScript
Write-Host $rootDiag.Output.TrimEnd()
if ($rootDiag.ExitCode -ne 0) {
    throw "WSL root 上下文诊断命令失败 (ExitCode=$($rootDiag.ExitCode))，请检查发行版名称 '$targetDistro' 是否正确。"
}

Write-Host "`n--- [2/3] 检查默认用户上下文 (排查 ~/.local 阴影冲突) ---"
$userDiag = Invoke-WslBash -TargetDistro $targetDistro -User "" -ScriptBody $diagScript
Write-Host $userDiag.Output.TrimEnd()
if ($userDiag.ExitCode -ne 0) {
    Write-Warning "WSL 默认用户上下文诊断返回非零状态 (ExitCode=$($userDiag.ExitCode))"
}

$hasDxg = $rootDiag.Output -match "HAS_DXG=True"
$rootKernelOk = $rootDiag.Output -match "KERNEL_OK=True"

if ($CheckOnly) {
    if ($hasDxg -and -not $rootKernelOk) {
        Write-Warning "检测到 /dev/dxg GPU 透传，但 root 上下文中 phold 的 PyTorch CUDA kernel 未通过。"
        exit 2
    }
    Write-Host "`n[OK] CheckOnly 完成。"
    exit 0
}

if (-not $hasDxg) {
    Write-Warning "WSL 未检测到 /dev/dxg GPU 透传，无法安装或验证 GPU 版 PyTorch，跳过重装。"
} elseif ($rootKernelOk) {
    Write-Host "`n[OK] root 上下文中 phold 对应解释器的 CUDA kernel 已正常通过，无需重装。"
} else {
    Write-Host "`n--- [3/3] 清理冲突包并为 phold 解释器安装 CUDA PyTorch ($CudaIndex) ---"
    $fixScript = @"
set -e
export PATH="`$PATH:/usr/local/bin:/root/.local/bin"
PHOLD_BIN="`$(command -v phold 2>/dev/null || true)"
PY_BIN=""
if [ -n "`$PHOLD_BIN" ] && [ -r "`$PHOLD_BIN" ]; then
  SHEBANG="`$(head -n 1 "`$PHOLD_BIN" | sed -n 's/^#![[:space:]]*//p')"
  case "`$SHEBANG" in
    */env\ *) PY_BIN="`$(echo "`$SHEBANG" | awk '{print `$2}')" ;;
    *) PY_BIN="`$(echo "`$SHEBANG" | awk '{print `$1}')" ;;
  esac
fi
if [ -z "`$PY_BIN" ] || [ ! -x "`$PY_BIN" ]; then
  PY_BIN="`$(command -v python3)"
fi
echo "TARGET_PY=`$PY_BIN"
"`$PY_BIN" -m pip uninstall -y torch >/dev/null 2>&1 || true
for d in /root/.local/lib/python*/site-packages/torch /home/*/.local/lib/python*/site-packages/torch; do
  if [ -d "`$d" ]; then
    echo "REMOVING_SHADOW=`$d"
    rm -rf "`$d"
  fi
done
if ! "`$PY_BIN" -m pip install --break-system-packages --upgrade --force-reinstall torch --index-url "$CudaIndex"; then
  echo "PRIMARY_INDEX_FAILED_TRY_CU124"
  "`$PY_BIN" -m pip install --break-system-packages --upgrade --force-reinstall torch --index-url "https://download.pytorch.org/whl/cu124"
fi
"`$PY_BIN" -c "import torch; print('POST_FIX_TORCH=' + torch.__version__, 'CUDA=' + str(torch.cuda.is_available()), 'DEV=' + (torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'NONE'), 'KERNEL=' + str((torch.zeros(1).cuda()+1).item()))"
"@
    $fixRes = Invoke-WslBash -TargetDistro $targetDistro -User "root" -ScriptBody $fixScript
    Write-Host $fixRes.Output.TrimEnd()
    if ($fixRes.ExitCode -ne 0 -or ($fixRes.Output -notmatch "CUDA=True")) {
        throw "WSL PyTorch CUDA 修复未成功，请检查上面输出。"
    }
}

if ($RunSmokeTest) {
    Write-Host "`n--- [冒烟验证] 调用 phold proteins-predict 确认输出 Using device: cuda:0 ---"
    $winDb = Join-Path $projectRoot "database\phold_db"
    if (-not (Test-Path -LiteralPath $winDb)) {
        throw "未找到本地 Phold 数据库目录: $winDb"
    }
    $drive = $winDb.Substring(0, 1).ToLowerInvariant()
    $rest = ($winDb.Substring(2) -replace "\\", "/").TrimStart("/")
    $wslDb = "/mnt/$drive/$rest"

    $smokeScript = @"
set -e
TMPD=`$(mktemp -d /tmp/phold_gpu_smoke_XXXX)
cat > "`$TMPD/smoke.faa" << "EOF"
>smoke_p1
MKTIIALSYIFCLVFADYKDDDDKGGGGSGGGGSGGGGSMKTIIALSYIFCLVFADYKDDDDKGGGGS
EOF
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
phold proteins-predict -i "`$TMPD/smoke.faa" -o "`$TMPD/out" -d "$wslDb" -t 4 -f 2>&1
rm -rf "`$TMPD"
"@
    $smokeRes = Invoke-WslBash -TargetDistro $targetDistro -User "root" -ScriptBody $smokeScript
    Write-Host $smokeRes.Output.TrimEnd()
    if ($smokeRes.Output -notmatch "Using device:\s*cuda:0") {
        throw "phold 冒烟测试未输出 Using device: cuda:0"
    }
    Write-Host "`n[OK] Phold GPU 冒烟测试通过 (Using device: cuda:0)。"
}
