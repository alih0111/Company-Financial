# PRICE_HISTORY PRODUCTION CANARY REPORT

Endpoint: `GET /api/price-history` only. Global mode stayed `LEGACY`. No other
endpoint was canaried. No write path, schema, analytics or Python code changed.

## 0. Environment (important, honest scope)

The canary was executed end-to-end in the available workspace environment:

- real Go API process (`go-app-canary.exe`) with the JWT middleware,
- real HTTP requests (50) plus one incidental request,
- legacy source: live SQL Server `codal`,
- canonical source: the designated shadow/test database
  `company_financial_analytics_shadow_v121` (there is no separate production
  canonical PostgreSQL cluster in this workspace; production PostgreSQL must not
  be modified).

This validates the routing/contract/fallback mechanics under real serving. It does
**not** claim a global canonical cutover, and the canonical backend is the
approved shadow/test database by design.

## 1. Symbols canaried

| Symbol | Rationale | Canonical observations |
| --- | --- | --- |
| کیمیا | normal/high-volume, already exact in Phase 1–3 | 2,354 |
| غاذر | large history (2004→2026), already exact in Phase 1–3 | 3,723 |
| کسرا | different identity/alias case (security symbol ≠ legal display name), validated exact pre-run | 3,660 |

Control (non-allowlisted): `سباقر` (plus one incidental `زگلدشت`).

Configuration: `CDF_READ_MODE=legacy`, `CDF_PRICE_HISTORY_CANARY_ENABLED=true`,
allowlist = the three symbols, `CDF_PRICE_HISTORY_CANARY_PERCENT=0`,
`CDF_PRICE_HISTORY_CANARY_VERIFY=true`, timeout 1500 ms. Port 5055.

## 2. Preflight result

| Check | Result |
| --- | --- |
| Application healthy before enabling | ✅ health endpoint OK |
| SQL Server healthy | ✅ live queries succeeded |
| Canonical PostgreSQL healthy | ✅ 705,812 observations, 273 companies |
| Canonical connection read-only | ✅ `SHOW default_transaction_read_only = on` |
| No pending schema changes | ✅ canonical schema untouched |
| No unexpected integration diagnostics | ✅ prior shadow run 0 unexpected |
| Current default is LEGACY | ✅ |
| Allowlist only intended symbols | ✅ 3 |
| Percentage exactly 0 | ✅ |
| Pre-run exact validation of the 3 symbols | ✅ 3 × 210 exact, 0 unexpected |

## 3. Aggregate results

| Metric | Value |
| --- | --- |
| Total price-history requests observed | 51 |
| Canary selected | 45 |
| Canonical served | **45** |
| Fallback | **0** |
| Canonical errors / timeouts | **0 / 0** |
| Comparison exact | 50,925 |
| Comparison expected | 0 |
| Comparison unexpected | **0** |
| Legacy-served (non-allowlisted/incidental) | 6 |
| HTTP 200 | 50 / 50 runner requests |
| Contract keys (all 9 fields) | exact match on every response |

## 4. Per-symbol summary

| Symbol | Requests | Canonical served | Fallbacks | Exact | Expected | Unexpected | Canon. errors | Canon. median / p95 | HTTP total median / p95 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| کیمیا | 15 | 15 | 0 | 16975 | 0 | 0 | 0 | 2.43 / 3.65 ms | 89.4 / 106.2 ms |
| غاذر | 15 | 15 | 0 | 16975 | 0 | 0 | 0 | 1.99 / 2.51 ms | 84.9 / 151.3 ms |
| کسرا | 15 | 15 | 0 | 16975 | 0 | 0 | 0 | 2.12 / 2.90 ms | 113.7 / 326.7 ms |
| سباقر (control, non-allowlisted) | 5 | 0 | 0 | 0 | 0 | 0 | 0 | — | 80.2 / 81.7 ms |

HTTP total latency includes the synchronous `VERIFY=true` legacy read, so it is
dominated by the legacy verification path, not by canonical serving. The
canonical latency figures above are the canonical read only.

## 5. Contract and correctness

- Field names/types identical to legacy (`date`, `jalali_date`, `closing_price`,
  `last_price`, `high_price`, `low_price`, `volume`, `trade_value`,
  `change_percent`).
- Dates descending, `limit` honoured (rows == limit: 30/90/365).
- No canonical UUID exposed; no client change required.
- Verify comparison was exact for every served row across every request;
  expected 0, unexpected 0.

## 6. Latency

| Path | median | p95 |
| --- | --- | --- |
| Canonical read (served) | 2.11 ms | 3.43 ms |
| Legacy verification read | 66.8 ms | 77.6 ms |

Canonical is ~30× faster; no pathological latency. Within the test-environment
expectation range (canonical 1–2 ms, legacy 50–70 ms).

## 7. Fallback

Zero fallbacks occurred because canonical was healthy throughout. Fallback
mechanics were already validated in the Phase-3 simulation (unknown symbol,
injected PostgreSQL failure, live 1 ms timeout, both unavailable). During this
production canary no fallback was triggered and none was needed.

