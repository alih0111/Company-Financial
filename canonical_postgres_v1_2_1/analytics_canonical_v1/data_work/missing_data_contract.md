# Canonical v1 — Missing-Data Contract

Defines, per eligibility input / metric / factor, what happens when required
canonical source facts are absent. Uses the existing engine semantics; **no new
penalties or weights are invented**. No legacy fill-ins. Balance-sheet/stock
metrics are never TTM-chained.

Classification vocabulary: `REQUIRED_FOR_POPULATION`, `OPTIONAL_WITH_NULL`,
`OPTIONAL_WITH_DQ_PENALTY`, `EXCLUDED_IF_MISSING`, `NOT_APPLICABLE`.

## Deterministic participation rule

A company participates in canonical scoring iff it is an eligible canonical
subject (`is_active`, resolved identity, and (`income_statement` present OR ≥ 6
monthly rows)). Missing metrics/factors **never** exclude a participating company;
each absent factor receives its documented **neutral** percentile. Percentiles are
computed only over companies that have the factor's underlying value; the
denominator change is explicit and deterministic. Missing values are **not**
treated as zero, and no legacy value is substituted.

## A. Eligibility / population inputs

| input | class | behavior when absent |
| --- | --- | --- |
| resolved identity (external id / legacy map) | `REQUIRED_FOR_POPULATION` | excluded (`unresolved_identity`) |
| financial statement (`income_statement`) | `REQUIRED_FOR_POPULATION` (via OR) | excluded only if also < min monthly |
| monthly rows (≥ 6) | `REQUIRED_FOR_POPULATION` (via OR) | excluded only if also no income statement |
| primary security | `NOT_APPLICABLE` | optional; market factors neutral |
| market price | `OPTIONAL_WITH_DQ_PENALTY` | `missing_price`; market factors neutral |

## B. Metrics

| metric | class | null behavior |
| --- | --- | --- |
| `sales_ttm`, `sales_growth_12m` | `OPTIONAL_WITH_NULL` | NULL if < required monthly history |
| `revenue_ttm`, `net_profit_ttm`, `operating_profit_ttm`, `eps_ttm`, `ocf_ttm` | `OPTIONAL_WITH_NULL` | direct → report-chain → NULL + provenance |
| `net_margin`, `operating_margin`, `roe` | `OPTIONAL_WITH_NULL` | NULL if numerator/denominator absent |
| `current_ratio`, `debt_ratio` | `OPTIONAL_WITH_NULL` | NULL if a stock leg absent |
| `pe` | `OPTIONAL_WITH_DQ_PENALTY` | invalid/missing → worst valuation rank + `ValuationPenalty` (as specified) |
| `ps` | `OPTIONAL_WITH_NULL` | NULL if pe/margin invalid |
| `price_momentum_30d`, `volatility_30d` | `OPTIONAL_WITH_NULL` | NULL if < 30 observations |
| `avg_trade_value_30d` | `OPTIONAL_WITH_NULL` (neutral worst) | NULL → liquidity rank 0.0 by design |

## C. Factors (21)

Every factor is `OPTIONAL_WITH_NULL`; none is `EXCLUDED_IF_MISSING`. Neutral
percentiles are the existing engine defaults:

| factor group | neutral when underlying missing | class |
| --- | --- | --- |
| SalesGrowth, SalesGrowth3M, RevenueGrowth, OperatingProfitGrowth, NetProfitGrowth, OperatingMargin, NetMargin, MarginTrend, ROE, Leverage, CurrentRatio, CashConversion, Stability, LowVolatility, Momentum | `0.30` | `OPTIONAL_WITH_NULL` |
| InterestCoverage, EarningsQuality | `0.50` | `OPTIONAL_WITH_NULL` |
| PE, PS, PB | `0.00` (invalid/missing = worst, by spec) | `OPTIONAL_WITH_DQ_PENALTY` |
| Liquidity | `0.00` (no-data = worst, by spec) | `OPTIONAL_WITH_NULL` |

## D. Category / QuantScore aggregation

```
category = max(0, Σ_f (weight_f × rank_f) − penalty_category)
QuantScore = DataQualityScore × Σ_category category      (all 4 categories)
```

Every factor rank is always defined (data-driven percentile or documented neutral),
so every participating company receives a deterministic QuantScore. `DataQualityScore`
reflects coverage/freshness flags (including `SOURCE_ABSENT`-driven gaps via
`missing_current_financials`/`missing_comparable_period`).

## E. Answer

Yes — a company may legitimately participate with partial factors. The rule is the
deterministic neutral-percentile policy above; missingness is explicit
(`NULL` metrics + DQ provenance), and no implicit zero-filling or legacy fill-in is
used.
