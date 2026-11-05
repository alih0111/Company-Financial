param(
    [ValidateSet('All', 'Go', 'Python', 'Frontend')]
    [string]$Only = 'All'
)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root '.venv\Scripts\python.exe'
$failed = [System.Collections.Generic.List[string]]::new()

# Pass only system settings to verification and child processes. In particular,
# credentials and live-service configuration must never reach test fixtures.
$allowedEnvironment = @('PATH', 'SYSTEMROOT', 'WINDIR', 'TEMP', 'TMP', 'USERPROFILE',
    'HOME', 'PATHEXT', 'COMSPEC', 'NUMBER_OF_PROCESSORS', 'PROCESSOR_ARCHITECTURE',
    'APPDATA', 'LOCALAPPDATA')
foreach ($entry in [Environment]::GetEnvironmentVariables('Process').GetEnumerator()) {
    if ($entry.Key -notin $allowedEnvironment) {
        [Environment]::SetEnvironmentVariable([string]$entry.Key, $null, 'Process')
    }
}
$env:RFA_TEST_LIVE_REFRESH = '0'
$env:CODAL_AUTO_SYNC_ENABLED = '0'
$env:QVT_PAPER_OBSERVER_ENABLED = '0'
$env:PYTHONDONTWRITEBYTECODE = '1'

function Invoke-Check([string]$name, [string]$directory, [scriptblock]$command) {
    Write-Host "`n--- $name ---"
    Push-Location -LiteralPath $directory
    try {
        & $command
        if ($LASTEXITCODE -ne 0) { $failed.Add($name) }
    } catch {
        Write-Error -ErrorRecord $_ -ErrorAction Continue
        $failed.Add($name)
    } finally {
        Pop-Location
    }
}

if ($Only -in @('All', 'Go')) {
    Invoke-Check 'Go tests' (Join-Path $root 'go-app') { & go test -v ./... }
}
if ($Only -in @('All', 'Python')) {
    if (-not (Test-Path -LiteralPath $python)) {
        $failed.Add('Python environment missing')
    } else {
        Invoke-Check 'Python offline paper and HTTP' $root {
            & $python -m pytest -q -ra ranking_research/tests/test_paper_cycle_http.py `
                ranking_research/tests/test_paper_account_atomic.py `
                ranking_research/tests/test_paper_calendar_interface.py::test_sales_pit_capability_blocked_for_public_profile `
                ranking_research/tests/test_paper_month_report.py `
                ranking_research/tests/test_paper_month_report_v2.py `
                ranking_research/tests/test_paper_calendar_tf02a_regressions.py::test_g3_refresh_consumes_candidate_witness_and_short_archive_is_gap `
                ranking_research/tests/test_paper_calendar_tf02a_regressions.py::test_g5_one_input_consistent_across_fill_status_and_cycle `
                ranking_research/tests/test_paper_calendar_tf03_regressions.py::test_inactive_public_draft_creator_is_append_only_and_temp_only `
                ranking_research/tests/test_paper_calendar_tf03_regressions.py::test_subprocess_public_cycle_fill_mark_replay_isolated_and_network_blocked `
                ranking_research/tests/test_selected_artifact_package.py `
                ranking_research/tests/test_evidence_paths.py `
                ranking_research/tests/test_isolated_rebuild_verifier.py `
                ranking_research/tests/test_factor_coverage.py `
                ranking_research/tests/test_experimental_risk.py `
                ranking_research/tests/test_paper_model_review.py `
                ranking_research/tests/test_paper_month_trial.py::test_missing_review_policy_does_not_reenable_rotation `
                ranking_research/tests/test_experimental_paper.py::test_real_cli_buy_sell_accounting_preview_and_next_day_replay `
                ranking_research/tests/test_experimental_paper.py::test_mark_preserves_calendar_blocking_reasons_without_account_write
        }
    }
}
if ($Only -in @('All', 'Frontend')) {
    $client = Join-Path $root 'client'
    Invoke-Check 'Frontend build' $client { & npm run build }
    Invoke-Check 'Frontend lint' $client { & npm run lint }
    Invoke-Check 'CSV tests' $client { & npm run test:csv }
    Invoke-Check 'Error handling tests' $client { & npm run test:errors }
    Invoke-Check 'QVT ratio tests' $client { & npm run test:qvt-ratio }
    Invoke-Check 'Indicator tests' $client { & npm run test:indicators }
}
if ($failed.Count -gt 0) {
    Write-Host "`nFailed checks: $($failed -join ', ')"
    exit 1
}
Write-Host "`nAll requested checks passed. Live refresh tests are separate and were not enabled."
