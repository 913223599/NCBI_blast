<#
.SYNOPSIS
    Bootstrap or locate Node.js LTS (>=20) and Python (3.13 preferred for vendor/ete4 cp313 ABI, >=3.11 fallback) + uv.

.DESCRIPTION
    Multi-tier runtime self-healing launcher helper:
    1. Probes portable tools\runtime, bundled tools\miniconda, PATH, py.exe, and registry/common install paths
       (explicitly filtering Windows Store Microsoft\WindowsApps\python.exe stub aliases), prioritizing Python 3.13.
    2. When Python 3.13 or Node.js >=20 is missing and winget is available, invokes winget with PrependPath=1 and
       immediately refreshes PATH from Windows Registry (HKLM + HKCU) so RUN_DEV_ELECTRON.bat continues in-session.
    3. When winget is unavailable or fails, automatically downloads portable Node.js LTS and standalone
       Python 3.13.9 + uv.exe from China mirrors (npmmirror / TUNA PyPI, with official fallback) into
       tools\runtime\ with zero global system pollution or admin privilege requirements.
    4. Emits scratch\runtime_env.bat so RUN_DEV_ELECTRON.bat loads updated PATH, PYTHON_EXE, and UV_EXE.
#>
[CmdletBinding()]
param(
    [string]$ProjectRoot = "",
    [string]$RuntimeDir = "",
    [string]$EnvBatPath = "",
    [ValidateSet("Auto", "Only", "Disabled")]
    [string]$WingetMode = "Auto",
    [string]$WingetExe = "winget",
    [switch]$DisableSystemProbe,
    [switch]$DisableBundledProbe,
    [switch]$SkipUvBootstrap
)

$ErrorActionPreference = "Stop"

if (-not $ProjectRoot) {
    $scriptDir = $PSScriptRoot
    if (-not $scriptDir) { $scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition }
    $ProjectRoot = Split-Path -Parent $scriptDir
}
$ProjectRoot = [System.IO.Path]::GetFullPath($ProjectRoot).TrimEnd('\')
if (-not $RuntimeDir) {
    $RuntimeDir = Join-Path $ProjectRoot "tools\runtime"
}
if (-not $EnvBatPath) {
    $EnvBatPath = Join-Path $ProjectRoot "scratch\runtime_env.bat"
}

function Write-Info([string]$Message) { Write-Host "[runtime] $Message" }
function Write-Warn([string]$Message) { Write-Host "[runtime][WARN] $Message" }
function Write-Err([string]$Message) { Write-Host "[runtime][ERROR] $Message" }

function Refresh-SessionPathFromRegistry {
    if ($DisableSystemProbe) { return }
    try {
        $machinePath = [Environment]::GetEnvironmentVariable("Path", "Machine")
        $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
        $merged = @($machinePath, $userPath, $env:PATH) -join ";"
        $seen = New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::OrdinalIgnoreCase)
        $cleanParts = New-Object 'System.Collections.Generic.List[string]'
        foreach ($part in ($merged -split ";")) {
            $trimmed = $part.Trim()
            if ($trimmed -and $seen.Add($trimmed)) {
                $cleanParts.Add($trimmed)
            }
        }
        $env:PATH = ($cleanParts -join ";")
    } catch {
        # Best effort only
    }
}

function Test-ValidNodeExe([string]$NodeExe) {
    if (-not $NodeExe -or -not (Test-Path $NodeExe -PathType Leaf)) { return $null }
    $dir = Split-Path -Parent $NodeExe
    $npmCmd = Join-Path $dir "npm.cmd"
    if (-not (Test-Path $npmCmd -PathType Leaf)) {
        return $null
    }
    try {
        $rawOut = & $NodeExe -e "console.log(process.versions.node)" 2>$null
        $nodeRc = $LASTEXITCODE
        $verText = ($rawOut | Select-Object -First 1)
        if ($nodeRc -ne 0 -or -not $verText) { return $null }
        $verText = $verText.Trim()
        if ($verText -match "^(\d+)\.") {
            $major = [int]$matches[1]
            if ($major -ge 20) {
                return [PSCustomObject]@{ Exe = $NodeExe; Dir = $dir; Version = $verText }
            }
        }
    } catch {
        return $null
    }
    return $null
}

