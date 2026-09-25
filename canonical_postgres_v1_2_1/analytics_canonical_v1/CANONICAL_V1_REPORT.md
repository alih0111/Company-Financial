# Canonical Analytics v1 — Decision Report

Score version: `canonical-v1-dev`. Canonical-only (core, ingestion, fundamentals,
market). No SQL Server, no legacy frozen inputs, no `Product1`/`NPUnitRatio`/`OpK`/`OpAmt`,
no `compat_v37`. `baseline_weights_v37` used as prototype only
(`NOT VALIDATED FOR CANONICAL V1`).

Run context: `as_of_date = 2026-09-24`, `source_cutoff_at = 2026-09-24T20:41:02+00:00`.
Stored as `analytics.score_runs.score_version = 'canonical-v1-dev'` (run
`6bd0efed-6e34-4e68-8af1-ed1fd03567f4`) alongside the existing `v3.7-compat` run.
Reproducibility hash: `138383172f57589558ce1c1392b91c3ac64c6a6b6881e11821794c1c05ec14b4`
(identical across reruns).

## 1. Population

| population | count |
| --- | --- |
| v3.7 oracle (legacy `mahane ∪ miandore2`) | 276 |
| **canonical v1** (income statement OR ≥6 monthly, active, resolved) | **267** |
| intersection (mapped via `core.legacy_entity_map`) | 267 |

Differences vs 276 are **not a bug**: 5 legacy subjects have no canonical company
(migration gap), and the 2 funds are excluded by policy (no fundamentals). See
`population_spec.md`; classifications `POPULATION_POLICY_CHANGE` /
`MISSING_CANONICAL_DATA` in `output/oracle_comparison.md`.

## 2. Metric coverage / missing-data rates (267 subjects)

| metric | present | missing | missing % | notes |
| --- | --- | --- | --- | --- |
| eps_ttm | 258 | 9 | 3.4% | good |
| pe | 258 | 9 | 3.4% | good |
| price_momentum_30d | 259 | 8 | 3.0% | good |
| volatility_30d | 267 | 0 | 0.0% | good |
| avg_trade_value_30d | 267 | 0 | 0.0% | good |
| sales_ttm | 184 | 83 | 31.1% | no monthly rows |
| sales_growth_12m | 181 | 86 | 32.2% | needs 24 records |
| operating_profit_ttm | 128 | 139 | 52.1% | legacy `OperatingProfitNew` often NULL |
| revenue_ttm | 99 | 168 | 62.9% | **legacy `RevenueNew` often NULL** |
| net_profit_ttm | 99 | 168 | 62.9% | **legacy `NetProfitAmount` often NULL** |
| net_margin / operating_margin / roe | 99 | 168 | 62.9% | depend on TTM |
| current_ratio / debt_ratio | 102 | 165 | 61.8% | balance-sheet facts sparse |
| ps | 95 | 172 | 64.4% | depends on net margin |

Root cause: the canonical migration mapped monetary amount facts from legacy
columns (`NetProfitAmount`, `RevenueNew`, balance-sheet columns) that are NULL in
most historical `miandore2` rows. This is a **data-ingestion backfill** problem,
not a model defect. `eps_ttm` (which mapped a reliably-present legacy column) has
97% coverage, confirming the engine itself is sound.

## 3. Legacy heuristic removals

`legacy_removal_matrix.md`. Canonical v1 contains none of: `Product1/2/3`,
`Num1_Value*`, `Num2_Value*`, `NPUnitRatio`, `OpK`, `OpAmt`, `OpAbs`, legacy TTM
product path, `GETDATE()` staleness. TTM uses canonical `period_order`
(`current`/`prior_year_same_period`/`prior_fiscal_year`); units are canonical IRR /
rial_per_share; no scale detection.

## 4. Major differences vs v3.7 (`output/oracle_comparison.md`)

* **BUG_SUSPECTED total: 0.**
* `SalesLast12M`: 184 `CANONICAL_UNIT_FIX` (canonical IRR vs oracle million-IRR),
  81 `SAME`, 2 missing.
* `ROE`, `NetProfitMargin12M`, `SalesGrowth12M`: 263–267 `SAME`.
* `TTMNetProfit`: 99 `CANONICAL_UNIT_FIX`, 158 `LEGACY_HEURISTIC_REMOVED`
  (oracle used `Product1`/`NPUnitRatio`; canonical correctly returns NULL),
  10 `SAME`.
