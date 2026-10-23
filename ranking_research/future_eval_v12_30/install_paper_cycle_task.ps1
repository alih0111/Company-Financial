$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$runner = Join-Path $PSScriptRoot 'run_paper_cycle.ps1'
if (-not (Test-Path -LiteralPath (Join-Path $root '.venv\Scripts\python.exe'))) {
  throw 'Project Python runtime was not found at .venv\Scripts\python.exe.'
}
$zone = (Get-TimeZone).Id
if ($zone -notin @('Iran Standard Time', 'Asia/Tehran')) {
  throw "Windows timezone is '$zone', not Tehran. Set Windows timezone to Iran Standard Time before installing; the task must run at 22:30 Tehran time."
}
$identity = [Security.Principal.WindowsIdentity]::GetCurrent().Name
$action = New-ScheduledTaskAction -Execute (Join-Path $PSHOME 'powershell.exe') `
  -Argument "-NoLogo -NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$runner`"" `
  -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -Daily -At '10:30 PM'
$principal = New-ScheduledTaskPrincipal -UserId $identity -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew `
  -RestartCount 2 -RestartInterval (New-TimeSpan -Minutes 15) `
  -ExecutionTimeLimit (New-TimeSpan -Minutes 90) -Hidden -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$task = Register-ScheduledTask -TaskName 'CompanyFinancial-PaperCycle' `
  -Description 'Daily local ranking and read-only paper portfolio review. No brokerage access or real orders.' `
  -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force
Start-ScheduledTask -TaskName $task.TaskName
$info = Get-ScheduledTaskInfo -TaskName $task.TaskName
$configPath = Join-Path $root 'ranking_research\output\paper_cycle\task-config.json'
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $configPath) | Out-Null
[ordered]@{
  installed = $true
  task_name = $task.TaskName
  daily_local_time = '22:30'
  timezone = 'Asia/Tehran'
  windows_timezone = $zone
  next_run_time = $info.NextRunTime.ToString('o')
  start_when_available = $true
  window_requires_user_session = $true
  run_as = $identity
  installed_at_utc = [DateTime]::UtcNow.ToString('o')
} | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $configPath -Encoding UTF8
[pscustomobject]@{
  task_name = $task.TaskName
  task_path = $task.TaskPath
  state = (Get-ScheduledTask -TaskName $task.TaskName).State.ToString()
  start_time_local = '22:30'
  windows_timezone = $zone
  run_as = $identity
  logon_requirement = 'This user must be signed in for the task to access the network; no password or API token is stored by Task Scheduler.'
  next_run_time = $info.NextRunTime
  last_run_time = $info.LastRunTime
  last_task_result = $info.LastTaskResult
  stopped = 'Stop-ScheduledTask -TaskName CompanyFinancial-PaperCycle'
  disable_future_runs = 'Disable-ScheduledTask -TaskName CompanyFinancial-PaperCycle'
  manual = "powershell -NoProfile -ExecutionPolicy Bypass -File `"$runner`""
} | ConvertTo-Json -Depth 4
