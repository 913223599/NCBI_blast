# -*- coding: utf-8 -*-
# NCBI Bio-Station 全栈一键质量门禁脚本
# 依次执行：Electron 语法/ESLint 与版本同步校验、Ruff 与 Pyright 检查、
# Pytest 离线回归套件、前端 ESLint + Vitest + TypeScript + Vite 构建、Modern Web Guidance 扫描。

param(
    [switch]$SkipLegacyScan
)

$ErrorActionPreference = "Stop"
$env:PYTHONUTF8 = "1"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$PythonExe = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $PythonExe)) {
    $PythonExe = "python"
}
$PyrightExe = Join-Path $ProjectRoot ".venv\Scripts\pyright.exe"
if (-not (Test-Path $PyrightExe)) {
    $PyrightExe = "pyright"
}

Push-Location $ProjectRoot
try {
    Write-Host "=== [1/6] Electron Syntax, Version Sync & Electron ESLint ===" -ForegroundColor Cyan
    node --check (Join-Path $ProjectRoot "electron-shell\main.js")
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    node --check (Join-Path $ProjectRoot "electron-shell\preload.js")
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    node --check (Join-Path $ProjectRoot "electron-shell\dev-runner.js")
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    node --check (Join-Path $ProjectRoot "electron-shell\electron-builder.config.js")
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    node (Join-Path $ProjectRoot "scripts\sync_version.mjs") --check
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

    Push-Location (Join-Path $ProjectRoot "src\web-next")
    try {
        npm run lint:electron
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    }
    finally {
        Pop-Location
    }

    Write-Host "=== [2/6] Python Ruff & Pyright Static Checks ===" -ForegroundColor Cyan
    ruff check src tests
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    $TrackedScripts = @(git ls-files "scripts/*.py" "scripts/**/*.py")
    if ($TrackedScripts.Count -gt 0) {
        ruff check @TrackedScripts
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    }
    & $PyrightExe -p (Join-Path $ProjectRoot "pyrightconfig.ci.json")
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

    Write-Host "=== [3/6] Backend Pytest Offline Guard & Regression Suites ===" -ForegroundColor Cyan
    & $PythonExe -m pytest -m offline -q
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

    Write-Host "=== [4/6] Frontend ESLint & Vitest Unit Tests ===" -ForegroundColor Cyan
    Push-Location (Join-Path $ProjectRoot "src\web-next")
    try {
        npm run lint
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

        npm run test -- --run
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

        Write-Host "=== [5/6] Frontend TypeCheck & Production Build ===" -ForegroundColor Cyan
        npm run build
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    }
    finally {
        Pop-Location
    }

    if (-not $SkipLegacyScan) {
        Write-Host "=== [6/6] Modern Web Guidance Legacy Scan ===" -ForegroundColor Cyan
        npx.cmd -y modern-web-guidance@latest legacy-scan (Join-Path $ProjectRoot "src\web-next\src") --json
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    }

    Write-Host "ALL QUALITY GATES PASSED." -ForegroundColor Green
}
finally {
    Pop-Location
}
