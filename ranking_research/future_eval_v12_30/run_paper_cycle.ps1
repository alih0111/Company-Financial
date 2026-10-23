$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$python = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) { throw 'Project Python runtime is missing.' }
Set-Location -LiteralPath $root
$secretPath = Join-Path $env:LOCALAPPDATA 'CompanyFinancial\PaperCycle\tsetmc-readonly.dpapi'
$identityState = 'matched_task_identity'
try {
  $taskConfigPath = Join-Path $root 'ranking_research\output\paper_cycle\task-config.json'
  if (Test-Path -LiteralPath $taskConfigPath) {
    $configuredIdentity = (Get-Content -Raw -LiteralPath $taskConfigPath | ConvertFrom-Json).run_as
    $actualIdentity = [Security.Principal.WindowsIdentity]::GetCurrent().Name
    if ($configuredIdentity -and $actualIdentity -ine $configuredIdentity) { $identityState = 'task_identity_mismatch' }
  }
} catch { $identityState = 'task_identity_check_failed' }
$env:TSETMC_CREDENTIAL_IDENTITY_STATE = $identityState
if (-not (Test-Path -LiteralPath $secretPath)) { $env:TSETMC_CREDENTIAL_STATE = 'absent' }
if ((Test-Path -LiteralPath $secretPath) -and $identityState -ne 'matched_task_identity') {
  $env:TSETMC_CREDENTIAL_STATE = $identityState
}
if ((Test-Path -LiteralPath $secretPath) -and $identityState -eq 'matched_task_identity') {
  $secure = $null
  $bstr = [IntPtr]::Zero
  try {
    $protected = Get-Content -Raw -LiteralPath $secretPath
    $secure = ConvertTo-SecureString -String $protected
    $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    $env:TSETMC_READONLY_BEARER_TOKEN = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
    $env:TSETMC_CREDENTIAL_STATE = if ($identityState -eq 'matched_task_identity') { 'decrypted_for_current_user_unvalidated' } else { $identityState }
  } catch {
    Remove-Item Env:TSETMC_READONLY_BEARER_TOKEN -ErrorAction SilentlyContinue
    $env:TSETMC_CREDENTIAL_STATE = 'dpapi_unreadable_or_user_mismatch'
  } finally {
    if ($bstr -ne [IntPtr]::Zero) { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr) }
    if ($secure) { $secure.Dispose() }
  }
}
try {
  & $python -B (Join-Path $PSScriptRoot 'paper_cycle.py')
  exit $LASTEXITCODE
} finally {
  Remove-Item Env:TSETMC_READONLY_BEARER_TOKEN -ErrorAction SilentlyContinue
  Remove-Item Env:TSETMC_CREDENTIAL_STATE -ErrorAction SilentlyContinue
  Remove-Item Env:TSETMC_CREDENTIAL_IDENTITY_STATE -ErrorAction SilentlyContinue
}
