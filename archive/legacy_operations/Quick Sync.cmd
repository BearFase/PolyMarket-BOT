@echo off
echo ================================================
echo POLYMARKET BOT - DAILY UPDATE
echo ================================================
echo.

cd /d "%~dp0"
python daily_update.py --quick

echo.
echo ================================================
echo Done! Opening live dashboard...
echo ================================================
echo.

powershell -NoProfile -Command "Get-NetTCPConnection -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique | ForEach-Object { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue }" > NUL 2>&1
start /B python dashboard_server.py > dashboard_server.log 2>&1
timeout /t 2 /nobreak >nul
start http://127.0.0.1:8765/dashboard_live.html
