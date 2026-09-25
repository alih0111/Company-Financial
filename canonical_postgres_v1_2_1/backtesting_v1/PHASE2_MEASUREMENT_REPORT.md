# Phase-2 Measurement Hardening Report

Scope: harden Phase-1 measurement and control for known confounders. No factor
weights, definitions, QuantScore formula, neutral percentiles, or model parameters
changed. No paper trading; no production/legacy dependency.

## Key results

| item | value |
| --- | --- |
| Phase-1 +721% path accounting-valid | **Yes** (contiguous, non-overlapping; corrected path identical) |
| portfolio-path bugs | dropped cash intervals (fixed); contiguity check (fixed) |
| zero-tradable dates | 3 (`2026-02-25/03-31/04-29`); cash-interval policy |
| market revisions | 126/705,685 keys (0.0179%) conflicting, historically non-orderable → flagged |
| corporate actions | 0 rows; raw price return only; 1,250 extreme events flagged, strategy exposure 0.48% vs bench 0.16% |
| raw QuantScore IC (21d) | 0.1088, CI [0.0736, 0.1415] |
| coverage-controlled IC | low 0.1119; medium −0.0741 (n=46, CI spans 0); high **0.1547** |
| coverage-neutralized IC (diagnostic) | 0.1239, CI [0.0857, 0.1569] |
| partial association (score coef) | pooled +0.00156; per-date +0.00158 (positive after coverage control) |
| matched benchmark | strategy 0.0398 vs matched control 0.0228 → **+0.0170/period** |
| horizons | 5d 0.0335 · 21d 0.1088 · 63d 0.1519 |
| reproduction hashes | identical across two runs: `777e4b7ea2bc6db07999fef89fd35dfd9c6dc71b73df1885f89e66299297ee17` |
| tests | backtesting 20 · canonical 18 · oracle 3, all green; oracle hash unchanged |

## Answers

* **Was +721% accounting-valid?** Yes — one contiguous, non-overlapping wealth path.
* **Coverage confounding?** Present and material (Pearson 0.581; returns rise with
  coverage), but the QuantScore association **persists within low/high coverage
  strata and after neutralization**, and beats a coverage-matched control.
* **Category effects?** Signal present with/without each category; stronger when
  profitability is available (small n).
* **Factor confounding?** Several factor ICs are inseparable from coverage
  (`factor_controlled_diagnostics.csv`): e.g. OperatingProfitGrowth, Stability are
  `COVERAGE_CONFOUNDED`; PE, SalesGrowth, ROE, PS/PB, LowVolatility, RevenueGrowth
  `SIGNAL_PERSISTS_AFTER_COVERAGE_CONTROL`; many `SIGNAL_INCONCLUSIVE` (tiny raw IC).
* **Liquidity/tradability?** Not measurable historically (trade_value only 2026);
  Liquidity factor neutral. No liquidity filter introduced.
* **Concentration?** Moderate; best 10% of periods = 41.2% of positive P&L; 118
  companies traded.
* **Cost sensitivity?** Net cumulative 7.21 → 6.90 → 6.46 → 5.78 for 0/10/25/50 bps.

## Gate

# BACKTEST_MEASUREMENT_HARDENED

Portfolio path valid; no overlap double-counting; market revision risk quantified
(0.018%) and bounded; corporate-action limitation explicitly bounded (raw returns);
coverage confounding measured and controlled; benchmark fairness established
(identical dates/execution/tradability/return/cost conventions);
reproducible; no canonical model parameter tuned.

This does **not** claim the model is predictive or profitable.

## Recommended next phase

**FACTOR AND MODEL VALIDATION** — formally decide which factors have robust
evidence and design out-of-sample experiments (still no production cutover).
