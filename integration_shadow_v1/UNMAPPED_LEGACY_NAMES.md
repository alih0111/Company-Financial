# UNMAPPED LEGACY NAMES — Investigation

Phase 1 `/api/CompanyNames` comparison found 4 legacy-only names. This document
resolves each one against legacy and canonical evidence.

Evidence sources: SQL Server `miandore2`, `mahane`, `MarketPriceHistory`,
`TrackedTickers`; PostgreSQL `core.legacy_entity_map`, `core.companies`,
`core.securities`, `core.security_aliases`. Read-only throughout.

## Results

| Legacy name | Legacy CompanyID | Legacy data | Canonical mapping | Classification |
| --- | --- | --- | --- | --- |
| کسرا | `7e41b7fd7ba1c353199eba22667db254` | miandore2 28, mahane 75, MarketPriceHistory 17 | **mapped** → company `298fce3f…`, security symbol `کسرا` | **Alias-only naming issue** |
| خاهن | `326f53e9133b7e24c3b9ffec1e73fa18` | miandore2 28, mahane 0, MarketPriceHistory 0 | none | **Canonical scope exclusion** |
| شخارک | `9ec90a47014c21843c4239f7a99a76f1` | miandore2 27, mahane 44, MarketPriceHistory 0 | none | **Canonical scope exclusion** |
| شکیمیا | `6081d3f368b7889ba242435db91b5b2f` | miandore2 3, mahane 0, MarketPriceHistory 0 | none | **Canonical scope exclusion** |

## 1. کسرا — alias-only naming issue

- `core.legacy_entity_map` maps `7e41b7fd…` (source tables `mahane`, `miandore2`,
  `MarketPriceHistory`) to canonical company `298fce3f-f6fe-451e-93e1-f4d4ca508782`.
- That company's `display_name` is the full legal name
  `کاتالیستهای صنعتی آریا`, while its security `codal_symbol` and
  `security_aliases` (`alias_type` `symbol` and `company_name`) are `کسرا`.
- Therefore the entity **is** canonical; only the name-set comparison flagged it,
  because `CompanyNames` canonical returns `display_name` (legal name) while
  legacy returns the trading name/symbol.
- Phase-2 fundamentals comparisons confirm the mapping works: کسرا matched 75/75
  monthly rows and 28/28 income-statement rows with 0 unexpected differences.
- **No remediation needed.** This is exactly the documented Company vs Security
  alias model. A future `CompanyNames` canonical reader should prefer/union
  `security_aliases` display symbols (documented as future API-migration work).

## 2. خاهن، شخارک، شکیمیا — canonical scope exclusion

- None appear in `core.legacy_entity_map`, `core.companies`, `core.securities`
  or `core.security_aliases`.
- All three have **zero** `MarketPriceHistory` rows and **zero**
  `security_aliases`.
- In legacy `TrackedTickers` all three exist with `Source = 'miandore2'` (seeded
  from the financial-facts table only), whereas canonical-universe names such as
  کسرا are `Source = 'market_price_history'`.
- The canonical full-universe migration was driven by market/security identity
  (tsetmc ins code / BRS prices). These three have no market identity, so they
  were legitimately excluded from the canonical universe rather than failed.
- Phase-2 shadow results show them as expected `LEGACY_ONLY`
  (خاهن 28 financial rows, شخارک 27 financial + 44 monthly, شکیمیا 3 financial),
  never as `NUMERIC_MISMATCH`.

## Decision

- **No canonical data was created or modified.**
- **No identity mapping was changed.** There is no evidence of a mapping defect;
  the mapping rows that exist are correct.
- No remediation is required for Phase 2. If product scope later requires these
  three companies, the correct path is a dedicated identity-resolution intake
  (ins code / market identity), not a fake canonical company — explicitly out of
  scope here.
- Residual future work: make the canonical `CompanyNames` reader union
  `security_aliases` symbols so symbol-named companies (e.g. کسرا) match the
  legacy name set without changing canonical identity.