## 8. Kill switch (exercised)

After the canary, the process was restarted with
`CDF_PRICE_HISTORY_CANARY_ENABLED=false`:

- health reported `price_history_canary_enabled=false`, `read_mode=legacy`;
- allowlisted symbols کیمیا/غاذر/کسرا and control symbols all returned 30 rows
  via legacy (~63–102 ms);
- no canonical selection and no canary diagnostics were produced.

Rollback is configuration-only and was proven operational.

## 9. Stop conditions

None triggered. All stop conditions (semantic mismatch, contract mismatch,
incorrect date/order/price, repeated timeout/error, fallback malfunction,
client-visible regression, DB load, pool instability, inability to verify)
were absent.

## 10. Health / DB impact

No application errors; canonical reachable; read-only session enforced;
no connection-pool instability; zero canonical errors/timeouts; no unexpected DB
load (single-security indexed reads).

## 11. Artifacts

- `output/price_history_production_canary.json`
- `output/price_history_production_canary_samples.csv`
- raw server diagnostics preserved under `output_prodcanary/`
- prior simulation artifacts under `output/price_history_canary_*` not overwritten.

## 12. Tests / verification

`go build ./...` ✅, `go vet ./...` ✅, `go test -count=1 ./integration/...` ✅.
Write paths untouched; Python untouched; other endpoints remain legacy; global
`CANONICAL` mode not enabled.

## 13. Gate

**`PRICE_HISTORY_PRODUCTION_CANARY_PASS`**

This does **not** authorize global canonical cutover.

## 14. Global blockers (unchanged)

- SalesData `Product1/2/3` contract
- CompanyNames legal-name vs alias contract
- fundamentals full-population performance

Global status remains `GLOBAL_CANARY_NOT_READY`.

## 15. Recommendation

**A. Expand the price-history allowlist in another bounded batch** (next 2–3
symbols), keeping `PERCENT=0` and `VERIFY=true`, before considering any
percentage rollout.

---

# BATCH 2 (bounded allowlist expansion)

Status: **`PRICE_HISTORY_CANARY_BATCH2_PASS`**. Batch 1 evidence above is
preserved unchanged.

## B2.1 Symbols and selection reasons

Allowlisted (5):

| Symbol | Selection reason | Canonical observations |
| --- | --- | --- |
| وسپه | very long / large history (2001→2026) | ~5,548 |
| خودرو | long, high-volume history (2001→2026) | ~5,288 |
| بفجر | short / sparse history | ~10 |
| مبین | short / sparse history | ~12 |
| دزهراوی | sparse fundamentals (0 statements) but valid market history | ~4,190 |

Control (non-allowlisted): `سباقر`.

Evaluated and **excluded** (documented, not normalized away):

| Symbol | Finding |
| --- | --- |
| جم پیلن | legacy duplicate-symbol identity collision: legacy `CompanyName='جم پیلن'` matches rows for both `جم پیلن` (1,579 obs) and `جم پیلن3` (38 obs); canonical resolves the alias to a single security. Pre-validation showed 76 unexpected differences. |
| های وب | same collision (`های وب` 1,672 obs vs `های وب3` 54 obs); 34 unexpected differences. |

The canonical revision selection itself was correct (both "3" securities have
multiple versions per date and canonical deterministically picks the latest via
`collected_at DESC, id DESC`). The mismatch is a **legacy identity ambiguity**,
not a canonical defect, and makes these symbols unsafe to canary until identity
handling is decided. They were therefore excluded.

## B2.2 Requests and results

- Configuration: `CDF_READ_MODE=legacy`, canary enabled, `PERCENT=0`,
  `VERIFY=true`, timeout 1500 ms, 5-symbol allowlist.
- Request shapes: limits 30/90/365/5000 (full-history style) per symbol plus a
  non-allowlisted control; 95 HTTP requests total.
- HTTP: **95/95 HTTP 200**, contract keys exact on every response, ordering
  verified descending, `limit` honoured (e.g. بفجر returns all 10, مبین all 12).

| Metric | Value |
| --- | --- |
| Total requests | 95 |
| Canary selected | 90 |
| Canonical served | **90** |
| Fallback (organic) | **0** |
| Canonical errors / timeouts | **0 / 0** |
| Comparison exact | 247,212 |
| Comparison expected | 0 |
| Comparison unexpected | **0** |

Per-symbol:

| Symbol | Req | Canon. served | Fallback | Exact | Unexpected | Canon. median / p95 | HTTP total median / p95 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| وسپه | 18 | 18 | 0 | 85260 | 0 | 2.10 / 11.41 ms | 87.5 / 217.5 ms |
| خودرو | 18 | 18 | 0 | 85260 | 0 | 1.54 / 10.51 ms | 91.4 / 198.1 ms |
| بفجر | 18 | 18 | 0 | 1260 | 0 | 1.17 / 2.29 ms | 74.0 / 99.4 ms |
| مبین | 18 | 18 | 0 | 1512 | 0 | 0.97 / 1.75 ms | 69.1 / 104.4 ms |
| دزهراوی | 18 | 18 | 0 | 73920 | 0 | 1.57 / 10.84 ms | 76.6 / 189.1 ms |

