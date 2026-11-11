<#
.SYNOPSIS
    Ensure the Electron binary (node_modules\electron\dist) is complete and usable.

.DESCRIPTION
    Background: the electron npm package fetches and extracts its binary through
    a postinstall hook (install.js -> extract-zip). On some Node.js 22+ builds
    extract-zip silently stops after the first archive entry, leaving dist with a
    single empty "locales" folder. The app then starts Electron with no output at
    all, or reports "Electron failed to install correctly".

    This script repairs dist using PowerShell native extraction and the official
    hashes from checksums.json, without relying on the npm postinstall chain.

.PARAMETER ProjectRoot
    Project root. Defaults to the parent of the directory holding this script.

.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File scripts\ensure_electron.ps1
#>
[CmdletBinding()]
param(
    [string]$ProjectRoot = "",
    [string]$Mirror = "https://npmmirror.com/mirrors/electron/"
)

$ErrorActionPreference = "Stop"

if (-not $ProjectRoot) {
    $scriptDir = $PSScriptRoot
    if (-not $scriptDir) { $scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition }
    $ProjectRoot = Split-Path -Parent $scriptDir
}

$electronDir = Join-Path $ProjectRoot "electron-shell\node_modules\electron"
$distDir = Join-Path $electronDir "dist"
$pkgFile = Join-Path $electronDir "package.json"
$checksumsFile = Join-Path $electronDir "checksums.json"
$exePath = Join-Path $distDir "electron.exe"

function Write-Info([string]$Message) { Write-Host "[electron] $Message" }
function Write-Warn([string]$Message) { Write-Host "[electron][WARN] $Message" }

if (-not (Test-Path $pkgFile)) {
    Write-Warn "electron package not found, skip binary self-heal: $pkgFile"
    exit 0
}

$version = (Get-Content $pkgFile -Raw | ConvertFrom-Json).version
$zipName = "electron-v$version-win32-x64.zip"

function Test-DistOk {
    if (-not (Test-Path $exePath)) { return $false }
    $versionFile = Join-Path $distDir "version"
    if (-not (Test-Path $versionFile)) { return $false }
    $installed = (Get-Content $versionFile -Raw).Trim().TrimStart('v')
    if ($installed -ne $version) { return $false }
    return $true
}

if (Test-DistOk) {
    Write-Info "Electron binary ready (v$version), nothing to repair."
    exit 0
}

Write-Warn "Electron binary missing or mismatched, repairing for v$version ..."
if (Test-Path $distDir) { Remove-Item $distDir -Recurse -Force -ErrorAction SilentlyContinue }
New-Item -ItemType Directory -Force $distDir | Out-Null

# Expected SHA256 from the official checksums.json shipped with the npm package
$expectedHash = $null
if (Test-Path $checksumsFile) {
    $checksums = Get-Content $checksumsFile -Raw | ConvertFrom-Json
    $expectedHash = $checksums.$zipName
}
if ($expectedHash) {
    Write-Info "Official checksum loaded: $expectedHash"
} else {
    Write-Warn "No official checksum found, hash verification will be skipped."
}

function Find-CachedZip {
    $cacheRoot = Join-Path $env:LOCALAPPDATA "electron\Cache"
    if (-not (Test-Path $cacheRoot)) { return $null }
    $candidates = Get-ChildItem $cacheRoot -Recurse -File -Filter $zipName -ErrorAction SilentlyContinue
    foreach ($candidate in $candidates) {
        if (-not $expectedHash) { return $candidate.FullName }
        $hash = (Get-FileHash $candidate.FullName -Algorithm SHA256).Hash
        if ($hash -eq $expectedHash.ToUpper()) { return $candidate.FullName }
        Write-Warn "Cached archive failed checksum, ignored: $($candidate.FullName)"
    }
    return $null
}

$zipPath = Find-CachedZip
if ($zipPath) {
    Write-Info "Using local cache: $zipPath"
} else {
    $zipPath = Join-Path $env:TEMP $zipName
    $url = "$($Mirror.TrimEnd('/'))/$version/$zipName"
    Write-Info "Downloading from mirror: $url"
    try {
        & curl.exe -L --silent --show-error --fail -o $zipPath $url
        if ($LASTEXITCODE -ne 0) { throw "curl exit code $LASTEXITCODE" }
    } catch {
        Write-Warn "Download failed: $($_.Exception.Message)"
        Write-Warn "Check network access, or fetch the archive from https://github.com/electron/electron/releases"
        exit 1
    }
    if ($expectedHash) {
        $hash = (Get-FileHash $zipPath -Algorithm SHA256).Hash
        if ($hash -ne $expectedHash.ToUpper()) {
            Write-Warn "Downloaded archive checksum mismatch (expected $expectedHash, got $hash), aborted."
            Remove-Item $zipPath -Force -ErrorAction SilentlyContinue
            exit 1
        }
        Write-Info "Downloaded archive checksum verified."
    }
}

try {
    Expand-Archive -Path $zipPath -DestinationPath $distDir -Force
} catch {
    Write-Warn "Extraction failed: $($_.Exception.Message)"
    exit 1
}

Set-Content -Path (Join-Path $distDir "version") -Value $version -Encoding ascii -NoNewline
Set-Content -Path (Join-Path $electronDir "path.txt") -Value "electron.exe" -Encoding ascii -NoNewline

if (-not (Test-DistOk)) {
    Write-Warn "Verification failed after repair. Please reinstall the electron package manually."
    exit 1
}

Write-Info "Electron binary repaired (v$version)."
exit 0