function Find-NodeRuntime {
    $candidates = New-Object 'System.Collections.Generic.List[string]'
    $candidates.Add((Join-Path $RuntimeDir "node\node.exe"))

    if (-not $DisableSystemProbe) {
        Get-Command node.exe -All -ErrorAction SilentlyContinue | ForEach-Object {
            if ($_.Source) { $candidates.Add($_.Source) }
        }
        $commonDirs = @(
            (Join-Path $env:ProgramFiles "nodejs"),
            (Join-Path ${env:ProgramFiles(x86)} "nodejs"),
            (Join-Path $env:LOCALAPPDATA "Programs\nodejs"),
            $env:NVM_SYMLINK,
            "D:\nodejs",
            "C:\nodejs"
        )
        foreach ($d in $commonDirs) {
            if ($d) { $candidates.Add((Join-Path $d "node.exe")) }
        }
    }

    $seen = New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::OrdinalIgnoreCase)
    foreach ($cand in $candidates) {
        if (-not $cand -or -not $seen.Add($cand)) { continue }
        $res = Test-ValidNodeExe $cand
        if ($res) { return $res }
    }
    return $null
}

function Test-ValidPythonExe([string]$PyExe, [switch]$Require313) {
    if (-not $PyExe -or -not (Test-Path $PyExe -PathType Leaf)) { return $null }
    if ($PyExe -match "\\Microsoft\\WindowsApps\\") { return $null }
    try {
        $probe = & $PyExe -c "import sys, sqlite3, ssl; print(f'{sys.version_info[0]}.{sys.version_info[1]}.{sys.version_info[2]}')" 2>$null
        if ($LASTEXITCODE -ne 0 -or -not $probe) { return $null }
        $ver = ($probe | Select-Object -First 1).Trim()
        if ($ver -match "^(\d+)\.(\d+)\.(\d+)$") {
            $maj = [int]$matches[1]
            $min = [int]$matches[2]
            if ($Require313) {
                if ($maj -eq 3 -and $min -eq 13) {
                    return [PSCustomObject]@{ Exe = $PyExe; Dir = (Split-Path -Parent $PyExe); Version = $ver; Minor = $min }
                }
            } elseif ($maj -eq 3 -and $min -ge 11) {
                return [PSCustomObject]@{ Exe = $PyExe; Dir = (Split-Path -Parent $PyExe); Version = $ver; Minor = $min }
            }
        }
    } catch {
        return $null
    }
    return $null
}

