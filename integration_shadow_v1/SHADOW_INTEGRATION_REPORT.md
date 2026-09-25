# SHADOW INTEGRATION REPORT — Phase 2 + Phase 3 (price-history canary)

## Gate

**`SHADOW_INTEGRATION_PHASE2_READY`**

## Phase 3 endpoint canary

**`GET /api/price-history` → `PRICE_HISTORY_CANARY_READY`.** Implemented as an
opt-in, deterministic, config-only canary with automatic legacy fallback. Live
simulation: 1260 exact / 0 expected / 0 unexpected, canonical median 1.35 ms vs
legacy 73.2 ms (`PRICE_HISTORY_CANARY_REPORT.md`).

## Phase 4 production canary

Bounded production canary for `GET /api/price-history` with 3 allowlisted symbols
(`کیمیا`, `غاذر`, `کسرا`), `PERCENT=0`, `VERIFY=true`, global mode `LEGACY`.
Result: 51 requests, 45 canonical-served, 0 fallback, 0 canonical errors,
50,925 exact comparisons / 0 unexpected, canonical median 2.11 ms / p95 3.43 ms,
HTTP contract exact. Kill switch exercised (canary disabled → 100% legacy).
Gate: `PRICE_HISTORY_PRODUCTION_CANARY_PASS`. Report:
`PRICE_HISTORY_PRODUCTION_CANARY_REPORT.md`.

## Global canary readiness

**`GLOBAL_CANARY_NOT_READY`** — one endpoint passing does not promote the
application. Unresolved: `SalesData` `Product1/2/3` contract, `CompanyNames`
alias/legal-name presentation, fundamentals N+1 latency. See §12.

## 1. What Phase 2 adds

- Fundamentals dual-read for `GET /api/SalesData` and `GET /api/SalesData2`.
- Canonical repositories for `fundamentals.monthly_activities` and
  `fundamentals.financial_facts` (+ `financial_statements` + `ingestion.reports`),
  resolved through `core.legacy_entity_map`.
- A safe rewrite of the canonical market query (root cause profiled, not guessed).
- Resolution of the four unmapped legacy names.
- Extended Go tests and updated artifacts.

Phase 1 guarantees are preserved: default `LEGACY`, legacy-authoritative `SHADOW`,
no write-path changes, no analytics-formula changes, config-only rollback.

## 2. Fundamentals canonical mappings

| Endpoint | Legacy | Canonical | Key |
| --- | --- | --- | --- |
| `/api/SalesData2` | `mahane` Value1/2/3 | `fundamentals.monthly_activities` (production_quantity, sales_quantity, reported_sales_amount, sales_amount_rial) | `companyID|ReportDate` |
| `/api/SalesData` | `miandore2` mapped metrics | `fundamentals.financial_facts` (income_statement, period_order=1) | `companyID|ReportDate` |

- Units: `mahane.Value3` = million_rial (verified against
  `reported_sales_amount`); canonical `sales_amount_rial` = ×1e6, classified
  `EXPECTED_UNIT_PRESENTATION`. `miandore2` money columns = million_rial, matching
  canonical `reported_value`.
- Identity: legacy 32-hex `CompanyID` → `core.legacy_entity_map`.
- `Product1/2/3` (legacy `EPS × Capital`) are deliberately excluded and never
  re-derived.

## 3. New shadow comparisons

- 12 heterogeneous companies × 2 fundamentals endpoints = 24 comparisons
  (plus 8 endpoint comparisons from Phase 1).
- Exact **4648**; expected **106** legacy-only + **384** unit + **83** semantic +
  **1** order; unexpected **0**; errors **0**.
- `SalesData2`: 384 matched, 0 unexpected. `SalesData`: 252 matched, 0 unexpected.

## 4. Market query root cause + fix

- Root cause: `VIEW_EXPANSION` + `QUERY_SHAPE`. `market.daily_prices` ranked
  331,265 rows before the security predicate was applied.
- Fix: resolve the security UUID once, read `market.price_observations` directly
  with `DISTINCT ON (trade_date)`, preserving `collected_at DESC, id DESC`.
- No index created or proposed; the existing `ix_price_observations_cutoff` is used.
- Median 655.6 ms → 1.8 ms (15 samples); p95 700.9 ms → 6.8 ms.
- Endpoint-level canonical latency 3280.4 ms → 71.1 ms (6 symbols).
- Equivalence: same rows/dates/prices/ordering; `EXCEPT` 0/0; shadow still
  1260 exact / 0 unexpected.

## 5. Unmapped legacy names

| Name | Classification |
| --- | --- |
| کسرا | Alias-only naming issue (mapped; canonical legal display_name differs from symbol) |
| خاهن | Canonical scope exclusion (no market/security identity) |
| شخارک | Canonical scope exclusion |
| شکیمیا | Canonical scope exclusion |

No canonical data or mapping was changed. Detail: `UNMAPPED_LEGACY_NAMES.md`.

## 6. Files changed (Phase 2)

- `go-app/integration/canonical.go` — `ResolveSecurityID`, optimized `PriceHistory`,
  `MonthlyActivitiesByLegacyCompanyID`, `FinancialMetricsByLegacyCompanyID`.