* `PEApprox`/`PERank`, `NetProfitGrowthRank`, `OperatingMarginRank`: `FORMULA_CHANGE`
  where the oracle's legacy EPS/operating-profit path was removed.
* `OperatingMargin12M`: 222 `SAME`, 43 `MISSING_CANONICAL_DATA`, 2 formula.

## 5. Factor review status

All 21 factors reviewed (`factor_review.md`): 10 `KEEP_CANONICAL` (mostly ratios
already unit-free), 11 `KEEP_WITH_NEW_FORMULA` (formula re-expressed on canonical
facts), 0 `REMOVE`. The factor set is retained; only input construction changed.
Weights: `baseline_weights_v37` prototype, `NOT VALIDATED FOR CANONICAL V1`.

## 6. Metrics needing further work

1. `revenue_ttm`, `net_profit_ttm`, `operating_profit_ttm` — need amount-fact
   backfill (data work).
2. `current_ratio`, `debt_ratio` — need balance-sheet fact backfill.
3. `sales_ttm`/`sales_growth_12m` — need monthly coverage for income-only companies.
4. `eps_ttm` — currently uses canonical `eps` TTM; confirm treatment when `eps`
   period columns are sparse (coverage high, but verify edge cases).
5. `operating_margin`/`roe` inherit blocker 1.

## 7. Data quality

Flag model in `data_quality.md` / `data_quality.py`; `DataQualityScore` is a
prototype (component weights `NOT VALIDATED FOR CANONICAL V1`). Flags emitted per
company in `analytics.company_scores.details`.

## 8. Known limitations

* Prototype weights are unvalidated.
* Historical amount/balance-sheet facts are sparse in canonical (migration gap).
* `fiscal_year`/`fiscal_month` are NULL on canonical statements; the engine derives
  them from `period_end_date` (documented proxy). A future ingestion improvement
  should populate them.
* PIT for legacy synthetic reports uses `period_end_date <= as_of` because their
  `published_at` is NULL; reports with known `published_at` use the cutoff.

## 9. Tests

`tests/test_canonical_v1.py` — 7 passed:
no SQL Server / legacy dependency (tokenized source scan), units contract, TTM edge
cases, DQ score, deterministic run, population policy (funds excluded), PIT cutoff.

## 9b. Revision — Report-chain TTM (Class-B recovery)

Implemented canonical report-chain TTM (`report_chain_ttm.py`,
`report_chain_ttm_spec.md`), resolution order A direct → B chain → C NULL.
Updated coverage vs the pre-chain run:

| metric | before | after |
| --- | --- | --- |
| `operating_profit_ttm` | 128 | **257** (128 direct + 129 `REPORT_CHAIN_TTM`) |
| `operating_profit_growth` | 39 | 237 |
| `eps_ttm` | 258 | 264 |
| `revenue_ttm` | 99 | 101 |
| `net_profit_ttm` | 99 | 99 |
| `quant_score` mean/median | 33.58 / 32.17 | 34.12 / 33.04 |

No previously non-NULL TTM/base value changed. 7 `operating_profit` cases remain
`MISSING_PRIOR_ANNUAL` (non-Esfand fiscal years). Details:
`data_work/REPORT_CHAIN_TTM_REPORT.md`; gate **REPORT_CHAIN_TTM_PASS**.
The large `SOURCE_ABSENT` class is unchanged (legacy amount/balance columns absent).

## 10. Gate

# CANONICAL_V1_METRICS_READY

Rationale: canonical-only metrics are correct, reproducible, PIT-safe, and free of
legacy heuristics (BUG_SUSPECTED = 0; report-chain TTM `PASS`). The remaining
historical sparsity is genuine legacy source absence, explicitly accepted, with
deterministic neutral-factor scoring and DQ provenance
(`data_work/missing_data_contract.md`). The 5 no-canonical subjects are accepted
out-of-scope (`ACCEPTED_CANONICAL_SCOPE_EXCLUSION`); legacy population parity is not
required. See `CANONICAL_V1_READINESS.md`. Production Go API cutover is **not**
performed. Next major phase (not started): point-in-time backtesting framework.
