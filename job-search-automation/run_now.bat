@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" call setup_windows.bat
if not exist ".venv\Scripts\python.exe" exit /b 1
echo Starting a thorough live search. This can take 20-60 minutes.
".venv\Scripts\python.exe" -m jobfinder scan --mode deep --provider auto --open
if errorlevel 1 pause
