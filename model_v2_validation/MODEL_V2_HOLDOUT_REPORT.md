# MODEL V2 HOLDOUT REPORT (2025)

Evaluated exactly once per frozen candidate, after the selection was fixed using
development + validation only. The holdout was not used to select, tune or reject.

## Frozen selection

`canonical-v2-exp-a` (Robust Core), config hash
`4997a85e4d6f33e72dc2c1d27286002d736f21073c377337aaac009306255364`.

## Holdout outcome

| model | IC21 | pos.frac | t-stat | top−bottom21 | port raw | port cost | maxDD | turnover | cov.corr |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| **exp-a (selected)** | 0.161 | 1.00 | — | 0.0394 | 0.636 | 0.614 | −0.177 | 0.625 | 0.115 |
| exp-b | 0.157 | 0.92 | — | 0.0365 | 0.590 | 0.567 | −0.182 | 0.684 | 0.154 |
| exp-c | 0.170 | 1.00 | — | 0.0398 | 0.600 | 0.581 | −0.219 | 0.578 | 0.227 |
| v1 baseline | 0.166 | 1.00 | — | 0.0455 | **0.747** | 0.730 | −0.151 | 0.476 | **0.575** |

Benchmark raw (equal-weight tradable): 0.253 for every model (same universe).

## Objective assessment

- Positive on the holdout: IC21 > 0, positive-IC fraction 1.0, top-minus-bottom
  positive for all candidates. The signal is not destroyed out of sample.
- **Mixed vs development:** exp-a dominated the baseline in development
  (portfolio 1.95 vs 1.49) but not in holdout (0.636 vs 0.747). The relative
  return ordering reverses.
- IC is comparable to the baseline on holdout (0.161 vs 0.166); top−bottom spread
  is slightly lower (0.0394 vs 0.0455).
- **Coverage bias** remains dramatically better for exp-a (0.115 vs 0.575), which
  matters because canonical-v1's holdout IC may be partly coverage-driven.
- exp-a turnover is higher (0.625 vs 0.476), a real implementation cost.

## Conclusion

The holdout does **not** materially contradict the core claim (exp-a improves
coverage robustness and development IC), but it **does** contradict the claim that
exp-a is a uniformly better return model: on 2025 it underperforms the frozen
baseline on cumulative return and drawdown. Result preserved as-is; no tuning
after viewing.

Gate implication: **MODEL_V2_VALIDATION_WEAK** — candidate is valid and
leakage-free but not decisively better than the frozen baseline out of sample.
