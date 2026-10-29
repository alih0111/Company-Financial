@echo off
cd /d "%~dp0"
set PYTHONDONTWRITEBYTECODE=1
".venv\Scripts\python.exe" -B -X utf8 ranking_research\future_eval_v12_30\paper_month_trial.py
set "paper_exit=%errorlevel%"
echo.
echo Paper portfolio update exit code: %paper_exit%
echo See the experimental paper portfolio page for the result.
pause
exit /b %paper_exit%
