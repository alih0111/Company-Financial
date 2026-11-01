@echo off
cd /d "%~dp0"
set PYTHONDONTWRITEBYTECODE=1
echo Closing the paper basket: recording an explicit SELL decision for P1 and P3...
".venv\Scripts\python.exe" -B -X utf8 ranking_research\future_eval_v12_30\paper_month_trial.py --sell
set "close_exit=%errorlevel%"
echo.
echo Close exit code: %close_exit%
echo The sell decision is recorded. The paper sell applies at the closing price of the
echo first eligible session after this command; run Update-Paper-Portfolio.cmd that day
echo (or wait for the scheduled run) to record it. It is never backdated.
pause
exit /b %close_exit%
