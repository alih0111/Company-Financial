$ErrorActionPreference = 'Stop'
$secretDir = Join-Path $env:LOCALAPPDATA 'CompanyFinancial\PaperCycle'
$secretPath = Join-Path $secretDir 'tsetmc-readonly.dpapi'
$taskConfigPath = Join-Path (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path 'ranking_research\output\paper_cycle\task-config.json'
$currentIdentity = [Security.Principal.WindowsIdentity]::GetCurrent().Name
if (Test-Path -LiteralPath $taskConfigPath) {
  $taskIdentity = (Get-Content -Raw -LiteralPath $taskConfigPath | ConvertFrom-Json).run_as
  if ($taskIdentity -and $taskIdentity -ine $currentIdentity) {
    throw "Credential not stored: current user '$currentIdentity' differs from scheduled task user '$taskIdentity'. Run this command in that user's Windows session."
  }
}
New-Item -ItemType Directory -Force -Path $secretDir | Out-Null
$credential = Read-Host "TSETMC read-only bearer token (DPAPI user scope: $currentIdentity)" -AsSecureString
try {
  $protected = ConvertFrom-SecureString -SecureString $credential
  Set-Content -LiteralPath $secretPath -Value $protected -Encoding ASCII
  Write-Output "Credential stored encrypted for Windows user '$currentIdentity'. The token's future validity is not checked or guaranteed; the next calendar request reports rejection without printing the token."
} finally {
  if ($credential) { $credential.Dispose() }
}
