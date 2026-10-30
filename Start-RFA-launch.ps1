$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$mainScript = Join-Path $root 'Start-RFA.ps1'
$runtimeDir = Join-Path $root 'go-app\.runtime\desktop-launcher'
$logDir = Join-Path $runtimeDir 'logs'
$runTag = '{0}-{1}' -f $PID, (Get-Date -Format 'yyyyMMdd-HHmmssfff')
$errorLog = Join-Path $logDir "launcher-errors-$runTag.log"
$mutex = New-Object System.Threading.Mutex($false, 'Local\RFA.CompanyFinancial.Launcher')
$ownsMutex = $false

try {
    try {
        $ownsMutex = $mutex.WaitOne(0)
    } catch [System.Threading.AbandonedMutexException] {
        $ownsMutex = $true
    }
    if (-not $ownsMutex) {
        Add-Type -AssemblyName System.Windows.Forms
        [System.Windows.Forms.MessageBox]::Show(
            'راه‌انداز RFA از قبل باز است. از همان پنجره‌ی باز استفاده کنید.',
            'راه‌انداز RFA', 'OK', 'Information'
        ) | Out-Null
        return
    }

    try {
        $tokens = $null
        $parseErrors = $null
        [System.Management.Automation.Language.Parser]::ParseFile(
            $mainScript, [ref]$tokens, [ref]$parseErrors
        ) | Out-Null
        if ($parseErrors.Count -gt 0) {
            throw (($parseErrors | ForEach-Object { $_.ToString() }) -join "`r`n")
        }
        & $mainScript
    } catch {
        $details = ($_ | Out-String).Trim()
        Write-Host "`nRFA launcher failed:`n$details" -ForegroundColor Red
        try {
            New-Item -ItemType Directory -Path $logDir -Force | Out-Null
            [System.IO.File]::AppendAllText(
                $errorLog,
                "$(Get-Date -Format o) LAUNCH FAILURE`r`n$details`r`n",
                [System.Text.UTF8Encoding]::new($false)
            )
        } catch { }
        Read-Host 'پنجره را باز بگذار و متن خطا را برای Codex بفرست؛ برای خروج Enter بزن'
    }
} finally {
    if ($ownsMutex) {
        try { $mutex.ReleaseMutex() } catch { }
    }
    $mutex.Dispose()
}
