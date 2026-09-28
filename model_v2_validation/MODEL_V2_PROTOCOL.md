# MODEL V2 PROTOCOL

Status: **FROZEN** (no leakage; canonical-v1 untouched). Model v2 experimentation
only; no production replacement, no BUY/HOLD/SELL.

## Data

Single frozen PIT source:
`canonical_postgres_v1_2_1/backtesting_v1/output/phase3_signals.csv`
(per signal date/company: 21 canonical `factor_rank` percentiles,
`factor_available`, `category_available`, `quant_score` = canonical-v1 baseline,
`n_factors_available`, and forward `ret_5/ret_21/ret_63`). This snapshot was
frozen before any forward return and is **not** recomputed by Model v2. The
frozen v3.7 oracle and canonical-v1/backtesting evidence are untouched.

## Chronological split (frozen)

| role | period |
| --- | --- |
| Development | 2021–2023 |
| Validation | 2024 |
| Holdout | 2025 |
| Forward monitoring | 2026 (n=3 signal dates; monitoring only) |

## Rules

1. Weights are **predeclared** in `MODEL_REGISTRY.json`; developed only on
   development. Validation 2024 chooses among the predeclared candidate set.
2. Holdout 2025 is never used for factor/weight/threshold/direction selection; it
   is evaluated **once** per frozen candidate.
3. 2026 is monitoring only; never used to tune.
4. No black-box ML; transparent, deterministic weights.
5. Direction-unstable factors are held, never flipped in place.
6. All candidates use new version ids (`canonical-v2-exp-*`); canonical-v1 is
   never mutated.

## Selection rule (predeclared, dev+validation only)

```
selection_score = 0.5*mean(dev_ic21, val_ic21)
                + 0.2*mean(dev_positive_frac, val_positive_frac)
                - 0.2*|mean(dev_coverage_corr, val_coverage_corr)|
                - 0.1*|mean(dev_drawdown, val_drawdown)|
selected = argmax(selection_score)          # tie-break: fewer factors (simpler)
```

The selection function receives only development and validation evidence. It is
tested (`tests/test_model_v2.py::test_holdout_leakage_prevention`) that holdout
values cannot affect it.

## Evaluation

Spearman IC (5d/21d/63d), monthly IC distribution (mean, median, positive
fraction, t-stat), quantile top-minus-bottom (21d), top-20 portfolio,
equal-weight benchmark, turnover, max drawdown, volatility, eligible count,
coverage (`corr(score, n_factors_available)`), performance by year and by
coverage stratum. Costs: `RAW_GROSS` and `SIMPLE_COST_SCENARIO`
(10 bps/side × 2 × turnover); documented as illustrative, not realistic net.
