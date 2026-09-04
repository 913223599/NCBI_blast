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

REM 5. Check Electron and Frontend deps with China npmmirror
echo [2/3] Checking Electron and Frontend dependencies with npmmirror...
SET "npm_config_registry=https://registry.npmmirror.com"
SET "ELECTRON_MIRROR=https://npmmirror.com/mirrors/electron/"

if not exist "electron-shell\node_modules\electron" (
    echo [INFO] Installing Electron shell dependencies via npmmirror...
    pushd electron-shell
    call npm install --registry=https://registry.npmmirror.com
    if errorlevel 1 (
        echo [ERROR] Failed to install Electron dependencies.
        popd
        pause
        exit /b 1
    )
    popd
) else (
    echo [INFO] Electron shell dependencies ready.
)

if not exist "src\web-next\node_modules\vite" (
    echo [INFO] Installing Frontend Vite dependencies via npmmirror...
    pushd src\web-next
    call npm install --registry=https://registry.npmmirror.com
    if errorlevel 1 (
        echo [ERROR] Failed to install Frontend dependencies.
        popd
        pause
        exit /b 1
    )
    popd
) else (
    echo [INFO] Frontend Vite dependencies ready.
)

REM 6. Start Services
echo [3/3] Starting Services...

echo [INFO] Starting Vite Dev Server...
start "Vite Dev Server" /D "src\web-next" cmd /c "npm run dev || pause"

echo [INFO] Waiting for Vite Dev Server to initialize...
ping 127.0.0.1 -n 5 >nul

echo [INFO] Starting Electron Desktop Application...
pushd electron-shell
call npm run dev
if errorlevel 1 (
    echo.
    echo [ERROR] Electron process exited with code %errorlevel%.
    popd
    pause
    exit /b %errorlevel%
)
popd

echo.
echo ===================================================
echo   Application Closed Traditionally.
echo ===================================================
pause
ENDLOCAL
