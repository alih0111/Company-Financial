# RESEARCH BUNDLE — DATA DICTIONARY

Every field in every exported file. Units: prices in IRR; returns/dispersion/momentum/
drawdown as decimal fractions (0.05 = 5%) unless noted; liquidity/trade value in IRR;
volume in shares; trade_count in trades; scores/percentiles in [0,1] unless noted.

## monthly_pit_panel.parquet — 13,409 rows × ~97 columns
One row per (signal_date, security). The 63 frozen month-end signal dates × the covered
universe. ALL feature columns are ex-ante: computed only from observations with
trade_date ≤ signal_date, financial inputs with published_at ≤ cutoff (legacy-migrated:
period_end ≤ as_of), shares per the historical TSETMC+Codal knowledge contract.

### identifiers & flags
| field | definition |
|---|---|
| signal_date | frozen month-end evaluation date (YYYY-MM-DD) |
| security_id | canonical `core.securities.id` (primary security; 100% non-null) |
| feature_availability | FULL / NO_PRICE_DATA_ON_OR_BEFORE_T / NO_RAW_CACHE — the 72 rows the v1 bundle dropped are retained here with NULL features (raw TSETMC daily history starts after the signal date for late-listed names) |
| symbol | Codal/TSETMC covered symbol |
| in_ui_reconstruction | row present in the frozen UI-score artifact |
| has_price_series | raw pClosing series has a row on/before the signal date |
| ui_rank | cross-sectional midrank percentile [0,1] of ui_score within the date |
| ui_quintile | Q1..Q5 by ASCENDING ui_score: Q1 = lowest score, Q5 = HIGHEST score (quintile q = rows[q·⌊n/5⌋:(q+1)·⌊n/5⌋] on the ascending sort, remainder included in Q5). Canonical convention — matches the validated ladder and the IC sign |

### frozen UI outputs (canonical-v1-dev; DO NOT re-tune)
| field | definition |
|---|---|
| ui_score | final displayed 0-100 score = DQ × (growth+profitability+valuation+market), rounded 2dp; DQ = 0.45·financials + 0.20·monthly + 0.35·price |
| growth_score / profitability_score / valuation_score / market_risk_score | weighted rank sums (max 36/26/16/11) with the frozen penalties |
| data_quality_score | the DQ multiplier |

### fundamental raw metrics (engine values at T; unit: % for growth/margins/roe/earnings_quality, ratio for coverage/leverage/current ratio/pe/ps/pb, IRR for ttm/market_cap, score01 for stability)
sales_growth_12m, sales_growth_3m, revenue_growth, operating_profit_growth,
net_profit_growth, eps_growth, operating_margin, net_margin, roe, margin_trend,
interest_coverage, cash_conversion, earnings_quality, current_ratio, debt_ratio,
sales_stability, pe, ps, pb, latest_price, market_cap, shares_outstanding,
net_profit_ttm, revenue_ttm
### fundamental ranks (cross-sectional midrank percentiles [0,1] at T)
SalesGrowthRank, SalesGrowth3MRank, RevenueGrowthRank, OperatingProfitGrowthRank,
NetProfitGrowthRank, OperatingMarginRank, NetMarginRank, MarginTrendRank,
InterestCoverageRank, EarningsQualityRank, CashConversionRank, ROERank, LeverageRank,
CurrentRatioRank, StabilityRank, LiquidityRank, LowVolatilityRank, MomentumRank,
PERank, PSRank, PBRank
Known limitation: ocf_ttm is not materialized in this artifact (derivable via Engine re-run).

### price-derived features (raw pClosing; lookback k = trading rows of that security)
| field | derivation |
|---|---|
| return_kd (k = 5,10,20,30,60,90,120) | pClosing(T)/pClosing(k rows earlier) − 1 (unadjusted) |
| return_kd_adjusted | same on factor-adjusted pClosing |
| momentum_20/30/60/90 | identical to return_20d/30d/60d/90d (aliases, documented) |
| volatility_10/20/30/60 | stdev(ddof=1) of the trailing k daily returns |
| downside_volatility_30 | stdev of negative returns within the trailing 30d window |
| drawdown_20/60/120 | pClosing(T)/max(pClosing over trailing k rows incl T) − 1 (≤0) |
| distance_from_20d_high / 60d_high / 120d_high | identical values to drawdown_20/60/120 (aliases) |
| distance_from_20d_low / 60d_low | pClosing(T)/min(pClosing over trailing k rows) − 1 (≥0) |
| liquidity_20/30/60 | mean(qTotCap) over trailing k rows (IRR) |
| trade_value / volume / trade_count | latest row ≤ T (volume is NULL — see limitations) |

