$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$python = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) { throw 'Project Python runtime is missing.' }
$runDir = Join-Path $root '.runtime\factormix-monthly-paper'
New-Item -ItemType Directory -Force -Path $runDir | Out-Null
$stamp = Get-Date -Format 'yyyyMMdd-HHmmssfff'
$env:PYTHONUTF8 = '1'
$process = Start-Process -FilePath $python -ArgumentList '-B', '-m', 'factormix.monthly_paper' `
  -WorkingDirectory $root -WindowStyle Hidden -Wait -PassThru `
  -RedirectStandardOutput (Join-Path $runDir "task-$stamp.out.log") `
  -RedirectStandardError (Join-Path $runDir "task-$stamp.err.log")
exit $process.ExitCode
