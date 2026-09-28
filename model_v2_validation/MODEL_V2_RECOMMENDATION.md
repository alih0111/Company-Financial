# MODEL V2 RECOMMENDATION

## Gate

- Model v2: **`MODEL_V2_VALIDATION_WEAK`**
- Signal Engine: **`MODEL_V2_NOT_READY_FOR_SIGNAL_ENGINE_EVALUATION`**

Rationale: the frozen candidate `canonical-v2-exp-a` is valid, deterministic and
leakage-free, and it removes the dominant known confounder (coverage bias
0.576 → 0.055 in development, 0.575 → 0.115 in holdout). But it does **not**
decisively beat the frozen canonical-v1 baseline out of sample: on 2025 the
baseline has higher cumulative return (0.747 vs 0.636) and smaller drawdown, while
IC is comparable. Higher turnover (0.625 vs 0.476) adds cost. This is not a
holdout failure, but it is not enough for a ready candidate.

## What is solid

- Coverage bias is substantially reduced by all v2 candidates; exp-a is simplest.
- Development IC improves materially (0.050 → 0.093) and forward 2026 IC is
  higher (0.308 → 0.332), both monitoring-grade.
- No leakage, no v1 mutation, fully reproducible via config hashes.

## Recommended next actions (single action first)

1. **Bounded coverage-controlled revalidation of exp-a**: extend the frozen
   protocol with a coverage-matched cross-section (subsample to equal
   `n_factors_available` strata) and re-measure whether exp-a beats baseline when
   coverage is held constant. This isolates the coverage confounder without
   touching 2025 for tuning.
2. Reduce exp-a turnover (add a hysteresis/no-trade band) as a new explicitly
   versioned experiment, still selected on dev+val only.
3. Only after (1)–(2) provide consistent dev+val evidence, consider
   `MODEL_V2_READY_FOR_SIGNAL_ENGINE_EVALUATION`.

## Explicit non-actions

- canonical-v1 remains the application default; not replaced.
- No BUY/HOLD/SELL generation.
- Holdout not re-inspected for tuning.
- Model choice rule not modified after seeing holdout.