- `go-app/integration/source.go` — extended `canonicalSource`.
- `go-app/integration/mode.go` — `MaxCompanies` cap.
- `go-app/integration/shadow.go` — `CompareSalesData`, `CompareSalesData2`, specs,
  record builders.
- `go-app/integration/shadow_test.go` — fundamentals + isolation tests.
- `go-app/handlers/sales_data.go` — extended SELECT (shadow-only columns) + hook.
- `go-app/handlers/sales_data2.go` — shadow hook capturing pre-presentation values.
- `go-app/cmd/shadowcheck/main.go` — fundamentals sample + legacy builders.
- Artifacts: `MARKET_QUERY_PROFILE.md`, `UNMAPPED_LEGACY_NAMES.md`, updated
  matrices/reports/manifest/outputs.

**Not changed:** `config/db.go`, any write handler, any Python file, all canonical
schema/analytics code, and the existing legacy response contracts.

## 7. Tests

- `go build ./...` → pass.
- `go vet ./...` → pass.
- `go test ./integration/...` → pass (includes SalesData/SalesData2 legacy+shadow,
  canonical failure isolation, unit normalization, date/NULL/ordering comparison,
  identity, write-safety guards).
- Python: not modified. `py/tests` 23 passed (unittest); `py2/tests` 4 passed
  (domain runner).
- Canonical analytics tests: **not rerun** — no canonical analytics code was
  touched in Phase 2; rerunning would be ceremony only.

## 8. Write-safety

`guard_test.go` confirms the integration package contains no `INSERT`, `UPDATE`,
`DELETE`, `MERGE`, DDL, no hard-coded credentials and no legacy heuristic tokens.
The canonical PostgreSQL session is also forced read-only.

## 9. Read-only / production behavior

- SQL Server remains authoritative and read-only from the app.
- Default mode remains `LEGACY`; no canonical connection is opened by default.
- No production traffic was switched to canonical.
- Rollback remains configuration-only (`CDF_READ_MODE=legacy`).

## 10. Performance before/after

| Metric | Before | After |
| --- | --- | --- |
| Canonical market query median (15 samples) | 655.6 ms | 1.8 ms |
| Canonical market query p95 | 700.9 ms | 6.8 ms |
| Endpoint canonical aggregate (6 symbols) | 3280.4 ms | 46–71 ms |
| SalesData canonical aggregate (12 companies) | n/a | 1475 ms cold / ~87 ms warm |

## 11. Residual risks

- SalesData canonical read is N+1 per company; batch by `= ANY(...ids)` in a
  later phase if needed.
- Canonical `CompanyNames` returns legal `display_name`; for a future canonical
  canary it should union `security_aliases` symbols so alias-only names (کسرا)
  match. This is an API-layer decision, not a data defect.

## 12. Canary readiness assessment (not enabled)

| Requirement | Status |
| --- | --- |
| Selected endpoints have zero unexplained semantic mismatches | ✅ |
| Canonical failure behavior understood | ✅ |
| Market performance no longer pathological | ✅ |
| Fundamentals shadow comparisons understood | ✅ |
| Rollback config-only | ✅ |
| Production response contract preserve | ✅ |

Blocking concerns for a CANONICAL-read canary:

1. `/api/SalesData` exposes legacy `Product1/2/3` which have **no canonical
   equivalent**; a canary cannot serve them without an explicit product decision.
2. The canonical `CompanyNames` reader would expose legal names/identity
   differently (alias-only case), risking a client-visible change.
3. SalesData canonical N+1 latency (~113 ms/company) is acceptable but unproven
   at full population.

For those three endpoints: **CANARY_READ_NOT_READY**. These are
product/API-contract decisions, not integration defects.

## 12b. Phase 3 — price-history canary (implemented)

`GET /api/price-history` now has an endpoint-level canonical read canary:

- Selection: deterministic allowlist (`CDF_PRICE_HISTORY_CANARY_SYMBOLS`) and/or
  stable FNV-1a percentage (`CDF_PRICE_HISTORY_CANARY_PERCENT`). Default off.
- Serving: canonical with automatic legacy fallback on error/timeout/empty;
  response contract identical to legacy.
- Kill switch: `CDF_PRICE_HISTORY_CANARY_ENABLED=false` (config-only).
- Verification: optional synchronous legacy comparison during the canary.
- Diagnostics: `price_history_canary_summary.json` + `price_history_canary_samples.csv`.

Live results (6 allowlisted symbols): 1260 exact / 0 expected / 0 unexpected /
0 canonical-served errors; fallback verified for unknown symbol, injected
PostgreSQL failure, live 1 ms timeout and both-unavailable. Canonical median
1.40 ms vs legacy baseline 55.8 ms. Gate: `PRICE_HISTORY_CANARY_READY`.
Details: `PRICE_HISTORY_CANARY_SPEC.md`, `PRICE_HISTORY_CANARY_RUNBOOK.md`,
`PRICE_HISTORY_CANARY_REPORT.md`.

## 13. Recommended next single action

Run a bounded production canary for `GET /api/price-history` with 1–3 allowlisted
symbols and `VERIFY=true`, watching `comparison_unexpected` and `canary_fallback`,
then expand the allowlist in small batches. Do not extend to fundamentals
endpoints until the `SalesData` `Product1/2/3` contract and `CompanyNames` alias
presentation are decided, and do not enable global `CANONICAL`.
