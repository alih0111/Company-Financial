# Point-in-Time Contract (Backtesting v1)

## 1. Signal snapshot

At evaluation date `T`, the signal snapshot is produced by
`analytics_canonical_v1.compute_metrics.Engine(as_of=T, cutoff=end_of_day_T)` and
frozen. Only data visible at `T` may enter.

| source | eligibility at `T` |
| --- | --- |
| `ingestion.reports` / `report_versions` / `parse_runs` | report with `published_at <= T`; legacy synthetic reports (no `published_at`) use `period_end_date <= T` |
| `fundamentals.financial_statements` / `financial_facts` | `period_end_date <= T` (or `published_at <= T`); superseded reports excluded |
| `fundamentals.monthly_activities` | `period_end_date <= T` |
| `market.price_observations` | **`trade_date <= T`** (historical mode) |
| `market.corporate_actions` | `action_date <= T` (currently empty) |
| report-chain TTM | all three legs drawn from the PIT-filtered report index; a later correction/future report cannot enter |

## 2. Documented market-PIT limitation (important)

Canonical `market.price_observations.collected_at` is **migration ingestion time**
(2026-07-30 … 2026-09-24), not historical availability. Using
`collected_at <= T` for a historical `T` returns nothing, so the engine's default
market-PIT mode cannot reconstruct history.

The backtester therefore uses an explicit, opt-in **`market_pit="trade_date"`** mode:
a price for `trade_date = d` is considered available at end of `d`. This prevents
future prices from leaking while remaining PIT-safe. The production/default engine
behavior (`collected_at`) is unchanged.

Impact: market factors are reconstructed from `trade_date`; the initial baseline is
valid on this convention. A future data fix could populate true per-row
availability timestamps.

## 3. Signal vs execution vs return

* **Signal date `T`**: snapshot uses data through end of `T` (close of `T` included
  in price-derived factors).
* **Execution date**: the **first trading date strictly after `T`**
  (`next_trading_day_close`) — never same-close, to avoid look-ahead.
* **Exit**: entry + H trading days (`exit_after`), H ∈ {5, 21, 63} for diagnostics;
  portfolio holding uses the next rebalance's execution date.
* Forward returns are computed **only after** all snapshots are frozen.

## 4. Anti-look-ahead tests

`tests/test_backtest_v1.py`: future report rejection, future correction rejection,
future price rejection (trade_date mode), report-chain missing-leg safety,
signal/execution separation, no survivorship from a static universe.
