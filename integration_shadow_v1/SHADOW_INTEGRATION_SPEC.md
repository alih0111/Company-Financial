# SHADOW INTEGRATION SPEC — Phase 1

## 1. Purpose

Define the first safe read-only integration layer between the legacy Go/Python
application and canonical PostgreSQL, using **shadow reads**, **dual-read
comparison**, **feature flags** and **no production behavior change**.

SQL Server remains the production source of truth. The canonical canonical
PostgreSQL environment is used read-only. No production cutover occurs.

## 2. Read modes

Three conceptual modes, selected by configuration:

| Mode | Behavior |
| --- | --- |
| `LEGACY` (default) | Current SQL Server path only. No canonical connection is opened. |
| `SHADOW` | SQL Server remains authoritative for the API response. The canonical query also runs for comparison. The canonical result **never** changes the user-visible response. |
| `CANONICAL` | Reserved for later cutover. Phase 1 has **no code path** that serves canonical data to clients. |

### Configuration contract

| Env var | Meaning | Default |
| --- | --- | --- |
| `CDF_READ_MODE` | `legacy` \| `shadow` \| `canonical` | `legacy` |
| `CDF_READ_MODE_<ENDPOINT>` | Per-endpoint override, e.g. `CDF_READ_MODE_GET_/_API_/SUMMARY` (matched case-insensitively) | global mode |
| `CANONICAL_DATABASE_URL` / `CDF_CANONICAL_URL` / `DATABASE_URL` | PostgreSQL URL. SQLAlchemy `+psycopg` suffix is stripped. | none |
| `CDF_CANONICAL_DB` / `CDF_PILOT_DB` | Overrides the database name in the URL (used to point at the shadow DB) | URL's DB |
| `CDF_CANONICAL_READ_ONLY` | Force `default_transaction_read_only=on` on the session | `true` |
| `CDF_SHADOW_TIMEOUT_MS` | Canonical shadow read timeout | `2000` |
| `CDF_SHADOW_OUTPUT_DIR` | Diagnostics output directory | `../integration_shadow_v1/output` |
| `CDF_CANONICAL_SCORE_VERSION` | canonical analytics model/score version | `canonical-v1-dev` |
| `CDF_ALLOW_NON_TEST_PG` | Explicitly bypass the test-DB prefix guard (not for routine use) | unset |

**Safety guard:** the DSN builder refuses any database whose name does not start
with one of `company_financial_analytics_shadow_`, `company_financial_migration_pilot_`,
`company_financial_test_`. This prevents accidentally pointing shadow reads at a
production PostgreSQL. No credentials are hard-coded.

## 3. Architecture

```
HTTP handler
  ├─ legacy read (SQL Server)  ──► response (authoritative, unchanged)
  └─ integration.Shadow.Compare*(ctx, legacyResult)
         ├─ canonical source (PostgreSQL, read-only, context+timeout)
         ├─ compare.CompareRecords (normalize + classify)
         └─ diagnostics.Collector  ──► integration_shadow_v1/output/*
```

- `integration.Shadow` is the **single** place dual-read logic lives. Handlers do
  not implement comparison themselves.
- `canonicalSource` is an interface; `*PG` is the production implementation and
  tests inject fakes.
- Repositories/domains: company identity, market prices, analytics scores.
- The canonical result is compared only; there is no API that returns it.

## 4. SHADOW execution guarantees

1. Execute the legacy read.
2. Return the legacy result exactly as before.
3. Run the canonical read (unless `LEGACY`/disabled), under a timeout.
4. Compare normalized representations.
5. Record structured diagnostics.
6. Never replace the response with PostgreSQL data.
7. A canonical failure is recorded as `QUERY_ERROR` and **does not** break a
   successful legacy request (fail-open for reads). LEGACY remains authoritative.
8. A `CANONICAL` mode value exists in configuration but does not serve data.

## 5. Units and identity

- Canonical monetary values are **IRR**; legacy `FullPE`/scoring heuristics may be
  million-IRR. The comparator classifies a ~1e6 factor as
  `EXPECTED_UNIT_PRESENTATION`. No scale guessing is introduced and canonical
  stored values are never changed.
- Canonical identity: Company (`core.companies.id` UUID) ≠ Security
  (`core.securities.id` UUID). Legacy 32-hex `CompanyID` is resolved through
  `core.legacy_entity_map`; symbols via `core.security_aliases`.
- Legacy public IDs and JSON shapes are preserved; no client changes are required.

## 6. Point-in-time semantics

- Analytics consumption selects a completed `analytics.score_runs` row by
  `(score_version, as_of_date DESC, started_at DESC)`. PIT `source_cutoff_at` is a
  property of the run and is not re-derived in Go.
- The integration layer never reimplements factor formulas and never reads "latest
  row" naive SQL for analytics.

## 7. Failure isolation matrix

| Scenario | Expected behavior |
| --- | --- |
| PostgreSQL down, SQL Server healthy | Legacy response returned; `QUERY_ERROR` recorded |
| PostgreSQL timeout | Same; bounded by `CDF_SHADOW_TIMEOUT_MS` |
| Malformed canonical query | Same; error text recorded (no secrets) |
| SQL Server down | Existing handler behavior (legacy error); canonical irrelevant |
| Both down | Existing legacy error behavior |
| Comparison failure | Recorded; legacy response unaffected |
| Canonical empty | `LEGACY_ONLY` rows recorded (expected where allowed) |
| Legacy empty | `CANONICAL_ONLY` rows recorded |

## 8. Rollback

Trivial and config-only:

- Set `CDF_READ_MODE=legacy` (or unset) → no canonical connection, no dual reads.
- No production default was changed; no SQL Server code was removed.

## 9. Out of scope (this phase)

Ingestion writes, auth writes, portfolio/family writes, `compat_v37` as application
architecture, legacy heuristics (`Product1`, `NPUnitRatio`, `OpK`, `OpAmt`) in
canonical paths, and any production cutover decision in code.
