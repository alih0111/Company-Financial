# QuantScore Decomposition (Phase 3, DIAGNOSTIC_ONLY_NOT_MODEL)

Diagnostic effort to separate how much of the QuantScore association comes from
factor values, category composition, coverage/missingness, and market/tradability.
No replacement score is created.

## Series IC (21d, per-date mean, block-bootstrap context)

| diagnostic series | mean IC | interpretation |
| --- | --- | --- |
| **canonical QuantScore** | **0.1088** | control model |
| Σ category scores (growth+prof+val+mkt, no DQ) | 0.1279 | category content |
| n_factors_available (coverage only) | 0.0302 | coverage has a small standalone IC |
| market_score only | 0.0357 | market category weak |
| data_quality_score only | 0.0397 | DQ correlates slightly with returns |

## Attribution

* **Factor/category content dominates.** Category sum IC (0.128) ≥ QuantScore IC
  (0.109); DQ multiplication and penalties slightly attenuate the raw association.
* **Coverage contributes a small independent component** (n_factors IC 0.030) and is
  correlated with the score (Pearson 0.581, Phase 2). Coverage-controlled and
  coverage-neutralized QuantScore IC (0.112 / 0.124, Phase 2) remain positive, so
  the association is not merely coverage.
* **Valuation/growth carry the signal**; market is weak; profitability is
  unmeasurable historically.
* **Market/tradability**: Liquidity is neutral historically (no `trade_value_rial`
  before 2026), so market/tradability compensation cannot explain the result;
  `corr(QuantScore, market_score) = 0.294`.

## Coverage-controlled IC (Phase 2/3)

| stratum | IC |
| --- | --- |
| low (≤7) | 0.112 |
| medium (8–14) | −0.074 (n=46, CI spans 0) |
| high (≥15) | 0.155 |
| coverage-neutralized (diagnostic) | 0.124 |

## Conclusion

Most of the QuantScore association is attributable to **factor values in valuation
and growth**; coverage adds a small but real component; the market category and
liquidity/tradability contribute little. All decomposition series are
`DIAGNOSTIC_ONLY_NOT_MODEL` and must not be promoted to production.
