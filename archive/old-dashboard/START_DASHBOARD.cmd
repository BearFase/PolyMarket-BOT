@echo off
echo.
echo ========================================
echo   POLYMARKET COMMAND CENTER
echo ========================================
echo.
echo Starting dashboard...
echo.

cd /d "%~dp0"
python serve.py

pause
