# Report-Chain TTM (Class-B recovery) — Report

Canonical-only implementation. No SQL Server, legacy CSV, `compat_v37`, v3.7
oracle, `Product1`, `NPUnitRatio`, `OpK`, `OpAmt`, or scale guessing in the runtime
path. SQL Server remained SELECT-only. No factor weights changed.

## 1. Implementation

* `report_chain_ttm.py` — pure canonical helper (`direct_ttm`, `chain_ttm`,
  `resolve_ttm`, `chain_legs`) with machine-readable flow sets.
* `compute_metrics.py` — TTM resolution order now **A direct canonical → B
  report-chain → C NULL + provenance**; provenance recorded per metric in
  `_ttm_prov`.
* `report_chain_ttm_spec.md`, `metric_spec.json` (`flow_types`), `data_quality.py`
  (provenance severities), `tests/test_report_chain_ttm.py`.

## 2. Exact contract

```
m != 12:  TTM(t, m) = FY(t-1, 12M) + YTD(t, m) - YTD(t-1, m)
m == 12:  TTM(t, 12) = YTD(t, 12)
```

Each leg is a canonical fact `period_order = 1` (company, metric_code, statement
scope identical); periods matched via canonical `period_end_date` →
`(fiscal_year, fiscal_month)`; row adjacency never assumed. Stock metrics
(`total_assets`, `current_assets`, `total_liabilities`, `current_liabilities`,
`total_equity`) are `STOCK_POINT_IN_TIME` and are **never** chained.

## 3. PIT behavior

The report index is built only from statements already filtered by the run's
`source_cutoff_at`/`as_of_date` (reports with `published_at` use the cutoff; legacy
synthetic reports use `period_end_date <= as_of`); superseded reports are excluded.
A corrected/future report cannot enter an earlier run. Test
`test_pit_cutoff_excludes_future_reports` proves no report after `as_of` reaches the
index; `test_superseded_reports_excluded` proves superseded reports do not win.

## 4. Recovered count and coverage before/after

| metric | before present | after present | recovered |
| --- | --- | --- | --- |
| `operating_profit_ttm` | 128 | **257** | **129** (`REPORT_CHAIN_TTM`) |
| `operating_profit_growth` | 39 | **237** | 198 |
| `eps_ttm` | 258 | 264 | 6 |
| `revenue_ttm` | 99 | 101 | 2 |
| `net_profit_ttm` | 99 | 99 | 0 |
| `operating_margin` | 99 | 101 | 2 |
| `ocf_ttm` (now exposed) | — | 99 | — |

`operating_profit_ttm` provenance: **128 `DIRECT_CANONICAL` (unchanged) + 129
`REPORT_CHAIN_TTM`**.

### Audit hypothesis vs actual

Audit predicted ~136 Class-B `operating_profit` cases; actual recovered = **129**.
The difference is explained, not forced: 7 remaining cases are
`MISSING_PRIOR_ANNUAL` — companies with **no month‑12 annual report** in canonical
(non-Esfand fiscal years: بکهنوج، بگیلان، شلیا، شمس، فخوز، فپنتا، قلرست). The
audit over-counted because it aggregated `period_order` across duplicate reports and
did not apply the engine's PIT/latest-cell selection; the engine correctly returns
NULL for a genuinely absent annual leg. 3 further cases have no `operating_profit`
fact at all.

## 5. Downstream impact (no factor/weight changes)

* `changed-while-non-NULL` by metric: `growth_score` 237, `valuation_score` 226,
  `quant_score` 260, `profitability_score` 107.
* **No previously non-NULL TTM/base metric changed value** — only population-wide
  percentile ranks and the category/QuantScore aggregates shifted as coverage grew.
* `quant_score` mean/median: 33.58/32.17 → **34.12/33.04**.
* `operating_margin` mean/median: 27.49/29.95 → 28.17/29.95 (limited by missing
  `revenue`).

## 6. Oracle comparison (explanation only — no parity goal)

`output/oracle_comparison.md` re-run: `BUG_SUSPECTED = 0`.
`PEApprox` `LEGACY_HEURISTIC_REMOVED` 6 → 0 (EPS chain recovered);
`OperatingMargin12M` `MISSING_CANONICAL_DATA` 43 → 41 (further limited by missing
revenue). The v3.7 oracle golden hash is **unchanged**
(`849a4efd49711101eb5e29c719d8c233efa0d7e6c928d47b21882540cbbac264`).

## 7. Score run

New append-only run with `score_version = canonical-v1-dev`,
`code_version = canonical-v1-dev+report-chain-ttm`,
`parameters.implementation_revision = report-chain-ttm-v1`. Prior runs preserved.

## 8. Remaining missing-data classes

* `SOURCE_ABSENT` (unchanged): revenue/net_profit/balance-sheet for ~140–165
  companies — legacy amount/balance columns never populated; keep NULL + DQ.
* `MISSING_PRIOR_ANNUAL` (7 `operating_profit`): non-Esfand fiscal years.
* `INSUFFICIENT_TTM_PERIODS` / `MISSING_PRIOR_COMPARABLE`: small.
* `POLICY_EXCLUSION` / `IDENTITY_MAPPING_GAP`: population only.

## 9. Gate

# REPORT_CHAIN_TTM_PASS

Broader analytics gate unchanged: **CANONICAL_V1_NEEDS_DATA_WORK** (large
`SOURCE_ABSENT` remains; not promoted).
