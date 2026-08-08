@echo off
cd /d "%~dp0"
set "BOT_PYTHON=%~dp0.venv\Scripts\python.exe"
if not exist "%BOT_PYTHON%" (
  echo Project Python environment is missing.
  echo Expected: %BOT_PYTHON%
  echo Run: py -m venv .venv
  echo Then: .venv\Scripts\python.exe -m pip install -r requirements.txt
  pause
  exit /b 1
)
echo Starting and verifying the live dashboard...
"%BOT_PYTHON%" bot_launcher.py task-start
if errorlevel 1 (
  echo Dashboard failed to start.
  echo Check dashboard_server_error.log and dashboard_server.log for details.
  pause
  exit /b 1
)
start "" "http://127.0.0.1:8766/"
echo Dashboard opened. The background server is running.
