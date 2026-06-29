@echo off
chcp 65001 >nul
SETLOCAL EnableDelayedExpansion

SET "PROJECT_ROOT=%~dp0"
CD /D "%PROJECT_ROOT%"

TITLE NCBI BLAST Pro Dev Launcher

echo =======================================
echo   NCBI BLAST Pro - Electron Dev Mode
echo =======================================
echo [Status] Project Root: %PROJECT_ROOT%
echo [0/4] Cleaning up zombie processes (Skipped global kill)...
REM taskkill /F /IM python.exe /T >nul 2>&1
REM taskkill /F /IM electron.exe /T >nul 2>&1
ping 127.0.0.1 -n 2 >nul

REM 0. Check and Install Node.js
where npm >nul 2>&1
if errorlevel 1 (
    echo [WARN] Node.js not found in PATH.
    echo [INFO] Attempting to auto-install Node.js via winget...
    winget install OpenJS.NodeJS --silent --accept-package-agreements --accept-source-agreements
    if errorlevel 1 (
        echo [ERROR] Auto-install failed. Please install Node.js manually from https://nodejs.org/
        pause
        exit /b 1
    )
    echo [INFO] Node.js installed successfully.
    echo [INFO] Please close this window and run the script again to refresh environment variables.
    pause
    exit /b 0
)

REM 0.5. Check and Install Python
where python >nul 2>&1
if errorlevel 1 (
    echo [WARN] Python not found in PATH.
    echo [INFO] Attempting to auto-install Python 3 via winget...
    winget install Python.Python.3.11 --silent --accept-package-agreements --accept-source-agreements
    if errorlevel 1 (
        echo [ERROR] Auto-install failed. Please install Python manually from https://www.python.org/
        pause
        exit /b 1
    )
    echo [INFO] Python installed successfully.
    echo [INFO] Please close this window and run the script again to refresh environment variables.
    pause
    exit /b 0
)

REM 1. Check Python VENV
REM 验证现有的虚拟环境是否有效（防止直接复制带来的路径失效问题）
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" --version >nul 2>&1
    if errorlevel 1 (
        echo [WARN] Existing .venv is broken ^(likely copied from another device^).
        echo [INFO] Recreating virtual environment...
        rmdir /s /q .venv
    )
)

if not exist ".venv\Scripts\python.exe" (
    echo [INFO] Auto-creating Python virtual environment...
    python -m venv .venv
    if errorlevel 1 (
        echo [ERROR] Failed to create virtual environment.
        pause
        exit /b 1
    )
    echo [INFO] Virtual environment created successfully.
)

REM 2. Check Electron deps
if not exist "electron-shell\node_modules\electron" (
    echo [1/4] Installing Electron deps...
    pushd electron-shell
    call npm install
    popd
) else (
    echo [1/4] Electron deps ready
)

REM 3. Check Vite deps
if not exist "src\web-next\node_modules" (
    echo [2/4] Installing Vite deps...
    pushd src\web-next
    call npm install
    popd
) else (
    echo [2/4] Vite deps ready
)

REM 4. Check Python API deps
echo [3/4] Checking Python API deps...
".venv\Scripts\python.exe" -c "import fastapi, uvicorn, websockets" >nul 2>&1
if errorlevel 1 (
    echo     Installing missing Python dependencies...
    ".venv\Scripts\pip.exe" install fastapi uvicorn[standard] websockets
)

REM 5. Start Vite Dev Server
echo [4/4] Starting Vite Dev Server (New Window)...
REM Using /D to set working directory directly to avoid complex quoting in cmd /c
start "Vite Dev Server" /D "src\web-next" cmd /c "npm run dev || pause"

echo Waiting for Vite to start...
ping 127.0.0.1 -n 6 >nul

REM 6. Start Electron
echo Starting Electron...
pushd electron-shell
call npm run dev
if errorlevel 1 (
    echo.
    echo [ERROR] Electron process exited with error code %errorlevel%.
    popd
    pause
    exit /b %errorlevel%
)
popd

echo.
echo =======================================
echo   Application Closed Traditionally.
echo =======================================
pause
ENDLOCAL