## B2.3 Behavior by history size / limit

- Median canonical latency is flat (~1–2 ms) regardless of symbol or limit.
- p95 rises modestly at the 5000-row full-history requests (up to ~11 ms) due to
  payload size; still far below legacy.
- Latency does **not** scale materially with observation count (وسپه ~5,548 obs
  remains ~2 ms median).
- No query optimization attempted; no regression observed.

## B2.4 Controlled fallback (exercised)

A second server instance was started with `CDF_PRICE_HISTORY_CANARY_TIMEOUT_MS=1`
to safely force canonical timeouts:

- canary selected 5; canonical served 0; **fallback 5**; canonical errors 5.
- Every request returned HTTP 200 with the correct row counts (30/30/10/12/30),
  served by legacy; fallback median 69.8 ms / p95 87.8 ms.
- Canonical connectivity was restored immediately after (server stopped; normal
  canonical remains healthy).

## B2.5 Kill switch (re-exercised)

Restarted with `CDF_PRICE_HISTORY_CANARY_ENABLED=false`:
`canary_enabled=false`, `read_mode=legacy`, all allowlisted symbols served legacy
(~73–125 ms). Rollback remains config-only.

## B2.6 Health impact

Canonical pool stable, SQL Server stable, no elevated API errors, no write
queries, no connection leak or goroutine issue observed in verify mode. All
requests returned valid responses.

## B2.7 Batch-2 gate

**`PRICE_HISTORY_CANARY_BATCH2_PASS`**

## B2.8 Percentage-rollout readiness

**`PRICE_HISTORY_PERCENT_ROLLOUT_NOT_READY`**

Reason: a percentage rollout would deterministically route currently-excluded
identity-collision symbols (e.g. `جم پیلن`, `های وب`) to canonical, where they
resolve to a **single** security while legacy returns rows for **two**
instruments sharing the company name. That is a client-visible divergence not
covered by the allowlist validation. Percentage rollout must wait until the
legacy duplicate-symbol identity cases are resolved (or explicitly excluded).

This applies to `/api/price-history` only and does not change
`GLOBAL_CANARY_NOT_READY`.

---

# BATCH 2 FOLLOW-UP — IDENTITY ELIGIBILITY GUARD

The Batch-2 blocker is now mitigated by a deterministic identity-eligibility
guard rather than by fixing legacy identity ambiguities.

- Full audit: 285 symbols → **276 CANONICAL_SAFE**, **3 LEGACY_IDENTITY_COLLISION**
  (جم پیلن، **سیمرغ (new)**، های وب), 5 LEGACY_ONLY, 1 CANONICAL_UNMAPPED, 0 other.
- Guard runs **before** allowlist/percentage selection; unsafe symbols are forced
  to legacy and can never be canonical-served. Default-deny on a missing registry.
- Real HTTP proof (guard active, allowlist deliberately included 3 collisions +
  1 safe): collisions canonical_served **0** (forced legacy), safe served
  canonically (exact 1050, unexpected 0); `eligibility_guard_forced_legacy=16`.
- Safe sample (وسپه، خودرو، کسرا، کیمیا، دزهراوی) re-verified exact with the guard
  active: 210 exact each, 0 unexpected.
- Percentage simulation (1/5/10/25/100%): `unsafe_canonical_served=0` at every
  level; at 100%, 276/276 CANONICAL_SAFE selected.
- Gate: `PRICE_HISTORY_IDENTITY_GUARD_READY`. Percentage rollout remains
  **not enabled** in this task.

Details: `PRICE_HISTORY_IDENTITY_ELIGIBILITY.md`,
`output/price_history_identity_eligibility.csv`,
`output/price_history_percent_simulation.json`.

---

# 5% DETERMINISTIC PERCENTAGE ROLLOUT

Status: **`PRICE_HISTORY_PERCENT5_PASS`** (see
`PRICE_HISTORY_PERCENT_ROLLOUT_REPORT.md`).

- 5% cohort: **14 `CANONICAL_SAFE` symbols**, **0 unsafe**; deterministic.
- Real HTTP: **115 requests / 115 × 200**, all 14/14 cohort symbols exercised;
  **70 canonical-served**, 0 fallback, 0 errors, **expected 0 / unexpected 0**.
- Latency: canonical median 1.68 ms / p95 2.99 ms; legacy verify 62.0 / 79.4 ms.
- Collisions/unsafe stayed legacy; isolated 100% control forced
  `legacy_identity_collision`/coverage/unmapped to legacy (0 canonical-served).
- Kill switch verified (config-only → 100% legacy).
- Correctness finding addressed: date-coverage divergence (`های وب3`, plus the
  three "3" securities and کسرا's legal-name alias) now classified
  `LEGACY_COVERAGE_DIVERGENCE` and forced to legacy.
- Next-step assessment: `PRICE_HISTORY_PERCENT10_READY` (not executed).
- Global remains `GLOBAL_CANARY_NOT_READY`.
