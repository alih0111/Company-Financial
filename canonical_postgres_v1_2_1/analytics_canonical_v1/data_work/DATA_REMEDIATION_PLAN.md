# Canonical Data Remediation Plan

No destructive/broad writes performed. This plan is ordered safest-first. It does
**not** reintroduce Product1, NPUnitRatio, OpK/OpAmt, scale guessing, or any legacy
heuristic into canonical data or canonical analytics.

## Findings that shape the plan

1. Canonical migration is faithful (`MIGRATION_NOT_IMPORTED = 0`).
2. Population difference is fully explained (5 identity gaps + 4 policy
   exclusions).
3. The large `revenue_ttm`/`net_profit_ttm`/balance-sheet gap is
   `SOURCE_ABSENT` in legacy columns — not a migration bug.
4. `operating_profit` TTM (and derived `operating_margin`) is recoverable from
   legitimate canonical prior reports (class B, 137 rows).
5. Non-null legacy monetary/balance coverage is ~102–127 of 267 companies; the
   remainder only ever existed as `Product1` (forbidden).

## Remediation options (A–E)

| class | definition | applies to |
| --- | --- | --- |
| A | source exists; migration/mapping can be corrected | 5 `IDENTITY_MAPPING_GAP` subjects |
| B | re-derive from legitimate canonical source fields | 137 `TTM_RECOVERABLE_REPORT_CHAIN` rows (mostly `operating_profit`) |
| C | source reports/raw can be re-ingested/re-parsed safely | 35 `INSUFFICIENT_TTM_PERIODS`; plus a bounded subset of `SOURCE_ABSENT` where a raw Codal report exists |
| D | historic source data genuinely does not exist | majority of `SOURCE_ABSENT` (~1,500 rows) |
| E | metric should remain NULL by canonical policy | 4 policy-excluded subjects; all missing facts stay NULL |

## Safest remediation order

> Status update: Step 1 is **DONE** (`REPORT_CHAIN_TTM_PASS`). Step 2 is
> **removed** (accepted scope exclusion, see below). Steps 3–5 are optional/later.

### Step 1 (B, no writes) — report-chain TTM  ✅ DONE
Add a canonical TTM variant that, when within-row prior columns are absent, joins
the prior reports from `fundamentals.financial_statements` /
`financial_facts` (current + `(FY-1, 12)` report − `(FY-1, same month)` report,
all `period_order = 1`). No legacy fields. Expected recovery: 137 rows
(≈136 `operating_profit`), improving `operating_profit_ttm`, `operating_margin`,
`operating_profit_growth`. Re-run canonical v1 and revalidate coverage.

### Step 2 — identity gaps: **NOT REQUIRED (accepted out-of-scope)**
The 5 legacy subjects (`خبهن`, `خاهن`, `شکیمیا`, `ولشرق`, `شخارک`) are classified
`ACCEPTED_CANONICAL_SCOPE_EXCLUSION`. Canonical population is intentionally allowed
to differ from v3.7. No migration is performed; no fake identities or market data
are created. **Removed from the required plan.**

### Step 3 (A, additive, PIT-aware) — confirm no migration losses
Re-check the 3-company deltas between legacy non-null column company counts and
canonical fact company counts for `revenue`/`net_profit`/balance (legacy→canonical
mapping). Audit says 0 `MIGRATION_NOT_IMPORTED`; confirm the deltas are only
companies not in the canonical universe, not lost values.

### Step 4 (C, scoped) — raw re-ingestion feasibility
For companies with `SOURCE_ABSENT` but a matching `ingestion.reports` /
`CodalReports` entry, evaluate re-parsing the original Codal report to populate
monetary/balance facts. `raw.report_payloads` is currently empty, so this requires
external re-fetch; feasible only for the small set of reports actually registered.
Do **not** synthesize values for the rest.

### Step 5 (D/E) — keep NULL + Data Quality
For genuinely unavailable history, keep canonical metrics `NULL` and rely on the
Data Quality model (`missing_current_financials`, `missing_comparable_period`,
`insufficient_history`). Do not backfill from `Product1`/`EPS × capital`.

## Guardrails

* SQL Server stays SELECT-only.
* Writes only to the shadow DB, only via additive migration; never overwrite
  `analytics.score_runs` rows.
* No legacy heuristic, no scale detection, no placeholder zeroes.
* Re-run `analytics_canonical_v1/tests` and the oracle golden test after each step.

## Expected ceiling

Even after Steps 1–2:
* `operating_profit`: ~264 companies available (from 128) — large gain.
* `revenue`/`net_profit`/balance-sheet: still limited to ~102–127 companies unless
  Step 4 raw re-ingestion succeeds broadly (currently unlikely). These remain
  `CANONICAL_DATA_SOURCE_LIMITED` in depth, though the model is correct.

## Proposed data-work gate

`CANONICAL_DATA_PARTIALLY_RECOVERABLE`

## Retained analytics gate

`CANONICAL_V1_NEEDS_DATA_WORK` (unchanged; remediation not yet executed).
