# Backtest Specification (Phase 1)

## Objective

Reconstruct Canonical Analytics v1 exactly as knowable historically and measure
subsequent canonical market returns, with explicit anti-look-ahead, universe, and
missingness diagnostics. Two questions: (A) did the analytics carry predictive
information? (B) is any result an artifact of look-ahead/survivorship/sparse
coverage/universe construction?

## Frozen model

`score_version = canonical-v1-dev`, `implementation_revision = report-chain-ttm-v1`.
Hashes of `metric_spec.json`, report-chain spec, factor review, and missing-data
contract are recorded in `run_manifest.json` / `summary_metrics.json`. Weights are
`NOT VALIDATED FOR CANONICAL V1`.

## Conventions (baseline)

| item | value |
| --- | --- |
| signal convention | analytics as-of `T` (close of `T` usable) |
| execution | next trading day close (`next_trading_day_close`) |
| return convention | raw price return (`closing_price_rial`); corporate actions absent |
| horizons (diagnostics) | 5 / 21 / 63 trading days |
| rebalance | monthly (last trading day) |
| portfolio | equal-weight top-20 by QuantScore |
| benchmark | equal-weight tradable universe, same schedule |
| costs | illustrative 10 bps/side; gross + net reported separately |
| segmentation | calendar years |

No parameter is chosen by maximizing historical results.

## Pipeline

1. `calendar`: canonical trading dates; rebalance dates.
2. `snapshot_builder`: for each `T`, canonical Engine (PIT) → signals with scores,
   category scores, 21 factor ranks/values, availability, DQ provenance.
3. `universe`: analyze eligible/tradable/exclusions (no survivorship).
4. Freeze signals → hash.
5. `forward_returns`: entry = next trading day; exits at H days / next rebalance.
6. `portfolio_simulator`: equal-weight selection, turnover, gross/net.
7. `diagnostics`: IC, quantile spreads, factor IC, missingness bias, year segments.
8. hashes + manifest; reproducibility by identical second run.

## Persistence decision

Phase 1 uses **file-based deterministic artifacts** under `backtesting_v1/output/`
(CSV/JSON). No new PostgreSQL schema is added, and `analytics.score_runs` is never
written. This keeps the backtest isolated from canonical/production state. A later
phase may add an append-only `backtesting.*` shadow schema (documented as
COMPATIBILITY_ONLY_NOT_CANONICAL); it is unnecessary for Phase 1 correctness.

## Artifacts

`run_manifest.json`, `rebalance_snapshots.csv`, `signal_snapshot.csv`,
`forward_returns.csv`, `factor_diagnostics.csv`, `quantile_diagnostics.csv`,
`missingness_diagnostics.csv`, `portfolio_returns.csv`, `turnover.csv`,
`summary_metrics.json`.

## Out of scope (Phase 1)

No weight/formula/direction/threshold changes; no neutral-percentile changes; no
frequency/top-N/holding optimization; no ML; no portfolio execution/paper trading;
no production integration.
