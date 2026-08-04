@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>&1
if errorlevel 1 (
  echo Python was not found. Install Python 3.11 or newer from https://www.python.org/downloads/windows/
  echo During installation, select "Add Python to PATH", then run this file again.
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo Creating the private Python environment...
  py -3 -m venv .venv
  if errorlevel 1 goto :failed
)

if not exist ".env" copy /Y ".env.example" ".env" >nul

echo Checking the program...
".venv\Scripts\python.exe" -m jobfinder doctor
if errorlevel 1 goto :failed

echo.
echo Setup is complete.
echo Run run_demo.bat first, then run_now.bat for a live deep search.
pause
exit /b 0

:failed
echo.
echo Setup failed. Confirm that Python 3.11 or newer is installed.
pause
exit /b 1
