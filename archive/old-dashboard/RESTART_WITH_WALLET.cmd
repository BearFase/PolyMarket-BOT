@echo off
echo.
echo ========================================
echo   POLYMARKET DASHBOARD - ADD WALLET
echo ========================================
echo.
echo Paste your wallet address (starts with 0x):
echo.
set /p WALLET="Wallet: "
echo.
echo Starting dashboard with wallet: %WALLET%
echo.

cd /d "%~dp0"
python serve.py --wallet %WALLET% --port 8081

pause
