# RESEARCH BUNDLE — DATA INVENTORY

Frozen: 2026-10-02. Purpose: a complete inventory of PIT-safe data actually available in
this project, so the next economic hypothesis is chosen from real data. This is INVENTORY
ONLY — no feature ICs, no correlations with future returns, no candidate signals.

Used-in legend: **UI** = UI score factor/component · **V2** = consumed by Model v2.1/v2.2 ·
**SIG** = consumed by Signal V1 · — = never materially used.

## PRICE

| field / file | source | meaning | freq | first | last | rows | coverage | PIT | raw/derived | used |
|---|---|---|---|---|---|---|---|---|---|---|
| `daily_market_panel.pClosing` | TSETMC GetInstrumentHistory (raw cache) | official weighted closing price, IRR | daily | 1998-06 (varies; 2002-11 for دارو) | 2026-09-30 | 837,525 | 100% of cached rows | trade_date ≤ T (frozen proxy) | raw | UI (basis), V2 (targets), SIG (features/outcomes) |
| `daily_market_panel.last_price` (pDrCotVal) | same | last traded price | daily | same | same | 837,525 | ~100% | same | raw | legacy UI basis only (finding A3); — in current score |
| `daily_market_panel.priceYesterday` | same | next-session reference price (re-based at events) | daily | same | same | ~100% | ~100% | same | raw | — (used only inside the gap-rule audit) |
| `daily_market_panel.high/low/open` (priceMax/Min/First) | same | daily high / low / open | daily | same | same | ~100% | ~100% | same | raw | — NEVER used in UI/V2/Signal V1 |
| `daily_market_panel.adjustment_factor` | CONFIRMED corporate actions | backward coefficient (after/before) | event-driven | 2002-05 (varies) | 2026-06 | ~651 events | see corporate actions | ex_date = action_date | derived | SIG (outcomes), UI (252d outcomes) |
| `daily_market_panel.adjusted_close` | derived | pClosing × cumulative factor | daily | same as price | same | 837,525 | 100% | same | derived | UI (targets), SIG |

## RETURNS (derived, adjusted and unadjusted)

| field (monthly panel) | derivation | first | coverage | used |
|---|---|---|---|---|
| `return_5d / return_10d` | pClosing(T)/pClosing(T−k) − 1 (unadjusted) | 2021-01-31 | ~99.9% | — NEVER used |
| `return_20d / return_30d` | same | 2021-01-31 | ~100% | return_30d ≈ Momentum30 (UI, V2) |
| `return_60d / return_90d` | same | 2021-01-31 | ~99.8/99.7% | return_60d ≈ Signal V1 Momentum60 |
| `return_120d` | same | 2021-01-31 | ~99.7% | — NEVER used |
| `return_*_adjusted` | same on adjusted pClosing (chain factors) | 2021-01-31 | ~99.7-99.9% | — NEVER used as features (outcomes only) |
| `forward_*` (outcomes file) | entry = first trade date strictly after T; exit = entry+H global trading days | per horizon | 21d 100% / 63d 98.4% / 126d 96.9% / 252d 86.5% | outcomes for UI validation, V2, SIG |

## VOLUME

| field | source | status |
|---|---|---|
| share volume (zTotTran5J) | TSETMC GetInstrumentHistory | **UNAVAILABLE — null in 100% of cached rows** (endpoint does not store it historically). Column kept in the daily panel, all-null, documented. No volume-based feature can be built from canonical data. |
| `market_state_daily.aggregate_volume` | sum over covered universe | null for the same reason (kept for schema completeness) |

## TRADE VALUE

| field | source | freq | first | coverage | used |
|---|---|---|---|---|---|
| `daily_market_panel.trade_value` (qTotCap) | raw cache | daily | 2002-11 (varies) | ~100% | — NEVER used directly (liquidity derived from it) |
| `monthly_pit_panel.trade_value` | raw, latest row ≤ T | monthly | 2021-01-31 | ~100% | — NEVER used |
| `market_state_daily.aggregate_trade_value` | sum over covered universe | daily | 1998+ | ~100% | — NEVER used |

## TRADE COUNT

