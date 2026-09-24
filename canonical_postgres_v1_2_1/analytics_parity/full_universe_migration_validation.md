# Full-Universe Canonical Migration Validation

## Counts

| object | source | target | expected | equal |
| --- | --- | --- | --- | --- |
| monthly (mahane) | 12075 | 12075 | 12075 | True |
| facts (miandore2 non-null mapped) | 6806 rows | 71361 | 71361 | True |
| prices (MPH) | 705812 | 705812 | 705812 | True |
| reports (incl synthetic legacy) | CodalReports 48 | 18915 | legacy-driven | n/a |

- canonical companies: 273, securities: 273

## Orphans

- facts without statement: **0**
- statements without parse_run: **0**
- monthly without parse_run: **0**
- securities without company: **0**
- prices without security: **0**
- legacy map company target missing: **0**

## Duplicates / identity

- duplicate tsetmc_ins_code: **0**
- duplicate price observation key: **0**
- duplicate report source id: **0**
- duplicate fact business key: **0**
- name-only securities: **0**

## Units

- bad canonical_unit: **0**
- monetary reported_unit mismatch: **0**
- quantity_unit NULL (allowed): **12075**

## Gate

**FULL_UNIVERSE_INPUTS_PASS**

