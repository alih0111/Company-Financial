# MONTHLY ROUTINE SOAK REPORT (Part A)

Routine MONTHLY_ACTIVITY canonical-primary soak, `CDF_MONTHLY_INGESTION_AUTHORITY=canonical`,
SQL Server mirror enabled, real `mahane` data (قاسم/چکاپا/شکیمیا).

| Metric | Value |
| --- | --- |
| cycles | 16 |
| genuinely new monthly inserts | **0** (source unchanged; reported explicitly, not fabricated) |
| canonical skipped (idempotent) | rest |
| reconciliation | `EXPECTED_UNIT_CONVERSION` 4, mismatches **0** |
| mirror | success |
| retry backlog | **0** |
| health | **HEALTHY** |
| latest source period | 1405/06/31 (caught up) |
| quarantines | شکیمیا classified (legacy-only scope exclusion) |

No NUMERIC_MISMATCH / DATE_MISMATCH / IDENTITY_MISMATCH / MISSING_CANONICAL /
WRITE_ERROR / UNCLASSIFIED. Value1/Value2 quantities exact; Value3 million_rial →
`sales_amount_rial` ×1e6. Artifact `output/monthly_routine_soak.csv`.

## Gate: `MONTHLY_ROUTINE_SOAK_PASS`
