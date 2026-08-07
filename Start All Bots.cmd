@echo off
rem Launches the full Polymarket stack. Double-click after any reboot.
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

echo Starting Polymarket research dashboard...
"%BOT_PYTHON%" bot_launcher.py start
if errorlevel 1 (
  echo.
  echo Startup failed. The diagnostic above identifies the failure.
  pause
  exit /b 1
)
echo.
echo   Your dashboard:   http://127.0.0.1:8766/
echo   Game Flow:        http://127.0.0.1:8766/game-flow
echo.
echo Startup health check passed. It is safe to close this window.
pause
