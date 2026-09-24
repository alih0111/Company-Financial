# Unit Validation

- monetary facts with canonical_unit != 'rial' and != 'rial_per_share': **0** (expected 0)
- monetary facts whose reported_unit != 'million_rial': **0** (expected 0)
- EPS facts with canonical_unit='rial_per_share': **851**
- monthly activities with quantity_unit NULL (allowed/unknown): **594**