### market-state variables (cross-sectional over the covered universe, ex ante at T)
| field | derivation |
|---|---|
| market_breadth_21d | fraction of covered names with positive 21d return |
| market_dispersion_21d | stdev of 21d returns across names |
| market_vol_level | cross-sectional median of trailing 21d daily vol |

## daily_market_panel.parquet — 837,525 rows
One row per (security, trade date) from the raw TSETMC daily history
(GetInstrumentHistory; source field names preserved in parentheses).

| field | source field | definition |
|---|---|---|
| date | dEven | trade date (Gregorian YYYY-MM-DD) |
| security_id / symbol | core.securities | canonical identity |
| pClosing | pClosing | official weighted closing price, IRR (CANONICAL price basis) |
| last_price | pDrCotVal | last traded price, IRR (legacy UI basis; see finding A3) |
| priceYesterday | priceYesterday | next-session reference price (re-based at adjustment events) |
| high / low | priceMax / priceMin | session high / low, IRR |
| open | priceFirst | session open, IRR |
| volume | zTotTran5J | **NULL — not stored by this endpoint (unavailable historically)** |
| trade_value | qTotCap | session trade value, IRR |
| trade_count | zTotTran | number of trades |
| adjustment_factor | derived | CONFIRMED backward coefficient (after/before) of corporate actions with ex_date = this date; 1.0 when none |
| security_traded | derived | true when zTotTran > 0 on that date |
| zero_trade_reason | derived | traded / market_closed_no_covered_trades (no covered name traded that date) / no_trade_unknown (other covered names traded but this security recorded zero trades — suspension or placeholder; NOT further classified) |
| adjusted_close | derived | pClosing × cumulative product of factors of all events AFTER this date (chain-continuous series) |

Not stored by the source (absent by construction, never synthesized): buyers/sellers
counts, individual/institutional split, order-book fields, base volume (baseVol exists
only in the CURRENT GetInstrument snapshot, not historically), allowed price range.

## event_panel.parquet — 20,348 rows
One row per canonical historical event.

| field | definition |
|---|---|
| symbol / security_id | covered identity (mapped from company_id via the primary security; 8,157/8,157 statements + 12,180/12,180 monthly reports mapped, 0 unmapped) |
| event_type | financial_report_income_statement · financial_report_balance_sheet · financial_report_<other> · monthly_sales_report · capital_increase_announcement_LT28 · corporate_action_<type> |
| effective_date | statement period_end / activity month / corporate-action ex-date (NEVER inferred) |
| published_at | Codal publication instant (jalali-source converted; may be NULL for legacy-migrated reports where period_end ≤ as_of is the visibility proxy) |
| collected_at | ingestion collection instant (rv.collected_at; monthly reports: published_at mirrored — the legacy migration did not carry a separate collection stamp) |
| source | codal / tsetmc_gap_rule_v1 / codal_lt28_search |
| source_id | report id / tracing no |
| is_correction_of | report id superseded by this report (4 rows in the whole window) |
| detail_json | fiscal year/month, sales amount, or the full corporate-action metadata (ex_date, reference prices, share economics, funding tags) |

## market_state_daily.parquet — 6,163 rows
One row per calendar date across the covered universe (equal-weight, covered-universe
state; NOT an official index — `market.index_observations` holds only 7 pilot rows).

| field | definition |
|---|---|
| date | trade date |
| eligible_symbol_count | covered names with a price row that date |
| equal_weight_market_return | mean daily return across names that traded |
| median_market_return | median daily return |
| breadth_positive_fraction | fraction of names with positive daily return |
| cross_sectional_return_dispersion | stdev of daily returns across names |
| market_return_20d | mean 20-trading-day return across names |
| market_drawdown | equal-weight level vs trailing peak − 1 |
| market_momentum_20d / market_momentum_60d | equal-weight level ratio vs 20/60 trading days earlier |
| aggregate_trade_value / aggregate_volume | sums over covered names (volume null — see VOLUME) |

## outcomes.parquet — 13,409 rows (SEPARATE from features)
| field | definition |
|---|---|
| forward_adjusted_return_21d/63d/126d/252d | adjusted pClosing(exit)/adjusted pClosing(entry) − 1; entry = first trade date strictly after the signal date; exit = entry + H trading days on the global calendar; NULL when the window is incomplete |
| forward_excess_return_21d/63d/126d/252d | forward adjusted return − same-date equal-weight mean across the full base product universe |

Outcomes were attached ONLY after the signal snapshot was frozen and hashed; the
construction code contains no outcome-source references (L7).
