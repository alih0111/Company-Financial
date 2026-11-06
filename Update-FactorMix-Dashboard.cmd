@echo off
setlocal
cd /d "%~dp0"
".venv\Scripts\python.exe" -m factormix.build_dashboard
if errorlevel 1 (
  echo FactorMix report update failed. Previous report has not been replaced.
  pause
  exit /b 1
)
echo Verified FactorMix dashboard rebuilt. This command does not fetch prices or place orders.
pause
