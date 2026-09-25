# Canonical v1 — Scoring Population Specification

The canonical scoring population is defined by **canonical identity**, not by the
legacy 276-subject rule. Exact equality with the v3.7 oracle population is **not**
required; every difference must be explainable.

## Subject definition

> One **eligible canonical company**, optionally linked to its **primary security**.

`population_273_vs_276` is therefore not a bug: legacy eligibility was
`mahane ∪ miandore2`; canonical eligibility is derived from canonical facts and
canonical identity.

## Company eligibility

A company is eligible iff at least one of:

1. it has ≥1 `fundamentals.financial_statements` row of type `income_statement`
   with a `net_profit` or `revenue` fact; or
2. it has ≥ `min_monthly_records` (default 6) rows in
   `fundamentals.monthly_activities`.

Additional rules:

* `core.companies.is_active` must be true.
* Identity must be resolved: the company must be reachable from a security with a
  non-null external identifier (`tsetmc_ins_code` or `codal_symbol`), or from
  `core.legacy_entity_map`. Otherwise → DQ `unresolved_identity`, excluded.

## Security eligibility

* Primary security = `core.securities WHERE is_primary AND is_active`; if none,
  the active security with the most `market.price_observations`.
* `security_type`:
  * `stock` → normal scoring.
  * `fund` / `etf` → **excluded** from the default equity scoring population
    (handled by a separate fund policy; not scored as an operating company).
  * `right`, `preferred` → not eligible as primary.
* A company may have multiple securities; only the primary one supplies market
  factors (no double counting).

## Price availability

* `has_market_price` = primary security has ≥1 eligible observation
  (`collected_at <= source_cutoff_at`).
* Missing price: market metrics are **NULL**; market factors take the neutral rank
  (or the explicit "no data" rank where v3.7 used worst, see `factor_review.md`);
  DQ records `missing_price`. Company is **not** excluded.
* Stale price: `source_cutoff_at - max(trade_date) > stale_days` (default 14) →
  DQ `stale_market_data`; market factors still computed but DQ penalty applies.

## Inactive securities / companies

`is_active = false` securities are never chosen as primary. Inactive companies are
excluded from the population (they remain canonical entities).

## Multiple securities

At most one primary per company (`uq_securities_one_primary_per_company`). If the
primary is missing, a deterministic fallback is chosen (most observations, then
lowest `id`) so runs are reproducible.

## Expected canonical population (shadow)

| bucket | expected |
| --- | --- |
| eligible companies (stocks, resolved, ≥1 data source) | ~271 |
| excluded funds (`fund`/`etf`) | 2 |
| legacy-only subjects with no canonical company | 5 (مigration gap, not fabricated) |

Differences vs the oracle's 276 are classified `POPULATION_POLICY_CHANGE` or
`MISSING_CANONICAL_DATA` in `compare_oracle.py`.
