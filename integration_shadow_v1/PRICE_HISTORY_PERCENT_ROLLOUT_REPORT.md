# PRICE_HISTORY 5% DETERMINISTIC PERCENTAGE ROLLOUT REPORT

Endpoint: `GET /api/price-history` only. Global mode `LEGACY`. No other endpoint,
no write path, no Python, no canonical data/schema/identity change.

## 0. Correctness finding during this task (important)

The first 5% run (before the coverage check) selected 15 safe symbols and
produced **403 `comparison_expected` differences, all from `های وب3`**. This was
a real client-visible divergence: legacy splits the instrument's history across
two symbol spellings (`های وب` 1,672 rows / `های وب3` 54 rows) while canonical
holds the full series under `های وب3`, so canonical serving returned a different
date range.

Root cause: the identity guard classified by identity count only; it did not
detect **date-coverage divergence**. This was not normalized away. The guard was
tightened with a deterministic coverage-safety rule (below), the registry was
regenerated, and the rollout was re-run. The pre-fix raw evidence is preserved in
`output_percent5_precoverage/`.

### Coverage-safety rule added

A symbol classified `CANONICAL_SAFE` by identity is reclassified
`LEGACY_COVERAGE_DIVERGENCE` (non-safe → legacy) if the union of legacy
`GregorianDate` values over `CompanyName`/`Symbol` spellings is not exactly equal
to the canonical security's `market.daily_prices.trade_date` set. This is purely
structural/identity-derived and changes no canonical data.

New classification counts: `CANONICAL_SAFE` 272, `LEGACY_IDENTITY_COLLISION` 3,
`LEGACY_COVERAGE_DIVERGENCE` 4, `LEGACY_ONLY` 5, `CANONICAL_UNMAPPED` 1.

Coverage divergences: `جم پیلن3`, `سیمرغ3`, `های وب3`,
`کاتالیست های صنعتی آریا` (legal-name alias of کسرا).

## 1. Configuration

`CDF_READ_MODE=legacy`, `CDF_PRICE_HISTORY_CANARY_ENABLED=true`,
`CDF_PRICE_HISTORY_CANARY_PERCENT=5`, `CDF_PRICE_HISTORY_CANARY_VERIFY=true`,
no allowlist, identity guard active (`CDF_PRICE_HISTORY_ELIGIBILITY_FILE`).

## 2. Exact 5% cohort

- `CANONICAL_SAFE` population: **272**; 5% bucket selects **14**.
- **0 unsafe selected** (collisions/coverage/legacy-only/unmapped never
  selected).
- Deterministic (FNV-1a mod 100; repeated simulation identical).

Selected cohort (symbol | bucket): خزامیا|4, دسبحا|3, زهلال|2, سغرب|1, غشوکو|2,
فبستم|2, فولاد|3, فپنتا|4, نان|0, وخارزم|0, پاکشو|3, چدن|3, کبافق|0, کیمیاتک|0.

(Pre-coverage the cohort had 15; `های وب3|1` was removed by the coverage check.)

## 3. Real request validation

Server exercised through the real JWT-protected HTTP API. Groups:
A selected-safe, B non-selected-safe, C collisions, D legacy-only,
E canonical-unmapped, F safe alias `کسرا`, G unknown.

| Group | Requests | HTTP 200 | contract | median ms | p95 ms |
| --- | --- | --- | --- | --- | --- |
| A selected-safe | 70 | 70 | ok | 84.9 | 116.8 |
| B non-selected-safe | 10 | 10 | ok | 73.8 | 108.5 |
| C collisions | 15 | 15 | ok | 74.8 | 92.1 |
| D legacy-only | 9 | 9 | ok | 76.2 | 103.6 |
| E unmapped | 3 | 3 | ok | 62.1 | 71.3 |
| F safe alias | 5 | 5 | ok | 69.8 | 108.3 |
| G unknown | 3 | 3 | ok | 67.8 | 92.0 |

Totals: **115 requests, 115 × HTTP 200**, contract keys exact, ordering
descending, limits honoured. **All 14/14 cohort symbols exercised** (distinct).

## 4. Routing results

| Metric | Value |
| --- | --- |
| total requests | 115 |
| canary selected | 70 |
| canonical served | **70** |
| legacy served | 45 |
| canonical ineligible (guard) | 30 |
| — legacy_identity_collision | 15 |
| — legacy_only | 9 |
| — canonical_unmapped | 3 |
| — other_unsafe (unknown) | 3 |
| fallbacks | **0** |
| canonical errors/timeouts | **0** |
| eligibility_guard_forced_legacy | 0 (no non-safe bucket < 5 at 5%) |

## 5. Comparisons (VERIFY=true)

**exact 48,888 / expected 0 / unexpected 0** across canonical-served requests.
No unexplained and no population mismatch for any served symbol.

## 6. Collision/unsafe symbols stayed legacy

Verified via the 5% run (canonical_served 0 for جم پیلن، های وب، سیمرغ، خاهن،
شخارک، شکیمیا، جم پیلن2) and an **isolated 100% control run**:
at 100%, only 3 `CANONICAL_SAFE` requests (فولاد) were canonical-served;
the three collisions and other non-safe symbols were hash-matched but
**forced legacy** (`eligibility_guard_forced_legacy=24`,
`canonical_ineligible=24`, collision canonical_served=0).

## 7. Latency

| Path | median | p95 |
| --- | --- | --- |
| Canonical read | 1.68 ms | 2.99 ms |
| Legacy verify read | 62.03 ms | 79.35 ms |
| HTTP total (VERIFY=true) | see §3 groups | — |

`VERIFY=true` still adds a synchronous legacy read; HTTP totals are not
steady-state canonical latency. No optimization/caching introduced.

## 8. Health

Canonical and SQL Server pools stable; read-only canonical session enforced; no
writes; no connection leak, goroutine issue, or elevated 5xx; no schema change.

## 9. Kill-switch drill

`CDF_PRICE_HISTORY_CANARY_ENABLED=false` + restart:
health `read_mode=legacy`, `canary_enabled=false`; **0 canonical selections**;
all requests served legacy; config-only, no code/DB change.

## 10. Gate

**`PRICE_HISTORY_PERCENT5_PASS`**

This does not authorize full endpoint cutover.

## 11. Next-step assessment

**`PRICE_HISTORY_PERCENT10_READY`** — 14/14 selected symbols exercised, 0
unexpected, guard proven under 100% hash selection, kill switch verified,
latency stable.

Global remains **`GLOBAL_CANARY_NOT_READY`**.
