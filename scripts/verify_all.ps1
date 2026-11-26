# -*- coding: utf-8 -*-
# NCBI Bio-Station 全栈一键质量门禁脚本
# 依次执行：Electron 语法校验、Ruff 全量静态检查、Pytest 核心守护套件、
# 前端 Vitest 单测、TypeScript 编译与 Vite 生产构建、Modern Web Guidance 合规扫描。

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

Push-Location $ProjectRoot
try {
    Write-Host "=== [1/6] Electron Main, Preload & Dev-Runner Syntax ===" -ForegroundColor Cyan
    node --check (Join-Path $ProjectRoot "electron-shell\main.js")
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    node --check (Join-Path $ProjectRoot "electron-shell\preload.js")
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    node --check (Join-Path $ProjectRoot "electron-shell\dev-runner.js")
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

    Write-Host "=== [2/6] Python Ruff Full Lint (src/) ===" -ForegroundColor Cyan
    ruff check src
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

    Write-Host "=== [3/6] Backend Pytest Core Guard Suites ===" -ForegroundColor Cyan
    & $PythonExe -m pytest tests/test_repo_hygiene.py tests/test_security_and_lan_guard.py tests/test_resource_guard_and_hygiene_p2.py tests/test_archive_guard.py tests/test_other_tools_api.py tests/test_publication_renderer_layouts.py tests/test_phage_discovery_split_imports.py tests/test_phase7_structure_3d_and_docx_citations.py -q
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

    Write-Host "=== [4/6] Frontend Vitest Unit Tests ===" -ForegroundColor Cyan
    Push-Location (Join-Path $ProjectRoot "src\web-next")
    try {
        npm run test -- --run
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

        Write-Host "=== [5/6] Frontend TypeCheck & Production Build ===" -ForegroundColor Cyan
        npm run build
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    } finally {
        Pop-Location
    }

    if (-not $SkipLegacyScan) {
        Write-Host "=== [6/6] Modern Web Guidance Legacy Scan ===" -ForegroundColor Cyan
        npx.cmd -y modern-web-guidance@latest legacy-scan (Join-Path $ProjectRoot "src\web-next\src") --json
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    }

    Write-Host "ALL QUALITY GATES PASSED." -ForegroundColor Green
} finally {
    Pop-Location
}
