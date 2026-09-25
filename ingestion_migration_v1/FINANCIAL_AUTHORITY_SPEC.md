# FINANCIAL AUTHORITY SPEC — FINANCIAL_STATEMENT canonical-primary

## 1. Scope

FINANCIAL_STATEMENT only. MARKET_PRICE and MONTHLY_ACTIVITY stay canonical-primary;
CODAL unchanged. No global-mode change.

## 2. Configuration

| Env | Values | Default |
| --- | --- | --- |
| `CDF_FINANCIAL_INGESTION_AUTHORITY` | `legacy` \| `canonical` | `legacy` |
| `CDF_FINANCIAL_FALLBACK_LEGACY` | `true` \| `false` | `true` |

## 3. Semantics

```
source/report -> existing parser -> canonical identity resolution
  -> report/version/parse lineage -> canonical financial statement/facts transaction (AUTHORITATIVE)
  -> SQL Server retained as mirror -> reconciliation
```

Outcomes: `CANONICAL_SUCCESS_LEGACY_SUCCESS`, `CANONICAL_SUCCESS_LEGACY_MIRROR_FAILED`,
`CANONICAL_FAILED_LEGACY_FALLBACK_USED`, `CANONICAL_FAILED`, `QUARANTINED_IDENTITY`.
Canonical failure is never reported healthy.

## 4. Targets / facts

`ingestion.reports`, `ingestion.report_versions`, `ingestion.parse_runs`,
`fundamentals.financial_statements`, `fundamentals.financial_facts`, and
`raw.report_payloads` where a source payload exists. Only canonical metrics
(revenue, operating_profit, net_profit, capital, eps, finance_cost,
other_non_operating, balance-sheet/cash-flow metrics) are written.
Product1/2/3, NPUnitRatio, OpK, OpAmt are never written (asserted in the hook).

## 5. Units / periods

monetary → IRR (`canonical_value = reported_value × 1e6` for million_rial);
EPS → rial_per_share; no scale guessing. Period linkage uses explicit
`period_end_date`, `period_order`, `comparison_type`; no row adjacency.

## 6. Versioning

same content → no new report_version; changed content → new report_version;
parser rerun → new parse_run (no fake source version); corrected reports use
supersession.

## 7. Freshness / health

`output/financial_authority_freshness.json`: authority, latest source report,
latest canonical period/write, statements, mirror state, retry backlog,
quarantine count, health (`HEALTHY`, `DEGRADED_LEGACY_MIRROR`, `CANONICAL_BEHIND`,
`CANONICAL_ERROR`, `IDENTITY_QUARANTINE`, `PARSER_ERROR`).

## 8. Rollback (one flip)

`CDF_FINANCIAL_INGESTION_AUTHORITY=legacy` — legacy-authoritative + canonical
secondary. Config-only; SQL Server retained.
