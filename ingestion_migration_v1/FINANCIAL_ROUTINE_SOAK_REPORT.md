# FINANCIAL ROUTINE SOAK REPORT (Part A)

Routine FINANCIAL_STATEMENT canonical-primary soak,
`CDF_FINANCIAL_INGESTION_AUTHORITY=canonical`, SQL Server mirror enabled, real
`miandore2` data (تاصیکو/قاسم/کسرا/چکاپا).

| Metric | Value |
| --- | --- |
| cycles | 24 |
| genuinely new source reports | **0** (source unchanged; reported, not fabricated) |
| canonical inserted | 0 (statements/facts reused) |
| reconciliation | `EXACT_EQUIVALENT` 40, `EXPECTED_UNIT_CONVERSION` 127, mismatches **0** |
| mirror | success |
| retry backlog | **0** |
| health | **HEALTHY** |

No NUMERIC_MISMATCH / DATE_MISMATCH / MISSING_CANONICAL / WRITE_ERROR /
UNCLASSIFIED. Report/version/parse lineage reused; monetary IRR and EPS
rial_per_share correct; period_order/period linkage correct; idempotent.
Artifact `output/financial_routine_soak.csv`.

## Gate: `FINANCIAL_ROUTINE_SOAK_PASS`
