param([switch]$Monitor)
$ErrorActionPreference = 'Stop'
$trialRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
Set-Location -LiteralPath $trialRoot
$trialScript = if ($Monitor) { 'paper_intraday_monitor.py' } else { 'paper_month_trial.py' }
& (Join-Path $trialRoot '.venv\Scripts\python.exe') -B -X utf8 (Join-Path $PSScriptRoot $trialScript)
exit $LASTEXITCODE
