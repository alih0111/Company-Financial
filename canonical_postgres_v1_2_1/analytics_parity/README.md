# Analytics Parity (SQL Server v3.7 vs Canonical PostgreSQL v1.2.1)

Shadow DB: `company_financial_analytics_shadow_v121` (schema v1.2.1 + full universe).
Reference: `dbo.vw_AIStockMetrics` v3.7 snapshot (READ ONLY), algorithm source =
`canonical_design_inputs/sql/vw_AIStockMetrics_production.sql` (repo v3.6 NOT used).

## Frozen time
- `captured_at` = `analysis_cutoff_at` = `2026-09-24T20:41:02Z`
- `analysis_as_of_date` = `2026-09-24`
- `reference_context.json`

## Artifacts
| file | content |
| --- | --- |
| `reference/v37_full_snapshot.csv` | کل خروجی ۹۴ ستونه v3.7 (276 ردیف) |
| `universe_manifest.csv` | universe explicit (282 symbol, include/exclude/reason) |
| `full_universe_migration_validation.md` | canonical inputs parity → FULL_UNIVERSE_INPUTS_PASS |
| `metric_comparison.md` | مقایسه dot‌به‌دات metricها |
| `factor_comparison.md` | وضعیت بازتولید فاکتورها |
| `quantscore_comparison.md` | مقایسه QuantScore |
| `population_validation.md` | population rank |
| `legacy_heuristics.md` | audit heuristicهای legacy |
| `tolerances.md` | toleranceها |
| `reproducibility.md` | determinism (hash) |
| `point_in_time_safety.md` | cutoff |
| `issues.md` | مسائل و classification |
| `company_traces/*.md` | trace ۸ شرکت pilot |
| `comparison_data/*.csv` | داده‌ی خام مقایسه |
| `_stored_score_run.txt` | score_run ثبت‌شده در schema `analytics` (shadow) |

## Tooling (`../analytics_v37_compat/`)
`snapshot_reference.py`, `build_universe_manifest.py`, `full_universe_validate.py`,
`compute_and_compare.py`, `gen_reports.py`.

## Status
canonical inputs parity PASS؛ اما analytics parity کامل نشد: `FINAL_ANALYTICS_PARITY_REPORT.md`.


## Secret Safety
- ??? connection string/password/token ??????? ???? ?? ????????/CSV?? ????? ???? credential ??? ?? ???? ???? ?? `.env` ?????? ??.
- ????? substring ?? **false positive** ???: `DB_PASSWORD` ?? ??? ????? ??? ?? ?????? ?????? ???? ????? ???? CSV?? (snapshot/reference) ???? ??????. ??? ?? ????? ?????? ??? ?????? ???? ???? ?? ??????? credential.