function Find-PythonRuntime([switch]$PreferOnly313) {
    $candidates = New-Object 'System.Collections.Generic.List[string]'
    $candidates.Add((Join-Path $RuntimeDir "python\python.exe"))

    if (-not $DisableBundledProbe) {
        $candidates.Add((Join-Path $ProjectRoot "tools\miniconda\python.exe"))
    }

    if (-not $DisableSystemProbe) {
        # Strictly prefer Python 3.13 first (matches vendor/ete4 *.cp313-win_amd64.pyd Cython ABI)
        $pyLauncher = Get-Command py.exe -ErrorAction SilentlyContinue
        if ($pyLauncher) {
            foreach ($flag in @("-3.13", "-3.12", "-3.11", "-3")) {
                try {
                    $resolved = & $pyLauncher.Source $flag -c "import sys; print(sys.executable)" 2>$null
                    if ($LASTEXITCODE -eq 0 -and $resolved) {
                        $candidates.Add(($resolved | Select-Object -First 1).Trim())
                    }
                } catch {}
            }
        }

        foreach ($verTag in @("313", "312", "311")) {
            if ($env:LOCALAPPDATA) {
                $candidates.Add((Join-Path $env:LOCALAPPDATA "Programs\Python\Python$verTag\python.exe"))
            }
            if ($env:ProgramFiles) {
                $candidates.Add((Join-Path $env:ProgramFiles "Python$verTag\python.exe"))
            }
            $candidates.Add("C:\Python$verTag\python.exe")
            $candidates.Add("D:\Python$verTag\python.exe")
        }

        Get-Command python.exe -All -ErrorAction SilentlyContinue | ForEach-Object {
            if ($_.Source) { $candidates.Add($_.Source) }
        }
    }

    $seen = New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::OrdinalIgnoreCase)
    $unique = New-Object 'System.Collections.Generic.List[string]'
    foreach ($cand in $candidates) {
        if ($cand -and $seen.Add($cand)) { $unique.Add($cand) }
    }

    # Pass 1: Look strictly for Python 3.13 across all candidates
    foreach ($cand in $unique) {
        $res313 = Test-ValidPythonExe $cand -Require313
        if ($res313) { return $res313 }
    }
    if ($PreferOnly313) { return $null }

    # Pass 2: Fallback to Python >= 3.11
    foreach ($cand in $unique) {
        $resFallback = Test-ValidPythonExe $cand
        if ($resFallback) { return $resFallback }
    }
    return $null
}

function Resolve-WingetPath {
    if ($WingetMode -eq "Disabled") { return $null }
    if (Test-Path $WingetExe -PathType Leaf) {
        return (Resolve-Path $WingetExe).Path
    }
    $cmd = Get-Command $WingetExe -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    return $null
}

function Install-NodeViaWinget([string]$WingetPath) {
    foreach ($pkgId in @("OpenJS.NodeJS.LTS", "OpenJS.NodeJS")) {
        Write-Info "Attempting to install Node.js ($pkgId) via winget..."
        try {
            & $WingetPath install --id $pkgId --exact --silent --accept-package-agreements --accept-source-agreements
            $wingetRc = $LASTEXITCODE
            Refresh-SessionPathFromRegistry
            $found = Find-NodeRuntime
            if ($found) { return $found }
            if ($wingetRc -ne 0) {
                Write-Warn "winget ($pkgId) exited with code $wingetRc and Node.js still unavailable."
            }
        } catch {
            Write-Warn "winget Node.js attempt failed ($pkgId): $($_.Exception.Message)"
        }
    }
    return $null
}

function Install-PythonViaWinget([string]$WingetPath) {
    $pkgId = "Python.Python.3.13"
    Write-Info "Attempting to install Python 3.13 ($pkgId) via winget with PrependPath=1..."
    try {
        & $WingetPath install --id $pkgId --exact --silent --accept-package-agreements --accept-source-agreements --override "/quiet PrependPath=1 InstallAllUsers=0 Include_pip=1 Include_test=0"
        $wingetRc = $LASTEXITCODE
        Refresh-SessionPathFromRegistry
        $found = Find-PythonRuntime -PreferOnly313
        if ($found) { return $found }
        if ($wingetRc -ne 0) {
            Write-Warn "winget ($pkgId) exited with code $wingetRc and Python 3.13 still unavailable."
        }
    } catch {
        Write-Warn "winget Python 3.13 attempt failed: $($_.Exception.Message)"
    }
    return $null
}

function Download-FileWithFallback([string[]]$Urls, [string]$DestPath) {
    $destDir = Split-Path -Parent $DestPath
    if (-not (Test-Path $destDir)) { New-Item -ItemType Directory -Force $destDir | Out-Null }
    foreach ($url in $Urls) {
        if (-not $url) { continue }
        Write-Info "Downloading: $url"
        try {
            if (Test-Path $DestPath) { Remove-Item $DestPath -Force -ErrorAction SilentlyContinue }
            & curl.exe -sSL --show-error --fail --connect-timeout 15 --max-time 300 -o $DestPath $url
            if ($LASTEXITCODE -eq 0 -and (Test-Path $DestPath) -and ((Get-Item $DestPath).Length -gt 102400)) {
                return $true
            }
        } catch {
            Write-Warn "Download failed ($url): $($_.Exception.Message)"
        }
    }
    return $false
}