| field | source | freq | coverage | used |
|---|---|---|---|---|
| `daily_market_panel.trade_count` (zTotTran) | raw cache | daily | ~100% | — NEVER used (V1 did not include it) |
| `monthly_pit_panel.trade_count` | raw, latest row ≤ T | monthly | ~100% | — NEVER used |

## LIQUIDITY

| field | derivation | coverage | used |
|---|---|---|---|
| `liquidity_20 / liquidity_60` | mean qTotCap over trailing 20/60 raw rows | **69.6% / 36.6%** (qTotCap ramp — older raw rows lack it) | — NEVER used |
| `liquidity_30` (=UI LiquidityRank input) | mean qTotCap trailing 30 | **57.0%** in the repaired monthly panel (raw qTotCap ramp; the UI Engine used `market.price_observations.trade_value_rial`, present only in recent brs_daily rows) | UI (LiquidityRank), SIG diagnostic only |
| **caveat** | qTotCap coverage starts ~2021 in the raw caches (57.3% of grid rows); earlier years lack it | | |

## VOLATILITY

| field | derivation | coverage | used |
|---|---|---|---|
| `volatility_30` | stdev of last 21 daily returns (trailing 30-row window) | 99.9% | UI (LowVolatilityRank), V2, SIG (InverseVolatility30Rank) |
| `volatility_10 / volatility_20 / volatility_60` | stdev over trailing 10/20/60 daily returns | 99.8-99.9% | — NEVER used |
| `downside_volatility_30` | stdev of negative returns within the 30d window | 97.5% | — NEVER used |
| `market_state_daily.median_volatility_21` | cross-sectional median of trailing 21d vol | 63 signal dates + 6,163 daily rows | — NEVER used |
| `monthly_pit_panel.market_breadth_21d / market_dispersion_21d / market_vol_level / market_median_return_21d` | cross-sectional 21d variants at signal date (materialized from raw caches) | 100% | — NEVER used |

## MOMENTUM

| field | derivation | coverage | used |
|---|---|---|---|
| `momentum_20 / momentum_30` | 20d/30d price return | ~100% | mom_30 = UI MomentumRank (UI, V2) · mom_20 NEVER used |
| `momentum_60` | 60d price return | 99.8% | SIG (primary timing input) · — in UI/V2 |
| `momentum_90` | 90d price return | 99.7% | — NEVER used |
| `market_state_daily.market_momentum_20d/60d` | equal-weight market level ratio | ~100% of daily dates | — NEVER used |

## DRAWDOWN / HIGH-LOW DISTANCE

| field | derivation | coverage | used |
|---|---|---|---|
| `drawdown_20 / drawdown_60 / drawdown_120` | pClosing/max(trailing k rows) − 1 | 99.7-100% | — NEVER used (V1 used drawdown_60 semantics via DistanceFrom60DayHigh) |
| `distance_from_20d_high / 60d_high / 120d_high` | identical values to drawdown_k (documented aliases) | same | V1 used the 60d one |
| `distance_from_20d_low / 60d_low` | pClosing/min(trailing k rows) − 1 (≥0) | 99.7-100% | — NEVER used |

## MARKET BREADTH / DISPERSION

| field | derivation | coverage | used |
|---|---|---|---|
| `market_state_daily.breadth_positive_fraction` | fraction of covered universe with positive daily return | ~100% of daily dates; 100% of signal dates (materialized) | diagnostic only (research_decision_panel) — NEVER a feature |
| `market_state_daily.cross_sectional_return_dispersion` | std of daily returns across the universe | same | — NEVER used |
| `monthly_pit_panel.market_breadth_21d / market_dispersion_21d / market_vol_level` | cross-sectional 21d variants at signal date | 99.9% | — NEVER used |
| `breadth_above_20d_ma` | **NOT DERIVABLE** — requires per-symbol 20d moving averages (derivable in a future build); left out per the no-new-features-at-execution rule | — | — |

## MARKET-LEVEL SERIES

