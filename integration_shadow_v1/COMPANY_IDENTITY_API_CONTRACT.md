# COMPANY / SECURITY IDENTITY API CONTRACT

Resolves the previous `CompanyNames` blocker by separating the **current
compatibility response** from the **future canonical contract**. Canonical
identity is never changed to imitate ambiguous legacy naming.

## Canonical internal identity (unchanged)

- **Company** = `core.companies.id` (UUID). Legal name (`legal_name`) and
  `display_name` are attributes, not identity.
- **Security** = `core.securities.id` (UUID), belongs to a company, carries
  `tsetmc_ins_code`, `codal_symbol`, `brs_name`, `isin`.
- **Aliases** = `core.security_aliases` (`alias_type`: `symbol`, `company_name`,
  …). Aliases are lookup values, not identity.
- **Legacy mapping** = `core.legacy_entity_map` (`entity_type` = `company` |
  `security`), explicit and revision-aware.
- `Company != Security`; no name/symbol is ever used as canonical identity and no
  new canonical entity is fabricated to satisfy legacy population counts.

## Current `/api/CompanyNames` behaviour (compatibility)

Legacy source: `SELECT DISTINCT CompanyName FROM miandore2 ORDER BY CompanyName`.
Response: `[]string` of names (trading names).

Current canonical shadow reader (`integration.PG.CompanyNames`): returns
`DISTINCT COALESCE(display_name, legal_name)` from `core.companies`.

Live shadow result (`endpoint_summary.csv`, 2026-09-25):

| Metric | Value |
| --- | --- |
| legacy rows | 267 |
| canonical rows | 273 |
| exact name match | 263 |
| canonical-only | 10 |
| legacy-only | 4 |
| unexpected differences | 0 |
| legacy latency | 28.1 ms |
| canonical latency | 6.6 ms |

- **4 legacy-only** (`خاهن`, `شخارک`, `شکیمیا`, `کسرا`): one alias-only naming
  difference (`کسرا`, canonical company exists with legal display name) and three
  canonical scope exclusions with no market identity. Documented in
  `UNMAPPED_LEGACY_NAMES.md`. No remediation, no identity change.
- **10 canonical-only**: canonical companies with no `miandore2` legacy row
  (canonical universe is market/security-driven). Expected coverage difference.

## Identity semantics decision

1. **Do not change canonical identity/naming to reproduce the legacy 267-name
   set.** The 263 shared names are an exact match; the residual is explained and
   classified.
2. A `CompanyNames` canonical reader may **union `core.security_aliases`**
   (symbol + company_name) with the company display/legal name so that
   symbol-named companies match the legacy name set *without touching canonical
   identity*. This is the agreed future clean contract; it is **not enabled** in
   this task (legacy response remains authoritative in LEGACY/SHADOW).
3. The client keys companies by **name string** today
   (`useCompanyData.ts` → `selectedCompany`; `CompanySelect` value = name). Any
   future identity-bearing response must keep a stable, client-visible name/symbol
   field and add IDs additively; existing fields, ordering and types must not
   change unexpectedly.

## Future clean API contract (documented, not yet enabled)

```
GET /api/CompanyNames
  -> [ { company_id_uuid, security_id_uuid?, symbol, display_name, legal_name,
         aliases[] } ]        # canonical
GET /api/CompanyNames?contract=legacy
  -> ["name", ...]            # existing compatibility shape
```

- Legacy-compatible response stays the default until an endpoint-level canary is
  approved (`GO_CANONICAL_READ_CANARY_READY`).
- Canonical UUIDs are never exposed on the legacy path (`PRICE_HISTORY_*` already
  follows this rule).
- Names/symbols remain presentation only; all join/key logic uses UUIDs
  internally.

## Gate impact

`CompanyNames` remains **SHADOW-ready but not canary-ready** because the canonical
name set is a presentation difference (10/4 rows), not an exact match. It is
classified `IDENTITY_PRESENTATION_DIFFERENCE` / `LEGACY_ONLY` / `CANONICAL_ONLY`,
never `UNCLASSIFIED`.
