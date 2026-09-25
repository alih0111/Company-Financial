# MARKET AUTHORITY RUNBOOK

## Enable canonical-primary for MARKET_PRICE

```powershell
$env:CDF_INGESTION_MODE            = "dual_write"     # canonical writes enabled
$env:CDF_CANONICAL_DB              = "company_financial_analytics_shadow_v121"
$env:CDF_MARKET_INGESTION_AUTHORITY = "canonical"      # market authority = canonical
$env:CDF_MARKET_FALLBACK_LEGACY     = "true"           # continuity on canonical failure
```

(Optional per-domain writes are already market-only via the authority flag;
monthly/financial keep their existing `CDF_INGESTION_MODE` behavior.)

## Disable / rollback (one flip)

```powershell
$env:CDF_MARKET_INGESTION_AUTHORITY = "legacy"
```

or remove the variable. This restores SQL Server-authoritative + canonical
secondary for MARKET_PRICE. Config-only — no code, schema, deployment or data
change. SQL Server tables are never dropped.

## Verify

- `output/market_authority_freshness.json` → `authority=CANONICAL`, `health`,
  `retry_backlog`.
- `output/market_authority_cycles.csv`, `market_authority_summary.json`.
- per-batch stdout: `domain=MARKET_PRICE authority=CANONICAL outcome=...`.

## Health states / actions

| state | meaning | action |
| --- | --- | --- |
| `HEALTHY` | canonical authoritative, mirror ok, backlog 0 | none |
| `DEGRADED_LEGACY_MIRROR` | canonical ok, SQL Server mirror behind | inspect mirror; canonical truth intact |
| `CANONICAL_BEHIND` | retry backlog > 0 | run `drivers/retry_market.py` |
| `CANONICAL_ERROR` | canonical writes failing | check DSN/PG; fallback keeps continuity; replay retry |

## Retry

`python drivers/retry_market.py` replays pending MARKET_PRICE retries from
`output/canonical_retry_manifest.jsonl` (re-reads legacy rows, canonical-only
write, marks done). Idempotent; no legacy re-run.

## Do not

- do not delete `MarketPriceHistory` or disable legacy market writes permanently;
- do not switch monthly/financial authority;
- do not enable `CANONICAL_ONLY` globally.
