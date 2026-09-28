# MODEL V2 EXPERIMENTS

Canonical-v1 (`canonical-v1-dev`) stays frozen as the baseline. Three
interpretable, deterministic candidates. Config hashes are in
`MODEL_REGISTRY.json`; machine-readable per-candidate metrics in
`output/model_v2_candidates.csv`.

## Baseline — `canonical-v1-dev`
Frozen `quant_score` column of the phase-3 snapshot (baseline_weights_v37, not
validated; neutral 0.3 for missing). Reproduced unchanged.

## `canonical-v2-exp-a` — Robust Core
Kind: robust factor composite. Config hash
`4997a85e4d6f33e72dc2c1d27286002d736f21073c377337aaac009306255364`.

| factor | weight |
| --- | --- |
| PERank | 0.35 |
| SalesGrowthRank | 0.20 |
| RevenueGrowthRank | 0.15 |
| LowVolatilityRank | 0.15 |
| SalesGrowth3MRank | 0.08 |
| EarningsQualityRank | 0.07 |

Missing policy: drop unavailable factors and renormalize weights (never rewards
availability). Hypothesis: a compact robust model is more stable and far less
coverage-biased than canonical-v1.

## `canonical-v2-exp-b` — Coverage-Aware
Kind: broad factor set with coverage-aware normalization (weighted mean over
available factors, weights renormalized by available weight mass). Sparse factors
carry small weights (NetProfitGrowth 0.03, ROE 0.02, PS 0.04, PB 0.03, etc.), so
availability does not inflate the score. Complete weights in
`MODEL_REGISTRY.json`. Hypothesis: retain breadth while removing coverage bias.

## `canonical-v2-exp-c` — Category-Balanced
Kind: category-first. Category score = mean of available factor ranks in the
category; categories combined with growth 0.35, profitability 0.20, valuation
0.30, market 0.15, renormalized over categories with any available factor.
Prevents a category with more measurable factors from dominating.
Hypothesis: category normalization improves temporal stability.

## Redundancy handling
Correlated pairs (PS↔PB, Leverage↔CurrentRatio, PE↔PS, SalesGrowth↔RevenueGrowth,
PE↔PB) are **not** included at full combined weight: Model A excludes them;
Model B down-weights redundant members (PS 0.04, PB 0.03, Leverage 0.01,
CurrentRatio 0.01).

## Direction policy
All factors use `higher_is_better` as stored. Direction-unstable factors
(OperatingProfitGrowth, Stability, Momentum) are held, not flipped.
