@echo off
chcp 65001 >nul
SETLOCAL EnableDelayedExpansion

REM ----------------------------------------------------
REM  NCBI BLAST Pro - Dev Launcher and Self-Healing
REM ----------------------------------------------------

SET "PROJECT_ROOT=%~dp0"
CD /D "%PROJECT_ROOT%"

TITLE NCBI BLAST Pro Dev Launcher

echo ===================================================
echo   NCBI BLAST Pro - Dev Mode and Environment Self-Healing
echo ===================================================
echo [Status] Project Root: %PROJECT_ROOT%

REM 1. Check Node.js
where node >nul 2>&1
if errorlevel 1 (
    echo [WARN] Node.js not found in PATH.
    where winget >nul 2>&1
    if not errorlevel 1 (
        echo [INFO] Attempting to auto-install Node.js via winget...
        winget install OpenJS.NodeJS --silent --accept-package-agreements --accept-source-agreements
        if errorlevel 1 (
            echo [ERROR] Auto-install failed. Please install Node.js manually: https://nodejs.org/
            pause
            exit /b 1
        )
        echo [INFO] Node.js installed successfully. Please restart launcher to refresh PATH.
        pause
        exit /b 0
    ) else (
        echo [ERROR] Node.js is required. Please install it from https://nodejs.org/
        pause
        exit /b 1
    )
)

REM 2. Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [WARN] Python not found or invalid.
    where winget >nul 2>&1
    if not errorlevel 1 (
        echo [INFO] Attempting to auto-install Python 3.11 via winget...
        winget install Python.Python.3.11 --silent --accept-package-agreements --accept-source-agreements
        if errorlevel 1 (
            echo [ERROR] Auto-install failed. Please install Python manually: https://www.python.org/downloads/
            pause
            exit /b 1
        )
        echo [INFO] Python installed successfully. Please restart launcher to refresh PATH.
        pause
        exit /b 0
    ) else (
        echo [ERROR] Python is required. Please install Python 3.10+ from https://www.python.org/downloads/
        pause
        exit /b 1
    )
)

REM 3. Check Python VENV
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -c "import sys" >nul 2>&1
    if errorlevel 1 (
        echo [WARN] Existing .venv is broken - likely copied from another device.
        echo [INFO] Recreating virtual environment...
        rmdir /s /q .venv
    )
)

if not exist ".venv\Scripts\python.exe" (
    echo [INFO] Creating Python virtual environment .venv...
    python -m venv .venv
    if errorlevel 1 (
        echo [ERROR] Failed to create virtual environment.
        pause
        exit /b 1
    )
    echo [INFO] Virtual environment created successfully.
)

REM 4. Self-healing environment, directories, binaries, and Python deps with China mirrors
echo [1/3] Running Environment Self-Healing and Python Dependency Audit...
if exist "src\utils\verify_and_install_deps.py" (
    ".venv\Scripts\python.exe" "src\utils\verify_and_install_deps.py"
) else (
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple --trusted-host pypi.tuna.tsinghua.edu.cn --extra-index-url https://mirrors.aliyun.com/pypi/simple/
)
if errorlevel 1 (
    echo [ERROR] Environment self-healing or dependency installation failed.
    pause
    exit /b 1
)

REM 5. Check Electron, Frontend and Root npm deps with China npmmirror (full manifest check)
echo [2/3] Checking Electron and Frontend dependencies with npmmirror...
SET "npm_config_registry=https://registry.npmmirror.com"
SET "ELECTRON_MIRROR=https://npmmirror.com/mirrors/electron/"

node "scripts\check_npm_deps.js" "electron-shell"
if errorlevel 1 (
    echo [INFO] Installing or repairing Electron shell dependencies via npmmirror...
    pushd electron-shell
    call npm install --registry=https://registry.npmmirror.com
    if errorlevel 1 (
        echo [ERROR] Failed to install Electron dependencies.
        popd
        pause
        exit /b 1
    )
    popd
    node "scripts\check_npm_deps.js" "electron-shell"
    if errorlevel 1 (
        echo [ERROR] Electron dependencies remain incomplete after npm install.
        pause
        exit /b 1
    )
)

