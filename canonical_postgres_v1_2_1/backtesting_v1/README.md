# Backtesting v1 — Phase 1

Point-in-time backtesting framework for **Canonical Analytics v1**
(`canonical-v1-dev`, report-chain revision). Infrastructure + one untuned baseline.

## Principles

* Metrics/scores come from `analytics_canonical_v1` (no formula duplication).
* Signal snapshots are **frozen before** forward returns are computed.
* Canonical-only runtime: no SQL Server, no legacy CSV, no `compat_v37`, no v3.7
  oracle input; no production/`analytics.score_runs` writes (file-based artifacts).
* No weight/formula/threshold tuning. `baseline_weights_v37` is a prototype.

## Layout

| file | role |
| --- | --- |
| `config.py` | config + frozen model identifiers/hashes |
| `calendar.py` | trading calendar from canonical dates; rebalance schedules |
| `market_data.py` | canonical price store (execution/exit prices only) |
| `snapshot_builder.py` | PIT signal snapshot via the canonical Engine |
| `universe.py` | PIT eligible/tradable universe + exclusion reasons |
| `forward_returns.py` | execution/exit resolution + forward returns |
| `portfolio_simulator.py` | equal-weight top-N / top-% + turnover + costs |
| `diagnostics.py` | IC, quantiles, factor IC, missingness bias, time segments |
| `run_backtest.py` | orchestration + artifacts + hashes |
| `tests/` | PIT, determinism, separation, no-legacy/oracle/write tests |

## Docs

`BACKTEST_SPEC.md`, `PIT_CONTRACT.md`, `UNIVERSE_POLICY.md`,
`CORPORATE_ACTION_AUDIT.md`, `MISSINGNESS_DIAGNOSTICS.md`, `BASELINE_REPORT.md`.

## Run

```powershell
$py = "C:\Users\aliheyd\AppData\Local\Temp\opencode\pgtest_venv\Scripts\python.exe"
$env:CDF_PILOT_DB="company_financial_analytics_shadow_v121"
& $py canonical_postgres_v1_2_1\backtesting_v1\run_backtest.py
```

Outputs land in `backtesting_v1/output/` (CSV/JSON). Deterministic:
`signal_snapshot`, `forward_returns`, `portfolio_path`, `summary` hashes.
