@echo off
TITLE NCBI_BLAST_DEV
PROMPT [$P$G]

echo =======================================
echo   NCBI BLAST Pro - Dev Launcher
echo =======================================

REM Checking python environment
if not exist ".\.venv\Scripts\python.exe" (
    echo [ERROR] No .venv found! 
    echo Please ensure target directory is: %cd%
    pause
    exit /b 1
)

echo [1/2] Starting Frontend (New Window)...
start "Vite Dev Server" cmd /c "cd src\web-next && npm run dev || pause"

echo [2/2] Connecting to Python Shell...
timeout /t 5 /nobreak >nul

set WEB_URL=http://localhost:5173
.\.venv\Scripts\python.exe -m src

echo.
echo Process finished.
pause
