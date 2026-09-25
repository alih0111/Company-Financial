# PRICE_HISTORY CANARY RUNBOOK

Endpoint `GET /api/price-history` only. Global read mode stays `LEGACY`.

## 1. Enable

```powershell
$env:CDF_CANONICAL_DB              = "company_financial_analytics_shadow_v121"
$env:CDF_PRICE_HISTORY_CANARY_ENABLED = "true"
$env:CDF_PRICE_HISTORY_CANARY_SYMBOLS = "کیمیا,غاذر,سباقر"   # start with a tiny allowlist
$env:CDF_PRICE_HISTORY_CANARY_VERIFY  = "true"                 # recommended during rollout
$env:CDF_PRICE_HISTORY_CANARY_TIMEOUT_MS = "1500"
# CDF_READ_MODE remains unset/legacy
```

Optional deterministic percentage (only after allowlist confidence):

```powershell
$env:CDF_PRICE_HISTORY_CANARY_PERCENT = "5"
```

Restart the API process after changing env. Confirm via health (§4).

## 2. Disable (kill switch)

```powershell
$env:CDF_PRICE_HISTORY_CANARY_ENABLED = "false"
```

or remove the variable. Restart. 100% of price-history requests are then served
from SQL Server again. No code or database change is required.

## 3. Allowlist setup

- Comma-separated symbol or legacy company name; entries are normalized
  (Arabic-Indic digits, ی/ک variants, whitespace).
- Prefer symbols already proven in Phase 1/2 comparisons.
- Grow the list by small batches, checking §5 metrics after each change.
- A symbol absent from the allowlist is always servable by legacy.

## 3b. Identity eligibility registry (safety prerequisite)

Canonical serving requires `CANONICAL_SAFE`; the guard also protects percentage
routing. Registry file: `CDF_PRICE_HISTORY_ELIGIBILITY_FILE`, default
`../integration_shadow_v1/output/price_history_identity_eligibility.csv`.

Regenerate (read-only audit of both databases):

```powershell
cd go-app
$env:CDF_CANONICAL_DB="company_financial_analytics_shadow_v121"
go run ./cmd/eligbuild
```

Expect ~276 `CANONICAL_SAFE`; collisions are listed explicitly. Verify:

- any allowlisted symbol not classified `CANONICAL_SAFE` is served by **legacy**
  even though it is allowlisted;
- diagnostics show `eligibility_guard_forced_legacy > 0` for such requests and no
  `canary_success` for them;
- a missing registry disables canonical serving entirely (fail-safe legacy).

Do not place known collision symbols in the canary allowlist. If one is placed
there by mistake, the guard still forces legacy.

## 4. Health checks

`GET /api/health/shadow` (no secrets) reports:

| Field | Expected during a healthy canary |
| --- | --- |
| `read_mode` | `legacy` |
| `canonical_reachable` | `true` |
| `price_history_canary_enabled` | `true` |
| `price_history_canary_symbol_count` | allowlist size |
| `price_history_canary_verify` | as configured |
| `price_history_canary_timeout_ms` | as configured |

When canary is disabled, `canonical_reachable=false` must not affect service
health: LEGACY is authoritative and no canonical connection is required.

## 5. Metrics to watch

From `output/price_history_canary_summary.json`:

- `canary_success` should grow for allowlisted symbols.
- `canary_fallback` should stay 0 for known-good symbols; any increase means
  canonical returned an error or an empty result for a symbol expected to have
  data.
- `canonical_errors` / `canonical_error` strings identify the cause (timeout,
  connection, empty).
- `comparison_unexpected` **must remain 0**. Any non-zero value blocks the canary.
- `latency.canonical_median_ms` / `p95` vs `latency.legacy_median_ms` / `p95`.

From `output/price_history_canary_samples.csv`: per-request symbol, route, result,
row count, latencies and error.

Alerting suggestions:
- page/warn if `comparison_unexpected > 0`
- warn if `canary_fallback` grows on an allowlisted symbol
- warn if `canonical_p95_ms` exceeds the configured timeout
- warn if `legacy_fallback_errors > 0` (both backends failing)

## 6. Fallback expectations

- Canonical error/timeout/empty ⇒ legacy serves the request; HTTP 200, correct
  body; a fallback sample is recorded.
- Both backends fail ⇒ HTTP 500 with the legacy error (unchanged behavior).
- Client-visible responses never contain PostgreSQL errors while legacy works.

## 7. Rollback

1. Set `CDF_PRICE_HISTORY_CANARY_ENABLED=false` (or unset).
2. Restart the API.
3. Optionally unset `CDF_PRICE_HISTORY_CANARY_SYMBOLS` / `VERIFY` / `PERCENT`.

