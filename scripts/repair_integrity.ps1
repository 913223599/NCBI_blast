<#
.SYNOPSIS
    Detect and repair a Low integrity level label on the project tree.

.DESCRIPTION
    Sandboxing hosts (agent sandboxes, restricted runners) can relabel files with
    a "Low" mandatory integrity level, together with ACLs that only allow a
    synthetic SID to write.

    A Low-labelled executable is launched as a Low integrity process. Chromium
    then cannot initialise its profile/cache under %APPDATA% and aborts during
    startup: the process exits with 0x80000003 (STATUS_BREAKPOINT) and prints
    nothing at all - the main script never runs, so no application log is written.

    Only the integrity label of an EXECUTABLE IMAGE decides the integrity level of
    the process it starts. Data files stay readable and writable for a Medium
    process, so repairing the launch-critical executables is enough and completes
    in milliseconds instead of minutes.

    Default behaviour repairs only the launch-critical executables.
    Use -Full to re-label the whole project tree (slower, but cleans up everything).

.PARAMETER ProjectRoot
    Project root. Defaults to the parent of the directory holding this script.

.PARAMETER Full
    Re-label the entire project tree instead of only the launch-critical images.

.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File scripts\repair_integrity.ps1

.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File scripts\repair_integrity.ps1 -Full
#>
[CmdletBinding()]
param(
    [string]$ProjectRoot = "",
    [switch]$Full
)

$ErrorActionPreference = "Stop"

if (-not $ProjectRoot) {
    $scriptDir = $PSScriptRoot
    if (-not $scriptDir) { $scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition }
    $ProjectRoot = Split-Path -Parent $scriptDir
}

# Executable images that actually get launched; their label decides the process
# integrity level of everything they start.
$CriticalImages = @(
    "electron-shell\node_modules\electron\dist\electron.exe",
    ".venv\Scripts\python.exe",
    ".venv\Scripts\pythonw.exe",
    "tools\runtime\node\node.exe",
    "tools\runtime\python\python.exe",
    "tools\runtime\python\pythonw.exe",
    "tools\runtime\bin\uv.exe",
    "src\workbench\bin\FastTree.exe",
    "src\workbench\bin\muscle.exe",
    "src\workbench\bin\mafft.exe",
    "vendor\fasttree\FastTree.exe",
    "vendor\iqtree3\iqtree.exe",
    "vendor\MrBayes\mb.exe",
    "tools\miniconda\Scripts\conda.exe",
    "tools\miniconda\python.exe",
    "tools\ncbi_dist\bin\tree-tools\FastTree.exe",
    "tools\ncbi_dist\bin\tree-tools\muscle.exe",
    "tools\ncbi_dist\bin\sra-tools\prefetch.exe",
    "tools\ncbi_dist\bin\sra-tools\fasterq-dump.exe",
    "tools\ncbi_dist\bin\sra-tools\libwinpthread-1.dll"
)

# Also check any Playwright headless/Chromium binaries cached inside vendor\ms-playwright
$PlaywrightVendorRoot = Join-Path $ProjectRoot "vendor\ms-playwright"
if (Test-Path $PlaywrightVendorRoot) {
    Get-ChildItem -Path $PlaywrightVendorRoot -Recurse -File -Include "chrome.exe","chrome-headless-shell.exe" -ErrorAction SilentlyContinue | ForEach-Object {
        $CriticalImages += $_.FullName.Substring($ProjectRoot.Length + 1)
    }
}

$ElectronExe = Join-Path $ProjectRoot "electron-shell\node_modules\electron\dist\electron.exe"

function Test-LowIntegrity([string]$Path) {
    if (-not (Test-Path $Path)) { return $false }
    $output = & icacls $Path 2>&1
    return (($output -join "`n") -match "Low Mandatory Level")
}

function Set-Medium([string]$Path) {
    try {
        & icacls $Path /setintegritylevel Medium 2>&1 | Out-Null
        return $LASTEXITCODE -eq 0
    } catch {
        return $false
    }
}

# ---- Full mode: re-label the whole tree (slow) -----------------------------
if ($Full) {
    Write-Host "[integrity] Full re-label of the project tree (this can take a few minutes)..."
    & icacls $ProjectRoot /setintegritylevel "(OI)(CI)Medium" /T /C /Q | Out-Null
    if (Test-LowIntegrity $ElectronExe) {
        Write-Host "[integrity][WARN] Repair incomplete. Run this script as Administrator."
        exit 1
    }
    Write-Host "[integrity] Full re-label completed."
    exit 0
}

# ---- Default mode: repair launch-critical images only (milliseconds) -------
$watch = [Diagnostics.Stopwatch]::StartNew()

$lowImages = @()
foreach ($rel in $CriticalImages) {
    $imagePath = Join-Path $ProjectRoot $rel
    if (Test-Path $imagePath) {
        if (Test-LowIntegrity $imagePath) { $lowImages += $imagePath }
    }
}

if ($lowImages.Count -eq 0) {
    Write-Host "[integrity] Integrity labels are normal (Medium), nothing to repair."
    exit 0
}

Write-Host "[integrity][WARN] Low integrity label detected on $($lowImages.Count) launch-critical image(s)."
Write-Host "[integrity] A Low-labelled binary makes Chromium abort at startup (0x80000003) with no output."

foreach ($image in $lowImages) {
    if (Set-Medium $image) {
        Write-Host "[integrity] Repaired: $image"
    }
}

# Give the project root an inheritable Medium label so newly created files are
# not downgraded again (non-recursive, so it stays fast).
try { & icacls $ProjectRoot /setintegritylevel "(OI)(CI)Medium" 2>&1 | Out-Null } catch { }

$watch.Stop()

$stillLow = @($lowImages | Where-Object { Test-LowIntegrity $_ })
if ($stillLow.Count -gt 0) {
    Write-Host "[integrity][WARN] Repair failed for: $($stillLow -join ', ')"
    Write-Host "[integrity][WARN] Run as Administrator, or use -Full for a whole-tree pass."
    exit 1
}

if (Test-LowIntegrity $ElectronExe) {
    Write-Host "[integrity][WARN] electron.exe is still Low. Try -Full as Administrator."
    exit 1
}

Write-Host "[integrity] Integrity repaired in $([math]::Round($watch.Elapsed.TotalMilliseconds)) ms."
exit 0
