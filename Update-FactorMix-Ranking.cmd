@echo off
setlocal
cd /d "%~dp0"
".venv\Scripts\python.exe" -B -m factormix.refresh_ranking
if errorlevel 1 (
  echo FactorMix ranking refresh failed. See .runtime\factormix-ranking\status.json
  pause
  exit /b 1
)
echo FactorMix scores and ranking updated.
pause
