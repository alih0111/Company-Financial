# PRICE_HISTORY IDENTITY ELIGIBILITY

Deterministic registry that decides whether a legacy price-history symbol may
ever be canonical-served under the current endpoint contract. Only
`CANONICAL_SAFE` symbols may be canonical-served; everything else routes to
legacy. This makes percentage rollout safe without modifying canonical identity.

## 1. Classification rule (from identity structure, not price differences)

Inputs (read-only):

- SQL Server `MarketPriceHistory` (`CompanyName`, `Symbol`, `InstrumentCode`,
  `CompanyID`), and `TrackedTickers.Symbol`.
- Canonical `core.securities` (`codal_symbol`, `brs_name`, `tsetmc_ins_code`),
  `core.security_aliases` (`alias_value`), `core.legacy_entity_map`.

For a normalized name `N`:

1. **Legacy identities** = distinct legacy market identity keys among rows where
   normalized `CompanyName = N` OR normalized `Symbol = N`. Identity key =
   `InstrumentCode` when present, else `Symbol` + `CompanyID`.
2. **Canonical securities** = union of securities where normalized
   `codal_symbol = N` or `brs_name = N`, plus securities referenced by
   `security_aliases.alias_value = N`.

| Condition | Classification |
| --- | --- |
| 0 canonical securities, 0 legacy rows, name tracked | `LEGACY_ONLY` |
| 0 canonical securities, 0 legacy rows | `NO_MARKET_DATA` |
| 0 canonical securities, >0 legacy rows | `CANONICAL_UNMAPPED` |
| >1 canonical securities | `OTHER_UNSAFE` |
| exactly 1 canonical security, >1 legacy identities | `LEGACY_IDENTITY_COLLISION` |
| exactly 1 canonical security, ≤1 legacy identity | `CANONICAL_SAFE` |

A collision is detected purely from the identity/mapping structure (a legacy name
resolving to more than one legacy identity), independent of any price comparison.

## 2. Full-universe audit result

Total symbols audited: **285** (legacy market names + tracked names).

| Classification | Count |
| --- | --- |
| `CANONICAL_SAFE` | **276** |
| `LEGACY_IDENTITY_COLLISION` | **3** |
| `LEGACY_ONLY` | 5 |
| `CANONICAL_UNMAPPED` | 1 |
| `NO_MARKET_DATA` | 0 |
| `OTHER_UNSAFE` | 0 |

### Identity collisions (explicit list)

| Symbol | Legacy identities | Canonical securities | Observations | Note |
| --- | --- | --- | --- | --- |
| جم پیلن | 3 | 1 | 1618 | `جم پیلن` + `جم پیلن3` (+ `جم پیلن2`) share CompanyName `جم پیلن` |
| سیمرغ | 2 | 1 | 1653 | `سیمرغ` + `سیمرغ3` — **newly discovered in this audit** |
| های وب | 2 | 1 | 1726 | `های وب` + `های وب3` |

### Other non-safe classes

- `LEGACY_ONLY` (5): خاهن، خبهن، شخارک، شکیمیا، ولشرق — tracked legacy names
  with no market rows and no canonical security (canonical scope exclusion).
- `CANONICAL_UNMAPPED` (1): جم پیلن2 — legacy market rows with no canonical
  security match.

## 3. Previously validated symbols remain CANONICAL_SAFE

کیمیا، غاذر، کسرا، وسپه، خودرو، بفجر، مبین، دزهراوی → all `CANONICAL_SAFE`.
`کسرا` confirms the distinction: a **safe alias** (symbol/legal-name alias to one
canonical security, one legacy identity) versus an ambiguous **legacy identity
collision** (one name spanning multiple legacy identities).

## 4. Routing guard

Precedence for `/api/price-history`:

```
normalize symbol
  -> eligibility check
       if not CANONICAL_SAFE  => LEGACY (guard)
       else                   => existing routing
                                 (SHADOW / CANONICAL / allowlist / percent / legacy)
```

- An unsafe symbol is **never** canonical-served, even if it is on the canary
  allowlist or its FNV bucket falls inside a rollout percentage.
- Default-deny: if the registry is not loaded, canonical serving is denied
  (legacy). `SHADOW` remains unchanged only when no registry is loaded; with a
  registry loaded, an ineligible symbol is not shadow-compared either.
- The hash algorithm is unchanged (FNV-1a mod 100). The eligibility guard runs
  first.

## 5. Diagnostics

Counters added: `canonical_safe`, `canonical_ineligible`,
`legacy_identity_collision`, `legacy_only`, `canonical_unmapped`,
`no_market_data`, `other_unsafe`, `eligibility_guard_forced_legacy`. No internal
IDs are exposed to the API client.

## 6. Percentage denominator

The rollout denominator is conceptually the **CANONICAL_SAFE** population (276),
not the entire legacy universe (285). The 9 non-safe symbols are always served by
legacy. See `output/price_history_percent_simulation.json`: at 100% the guard
serves 100% of `CANONICAL_SAFE` and 0% of non-safe; any raw hash matches on
non-safe symbols are forced legacy.

## 7. End-to-end guard evidence (real HTTP)

Server allowlist deliberately included three collision symbols plus one safe:

- جم پیلن، های وب، سیمرغ → canonical_served **0** (all forced legacy);
- وسپه → canonical_served 5, comparison exact 1050, unexpected 0;
- counters: `canonical_ineligible=16`, `eligibility_guard_forced_legacy=16`,
  `legacy_identity_collision=16`, `canonical_safe=5`.

## 8. Reproducibility

Registry: `output/price_history_identity_eligibility.csv` (deterministic, sorted
by classification then symbol). Generated by:

```powershell
cd go-app
$env:CDF_CANONICAL_DB="company_financial_analytics_shadow_v121"
go run ./cmd/eligbuild
```

The check is structural and reproducible from the two databases; regenerate after
market-identity data changes.

## 9. Future work (not in scope)

The long-term public API should expose an explicit unique security identifier
(e.g. canonical security UUID, `tsetmc_ins_code`, or a resolved `security_id`)
instead of an ambiguous display symbol. Until then the compatibility policy is:
**ambiguous symbol → LEGACY**. No canonical identity semantics were changed, no
securities merged, no aliases fabricated, no market data modified.