function Select-PortableNodeVersion {
    $preferredMajor = @("v24.", "v22.", "v20.")
    try {
        $jsonRaw = & curl.exe -sL --connect-timeout 10 --max-time 15 "https://npmmirror.com/mirrors/node/index.json"
        if ($LASTEXITCODE -eq 0 -and $jsonRaw) {
            $releases = $jsonRaw | ConvertFrom-Json
            foreach ($prefix in $preferredMajor) {
                $match = $releases | Where-Object {
                    $_.lts -and ($_.version -like "$prefix*") -and ($_.files -contains "win-x64-zip")
                } | Select-Object -First 1
                if ($match) { return [string]$match.version }
            }
            $anyLts = $releases | Where-Object { $_.lts -and ($_.files -contains "win-x64-zip") } | Select-Object -First 1
            if ($anyLts) { return [string]$anyLts.version }
        }
    } catch {
        Write-Warn "Failed to query npmmirror Node index, falling back to pinned LTS version."
    }
    return "v22.14.0"
}

function Install-PortableNodeFromMirror {
    $ver = Select-PortableNodeVersion
    $zipName = "node-$ver-win-x64.zip"
    $urls = @(
        "https://npmmirror.com/mirrors/node/$ver/$zipName",
        "https://nodejs.org/dist/$ver/$zipName"
    )
    $tmpRoot = Join-Path $env:TEMP ("ncbi_rt_node_" + [guid]::NewGuid().ToString("N"))
    New-Item -ItemType Directory -Force $tmpRoot | Out-Null
    try {
        $zipPath = Join-Path $tmpRoot $zipName
        if (-not (Download-FileWithFallback $urls $zipPath)) {
            return $null
        }
        $extractDir = Join-Path $tmpRoot "extract"
        Expand-Archive -Path $zipPath -DestinationPath $extractDir -Force
        $nodeExe = Get-ChildItem -Path $extractDir -Filter "node.exe" -Recurse | Select-Object -First 1
        if (-not $nodeExe) {
            Write-Warn "Downloaded archive does not contain node.exe"
            return $null
        }
        $sourceRoot = $nodeExe.Directory.FullName
        $targetNodeDir = Join-Path $RuntimeDir "node"
        if (Test-Path $targetNodeDir) { Remove-Item -Recurse -Force $targetNodeDir -ErrorAction SilentlyContinue }
        New-Item -ItemType Directory -Force (Split-Path -Parent $targetNodeDir) | Out-Null
        Move-Item -Path $sourceRoot -Destination $targetNodeDir -Force
        $info = Test-ValidNodeExe (Join-Path $targetNodeDir "node.exe")
        if ($info) {
            Write-Info "Portable Node.js ready at $targetNodeDir (v$($info.Version))"
        }
        return $info
    } finally {
        Remove-Item -Recurse -Force $tmpRoot -ErrorAction SilentlyContinue
    }
}

