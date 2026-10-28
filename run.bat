@echo off
setlocal
cd /d "%~dp0"
set "ACTION=%~1"
if "%ACTION%"=="" set "ACTION=start"
if /I "%ACTION%"=="run" set "ACTION=start"

if /I "%ACTION%"=="start" (
  if not exist ".venv\Scripts\python.exe" py -3 -m venv .venv
  if errorlevel 1 exit /b %errorlevel%
  .venv\Scripts\python.exe -m pip install -r requirements.txt
  if errorlevel 1 exit /b %errorlevel%
  set "LOCAL_IPTV_PYTHON=%CD%\.venv\Scripts\python.exe"
  .venv\Scripts\python.exe launcher.py start
  exit /b %errorlevel%
)

if exist ".venv\Scripts\python.exe" (
  .venv\Scripts\python.exe launcher.py "%ACTION%"
) else (
  py -3 launcher.py "%ACTION%"
)
exit /b %errorlevel%
