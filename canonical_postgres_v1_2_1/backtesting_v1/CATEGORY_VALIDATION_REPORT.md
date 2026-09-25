# Category Validation Report (Phase 3)

Category scores are the four canonical-v1 aggregates (growth, profitability,
valuation, market). Frozen; no change. Machine-readable: `category_validation.csv`.

| category | raw IC | coverage-controlled IC | 95% CI (raw) | 5d | 21d | 63d | 2021–23 | 2024–25 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| **Valuation** | 0.1136 | 0.1164 | [0.0835, 0.1462] | 0.036 | 0.114 | 0.167 | 0.077 | 0.157 |
| **Growth** | 0.0888 | 0.0678 | [0.0652, 0.1139] | 0.037 | 0.089 | 0.098 | 0.044 | 0.139 |
| Market | 0.0357 | −0.0058 | [−0.0148, 0.0860] | 0.021 | 0.036 | 0.076 | 0.007 | 0.071 |
| Profitability | 0.0087 | 0.0318 | [−0.0107, 0.0287] | 0.001 | 0.009 | 0.015 | −0.009 | 0.036 |

## Findings

* **Valuation dominates**: strongest, coverage-robust (its main component PE has
  97.7% coverage), stable across time and rising with horizon. The QuantScore result
  is heavily driven by valuation (PE weight 11).
* **Growth is second**: robust raw and after coverage control.
* **Market is weak/coverage-confounded**: controlled IC ≈ 0; its Liquidity component
  is unavailable historically (neutral).
* **Profitability has no measurable category signal** at current coverage
  (CI spans 0); its components (`ROE`, margins, cash conversion) are ~4.5% covered.

## Missingness sensitivity

Profitability/valuation components are the most coverage-limited; category ICs for
profitability are essentially unestimable historically, while PE-driven valuation
is well-populated. This matches the factor-level results.

## Dominance

Yes — one category (valuation) dominates the current QuantScore association, with
growth second; market contributes little and profitability is currently
unmeasurable. No category is modified; this informs the v2 experiment plan.
