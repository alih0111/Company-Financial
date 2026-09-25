# Coverage-Bias Report (Phase 2)

The frozen QuantScore (and all factor definitions / neutral percentiles) is
**unchanged**. This report measures how much of the apparent signal is confounded by
factor availability and whether the score carries information beyond coverage.

## 1. Coverage confounding exists

`pearson(QuantScore, n_factors_available) = 0.581`. Forward returns also increase
with coverage (Phase 1). So raw associations partly reflect coverage.

## 2. Coverage-controlled QuantScore IC (21d)

| stratum | mean IC | 95% block-bootstrap CI | n periods |
| --- | --- | --- | --- |
| all (raw) | 0.1088 | [0.0736, 0.1415] | 62 |
| low (≤7) | 0.1119 | [0.0764, 0.1440] | 62 |
| medium (8–14) | −0.0741 | [−0.2422, 0.0969] | 46 |
| high (≥15) | 0.1547 | [0.0575, 0.2502] | 62 |

Within **low** and **high** coverage the QuantScore IC remains positive and, in the
high stratum, **larger** than raw. The medium stratum is negative but small-sample
(n=46) and its CI spans zero → inconclusive, not evidence of reversal.

## 3. Partial association (analysis only)

`ret_21 ~ QuantScore + n_factors_available` (pooled OLS):
score coefficient **+0.00156**, n_factors coefficient +0.00022.
Per-date averaged: score **+0.00158**, n_factors **−0.00196**.
The score coefficient stays positive after controlling for coverage.

## 4. Coverage-neutralized score (DIAGNOSTIC_ONLY_NOT_MODEL)

Per date, QuantScore is regressed on `n_factors_available`; the residual is a
diagnostic only (never replaces canonical QuantScore). Residual IC = **0.1239**
(CI [0.0857, 0.1569]) — at least as strong as the raw score.

## 5. Coverage × score matrix (`coverage_score_matrix.csv`)

Within each coverage stratum, returns rise with score quintile:
low: q1 0.0188 → q5 0.0453; high: q1 0.0114 → q5 0.0429. The pattern persists
within coverage regimes (medium noisy).

## 6. Category availability (`category_coverage_diagnostics.csv`)

| category | available IC (n) | unavailable IC (n) |
| --- | --- | --- |
| growth | 0.089 (11,282) | 0.081 (1,130) |
| profitability | 0.147 (781) | 0.083 (11,631) |
| valuation | 0.089 (12,118) | 0.107 (294) |
| market | 0.089 (12,412) | — (0) |

The signal is present whether or not a category is available; it is somewhat
stronger when profitability is available (small n).

## 7. Matched benchmark (`matched_benchmark.csv`)

Controls matched on `n_factors_available` (deterministic), excluding selected names:

| group | mean 21d-equiv return |
| --- | --- |
| strategy top-20 | 0.0398 |
| coverage-matched control | 0.0228 |
| **strategy − matched** | **+0.0170 / period** |

The strategy still exceeds a coverage-matched control group.

## 8. Conclusion

The QuantScore association **persists within comparable coverage strata** and after
coverage neutralization; it is not solely a coverage artifact. Coverage still
inflates the *level* of raw results, so all Phase-2 findings are reported
coverage-stratified. No model change is made or recommended here.
