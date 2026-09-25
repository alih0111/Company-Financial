# MONTHLY AUTHORITY REPORT (Part B)

MONTHLY_ACTIVITY promoted to canonical-primary (shadow), reversible. Part A
market soak passed first, so promotion was allowed. SQL Server retained as
mirror; FINANCIAL_STATEMENT/CODAL unchanged.

## 1. Configuration

`CDF_MONTHLY_INGESTION_AUTHORITY=canonical`, `CDF_MONTHLY_FALLBACK_LEGACY=true`,
`CDF_INGESTION_MODE=dual_write`. Wired in `MianSql2.save_report_to_sql`
(canonical-first via `_legacy_insert` closure used as mirror/fallback).

## 2. Real cycles (`monthly_authority_cycles.csv`)

12 cycles over 3 companies × 2 periods × 3 rounds:

| Company | kind | outcome |
| --- | --- | --- |
| قاسم | repeated | `CANONICAL_SUCCESS_LEGACY_SUCCESS` |
| چکاپا | sparse | `CANONICAL_SUCCESS_LEGACY_SUCCESS` |
| شکیمیا | legacy-only/identity | `quarantined` (correct) |

Inserted **0**, skipped **48** (existing periods; idempotent). Second execution
of the same source created no duplicate canonical monthly data.

## 3. Unit reconciliation (`monthly_authority_reconciliation.csv`)

`EXPECTED_UNIT_CONVERSION` 4 (Value3 million_rial → `sales_amount_rial` ×1e6,
production/sales quantities exact); `CANONICAL_MISSING`, `IDENTITY_MISMATCH`,
`NUMERIC_MISMATCH`, `DATE_MISMATCH`, `WRITE_ERROR`, `UNCLASSIFIED` = **0**.

## 4. Mirror results

Legacy mirror success in all normal cycles. Mirror-failure injection:
`CANONICAL_SUCCESS_LEGACY_MIRROR_FAILED`, canonical status **written**
(authoritative) preserved, health `DEGRADED_LEGACY_MIRROR`.

## 5. Failure injection

| Scenario | Result |
| --- | --- |
| PostgreSQL unavailable | `CANONICAL_FAILED_LEGACY_FALLBACK_USED`; retry queued |
| SQL Server mirror failure | `CANONICAL_SUCCESS_LEGACY_MIRROR_FAILED` (canonical authoritative) |
| Unresolved identity | `quarantined` + DQ; health `IDENTITY_QUARANTINE` |
| Canonical constraint failure | covered by canonical rollback tests (`test_canonical_ingest_db`) |

## 6. Retry behavior

Pending `monthly_activity` retries replayed from the shared
`canonical_retry_manifest.jsonl` (re-read legacy `mahane`, canonical-only write,
marked done) → `retry_backlog=0`. Same retry system as market (generalized by
domain), no second system.

## 7. Freshness (`monthly_authority_freshness.json`)

`authority=CANONICAL`, latest source period `1405/06/31`, latest canonical period
present, canonical rows 12,075, mirror active, retry backlog 0, quarantine count
(monthly-domain, classified: legacy-only/`شکیمیا` + deliberate injection
`__unknown_id__`), health `IDENTITY_QUARANTINE`.

## 8. Go read-path end-to-end

Go canonical fundamentals read (`cmd/shadowcheck` → `MonthlyActivitiesByLegacyCompanyID`)
for افق/چخزر/چکاپا/دکپسول/شخارک/شکیمیا: all matched/expected with **0
unexpected** — the Go canonical monthly read sees the canonical data. No endpoint
rollout change.

## 9. Analytics visibility

Canonical monthly rows visible via `fundamentals.monthly_activities`; existing
score runs not overwritten.

## 10. Other domains

MARKET remains canonical-primary; FINANCIAL_STATEMENT and CODAL authority
unchanged (no global cutover).

## 11. Gate

**`MONTHLY_CANONICAL_AUTHORITY_READY`**
Routine-use: **`MONTHLY_CANONICAL_PRIMARY_READY_FOR_ROUTINE_USE`**
