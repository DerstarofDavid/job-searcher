@echo off
setlocal
cd /d "%~dp0"
if exist "reports\latest.html" (
  start "" "reports\latest.html"
) else (
  echo No live report exists yet. Run run_now.bat first.
  pause
)