function Install-PortablePythonFromMirror {
    $urls = @(
        "https://registry.npmmirror.com/-/binary/python/3.13.9/python-3.13.9-amd64.zip",
        "https://registry.npmmirror.com/-/binary/python/3.13.5/python-3.13.5-amd64.zip",
        "https://www.python.org/ftp/python/3.13.9/python-3.13.9-amd64.zip"
    )
    $tmpRoot = Join-Path $env:TEMP ("ncbi_rt_py_" + [guid]::NewGuid().ToString("N"))
    New-Item -ItemType Directory -Force $tmpRoot | Out-Null
    try {
        $zipPath = Join-Path $tmpRoot "python-3.13-amd64.zip"
        if (-not (Download-FileWithFallback $urls $zipPath)) {
            return $null
        }
        $targetPyDir = Join-Path $RuntimeDir "python"
        if (Test-Path $targetPyDir) { Remove-Item -Recurse -Force $targetPyDir -ErrorAction SilentlyContinue }
        New-Item -ItemType Directory -Force $targetPyDir | Out-Null
        Expand-Archive -Path $zipPath -DestinationPath $targetPyDir -Force

        # Repair stdlib venv launcher lookup when NuGet/archive layout contains __install__.json
        $ntScripts = Join-Path $targetPyDir "Lib\venv\scripts\nt"
        foreach ($launcher in @("venvlauncher.exe", "venvwlauncher.exe")) {
            $srcLauncher = Join-Path $ntScripts $launcher
            $dstLauncher = Join-Path $targetPyDir $launcher
            if ((Test-Path $srcLauncher) -and -not (Test-Path $dstLauncher)) {
                Copy-Item -Path $srcLauncher -Destination $dstLauncher -Force
            }
        }

        $info = Test-ValidPythonExe (Join-Path $targetPyDir "python.exe") -Require313
        if ($info) {
            Write-Info "Portable Python 3.13 ready at $targetPyDir (v$($info.Version))"
        }
        return $info
    } finally {
        Remove-Item -Recurse -Force $tmpRoot -ErrorAction SilentlyContinue
    }
}

function Find-UvExe {
    $portableUv = Join-Path $RuntimeDir "bin\uv.exe"
    if (Test-Path $portableUv -PathType Leaf) { return $portableUv }
    $venvUv = Join-Path $ProjectRoot ".venv\Scripts\uv.exe"
    if (Test-Path $venvUv -PathType Leaf) { return $venvUv }
    if (-not $DisableSystemProbe) {
        $cmd = Get-Command uv.exe -ErrorAction SilentlyContinue
        if ($cmd) { return $cmd.Source }
    }
    return $null
}

function Ensure-PortableUvExe {
    $existing = Find-UvExe
    if ($existing) { return $existing }

    $tmpRoot = Join-Path $env:TEMP ("ncbi_rt_uv_" + [guid]::NewGuid().ToString("N"))
    New-Item -ItemType Directory -Force $tmpRoot | Out-Null
    try {
        foreach ($indexBase in @(
            "https://pypi.tuna.tsinghua.edu.cn/simple/uv/",
            "https://mirrors.aliyun.com/pypi/simple/uv/"
        )) {
            try {
                $rawJson = & curl.exe -sSL --fail --connect-timeout 10 --max-time 20 -H "Accept: application/vnd.pypi.simple.v1+json" $indexBase
                if ($LASTEXITCODE -ne 0 -or -not $rawJson) { continue }
                $meta = $rawJson | ConvertFrom-Json
                $whl = $meta.files | Where-Object {
                    ($_.filename -like "*win_amd64.whl") -and (-not $_.yanked)
                } | Select-Object -Last 1
                if (-not $whl) { continue }
                $whlUrl = [Uri]::new([Uri]$indexBase, [string]$whl.url).AbsoluteUri
                $whlZip = Join-Path $tmpRoot "uv.zip"
                if (-not (Download-FileWithFallback @($whlUrl) $whlZip)) { continue }
                $exDir = Join-Path $tmpRoot "ex"
                Expand-Archive -Path $whlZip -DestinationPath $exDir -Force
                $uvBin = Get-ChildItem -Path $exDir -Filter "uv.exe" -Recurse | Select-Object -First 1
                if ($uvBin) {
                    $binDir = Join-Path $RuntimeDir "bin"
                    New-Item -ItemType Directory -Force $binDir | Out-Null
                    $targetUv = Join-Path $binDir "uv.exe"
                    Copy-Item -Path $uvBin.FullName -Destination $targetUv -Force
                    Write-Info "Portable uv.exe ready at $targetUv"
                    return $targetUv
                }
            } catch {
                Write-Warn "Failed to extract uv from $indexBase : $($_.Exception.Message)"
            }
        }
    } finally {
        Remove-Item -Recurse -Force $tmpRoot -ErrorAction SilentlyContinue
    }
    return $null
}

