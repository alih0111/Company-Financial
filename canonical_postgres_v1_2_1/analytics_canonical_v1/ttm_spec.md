# Canonical v1 — TTM Specification

Canonical TTM is defined **without** any legacy `Product1` fallback and **without**
scale detection. All inputs are canonical facts with a known `canonical_unit`.

## Definition (cumulative income-statement / cash-flow facts)

For a cumulative fact `X` from the latest eligible report with fiscal month `M`:

```
TTM(X) = X_current
       + X_prior_fiscal_year            (same company, fiscal year - 1, month 12)
       - X_prior_year_same_period       (same company, fiscal year - 1, month M)
```

When `M = 12`:

```
TTM(X) = X_current
```

`period_order` mapping in canonical facts: `1 = current`,
`2 = prior_year_same_period`, `3 = prior_fiscal_year` (within the same report).
The joins above use the corresponding report at `(FY-1, 12)` and `(FY-1, M)`.

## Edge cases (explicit)

| case | behavior |
| --- | --- |
| current period = 12 months (`M=12`) | `TTM = X_current` |
| missing prior-year-same-period | `TTM = NULL`; DQ `missing_comparable_period`; factor neutral |
| missing prior fiscal year (FY-1,12) | `TTM = NULL`; DQ `missing_comparable_period` |
| fiscal year change | detected via `fiscal_year`; if no matching `(FY-1, M)` report exists → `NULL` (no month arithmetic guessing) |
| restatement | a report with `is_restated = true` (or a superseding report) replaces the prior one for the same period |
| duplicate periods | deterministically keep the latest by `(period_end_date, report_version.version_no DESC, parse_run.started_at DESC)` |
| corrected reports | superseded chain removes the older report from eligibility |
| report versions | among versions of the same report, only the latest `version_no` with `collected_at <= source_cutoff_at` is used |
| point-in-time cutoff | only reports visible at `source_cutoff_at` are used |

## No Product1 fallback

If the amount-based TTM is unavailable and no canonical `net_profit`/`revenue`
fact exists for the required periods, `TTM = NULL`. v1 must **not** reconstruct net
profit from `EPS × capital` or from any legacy product column, even as a
production fallback. (A pure diagnostic may do so outside the engine.)

## Units

Each `X` must be read with its `canonical_unit`:

* monetary facts → IRR
* `eps` → `rial_per_share`

No unit inference. Mixed/unknown units → DQ `unknown_unit`, and the metric is
`NULL`.
