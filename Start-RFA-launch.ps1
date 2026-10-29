$root = $PSScriptRoot
$mainScript = Join-Path $root 'Start-RFA.ps1'
$logPath = Join-Path $root 'go-app\.runtime\desktop-launcher\launcher-session.log'

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
        New-Item -ItemType Directory -Path (Split-Path $logPath) -Force | Out-Null
        Add-Content -LiteralPath $logPath -Value "`r`n$(Get-Date -Format o) LAUNCH FAILURE`r`n$details"
    } catch { }
    Read-Host 'پنجره را باز بگذار و متن خطا را برای Codex بفرست؛ برای خروج Enter بزن'
}