node "scripts\check_npm_deps.js" "src\web-next"
if errorlevel 1 (
    echo [INFO] Installing or repairing Frontend Vite dependencies via npmmirror...
    pushd src\web-next
    call npm install --registry=https://registry.npmmirror.com
    if errorlevel 1 (
        echo [ERROR] Failed to install Frontend dependencies.
        popd
        pause
        exit /b 1
    )
    popd
    node "scripts\check_npm_deps.js" "src\web-next"
    if errorlevel 1 (
        echo [ERROR] Frontend dependencies remain incomplete after npm install.
        pause
        exit /b 1
    )
)

if exist "package.json" (
    node "scripts\check_npm_deps.js" "."
    if errorlevel 1 (
        echo [INFO] Installing or repairing root helper npm dependencies via npmmirror...
        call npm install --registry=https://registry.npmmirror.com
        if errorlevel 1 (
            echo [WARN] Failed to repair root npm dependencies, continuing...
        )
    )
)

REM 5b. Verify the Electron binary itself and the file integrity labels.
REM     - npm postinstall can silently leave dist empty (extract-zip breaks on Node 22+),
REM       so the binary is repaired from the official archive when needed.
REM     - A Low integrity label on electron.exe makes Chromium abort at startup with
REM       0x80000003 and no output, so the project tree is upgraded back to Medium.
echo [INFO] Verifying Electron binary and file integrity labels...
powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\ensure_electron.ps1"
if errorlevel 1 (
    echo [ERROR] Electron binary is missing and could not be repaired automatically.
    pause
    exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\repair_integrity.ps1"
if errorlevel 1 (
    echo [WARN] Integrity label repair failed. If Electron closes instantly with no output,
    echo        run this once as Administrator then retry:
    echo        powershell -NoProfile -ExecutionPolicy Bypass -File scripts\repair_integrity.ps1
    pause
)

REM 6. Start Services
echo [3/3] Starting Services...

REM Kill stale Vite instances first: a leftover server keeps 5173 busy, so the new
REM instance silently moves to 5174 while Electron still loads 5173 (blank window / stale app)
echo [INFO] Cleaning up stale Vite dev server on port 5173...
powershell -NoProfile -Command "Get-NetTCPConnection -LocalPort 5173 -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique | ForEach-Object { if ($_ -and $_ -ne 0) { try { Stop-Process -Id $_ -Force -ErrorAction Stop; Write-Host ('[INFO] Killed stale Vite process PID ' + $_) } catch {} } }"

echo [INFO] Starting Vite Dev Server...
start "Vite Dev Server" /D "src\web-next" cmd /c "npm run dev || pause"

REM Wait for the port to actually listen; a fixed ping delay is not enough on slow machines
echo [INFO] Waiting for Vite Dev Server to listen on 5173...
powershell -NoProfile -Command "$deadline = (Get-Date).AddSeconds(60); while ((Get-Date) -lt $deadline) { if (Get-NetTCPConnection -LocalPort 5173 -State Listen -ErrorAction SilentlyContinue) { Write-Host '[INFO] Vite is ready: http://localhost:5173'; exit 0 }; Start-Sleep -Milliseconds 500 }; Write-Host '[ERROR] Vite dev server did not listen on 5173 within 60s'; exit 1"
if errorlevel 1 (
    echo [ERROR] Frontend dev server failed to start. Please check the "Vite Dev Server" window.
    pause
    exit /b 1
)

REM Clear Node-mode variables possibly injected by a host process:
REM with ELECTRON_RUN_AS_NODE=1 electron.exe degrades into plain Node, "app" is undefined and it exits silently
set "ELECTRON_RUN_AS_NODE="
set "ELECTRON_NO_ATTACH_CONSOLE="

echo [INFO] Starting Electron Desktop Application...
pushd electron-shell
call npm run dev
set "ELECTRON_EXIT=%errorlevel%"
popd

echo [INFO] Electron exit code: %ELECTRON_EXIT%
if not "%ELECTRON_EXIT%"=="0" (
    echo.
    echo [ERROR] Electron process exited with code %ELECTRON_EXIT%.
    echo [INFO] Diagnostics written to: %PROJECT_ROOT%electron-shell\dev.log
    pause
    exit /b %ELECTRON_EXIT%
)

echo.
echo ===================================================
echo   Application Closed Traditionally.
echo ===================================================
pause
ENDLOCAL
