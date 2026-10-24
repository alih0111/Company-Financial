param(
  [switch]$SkipTokenPrompt,
  [ValidateSet('nscstart','public')][string]$CalendarProvider = 'nscstart',
  [string]$AccountPath = 'client\public\research\v12-36\paper-portfolio.json',
  [string]$RulesPath = 'ranking_research\output\paper_v12_38_first_fill\execution_rules_v1_2_0.json',
  [string]$EvidenceManifest = '',
  [string]$CalendarManifest = '',
  [string]$CalendarManifestSha256 = '',
  [string]$OutputDir = 'ranking_research\output\paper_v12_38_first_fill',
  [string]$PublicOutputDir = 'client\public\research\v12-38',
  [string]$ReferenceNowUtc = '',
  [switch]$Fixture,
  [switch]$ApplyFill
)
$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $false
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
Set-Location $root
$python = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) { throw 'Project Python runtime was not found at .venv\Scripts\python.exe' }
if ($ReferenceNowUtc -and -not $Fixture) { throw 'FIXTURE_CLOCK_REQUIRES_EXPLICIT_FIXTURE_MODE' }
$calendarManifest = if ($CalendarManifest) { (Resolve-Path -LiteralPath $CalendarManifest).Path } else { $null }
$calendarOutput = $null
$calendarError = $null

