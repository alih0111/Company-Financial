# MARKET AUTHORITY SPEC — MARKET_PRICE canonical-primary

## 1. Scope

MARKET_PRICE only. MONTHLY_ACTIVITY / FINANCIAL_STATEMENT / CODAL remain in
their existing DUAL_WRITE / legacy-authoritative state. No global change.

## 2. Authority configuration

| Env | Values | Default | Meaning |
| --- | --- | --- | --- |
| `CDF_MARKET_INGESTION_AUTHORITY` | `legacy` \| `canonical` | `legacy` | MARKET_PRICE destination authority |
| `CDF_MARKET_FALLBACK_LEGACY` | `true` \| `false` | `true` | write legacy for continuity when canonical fails |
| `CDF_INGESTION_MODE` | `legacy_only` \| `dual_write` \| `canonical_only` | `legacy_only` | canonical writes enabled for all domains |

`canonical` authority implies canonical writes are attempted regardless of the
global mode (the canonical DSN must be configured). It does **not** change the
meaning of global `DUAL_WRITE` for monthly/financial.

## 3. Canonical-primary semantics

```
source fetch -> normalize -> resolve canonical Security
  -> canonical PostgreSQL transaction (AUTHORITATIVE)
  -> on success: mirror to SQL Server (mirror failure does NOT invalidate)
  -> on canonical failure: optional legacy fallback for continuity,
     mark DEGRADED, queue canonical retry
```

Explicit outcomes:

| Outcome | Meaning |
| --- | --- |
| `CANONICAL_SUCCESS_LEGACY_SUCCESS` | canonical authoritative + mirror ok |
| `CANONICAL_SUCCESS_LEGACY_MIRROR_FAILED` | canonical authoritative; SQL Server mirror behind |
| `CANONICAL_FAILED_LEGACY_FALLBACK_USED` | canonical behind; legacy continuity write used; retry queued |
| `CANONICAL_FAILED` | canonical failed, no fallback (or fallback disabled) |

Canonical success is the authority. Ingesting is never reported successful when
the canonical write failed.

## 4. Write contract (unchanged)

`market.price_observations`, append-only, canonical Security identity, actual
source `collected_at`, IRR units, source metadata, stable hash + natural-key
compatibility, no historical overwrite, idempotent retry.

## 5. Rollback (one flip)

Set `CDF_MARKET_INGESTION_AUTHORITY=legacy` (default). Restores SQL Server
authoritative + canonical secondary. Config-only; no code/schema/data change.

## 6. Freshness / health

`output/market_authority_freshness.json` reports authority, latest source
collection/trade date, latest canonical observation/trade date, canonical rows,
retry backlog and health: `HEALTHY`, `DEGRADED_LEGACY_MIRROR`,
`CANONICAL_BEHIND`, `CANONICAL_ERROR`. Market is not healthy merely because SQL
Server has newer data.
