# Canonical v1 — Factor Review (KEEP / REPLACE / REMOVE)

Review of the 21 v3.7 factors. Status vocabulary: `KEEP_CANONICAL`,
`KEEP_WITH_NEW_FORMULA`, `REPLACE`, `REMOVE`, `NEEDS_RESEARCH`. No new weights are
decided here.

| # | v3.7 factor | weight | status | v3.7 behaviour | rationale | canonical formula / required data |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | SalesGrowth12M | 10 | `KEEP_CANONICAL` | `(last12-prev12)/abs(prev12)` on monthly sales | economically meaningful | same, from `monthly_activities.sales_amount_rial` |
| 2 | SalesGrowth3M | 6 | `KEEP_CANONICAL` | same over 3 records | momentum of sales | same |
| 3 | RevenueGrowth | 5 | `KEEP_WITH_NEW_FORMULA` | `(RevenueNew-RevenueLastYear)/abs(...)` within one row | sound, but legacy columns | `(revenue_ttm - revenue_prev_ttm)/abs(revenue_prev_ttm)` from canonical TTM |
| 4 | OperatingProfitGrowth | 5 | `KEEP_WITH_NEW_FORMULA` | `TTM(OpAbs)` with OpK/OpAbs heuristics and ±100× guards | sound intent; heuristics are legacy | `(operating_profit_ttm - prev)/abs(prev)` from canonical TTM, guard on sign only |
| 5 | NetProfitGrowth | 10 | `KEEP_WITH_NEW_FORMULA` | amount path / Product1 path / `NPUnitRatio` | Product1/NPUnitRatio are legacy | `(net_profit_ttm - net_profit_prev_ttm)/abs(prev)` canonical only |
| 6 | OperatingMargin | 4 | `KEEP_CANONICAL` | `SR_TTMOperatingProfit / SR_TTMRevenue`, fallbacks | meaningful | `operating_profit_ttm / abs(revenue_ttm)*100` |
| 7 | NetMargin | 4 | `KEEP_CANONICAL` | TTM net / TTM revenue, fallbacks | meaningful | `net_profit_ttm / abs(revenue_ttm)*100` |
| 8 | MarginTrend | 3 | `KEEP_WITH_NEW_FORMULA` | op margin latest − LY margin | meaningful | `operating_margin - prior_year_same_period operating_margin` (canonical TTM) |
| 9 | ROE | 6 | `KEEP_CANONICAL` | `SR_TTMNetProfit / equity` | meaningful | `net_profit_ttm / total_equity*100` |
| 10 | InterestCoverage | 3 | `KEEP_WITH_NEW_FORMULA` | `OpAmt / finance_cost` (OpAmt legacy) | meaningful; unit heuristic removed | `operating_profit_ttm / abs(finance_cost_ttm)` |
| 11 | EarningsQuality | 4 | `KEEP_WITH_NEW_FORMULA` | `abs(other_non_op)/abs(OpAmt)` | intent sound; splits "non-operating share" | `abs(other_non_operating_ttm) / abs(operating_profit_ttm)*100` |
| 12 | PE | 11 | `KEEP_WITH_NEW_FORMULA` | price / `TTMEPS` built via Product1/EPS | valuation meaningful; EPS path was legacy | `price / eps_ttm` (canonical `eps_ttm`) |
| 13 | PS | 3 | `KEEP_CANONICAL` | `PE × net margin` | already scale-free | `pe * (net_margin/100)` |
| 14 | PB | 2 | `KEEP_CANONICAL` | `PE × ROE` | already scale-free | `pe * (roe/100)` |
| 15 | Liquidity | 3 | `KEEP_CANONICAL` | avg 30d trade value | meaningful | `avg_trade_value_30d` |
| 16 | Stability | 1 | `KEEP_CANONICAL` | `1 - stdev/mean` of 12 monthly sales | meaningful | same from canonical monthly |
| 17 | LowVolatility | 2 | `KEEP_CANONICAL` | stdev of 30d close returns | meaningful | `volatility_30d` |
| 18 | Momentum | 1 | `KEEP_CANONICAL` | 30d price return, cropped | meaningful | `price_momentum_30d` |
| 19 | Leverage | 2 | `KEEP_WITH_NEW_FORMULA` | liabilities / equity | meaningful | canonical `total_liabilities / total_equity` (or `debt_ratio` if preferred) |
| 20 | CurrentRatio | 2 | `KEEP_CANONICAL` | current assets / current liabilities | meaningful | `current_ratio` |
| 21 | CashConversion | 2 | `KEEP_WITH_NEW_FORMULA` | `operating_cash_flow_ttm / net_profit_ttm` | meaningful | canonical `operating_cash_flow_ttm / net_profit_ttm` |

## Notes

* No factor is `REMOVE` purely for legacy reasons; v3.7's factor *set* is economically
  reasonable. The legacy debt is in the **input construction**, not the factor list.
* Factors marked `KEEP_WITH_NEW_FORMULA` are only changed where the v3.7 formula
  encoded a legacy unit heuristic or a `Product1` dependency.
* Any factor whose canonical inputs are frequently missing is flagged in
  `CANONICAL_V1_REPORT.md` with missing-data rates; that may later justify
  `NEEDS_RESEARCH`.

## Baseline weights (prototype only)

`baseline_weights_v37` = the weights above. They are used **only** as a prototype
baseline and are explicitly **NOT VALIDATED FOR CANONICAL V1**. Metric correctness
is the goal of this phase, not optimization.
