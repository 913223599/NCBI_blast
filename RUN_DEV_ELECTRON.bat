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
echo [0/4] Cleaning up zombie processes...
taskkill /F /IM python.exe /T >nul 2>&1
taskkill /F /IM electron.exe /T >nul 2>&1
ping 127.0.0.1 -n 2 >nul

REM 0. Check Node/NPM environment
where npm >nul 2>&1
if errorlevel 1 (
    echo [ERROR] 'npm' not found in PATH. Please install Node.js.
    pause
    exit /b 1
)

REM 1. Check Python VENV
if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] No .venv found at %PROJECT_ROOT%.venv
    echo Please create a virtual environment first.
    pause
    exit /b 1
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
