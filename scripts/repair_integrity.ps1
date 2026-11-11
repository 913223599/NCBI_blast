<#
.SYNOPSIS
    Detect and repair a Low integrity level label on the project tree.

.DESCRIPTION
    Sandboxing hosts (agent sandboxes, restricted runners) can relabel files with
    a "Low" mandatory integrity level, together with ACLs that only allow a
    synthetic SID to write.

    A Low-labelled electron.exe is launched as a Low integrity process. Chromium
    then cannot initialise its profile/cache under %APPDATA% and aborts during
    startup: the process exits with 0x80000003 (STATUS_BREAKPOINT) and prints
    nothing at all - the main script never runs, so no application log is written.

    This script upgrades the whole project tree back to Medium integrity, which is
    the normal level for files created by an interactive user.

.PARAMETER ProjectRoot
    Project root. Defaults to the parent of the directory holding this script.

.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File scripts\repair_integrity.ps1
#>
[CmdletBinding()]
param(
    [string]$ProjectRoot = ""
)

$ErrorActionPreference = "Stop"

if (-not $ProjectRoot) {
    $scriptDir = $PSScriptRoot
    if (-not $scriptDir) { $scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition }
    $ProjectRoot = Split-Path -Parent $scriptDir
}

$electronExe = Join-Path $ProjectRoot "electron-shell\node_modules\electron\dist\electron.exe"

function Test-LowIntegrity([string]$Path) {
    if (-not (Test-Path $Path)) { return $false }
    $output = & icacls $Path 2>&1
    return (($output -join "`n") -match "Low Mandatory Level")
}

$electronLow = Test-LowIntegrity $electronExe
$rootLow = Test-LowIntegrity $ProjectRoot

if (-not $electronLow -and -not $rootLow) {
    Write-Host "[integrity] Integrity labels are normal (Medium), nothing to repair."
    exit 0
}

Write-Host "[integrity][WARN] Low integrity label detected - Chromium cannot start from a Low-labelled binary."
Write-Host "[integrity] Repairing integrity level for the whole project tree (this can take a few minutes)..."

& icacls $ProjectRoot /setintegritylevel "(OI)(CI)Medium" /T /C /Q | Out-Null
$icaclsExit = $LASTEXITCODE

$stillLow = (Test-LowIntegrity $electronExe) -or (Test-LowIntegrity $ProjectRoot)
if ($stillLow) {
    Write-Host "[integrity][WARN] Repair incomplete (icacls exit=$icaclsExit). Run this script as Administrator."
    exit 1
}

Write-Host "[integrity] Integrity level restored to Medium."
exit 0
