# MONTHLY AUTHORITY SPEC — MONTHLY_ACTIVITY canonical-primary

## 1. Scope

MONTHLY_ACTIVITY only. FINANCIAL_STATEMENT and CODAL remain unchanged.
MARKET_PRICE stays canonical-primary. No global `CDF_INGESTION_MODE` change.

## 2. Configuration

| Env | Values | Default |
| --- | --- | --- |
| `CDF_MONTHLY_INGESTION_AUTHORITY` | `legacy` \| `canonical` | `legacy` |
| `CDF_MONTHLY_FALLBACK_LEGACY` | `true` \| `false` | `true` |

Canonical authority implies canonical writes (DSN required); global mode is not
reinterpreted.

## 3. Semantics

```
Codal monthly activity -> legacy parser semantics -> canonical identity resolution
  -> canonical normalization -> canonical PostgreSQL transaction (AUTHORITATIVE)
  -> SQL Server write/mirror retained -> reconciliation
```

Outcomes: `CANONICAL_SUCCESS_LEGACY_SUCCESS`,
`CANONICAL_SUCCESS_LEGACY_MIRROR_FAILED`,
`CANONICAL_FAILED_LEGACY_FALLBACK_USED`, `CANONICAL_FAILED`. Canonical failure is
never reported as healthy ingestion.

## 4. Contract

`fundamentals.monthly_activities`; Value1→production_quantity,
Value2→sales_quantity, Value3→sales/revenue; Value3 million_rial →
`sales_amount_rial` = Value3 × 1e6 (IRR). No scale guessing. No duplicate
company/period rows (logical dedup + `ON CONFLICT (parse_run_id)`). Identity via
`canonical_ingest.identity`; unresolved → quarantine, no fake entity.
Report/version/parse lineage reused; raw payload path available; no invented
source versions.

## 5. Freshness / health

`output/monthly_authority_freshness.json`: authority, latest source period,
latest canonical period, canonical rows, mirror state, retry backlog, quarantine
count, health (`HEALTHY`, `DEGRADED_LEGACY_MIRROR`, `CANONICAL_BEHIND`,
`CANONICAL_ERROR`, `IDENTITY_QUARANTINE`).

## 6. Rollback (one flip)

`CDF_MONTHLY_INGESTION_AUTHORITY=legacy` — restores legacy-authoritative +
canonical secondary. Config-only; no data/code/schema change.
