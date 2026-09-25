# Point-in-Time Universe Policy

No fixed/modern universe is used. At each rebalance date `T` the universe is
exactly what the canonical Engine scores from data visible at `T`.

## Layered definitions (kept separate)

| layer | definition |
| --- | --- |
| **Analytics eligibility** | canonical subject at `T`: `is_active`, resolved identity, and (`income_statement` present OR ≥ 6 monthly rows) |
| **Signal eligibility** | analytics-eligible company with a `quant_score` |
| **Tradability** | signal whose primary security has a canonical close on the execution date (next trading day) |
| **Forward-return availability** | has both entry and exit canonical closes |

## Exclusions (recorded per rebalance)

* `no_security` — no primary security mapped.
* `no_price_on_execution_date` — tradability failure; does not remove the company
  from analytics eligibility.

## Survivorship

Because eligibility is recomputed from PIT data at each `T` (never a static list),
a company enters only when it satisfies rules establishable at `T`, and exits when
it no longer does. `rebalance_snapshots.csv` tracks eligible/tradable/excluded and
additions/removals over time. The accepted out-of-scope legacy subjects
(`ACCEPTED_CANONICAL_SCOPE_EXCLUSION`) simply never appear.

## No fabrication

Prices are never fabricated or substituted from legacy tables; only
`market.price_observations` is used.
