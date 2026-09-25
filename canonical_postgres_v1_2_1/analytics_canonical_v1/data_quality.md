# Canonical v1 — Data Quality Model

Data quality is computed from canonical sources and the run's
`source_cutoff_at`/`as_of_date`. It never uses a runtime clock or legacy heuristics.

## Flags

| flag | severity | trigger | effect on metric | effect on eligibility | penalty / fallback |
| --- | --- | --- | --- | --- | --- |
| `unresolved_identity` | critical | no security with external id / no legacy map | all metrics NULL | **exclude** company | none (excluded) |
| `missing_current_financials` | high | no eligible income_statement at cutoff | TTM metrics NULL | keep if monthly data exists | factor neutral |
| `stale_financials` | medium | latest report age > `stale_financial_months` (default 8) | metrics computed | keep | DQ penalty |
| `stale_market_data` | medium | `cutoff - max(trade_date) > stale_days` (default 14) | market metrics computed | keep | DQ penalty |
| `missing_price` | high | primary security has no eligible observation | market metrics NULL | keep | market factor neutral / "no data" rank |
| `missing_monthly_activity` | medium | < `min_monthly_records` | sales metrics NULL | keep if financials exist | factor neutral |
| `unknown_quantity_unit` | low | `monthly_activities.quantity_unit IS NULL` | quantity metrics NULL | keep | informational |
| `insufficient_history` | medium | below a metric's `min_history` | that metric NULL | keep | factor neutral |
| `missing_comparable_period` | medium | TTM prior comparable missing | TTM metric NULL | keep | factor neutral |
| `low_confidence_corporate_action` | low | unconfirmed heuristic corporate action affects price | market metrics flagged | keep | DQ penalty |
| `unknown_unit` | high | `canonical_unit` missing/unexpected for a fact | affected metric NULL | keep | factor neutral |

## DataQualityScore (prototype)

A transparent 0..1 score computed from the flags above (coverage + freshness
components), replacing v3.7's `GETDATE()`-based score. Exact component weights are
marked `NOT VALIDATED FOR CANONICAL V1` and live in `compute_metrics.py`.

## TTM provenance (report-chain)

Per-metric TTM provenance is recorded in the run output (`_ttm_prov`), using the
shared codes: `DIRECT_CANONICAL`, `REPORT_CHAIN_TTM`, `INSUFFICIENT_TTM_PERIODS`,
`MISSING_PRIOR_ANNUAL`, `MISSING_PRIOR_COMPARABLE`, `NON_COMPARABLE_PERIOD`,
`PIT_UNAVAILABLE` (see `report_chain_ttm_spec.md`). Missing prior legs also raise
`missing_comparable_period`. Each recovered value is explainable down to its
`(latest YTD, prior annual, prior comparable YTD)` canonical cells.

## Emission

Flags are emitted to `metric_snapshots.details` (per metric) and to the run's
`parameters`/`company_scores.details`. Optionally mirrored to
`ingestion.data_quality_issues` in a future phase; this phase does not write there.
