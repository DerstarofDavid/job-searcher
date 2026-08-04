@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" exit /b 1
if not exist "logs" mkdir "logs"
echo.>>"logs\daily.log"
echo ===== Daily run started %date% %time% =====>>"logs\daily.log"
".venv\Scripts\python.exe" -m jobfinder scan --mode deep --provider auto >>"logs\daily.log" 2>&1
exit /b %errorlevel%
