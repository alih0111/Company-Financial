# Population Reconciliation — oracle (276) vs canonical v1 (267)

Arithmetic: `oracle 276`, `canonical population 267`, `intersection 267`,
therefore `oracle-only = 9` (276 − 267). No canonical subject is unmatched
(`canonical-only = 0`). Every one of the 9 is classified below. Machine-readable:
`population_reconciliation.csv`.

Context: `matched = 267` (all canonical subjects map via `core.legacy_entity_map`
to an oracle subject). One extra legacy key (`کسرا` second CompanyID
`4ccc9664…`) maps to a canonical subject but is not a v3.7 subject
(`canon_subjects_mapping_outside_oracle = 1`); it is not a scoring subject and is
documented, not a defect.

## The 9 oracle-only subjects

| # | legacy CompanyID | symbol | name | canonical mapping | reason | classification | policy/defect | remediation |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `09029850…` | — | خبهن | none | has `mahane`, no `MarketPriceHistory` | ACCEPTED_CANONICAL_SCOPE_EXCLUSION | accepted out-of-scope | NONE |
| 2 | `326f53e9…` | — | خاهن | none | has `miandore2`, no price | ACCEPTED_CANONICAL_SCOPE_EXCLUSION | accepted out-of-scope | NONE |
| 3 | `6081d3f3…` | — | شکیمیا | none | has `miandore2`, no price | ACCEPTED_CANONICAL_SCOPE_EXCLUSION | accepted out-of-scope | NONE |
| 4 | `857898d4…` | — | ولشرق | none | has `mahane`, no price | ACCEPTED_CANONICAL_SCOPE_EXCLUSION | accepted out-of-scope | NONE |
| 5 | `9ec90a47…` | — | شخارک | none | has `mahane` + `miandore2`, no price | ACCEPTED_CANONICAL_SCOPE_EXCLUSION | accepted out-of-scope | NONE |
| 6 | `0e1074b1…` | بمولد | بمولد | company `bd3c4219…` | no income_statement; monthly = 1 (< 6) | POLICY_EXCLUSION | expected policy | E |
| 7 | `357e4606…` | ثالوند | ثالوند | company `ca698afc…` | no income_statement; monthly = 1 | POLICY_EXCLUSION | expected policy | E |
| 8 | `47cec2ef…` | تاتمس | تاتمس | company `5564f3b0…` | no income_statement; monthly = 1 | POLICY_EXCLUSION | expected policy | E |
| 9 | `981b4b3a…` | فبستم | فبستم | company `e832aea3…` | no income_statement; monthly = 2 | POLICY_EXCLUSION | expected policy | E |

### Group A — ACCEPTED_CANONICAL_SCOPE_EXCLUSION (5)

Real legacy subjects carrying fundamentals/monthly but **zero**
`MarketPriceHistory` rows. The canonical universe was built from
`TrackedTickers ∩ MarketPriceHistory`, so they were never migrated as canonical
companies. They are **not** fabrications.

**Project decision:** these five are not important for the canonical v1 scope.
They are classified `ACCEPTED_CANONICAL_SCOPE_EXCLUSION`: remediation is
intentionally deferred/not required. No fake company/security/market data will be
created, and canonical population is intentionally allowed to differ from v3.7.
They are no longer treated as data-work blockers.

### Group B — POLICY_EXCLUSION (4)

Canonical company + primary security exist and are mapped, but the canonical v1
eligibility policy (`income_statement` present OR ≥ `min_monthly_records = 6`)
excludes them: they have no income statement and 1–2 monthly records. v3.7
included them (it only needed any sales). → expected policy difference,
remediation class **E** (a policy decision, not a data defect). If desired, the
min-monthly threshold could be revisited, but that is a model/policy change.

## Conclusion

`9/9` oracle-only subjects are explicitly classified; no unexplained population
difference remains. `canonical-only` subjects = 0. Of the 9: **5 are accepted
out-of-scope** (`ACCEPTED_CANONICAL_SCOPE_EXCLUSION`, no remediation) and **4 are
policy exclusions** (`POLICY_EXCLUSION`). Neither is a blocker for canonical v1.