| field | source | status |
|---|---|---|
| `market_state_daily.equal_weight_market_return / median_market_return` | equal-weight covered-universe daily return | available ~1998+ (6,163 daily rows) — NEVER used |
| `market_state_daily.market_drawdown / market_momentum_20d/60d` | equal-weight level vs trailing peak / ratio | NEVER used |
| **official index (TEDPIX etc.)** | `market.index_observations` | **UNAVAILABLE — table holds only 7 pilot rows**. No official index series is stored. Documented gap. |
| `aggregate_trade_value / aggregate_volume` | sums over covered universe | value ~100%; volume null (see VOLUME) |

## FINANCIAL STATEMENTS / SALES / PROFIT / MARGINS / ROE / CASH FLOW / LEVERAGE / CURRENT RATIO / VALUATION

All in `monthly_pit_panel` (raw value + cross-sectional percentile rank per date), sourced
from `fundamentals.financial_statements` + `financial_facts` + `monthly_activities` under
the frozen PIT rules (published_at ≤ cutoff; legacy-migrated: period_end ≤ as_of):

| field | meaning | coverage (2021 → 2026) | used |
|---|---|---|---|
| `sales_growth_12m` (sales_growth_12m) | 12-month sales vs prior 12m (monthly activity sums) | **0% → 68.7%** (monthly-activity backfill ramp) | UI, V2 |
| `sales_growth_3m` | 3m vs prior 3m | similar ramp | UI, V2 |
| `sales_stability` | 1 − pstdev/|mean| of last 12 monthly sales | similar | UI |
| `revenue_growth` | revenue TTM vs prior-year TTM (report chain) | ~92% flat | UI, V2 |
| `net_profit_growth` / `eps_growth` | net profit / EPS TTM growth (rank falls back EPS→net) | ~92-95% | UI, V2 |
| `operating_profit_growth` | operating profit TTM growth | ~90% | UI, V2 |
| `net_margin` / `operating_margin` | TTM margins | ~92-95% | UI, V2 |
| `margin_trend` | op margin YoY change (pp) | ~90% | UI |
| `roe` | net TTM / equity | ~92% | UI, V2 |
| `interest_coverage` | op TTM / |finance cost| | ~90% | UI |
| `cash_conversion` | OCF TTM / net TTM | ~85% | UI |
| `earnings_quality` | \|other non-operating\| / \|op TTM\| (lower better) | ~90% | UI |
| `current_ratio` / `debt_ratio` | balance-sheet ratios | ~90% | UI |
| `pe / ps / pb` | market_cap / quantity (VAL_DIRECT, historical shares) | 51.8% → 76.4% (share-path ramp) | UI (PERank/PSRank/PBRank), V2 (PERank as PERank_DIRECT_V2) |
| `market_cap / shares_outstanding` | price × PIT shares (zTitad contract) | ~100% (2026 run); historical per interval path | UI (valuation), SIG (eligibility base) |
| `net_profit_ttm / revenue_ttm` | TTM quantities | ~92-95% | UI (penalties), V2 |
| `ocf_ttm` | operating cash flow TTM | **NOT MATERIALIZED** in the frozen UI artifact — derivable via Engine re-run (documented gap; cash_conversion exists) | — |

## REPORT PUBLICATION DATES / TYPES / CORRECTIONS

| field | source | rows | used |
|---|---|---|---|
| `event_panel.published_at` | `ingestion.reports` | 26,745 reports total; event panel carries every statement + monthly activity report | PIT gate for all financial features |
| `event_panel.event_type` | statement_type / monthly / LT28 / corporate action | financial_report_income_statement / _balance_sheet / monthly_sales_report / capital_increase_announcement_LT28 / corporate_action_* | announcement layer |
| corrections | `ingestion.reports.supersedes_report_id` (4 rows) + `is_correction_of` column | only 4 superseding reports exist — corrections are nearly absent from the canonical window | — |
| LT28 announcements | `lt28_search.json` (1,158 letters, PublishDateTime) | announcement evidence for capital increases | knowledge-time for historical shares |

## CORPORATE ACTIONS / HISTORICAL SHARES

