# Exact v3.7 Compatibility Debugging — Progress Report

Read-only SQL Server diagnostics + canonical shadow analysis. No production
DB/code, no SQL Server writes, no canonical fact modifications.

## 1. Handoff vs repository verification

| claim | evidence | verdict |
| --- | --- | --- |
| 276 reference rows, 94 cols, ScoreVersion v3.7 | `reference_context.json`, snapshot | CONFIRMED |
| 282 TrackedTickers | live `SELECT COUNT(*)` = 282 | CONFIRMED |
| shadow 273 companies / 273 securities | live count | CONFIRMED |
| canonical inputs 12,004 monthly / 71,361 facts / 705,812 prices | live counts match `full_universe_migration_validation.md` | CONFIRMED |
| production view = repo snapshot | `OBJECT_DEFINITION(dbo.vw_AIStockMetrics)` normalized-diff vs `canonical_design_inputs/sql/vw_AIStockMetrics_production.sql` | **IDENTICAL** |
| gate ANALYTICS_PARITY_FAIL | reproduced | CONFIRMED |

### Discrepancies found

1. **`analytics_parity/_comparison_summary.json` is stale/inconsistent.**
   All 9 metrics carry identical stats `(exact=171, within=86, mismatch=16,
   max_abs=2813.5779…)`, which is impossible and contradicts both
   `metric_comparison.md` and `comparison_data/comparison_metrics.csv`
   (e.g. SalesLast12M = 83 exact / 190 mismatch). The raw CSV is authoritative;
   the JSON should be treated as corrupt/overwritten.
2. `SESSION_HANDOFF.md` §15 lists untracked dirs but omits `SESSION_HANDOFF.md`
   itself (also untracked). Cosmetic.

## 2. Population reconciliation (see `POPULATION_RECONCILIATION.md`)

* v3.7 population = `distinct CompanyID` in `mahane ∪ miandore2` (`CompanyList`),
  **not** `TrackedTickers` and independent of price availability → **276**.
* canonical universe = `TrackedTickers ∩ MarketPriceHistory` → **273**.
* 5 v3.7 companies have no price rows (خبهن، خاهن، شکیمیا، ولشرق، شخارک).
* 2 canonical companies are funds absent from v3.7 (مثقال، یاقوت).
* ⇒ rank denominators differ; exact rank/QuantScore parity is impossible until
  the compat population equals the 276 v3.7 subjects.

## 3. Root causes identified and FIXED

| # | root cause | fix | file |
| --- | --- | --- | --- |
| 1 | absolute monetary metrics compared canonical **rial** vs v3.7 **million rial** | divide monetary `canonical_value` by 1e6 | `compute_v37_faithful.py` |
| 2 | compat returned `d[1]` when p2/p3 missing (over-populated TTM) | exact v3.7 TTM: amount path → Product1 path → NULL | same |
| 3 | facts read across all statements nondeterministically | select latest report (`max period_end_date`) matching `ProfitDedup rn=1` | same |
| 4 | wrong share count `capital/1000` | `shares = capital/1e6` (= legacy `Num2_Value1`) / `ImpliedShares = Product1/EPS` | same |
| 5 | `LatestPrice = closing` only | `LatestPrice = COALESCE(last_price, closing_price)` | same |
| 6 | `OperatingProfitNew` per-share not normalized | `OpK`/`OpAbs`/`OpAmt` heuristics ported | same |
| 7 | volatility returns computed with wrong `LAG` direction | DESC-ordered `LAG` uses the **more recent** row; window is rn 2..30 | same |
| 8 | growth rank fallbacks missing | all 3 `OperatingProfitGrowthTTM` branches ported | same |

## 4. Parity before → after (273 common symbols)

| metric | reduced compat mismatch | faithful compat mismatch | faithful exact+within |
| --- | --- | --- | --- |
| SalesLast12M | 190 | **0** (273 exact) | 273 |
| SalesPrev12M | 190 | **0** (273 exact) | 273 |
| SalesGrowth12M | 3 | **0** | 273 |
| TTMNetProfit | 257 | 8 | 265 |
| OperatingMargin12M | 136 | **0** | 273 |
| NetProfitMargin12M | 18 | **0** | 273 |
| ROE | 16 | **0** | 273 |
| PEApprox | 241 | 7 | 266 |
| QuantScore | 273 | 250 (11 exact, 12 within) | 23 |

Rank-factor parity (v3.7 rank columns) after fixes:

* Reproduced to ≤0.01 for: SalesGrowth, SalesGrowth3M, RevenueGrowth,
  OperatingMargin, OperatingProfitGrowth (261/273), LowVolatility (266/273),
  Momentum, Stability, PS, PB, InterestCoverage.
* Remaining large: NetProfitGrowth (111), PE (97), MarginTrend (24),
  CashConversion (19), CurrentRatio (14).

## 5. Remaining blockers (ranked)

1. **Population (276 vs 273).** Produces ~2 mismatches/factor even for perfectly
   reproduced factors. Must align compat population to the 276 v3.7 subjects
   (migrate the 5 real no-price companies into the shadow; exclude the 2 funds),
   or compute ranks over the reference population.
2. **Legacy `Product1` not migrated (by design).** 8–9 companies take v3.7's
   Product1 fallback for `TTMNetProfit`/`PEApprox`/`NetProfitGrowth`. `Product1`
   is an independent legacy column and is **not** always `EPS×Num2_Value1`
   (Num2_Value1 itself has mixed scale across some reports), so it cannot be
   reconstructed exactly from canonical facts. These are legitimately
   `LEGACY_DERIVED_NOT_MIGRATED`, not an arithmetic bug.
3. **`NetProfitGrowthTTM`** depends on `NPUnitRatio`, whose anchors use the same
   Product1 → inherits blocker 2 for those companies.
4. **PE rank** inherits blockers 1–2 (invalid sentinel vs valid values).
5. Small residual rank offsets for CashConversion / CurrentRatio / MarginTrend /
   ROE likely from `ROUND(...,4)` + population tie-boundary effects.

## 6. Recommended next step

Align the compat population with v3.7 before further factor debugging:

* migrate the 5 v3.7-only companies (real mahane/miandore2 data, no price) into
  `company_financial_analytics_shadow_v121` (additive; no existing canonical
  facts changed); and
* restrict the compat rank population to v3.7 membership (drop the 2 funds), or
  treat the 2 funds as out-of-population.

This is the prerequisite for any exact rank/percentile/QuantScore parity.
