$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$python = Join-Path $root '.venv\Scripts\python.exe'
$script = Join-Path $PSScriptRoot 'refresh_chart_prices.py'
$action = New-ScheduledTaskAction -Execute $python -Argument ('-X utf8 "{0}"' -f $script) -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -Daily -At '19:00'
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -RestartCount 2 -RestartInterval (New-TimeSpan -Minutes 30)
$identity = [Security.Principal.WindowsIdentity]::GetCurrent().Name
$principal = New-ScheduledTaskPrincipal -UserId $identity -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName 'CompanyFinancial-DailyChartPrices' -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Description 'Refresh adjusted daily charts for all active securities from TSETMC.' -Force