# ---- Execution Pipeline ----
$wingetPath = Resolve-WingetPath

# 1. Node.js
$nodeRuntime = Find-NodeRuntime
if (-not $nodeRuntime -and $wingetPath) {
    $nodeRuntime = Install-NodeViaWinget $wingetPath
}
if (-not $nodeRuntime -and $WingetMode -ne "Only") {
    Write-Info "Bootstrapping portable Node.js LTS from mirror into $RuntimeDir..."
    $nodeRuntime = Install-PortableNodeFromMirror
}
if (-not $nodeRuntime) {
    Write-Err "Node.js >= 20 could not be located or installed automatically. Please install from https://nodejs.org/"
    exit 1
}
Write-Info "Node.js ready: v$($nodeRuntime.Version) ($($nodeRuntime.Exe))"

# 2. Python (target 3.13 for vendor/ete4 cp313 Cython extensions; fallback to >=3.11 if offline)
$pyRuntime = Find-PythonRuntime -PreferOnly313
if (-not $pyRuntime -and $wingetPath) {
    $pyRuntime = Install-PythonViaWinget $wingetPath
}
if (-not $pyRuntime -and $WingetMode -ne "Only") {
    Write-Info "Bootstrapping portable Python 3.13 from mirror into $RuntimeDir..."
    $pyRuntime = Install-PortablePythonFromMirror
}
if (-not $pyRuntime -and $WingetMode -ne "Only") {
    $pyRuntime = Find-PythonRuntime
}
if (-not $pyRuntime) {
    Write-Err "Python 3.13 could not be located or installed automatically. Please install from https://www.python.org/downloads/"
    exit 1
}
if ($pyRuntime.Minor -ne 13) {
    Write-Warn "Detected Python $($pyRuntime.Version). Python 3.13 is recommended for built-in vendor/ete4 cp313 extensions."
} else {
    Write-Info "Python ready: v$($pyRuntime.Version) ($($pyRuntime.Exe))"
}

# 3. Portable uv (best effort, dramatically accelerates venv creation and pip installs)
$uvExe = if ($SkipUvBootstrap) { Find-UvExe } else { Ensure-PortableUvExe }

# 4. Write runtime_env.bat for seamless in-session inheritance by RUN_DEV_ELECTRON.bat
$envDir = Split-Path -Parent $EnvBatPath
if ($envDir -and -not (Test-Path $envDir)) {
    New-Item -ItemType Directory -Force $envDir | Out-Null
}
$pathPrefixes = New-Object 'System.Collections.Generic.List[string]'
$pathPrefixes.Add($nodeRuntime.Dir)
$pathPrefixes.Add($pyRuntime.Dir)
$pyScripts = Join-Path $pyRuntime.Dir "Scripts"
if (Test-Path $pyScripts) { $pathPrefixes.Add($pyScripts) }
if ($uvExe) { $pathPrefixes.Add((Split-Path -Parent $uvExe)) }

$prefixStr = ($pathPrefixes -join ";")
$uvVal = if ($uvExe) { $uvExe } else { "" }

$batLines = @(
    "@echo off",
    "SET `"NODE_DIR=$($nodeRuntime.Dir)`"",
    "SET `"NODE_EXE=$($nodeRuntime.Exe)`"",
    "SET `"PYTHON_EXE=$($pyRuntime.Exe)`"",
    "SET `"PYTHON_DIR=$($pyRuntime.Dir)`"",
    "SET `"UV_EXE=$uvVal`"",
    "SET `"PATH=$prefixStr;%PATH%`""
)
[System.IO.File]::WriteAllLines($EnvBatPath, $batLines, (New-Object System.Text.UTF8Encoding($false)))
Write-Info "Runtime environment exported to $EnvBatPath"
exit 0
