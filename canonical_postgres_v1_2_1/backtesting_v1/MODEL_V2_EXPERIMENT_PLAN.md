# Model v2 Experiment Plan (Phase 3, DIAGNOSTIC ONLY)

No optimization is executed here. Candidates are proposed for the **next** phase
under new version identifiers; canonical-v1 stays frozen. Machine-readable:
`output/model_v2_experiment_plan.json`.

## Evidence summary driving candidates

* Robust: PE, SalesGrowth, RevenueGrowth, LowVolatility (+ weak: SalesGrowth3M,
  EarningsQuality).
* Direction-unstable (review, do not flip in place): OperatingProfitGrowth,
  Stability, Momentum; low-coverage negatives: Leverage, CurrentRatio,
  CashConversion.
* No measurable: OperatingMargin.
* Insufficient historical data (≈4.5% coverage): NetProfitGrowth, NetMargin, ROE,
  PS, PB, Leverage, CurrentRatio, CashConversion, Liquidity.
* Redundancy: PS↔PB 0.84, Leverage↔CurrentRatio 0.79, PE↔PS 0.73,
  SalesGrowth↔RevenueGrowth 0.70.
* Category: valuation dominates; growth second; market weak; profitability
  unmeasurable.

## Candidates

### `canonical-v2-exp-A` — remove no-measurable factors
Drop `OperatingMarginRank` (and optionally the redundant pair members PS or PB and
Leverage or CurrentRatio). Everything else identical to canonical-v1. Hypothesis:
same or better IC with fewer, better-supported factors.

### `canonical-v2-exp-B` — weight recalibration (dev+val only)
Increase LowVolatility (underweighted, robust); reduce NetProfitGrowth and ROE
(overweighted vs insufficient evidence). Grid searched **only** on development +
validation; holdout untouched. Direction-unstable factors held or zeroed, not
flipped.

### `canonical-v2-exp-C` — missingness/coverage policy experiment
New model/version (never mutating canonical-v1) that changes missing-factor
treatment (e.g., drop neutral scoring for genuinely-unmeasurable factors, or gate
profitability factors). Directly targets the coverage confounder. Requires a new
version id and its own OOS evaluation.

## Constraints for all candidates

* Use the frozen OOS protocol (`OOS_VALIDATION_PROTOCOL.md`).
* New version ids; no overwriting; no in-place edits to canonical-v1.
* Score diagnostics must be coverage-controlled and time/horizon reported.
* No black-box ML; transparent, reproducible weights only.
* Do not treat the holdout as a selection set.
