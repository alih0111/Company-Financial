# PRICE_HISTORY CANARY REPORT

Endpoint: `GET /api/price-history` (only). Global mode remained `LEGACY`.
Nothing broad was enabled.

## 1. Configuration under test

| Setting | Value |
| --- | --- |
| `CDF_READ_MODE` | `legacy` |
| `CDF_CANONICAL_DB` | `company_financial_analytics_shadow_v121` |
| `CDF_PRICE_HISTORY_CANARY_ENABLED` | `true` |
| `CDF_PRICE_HISTORY_CANARY_SYMBOLS` | 6 symbols |
| `CDF_PRICE_HISTORY_CANARY_VERIFY` | `true` |
| `CDF_PRICE_HISTORY_CANARY_TIMEOUT_MS` | `1500` |

Harness: `go run ./cmd/canarycheck`.

## 2. Symbols / requests tested

Allowlisted (representative, reused from Phase 1/2): `کیمیا`, `غاذر`, `سباقر`,
`دقاضی`, `دارو`, `فایرا` — 30 sessions each.

Edge cases: unknown symbol, injected PostgreSQL unavailable, injected both
backends unavailable, and a live 1 ms timeout run.

## 3. Results

| Metric | Value |
| --- | --- |
| canary-selected | 9 |
| canonical-served | 6 (30 rows each) |
| fallback | 3 (unknown → legacy; pg-unavailable → legacy; both-unavailable → error) |
| comparison exact | 1260 (6 × 30 × 7 fields) |
| comparison expected | 0 |
| comparison unexpected | **0** |
| canonical errors | 3 (empty unknown, injected pg failure, injected both) |
| legacy fallback errors | 1 (both unavailable) |

## 4. Latency (live)

| Path | median | p95 |
| --- | --- | --- |
| Canonical (canary-served) | **1.40 ms** | 1.71 ms |
| Legacy baseline (same symbols, 18 samples) | 55.75 ms | 71.04 ms |
| Fallback total (canonical failure + legacy) | 56.73 ms | — |

Canonical is ~40× faster than the legacy baseline (a prior run measured 1.35 ms
vs 73.20 ms). Fallback latency is dominated by the legacy read, as expected.

## 5. Failure injection

| Scenario | Result |
| --- | --- |
| Unknown symbol (canonical empty) | `fallback_served`, 0 rows, deterministic |
| PostgreSQL unavailable (injected) | `fallback_served`, 30 legacy rows |
| PostgreSQL timeout (live, 1 ms) | all 6 symbols `fallback_served`, 30 legacy rows each |
| Both unavailable (injected) | `fallback_failed`, legacy error returned (HTTP 500 path) |
| Legacy unavailable only | legacy error behavior unchanged |
| Missing `companyName` | unchanged 400 at handler entry (not route-dependent) |

No PostgreSQL failure was surfaced to the client while legacy was healthy.

## 6. Contract equivalence

Canonical rows are emitted through `PriceHistoryRow` with identical field names,
types, `YYYY-MM-DD` dates, DESC ordering, NULL→0 behavior and IRR units.
Comparison during canary verify was exact for every served row and field; no
canonical UUID is exposed and no client change is required.

## 7. Artifacts

- `output/price_history_canary_summary.json`
- `output/price_history_canary_samples.csv`

## 8. Tests

`go build ./...` ✅, `go vet ./...` ✅, `go test -count=1 ./integration/...` ✅.
New tests cover: default disabled, kill switch, allowlist/percentage
determinism, route matrix, canonical serve, fallback on error/empty,
fallback failure, canonical timeout fallback, verify in legacy mode, diagnostics
flush, and that other endpoints remain legacy. Existing SHADOW semantics tests
remain green. Python untouched.

## 9. Write-path confirmation

Read-only throughout. Static guard tests still confirm no `INSERT`/`UPDATE`/
`DELETE`/`MERGE`/DDL in the integration package and the canonical session is
forced read-only. No SQL Server write path was touched.

## 10. Other endpoints

`SalesData`, `SalesData2`, `CompanyNames`, `summary`, auth, portfolio/family and
Python ingestion are unchanged by this canary; only price-history routing is
affected.

## 11. Endpoint gate

**`PRICE_HISTORY_CANARY_READY`**

## 12. Global integration status

**`GLOBAL_CANARY_NOT_READY`** — the unresolved `SalesData` `Product1/2/3`
contract, `CompanyNames` alias/legal-name presentation, and fundamentals N+1
latency remain open. One endpoint being ready does not promote the application.

## 13. Recommended next single action

Run a bounded production canary for `GET /api/price-history` with 1–3 allowlisted
symbols and `VERIFY=true`, watching `comparison_unexpected` and `canary_fallback`,
then expand the allowlist in small batches. Do not touch the other endpoints or
enable global `CANONICAL`.
