@echo off
title Git Remote Sync

echo ========================================================
echo               Git Remote Sync (origin/master)
echo ========================================================
echo.

git status --short
echo.
echo [*] Pulling latest commits from remote...
git pull --rebase origin master

if %errorlevel% equ 0 (
    echo.
    echo ========================================================
    echo [SUCCESS] Local workspace is up to date!
    echo ========================================================
) else (
    echo.
    echo ========================================================
    echo [WARNING] Git pull failed. Check network or conflicts.
    echo ========================================================
)

echo.
pause
