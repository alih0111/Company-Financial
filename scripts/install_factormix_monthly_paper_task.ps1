$ErrorActionPreference = 'Stop'
if ((Get-TimeZone).Id -ne 'Iran Standard Time') {
  throw 'Set Windows to Iran Standard Time before installing this task.'
}
$name = 'CompanyFinancial-FactorMix-M15-Paper'
$runner = Join-Path $PSScriptRoot 'run_factormix_monthly_paper.ps1'
$identity = [Security.Principal.WindowsIdentity]::GetCurrent().Name
$action = New-ScheduledTaskAction -Execute 'powershell.exe' `
  -Argument ('-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "{0}"' -f $runner)
$trigger = '18:00', '21:30' | ForEach-Object { New-ScheduledTaskTrigger -Daily -At $_ }
$principal = New-ScheduledTaskPrincipal -UserId $identity -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew `
  -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Hours 4) `
  -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 30)
Register-ScheduledTask -TaskName $name -Action $action -Trigger $trigger -Principal $principal `
  -Settings $settings -Description 'Collect official prices and record monthly FactorMix paper decisions and fills.' -Force
Start-ScheduledTask -TaskName $name
