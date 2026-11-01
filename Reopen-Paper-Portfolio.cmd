@echo off
cd /d "%~dp0"
set PYTHONDONTWRITEBYTECODE=1
echo Re-opening the paper basket: recording an explicit BUY decision for cash-only accounts...
".venv\Scripts\python.exe" -B -X utf8 ranking_research\future_eval_v12_30\paper_month_trial.py --buy
set "reopen_exit=%errorlevel%"
echo.
echo Reopen exit code: %reopen_exit%
echo The buy decision is recorded. The paper buy applies at the closing price of the
echo first eligible session after this command; run Update-Paper-Portfolio.cmd that day
echo (or wait for the scheduled run) to record it. It is never backdated.
pause
exit /b %reopen_exit%