| field | source | rows | used |
|---|---|---|---|
| `market.corporate_actions` (source tsetmc_gap_rule_v1) | gap-rule events, CONFIRMED factors | 7,013 (cash_dividend 4,344 unclassified-semantics, rights 480, capital_increase 384, reverse_split 30, other 1,775) | UI (252d outcomes), SIG (adjustment) |
| `core.share_events` + sharechange caches | TSETMC numberOfShareOld/New + dEven | 1,227 events / 238 symbols | historical valid_from (share history contract) |
| `core.share_intervals` | reconstructed KNOWN intervals | 238 symbols; knowledge_from = Codal published_at | historical share PIT |
| `market.tsetmc_current_shares` | zTitad collector | 323 rows, collected 2026-10-02 14:55-15:01 | CURRENT production shares |

## UI SCORE / COMPONENTS / DATA QUALITY

| field | coverage | used |
|---|---|---|
| `ui_score` (canonical-v1-dev, frozen reconstruction) | 100% | UI product, V2 baseline, SIG eligibility |
| `growth_score / profitability_score / valuation_score / market_risk_score` | 100% | UI display; SIG-B input (ui_rank) |
| `data_quality_score` | 100% | UI display |
| 21 factor ranks (SalesGrowthRank … MomentumRank) | 99.7-100% | V2 (all), UI (weights), SIG (none directly) |
| DQ flags (missing_comparable_period, EPS_*, TTM_METHOD_MISMATCH, FISCAL_CALENDAR_UNKNOWN…) | per row | UI DQ; diagnostic only |

## UNUSED OR UNDERUSED DATA (PART 2 — inventory only, no predictive testing)

| field | coverage | history | possible economic interpretation |
|---|---|---|---|
| `distance_from_20d_low / 60d_low` | 99.7-100% | full window | proximity to recent lows — capitulation / support proximity |
| `momentum_20 / momentum_90` | ~100% | full window | very short-term drift; quarterly-scale drift |
| `return_5d / return_10d / return_120d` (+adjusted) | ~99.7-100% | full window | weekly reversal horizon; semi-annual horizon |
| `volatility_10 / volatility_20 / volatility_60` | 99.8-99.9% | full window | vol horizon structure (short vs quarterly vol) |
| `downside_volatility_30` | 97.5% | full window | downside-risk asymmetry |
| `drawdown_20 / drawdown_120`, `distance_from_120d_high` | 99.7-100% | full window | recent vs semi-annual peak proximity |
| `liquidity_20 / liquidity_60` | 99.7-100% | full window | liquidity horizon structure |
| `trade_count` (zTotTran) | ~100% daily+monthly | full window | trading intensity / attention proxy |
| `daily high / low / open / priceYesterday / priceChange / yClose / iClose / last / hEven` | ~100% | full window | intraday range (high−low)/pClosing — range-volatility; gap behavior (open vs prev close) |
| `GetInstrument.baseVol` | current snapshot | current | exchange base-volume (liquidity band) — current only |
| `GetInstrument.cgrValCot / cComVal / flow` | current | current | market/board classification — scoping metadata |
| `GetInstrumentShareChange.hEven / idn` | cached | full | intra-day stamp of share-state change |
| `market_state_daily.median_market_return` | ~100% daily | full window | market central tendency |
| `earnings_quality` (as a raw magnitude) | ~90% | full window | accrual quality — used in UI profitability only |
| `ocf_ttm` | derivable via Engine re-run, not materialized | full window | cash-flow level (cash_conversion uses the ratio) |

## KNOWN COVERAGE GAPS (summary)

1. Volume (zTotTran5J): **unavailable** in the TSETMC historical daily endpoint (null everywhere).
2. Official market index: **not stored** (`market.index_observations` has 7 pilot rows).
3. liquidity_30: 57.3% of grid rows (qTotCap ramp from ~2021).
4. sales_growth_12m / sales_growth_3m / sales_stability: 0% (2021) → 69% (2026) monthly-activity ramp.
5. PE/PS/PB historical coverage ramps 51.8% → 76.4% with the share-path.
6. ocf_ttm: not materialized in the frozen artifact (derivable by Engine re-run).
7. 126d/252d outcomes: missing for the last ~1-12 months of the grid (windows not yet complete).
