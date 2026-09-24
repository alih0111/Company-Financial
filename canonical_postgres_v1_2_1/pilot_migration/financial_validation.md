# Financial Facts Validation

Monetary: `canonical_value = legacy x 1,000,000`. EPS: `canonical_value = legacy` (rial_per_share).

| company | report (greg) | metric | period | legacy | expected canonical | actual canonical | status |
| --- | --- | --- | --- | --- | --- | --- | --- |

- facts checked: **2110**
- mismatches: **0**
- rows rounded within tolerance (<= 1e-6, numeric(30,6) vs FLOAT source): **1**
- tolerance: exact for EPS; monetary allowed |diff| <= 1e-6 absolute due to canonical_value numeric(30,6).
