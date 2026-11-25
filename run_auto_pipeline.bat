@echo off
setlocal
set "PROJECT_ROOT=%~dp0"
if "%PROJECT_ROOT:~-1%"=="\" set "PROJECT_ROOT=%PROJECT_ROOT:~0,-1%"
cd /d "%PROJECT_ROOT%"
set "AUTH="
if not "%YS_MAIL_AUTH_CODE%"=="" set "AUTH=%YS_MAIL_AUTH_CODE%"
if "%AUTH%"=="" (
  set "REGEXE=%SystemRoot%\System32\reg.exe"
  if not exist "%REGEXE%" set "REGEXE=reg"
  for /f "tokens=2,*" %%a in ('"%REGEXE%" query "HKCU\Environment" /v YS_MAIL_AUTH_CODE 2^>nul') do set "AUTH=%%b"
)
if "%AUTH%"=="" (
  if exist "%PROJECT_ROOT%\.mail_auth" set /p AUTH=<"%PROJECT_ROOT%\.mail_auth"
)
if "%AUTH%"=="" (
  if not exist "%PROJECT_ROOT%\results\email_downloads" mkdir "%PROJECT_ROOT%\results\email_downloads"
  echo [%date% %time%] AUTO_PIPELINE_FAIL AUTH_CODE_MISSING SYSROOT=%SystemRoot% >> "%PROJECT_ROOT%\results\email_downloads\run_errors.log"
  exit /b 2
)
set "YS_MAIL_AUTH_CODE=%AUTH%"
"%PROJECT_ROOT%\.venv\Scripts\python.exe" -X utf8 -m src.mail_download.auto_pipeline --config "%PROJECT_ROOT%\mail_config.json"
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" (
  if not exist "%PROJECT_ROOT%\results\email_downloads" mkdir "%PROJECT_ROOT%\results\email_downloads"
  echo [%date% %time%] AUTO_PIPELINE_FAIL exit=%RC% >> "%PROJECT_ROOT%\results\email_downloads\run_errors.log"
)
exit /b %RC%
