@echo off
setlocal
cd /d "F:\NCBI blast"
set "AUTH="
if not "%YS_MAIL_AUTH_CODE%"=="" set "AUTH=%YS_MAIL_AUTH_CODE%"
if "%AUTH%"=="" (
  set "REGEXE=%SystemRoot%\System32\reg.exe"
  if not exist "%REGEXE%" set "REGEXE=reg"
  for /f "tokens=2,*" %%a in ('"%REGEXE%" query "HKCU\Environment" /v YS_MAIL_AUTH_CODE 2^>nul') do set "AUTH=%%b"
)
if "%AUTH%"=="" (
  if exist "F:\NCBI blast\.mail_auth" set /p AUTH=<"F:\NCBI blast\.mail_auth"
)
if "%AUTH%"=="" (
  echo [%date% %time%] AUTO_PIPELINE_FAIL AUTH_CODE_MISSING SYSROOT=%SystemRoot% >> "F:\NCBI blast\results\email_downloads\run_errors.log"
  exit /b 2
)
set "YS_MAIL_AUTH_CODE=%AUTH%"
"F:\NCBI blast\.venv\Scripts\python.exe" -X utf8 -m src.mail_download.auto_pipeline --config "F:\NCBI blast\mail_config.json"
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" (
  echo [%date% %time%] AUTO_PIPELINE_FAIL exit=%RC% >> "F:\NCBI blast\results\email_downloads\run_errors.log"
)
exit /b %RC%
