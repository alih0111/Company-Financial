@echo off
cd /d "%~dp0"
set PYTHONDONTWRITEBYTECODE=1
echo Updating the previous experimental account (completes its pending buy when a session qualifies)...
".venv\Scripts\python.exe" -B -X utf8 ranking_research\future_eval_v12_30\experimental_paper.py update --publish
set "exp_exit=%errorlevel%"
echo Updating the 30-day P1/P3 trial...
".venv\Scripts\python.exe" -B -X utf8 ranking_research\future_eval_v12_30\paper_month_trial.py
set "paper_exit=%errorlevel%"
echo.
echo Previous-account exit code: %exp_exit%  /  Trial exit code: %paper_exit%
echo See the experimental paper portfolio page for the result.
echo To close the basket, run Close-Paper-Portfolio.cmd; to buy again after a close, run Reopen-Paper-Portfolio.cmd.
if not "%exp_exit%"=="0" set /a paper_exit=%exp_exit%
pause
exit /b %paper_exit%