try {
  if (-not [string]::IsNullOrWhiteSpace($env:TSETMC_CALENDAR_MANIFEST) -and (Test-Path -LiteralPath $env:TSETMC_CALENDAR_MANIFEST)) {
    $calendarManifest = $env:TSETMC_CALENDAR_MANIFEST
  } elseif ($CalendarProvider -eq 'nscstart' -and -not [string]::IsNullOrWhiteSpace($env:TSETMC_READONLY_BEARER_TOKEN)) {
    $calendarOutput = & $python 'ranking_research\future_eval_v12_30\acquire_tsetmc_open_sessions.py' 2>&1
    if ($LASTEXITCODE -eq 0) {
      $calendarResult = ($calendarOutput | Select-Object -Last 1 | Out-String).Trim() | ConvertFrom-Json
      $calendarManifest = [string]$calendarResult.manifest
    } else {
      $calendarError = ($calendarOutput | Out-String).Trim()
    }
  } elseif ($CalendarProvider -eq 'nscstart' -and -not $SkipTokenPrompt) {
    $secure = Read-Host 'TSETMC read-only bearer token for NSCStart (Enter to skip)' -AsSecureString
    $bstr = [IntPtr]::Zero
    try {
      $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
      $token = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
      if (-not [string]::IsNullOrWhiteSpace($token)) {
        $env:TSETMC_READONLY_BEARER_TOKEN = $token
        $calendarOutput = & $python 'ranking_research\future_eval_v12_30\acquire_tsetmc_open_sessions.py' 2>&1
        if ($LASTEXITCODE -eq 0) {
          $calendarResult = ($calendarOutput | Select-Object -Last 1 | Out-String).Trim() | ConvertFrom-Json
          $calendarManifest = [string]$calendarResult.manifest
        } else {
          $calendarError = ($calendarOutput | Out-String).Trim()
        }
      } else {
        $calendarError = 'No token supplied; official market-wide NSCStart calendar was not fetched.'
      }
    } finally {
      Remove-Item Env:TSETMC_READONLY_BEARER_TOKEN -ErrorAction SilentlyContinue
      if ($bstr -ne [IntPtr]::Zero) { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr) }
      if ($secure) { $secure.Dispose() }
      $token = $null
    }
  } else {
    $calendarError = if ($CalendarProvider -eq 'public') { 'Public profile requires an explicit pinned calendar manifest in this wrapper invocation.' } else { 'Token prompt skipped; official market-wide NSCStart calendar was not fetched.' }
  }

  if (-not $EvidenceManifest) {
    $candidateOutput = & $python 'ranking_research\future_eval_v12_30\acquire_paper_candidate_evidence.py' 2>&1
    if ($LASTEXITCODE -ne 0) { throw "Candidate evidence acquisition failed: $($candidateOutput | Out-String)" }
    $latest = Get-Content -Raw 'ranking_research\output\paper_v12_38_first_fill\latest-manifest.json' | ConvertFrom-Json
    $EvidenceManifest = [string]$latest.manifest_path
  }

  $account = Get-Content -Raw $AccountPath | ConvertFrom-Json
  $fillOutput = $null
  $fillError = $null
  $executionAttemptStatus = 'not_attempted'
  if ($calendarManifest -and -not $account.execution_recorded -and $account.paper_order.status -eq 'PENDING_FIRST_ELIGIBLE_SESSION_EVIDENCE') {
    $fillArgs = @('ranking_research\future_eval_v12_30\apply_paper_fill.py', '--session-calendar-manifest', $calendarManifest,
      '--evidence-manifest', $EvidenceManifest, '--calendar-provider', $CalendarProvider,
      '--account', $AccountPath, '--rules', $RulesPath, '--calendar-policy', 'ranking_research\paper_calendar_policy.public-paper-v1.json')
    if ($CalendarManifestSha256) { $fillArgs += @('--calendar-manifest-sha256', $CalendarManifestSha256) }
    if ($ReferenceNowUtc) { $fillArgs += @('--reference-now-utc', $ReferenceNowUtc) }
    if ($ApplyFill) { $fillArgs += '--apply-fill' }
    $previousErrorAction = $ErrorActionPreference
    try {
      # A refused preview is an expected product result. Capture the child's
      # exit/output and still run status refresh so the exact refusal reaches
      # the selected output account status instead of aborting the wrapper.
      $ErrorActionPreference = 'Continue'
      $fillOutput = & $python @fillArgs 2>&1
      $fillExitCode = $LASTEXITCODE
    } finally {
      $ErrorActionPreference = $previousErrorAction
    }
    if ($fillExitCode -ne 0) { $fillError = ($fillOutput | Out-String).Trim() }
    try { $executionAttemptStatus = [string](($fillOutput | Select-Object -Last 1 | Out-String | ConvertFrom-Json).status) } catch { $executionAttemptStatus = 'attempt_failed_or_unclassified' }
  } elseif ($account.execution_recorded) {
    $fillError = 'The pinned order already has a fill; duplicate application skipped.'
  } elseif ($account.paper_order.status -eq 'EXPIRED_NO_FILL') {
    $fillError = 'The pinned order is already expired; no later-session fill is allowed.'
  } elseif (-not $calendarManifest) {
    $fillError = 'No validated market-wide calendar manifest; fill application skipped.'
  }

  $refreshArgs = @('ranking_research\future_eval_v12_30\refresh_paper_decision_status.py', '--account', $AccountPath,
    '--execution-rules', $RulesPath, '--output-dir', $OutputDir, '--public-output-dir', $PublicOutputDir,
    '--calendar-provider', $CalendarProvider, '--evidence-manifest', $EvidenceManifest)
  if ($ReferenceNowUtc) { $refreshArgs += @('--reference-now-utc', $ReferenceNowUtc) }
  if ($CalendarProvider -eq 'public') { $refreshArgs += @('--public-calendar-manifest', $calendarManifest, '--public-calendar-manifest-sha256', $CalendarManifestSha256) }
  if ($calendarManifest -and $CalendarProvider -eq 'nscstart') { $refreshArgs += @('--session-calendar-manifest', $calendarManifest) }
  $refreshArgs += @('--execution-attempt-status', $executionAttemptStatus)
  $refreshOutput = & $python @refreshArgs 2>&1
  if ($LASTEXITCODE -ne 0) { throw "Status refresh failed: $($refreshOutput | Out-String)" }
  $result = Get-Content -Raw (Join-Path $PublicOutputDir 'paper-account-check.json') | ConvertFrom-Json
  [pscustomobject]@{
    checked_at_utc = $result.checked_at_utc
    decision_id = $result.decision.decision_id
    decision_at_utc = $result.decision.decided_at_utc
    order_id = $result.order.order_id
    order_status = $result.order.status
    calendar_manifest = $calendarManifest
    calendar_access_result = if ($calendarManifest) { 'validated official market calendar saved' } else { $calendarError }
    candidate_manifest = $EvidenceManifest
    fill_result = if ($fillOutput) { ($fillOutput | Out-String).Trim() } else { $fillError }
    fill_recorded = $result.fill_recorded
    cash_toman = $result.cash_reconciliation.cash_toman
    holdings_value_toman = $result.cash_reconciliation.holdings_value_toman
    balanced = $result.cash_reconciliation.balanced
    barriers = $result.barriers
    official_ledger_touched = $result.official_ledger_touched
  } | ConvertTo-Json -Depth 8
} finally {
  Remove-Item Env:TSETMC_READONLY_BEARER_TOKEN -ErrorAction SilentlyContinue
  Remove-Item Env:TSETMC_CALENDAR_MANIFEST -ErrorAction SilentlyContinue
}
