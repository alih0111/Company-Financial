@echo off
cd /d "%~dp0"
".venv\Scripts\python.exe" -B -m reportflow.run
if errorlevel 1 (
  echo ReportFlow backtest failed. See reportflow/artifacts.
  pause
  exit /b 1
)
echo Independent ReportFlow backtest and report updated.
pause
