# FUNDAMENTALS READ MIGRATION

Status: **SHADOW validated, 0 unexplained mismatch.** Legacy remains the served
response. No broad production cutover was performed.

Endpoints:
- `GET /api/SalesData` — income statement (`miandore2` → `fundamentals.financial_facts`)
- `GET /api/SalesData2` — monthly activity (`mahane` → `fundamentals.monthly_activities`)
- `GET /api/CompanyNames` — identity (`miandore2` → `core.companies`) — see
  `COMPANY_IDENTITY_API_CONTRACT.md`

Public response contract is unchanged: same field names, ordering, units and
IDs. Canonical values are read for comparison only; the legacy result is
authoritative in LEGACY and SHADOW modes.

## Canonical read repositories (read-only)

| Method | Source | Notes |
| --- | --- | --- |
| `FinancialMetricsByLegacyCompanyID` | `fundamentals.financial_facts` + `financial_statements` + `ingestion.reports` | pivoted per company/period; `period_order=1` |
| `MonthlyActivitiesByLegacyCompanyID` | `fundamentals.monthly_activities` | per period |
| `FinancialMetricsByLegacyIDs` | same | **set-based**, fixes N+1 |
| `MonthlyActivitiesByLegacyIDs` | same | **set-based**, fixes N+1 |
| `CompanyNames` | `core.companies` | display/legal name |
| `IdentityByLegacyCompanyID` | `core.legacy_entity_map` + `core.companies` + `core.securities` | Company/Security identity |

Identity resolution is via `core.legacy_entity_map` only; no name-hash and no
fabricated entity. Unresolved identities surface as explicit legacy-only rows.

## Live SHADOW comparison (2026-09-25)

| Endpoint | legacy rows | canonical rows | matched | exact fields | expected diffs | unexpected | errors |
| --- | --- | --- | --- | --- | --- | --- | --- |
| SalesData | 310 | 252 | 252 | 1512 | 58 (`LEGACY_ONLY`) | **0** | 0 |
| SalesData2 | 428 | 384 | 384 | 1536 | 384 unit-presentation + 44 `LEGACY_ONLY` | **0** | 0 |

- `EXPECTED_UNIT_PRESENTATION`: canonical `sales_amount_rial` (IRR) vs legacy
  `Value3` (million IRR) — documented unit difference, not a defect.
- `LEGACY_ONLY`: companies with no canonical identity (scope exclusion /
  alias-only), documented in `UNMAPPED_LEGACY_NAMES.md`.
- Machine-readable: `output/fundamentals_shadow_comparison.csv`.

## N+1 and performance

Before: the fundamentals shadow path issued **one canonical query per company**
(`for _, id := range ids { ...ByLegacyCompanyID(...) }`), an N+1 pattern.

Fix: `FinancialMetricsByLegacyIDs` / `MonthlyActivitiesByLegacyIDs` resolve the
whole bounded cohort in a single indexed query per domain, using
`lem.legacy_key = ANY(string_to_array($1, ','))` and `DISTINCT` to neutralise
multi-row legacy mappings. The per-company methods remain for the symbol page.

Latency (shadow, bounded cohort):

| Endpoint | legacy ms | canonical ms |
| --- | --- | --- |
| SalesData | 99.9 | 71.5 |
| SalesData2 | 39.9 | 32.9 |

Canonical is now at or below legacy latency on both fundamentals endpoints. No
cache was added; only the SQL pattern changed.

## LEGACY_ONLY field decision

`Product1/2/3` (and SalesData2 `value1/2/3`) have no canonical equivalent and are
`CLIENT_UNUSED`. See `LEGACY_FIELD_USAGE_AUDIT.md`. The client only needs the
derived `percentage`/`wow` presentation fields; defining those canonically is the
pre-condition for a future fundamentals cutover.

## Presentation contract (Phase 9)

`percentage`/`wow` are now explicitly defined in
`FUNDAMENTALS_PRESENTATION_CONTRACT.md` and implemented as the pure function
`integration.MonthlyPresentation` (SalesData2). `SalesData` `percentage` remains a
`LEGACY_HEURISTIC` with a pending canonical replacement decision. `Product1/2/3`
are deprecated compatibility-only and `CLIENT_UNUSED`.

Canary readiness: **SalesData2 canary-ready** (0 unexpected, defined
presentation, set-based reads). **SalesData not canary-ready** (income-statement
presentation undefined).

## Tests

- Set-based and per-company reads: unit tests via `fakeSource`.
- Shadow isolation on canonical failure, unit presentation, canonical-only
  allowance, NULL/date identity, score-version selection: `integration` package.
- Static guards: no writes, no legacy heuristics, no analytics formula
  duplication.
- `go build`, `go vet`, `go test` green.