Rollback is configuration-only and immediate. No database, schema, code, or
deployment change is involved.

## 8. Verification after rollback

- `GET /api/health/shadow` shows `price_history_canary_enabled=false`.
- A price-history request for a formerly allowlisted symbol returns the legacy
  dataset (compare row count and first/last dates against a pre-canary baseline).
- No new canary samples are produced (counters frozen).
- SQL Server remains the authority; canonical is not read for this endpoint in
  LEGACY mode with the canary disabled.

## 8b. Production canary procedure (as actually performed)

Environment note: the canonical backend is the designated shadow/test database
`company_financial_analytics_shadow_v121`; there is no separate production
canonical cluster in this workspace, and production PostgreSQL must not be
modified. The application process served real HTTP requests.

1. **Preflight** (all must pass before enabling):
   - `GET /api/health/shadow` returns OK; `read_mode=legacy`.
   - SQL Server reachable; canonical reachable; read-only session confirmed
     (`SHOW default_transaction_read_only` → `on`).
   - `CDF_PRICE_HISTORY_CANARY_PERCENT=0`; allowlist contains only intended
     symbols; no pending schema changes; prior shadow diagnostics 0 unexpected.
   - Pre-run `go run ./cmd/canarycheck` shows 0 unexpected for the chosen symbols.
2. **Enable** with the env in §1 (allowlist of 1–3 symbols, `VERIFY=true`,
   `CDF_READ_MODE=legacy`), then restart the API process.
3. **Confirm** health shows `price_history_canary_enabled=true` and the intended
   symbol count.
4. **Serve** real requests (multiple limits per symbol; include a non-allowlisted
   control symbol and a missing/unknown symbol).
5. **Monitor** `output/price_history_canary_summary.json` (or the production
   artifact) for `comparison_unexpected`, `canary_fallback`, `canonical_errors`,
   `canary_success`, and latency.
6. **Stop immediately** on any stop condition in §8 of the spec / §9 below.
7. **Rollback** by setting `CDF_PRICE_HISTORY_CANARY_ENABLED=false` and
   restarting, then verify health shows the canary disabled and allowlisted
   symbols are served by legacy.
8. **Record** the per-symbol summary and preserve the machine-readable artifacts.

### Actual production canary outcome

3 symbols (`کیمیا`, `غاذر`, `کسرا`), 51 requests, 45 canonical-served, 0
fallback, 0 unexpected, canonical median 2.11 ms / p95 3.43 ms. Kill switch was
exercised and restored legacy serving. See
`PRICE_HISTORY_PRODUCTION_CANARY_REPORT.md`.

## 8c. Percentage rollout (5%) procedure and observations

Enable (no allowlist; guard mandatory):

```powershell
$env:CDF_READ_MODE="legacy"
$env:CDF_PRICE_HISTORY_CANARY_ENABLED="true"
$env:CDF_PRICE_HISTORY_CANARY_PERCENT="5"
$env:CDF_PRICE_HISTORY_CANARY_VERIFY="true"
$env:CDF_PRICE_HISTORY_ELIGIBILITY_FILE="../integration_shadow_v1/output/price_history_identity_eligibility.csv"
```

Before enabling: regenerate the registry (`go run ./cmd/eligbuild`) and confirm
`unsafe_selected=0` in `price_history_percent5_cohort.csv`. The identity guard
runs before the bucket, so unsafe symbols are never selected.

Observed (5%): 14/14 selected symbols exercised, 70 canonical-served, 0 fallback,
0 expected, 0 unexpected, canonical median 1.68 ms; kill switch verified.

**Important:** the identity guard includes a date-coverage check. A symbol whose
legacy and canonical date sets differ is classified `LEGACY_COVERAGE_DIVERGENCE`
and forced to legacy, even if it has a single identity. During the first 5% run
`های وب3` was caught this way (403 population differences); the registry was
regenerated before the clean re-run.

Watch: `comparison_unexpected` (must be 0), `comparison_expected` (must be 0 for
served symbols), `eligibility_guard_forced_legacy`, `canary_fallback`,
`canonical_errors`, canonical median/p95.

## 9. Recommended rollout sequence

1. Verify allowlist symbols with `go run ./cmd/canarycheck` (0 unexpected).
2. Enable canary with 1–3 allowlisted symbols + `VERIFY=true`.
3. Observe for a soak window; require `comparison_unexpected = 0`.
4. Add symbols in small batches.
5. Only after sustained zero unexpected diffs, consider `PERCENT` for a broader
   but still deterministic share.
6. Never enable `CDF_READ_MODE=canonical` globally as part of this endpoint canary.
