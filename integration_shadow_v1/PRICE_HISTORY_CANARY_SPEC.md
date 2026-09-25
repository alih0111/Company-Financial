# PRICE_HISTORY CANARY SPEC

Endpoint: `GET /api/price-history` only. This is the first endpoint-level
canonical read canary. It does **not** authorize any broad canonical cutover.

## 1. Objective

Allow a tightly controlled, deterministic subset of price-history requests to be
served from canonical PostgreSQL while preserving the existing API contract,
instant config-only rollback, automatic legacy fallback and observability.

## 2. Modes and precedence

Existing global modes are unchanged: `LEGACY` (default), `SHADOW`, `CANONICAL`.
The canary is a separate, explicit switch.

Routing precedence for price-history (`Shadow.PriceHistoryRoute`):

| Condition | Route | Behavior |
| --- | --- | --- |
| endpoint mode = `SHADOW` | `RouteShadow` | legacy served + canonical compared only (never canonical serving) |
| endpoint mode = `CANONICAL` | `RouteCanary` | canonical served with fallback (reserved; not enabled) |
| canary enabled and symbol selected | `RouteCanary` | canonical served with fallback |
| otherwise | `RouteLegacy` | SQL Server only |

`SHADOW` semantics are preserved and never repurposed: a canary selection is
ignored in `SHADOW` mode.

## 3. Configuration

| Env var | Meaning | Default |
| --- | --- | --- |
| `CDF_PRICE_HISTORY_CANARY_ENABLED` | master switch | `false` |
| `CDF_PRICE_HISTORY_CANARY_SYMBOLS` | comma-separated symbol allowlist (normalized) | empty |
| `CDF_PRICE_HISTORY_CANARY_PERCENT` | optional deterministic percentage 0–100 | `0` |
| `CDF_PRICE_HISTORY_CANARY_VERIFY` | also run a legacy read to compare served canonical results | `false` |
| `CDF_PRICE_HISTORY_CANARY_TIMEOUT_MS` | canonical read timeout before fallback | `1500` |

Canonical connectivity continues to use the canonical URL/database contract from
`SHADOW_INTEGRATION_SPEC.md` (`CDF_CANONICAL_DB` etc.). Enabling the canary makes
the process open the canonical pool even while the global mode is `LEGACY`.

Safe default: disabled, or enabled with empty allowlist and 0% ⇒ **no request is
served canonically**.

## 4. Deterministic selection

- Allowlist: exact match on the normalized symbol (preferred for rollout).
- Percentage: stable `FNV-1a(symbol) % 100 < percent`. No runtime randomness and
  no dependence on process state; the same symbol always maps to the same bucket.
- Selection happens **before** any DB read, so routing is auditable from the
  symbol alone.

## 4b. Identity-eligibility guard (mandatory, before selection)

Canonical serving requires the symbol to be `CANONICAL_SAFE` in the identity
eligibility registry (`CDF_PRICE_HISTORY_ELIGIBILITY_FILE`, default
`../integration_shadow_v1/output/price_history_identity_eligibility.csv`). The
guard runs **before** allowlist and percentage selection; unsafe symbols are
forced to legacy and can never be canonical-served by allowlist or hash bucket.
Default-deny: a missing registry denies canonical serving. See
`PRICE_HISTORY_IDENTITY_ELIGIBILITY.md`.

Diagnostics: `canonical_safe`, `canonical_ineligible`,
`legacy_identity_collision`, `legacy_only`, `canonical_unmapped`,
`no_market_data`, `other_unsafe`, `eligibility_guard_forced_legacy`.

## 5. Response contract

Canonical rows are converted to the exact legacy JSON shape
(`PriceHistoryRow`): `date`, `jalali_date`, `closing_price`, `last_price`,
`high_price`, `low_price`, `volume`, `trade_value`, `change_percent`. Same field
names, numeric types, `YYYY-MM-DD` date format, DESC ordering, NULL→0 semantics
and IRR units. No canonical UUID is exposed and no client change is required.

## 6. Canonical query

The already validated optimized implementation is used (see
`MARKET_QUERY_PROFILE.md`): resolve the security once, read
`market.price_observations` directly filtered by security, `DISTINCT ON
(trade_date)` with `collected_at DESC, id DESC`. The slow full-view expansion is
not used and canonical data is never modified.

## 7. Fallback policy

For a canary-selected request:

1. Attempt the canonical read under `CDF_PRICE_HISTORY_CANARY_TIMEOUT_MS`.
2. Serve canonical if it succeeds and is **non-empty**.
3. Otherwise automatically execute the unchanged legacy SQL Server read and
   serve it. The canonical error is recorded; it is not surfaced to the client.
4. If legacy also fails, return the legacy error (HTTP 500). Errors are never
   swallowed.

Empty canonical results deterministically fall back to legacy so a known-good
symbol is never served an empty body.

## 8. Optional verification during canary

When `CDF_PRICE_HISTORY_CANARY_VERIFY=true`, a canonical-served request also runs
the legacy read and compares it via the existing framework. This is synchronous
for the bounded canary phase.

Trade-off: it adds the legacy read latency to canary-verify requests, but gives
continuous proof that served canonical results still match legacy. It does not
change the served response. For a broad rollout this should move to asynchronous
or sampled verification; that is a later decision.

## 9. Diagnostics

`Shadow` maintains secret-free canary counters and per-request samples. Two
artifacts are written to `CDF_SHADOW_OUTPUT_DIR` (default
`../integration_shadow_v1/output`):

- `price_history_canary_summary.json`
- `price_history_canary_samples.csv`

Counters: `total_requests`, `legacy_served_requests`, `shadow_requests`,
`canary_selected`, `canary_success`, `canary_fallback`, `canonical_errors`,
`legacy_fallback_errors`, `comparison_exact`, `comparison_expected`,
`comparison_unexpected`. Latency medians/p95 are reported for canonical, legacy
baseline and fallback. Samples include the symbol, route, row count, latencies and
an error string; no JWT, credential or connection string is ever recorded.

## 10. Health semantics

- Global `LEGACY` + canary disabled ⇒ canonical availability is irrelevant and
  never affects health.
- Canary enabled ⇒ canonical degradation is visible via
  `GET /api/health/shadow` (`canonical_reachable`, `price_history_canary_*`), but
  fallback keeps the endpoint serviceable while legacy is healthy.
- A canonical outage must not become a global production outage source.

## 11. Kill switch

`CDF_PRICE_HISTORY_CANARY_ENABLED=false` (or unset) is the single kill switch. It
immediately restores 100% legacy serving for this endpoint with no code, DB or
deploy change. See `PRICE_HISTORY_CANARY_RUNBOOK.md`.

## 12. Explicit non-goals

No changes to `SalesData`, `SalesData2`, `CompanyNames`, `summary`, auth,
portfolio/family or Python ingestion. No PostgreSQL cutover. No canonical schema
or market-data changes.
